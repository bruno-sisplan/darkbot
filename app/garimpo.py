"""Garimpo no perfil: o darkbot faz, no Chrome do perfil, o que o editor faz à mão para achar vídeos e aquecer o perfil.

Como o editor faz: abre um vídeo dark do nicho (ou pesquisa o tema/título), vai nos sugeridos, abre os que são DARK e
do MESMO NICHO (não precisa ser o mesmo assunto), deixa rodando um pouco, entra nos canais e assiste também (mesmo o
que está fora dos parâmetros: serve para afunilar o perfil) e repete pelos sugeridos dos novos.

Aqui é igual, com a IA escolhendo o que abrir:
1. ponto de partida: o vídeo do link, ou a busca no YouTube do perfil;
2. cada rodada: abre os escolhidos em abas, deixa rodando (sem som), lê os sugeridos de cada um;
3. a IA separa os sugeridos que são do nicho (pelo título, canal e duração) e a classificação dos canais tira o que
   não é dark; os melhores viram a próxima rodada (no máximo 1 por canal);
4. visita os canais mais fortes da rodada e assiste os vídeos mais vistos deles;
5. no fim, coleta a home (que já está aquecida no nicho).
Tudo o que é dark e do nicho vira uma coleta "Garimpo" do perfil: aparece em Descobrir, onde os parâmetros de viral
filtram e ordenam. Os sugeridos são os DO PERFIL (personalizados), que mudam conforme ele esquenta.
"""
import hashlib
import time
from pathlib import Path

from . import ai, analytics, chrome_profiles, config, db, jobs, research, youtube_api, youtube_web
from .scraper import _Collector

# rodadas, vídeos por rodada, segundos rodando, canais visitados por rodada, vídeos assistidos por canal
MODES = {
    "rapido": (2, 3, 45, 1, 1),
    "normal": (3, 4, 75, 1, 2),
    "profundo": (5, 5, 90, 2, 2),
}
HOME_SCROLLS = 6          # rolagens da home no fim (já aquecida)
CHANNEL_UPLOADS = 15      # últimos vídeos lidos de cada canal visitado
MIN_RELEVANCE = 2         # nota do juiz: 2 = mesmo nicho (outro assunto vale), 3 = mesmo vídeo/premissa

_ARGS = [
    "--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check",
    "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--autoplay-policy=no-user-gesture-required", "--mute-audio",   # os vídeos rodam sozinhos, sem som
]
_PLAY = "() => { const v = document.querySelector('video'); if (v) { v.muted = true; v.play().catch(() => {}); } }"
# Estado do player: anúncio na tela? botão "Pular" VISÍVEL? Mantém o vídeo tocando (sem som).
# O "Pular" é clicado com um clique de verdade do navegador (o YouTube ignora clique feito por código), como uma pessoa.
# Anúncio não pulável roda até o fim (não mexemos no anúncio); só não conta como tempo assistido do vídeo.
_SKIP = ".ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern"
_TICK = """() => {
  const p = document.querySelector('#movie_player');
  const ad = !!(p && (p.classList.contains('ad-showing') || p.classList.contains('ad-interrupting')));
  const skip = [...document.querySelectorAll('%s')].some(b => b.offsetParent !== null && getComputedStyle(b).display !== 'none');
  const v = document.querySelector('video');
  if (v) { v.muted = true; if (v.paused) v.play().catch(() => {}); }
  return { ad, skip: ad && skip, playing: !!(v && !v.paused && v.readyState > 2) };
}""" % _SKIP
WATCH_EXTRA_S = 120   # tempo a mais que espera por causa de anúncios, no máximo


def _initial(page) -> dict:
    try:
        return page.evaluate("() => window.ytInitialData || null") or {}
    except Exception:
        return {}


def _open(ctx, url: str):
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        return page
    except Exception:
        page.close()
        return None


def _watch(ctx, ids: list[str], seconds: int, job: jobs.Job, stats: dict | None = None) -> dict[str, list[tuple[str, str]]]:
    """Abre os vídeos em abas, dá o play em cada um, lê os sugeridos e deixa cada um rodando `seconds` segundos de
    VÍDEO de verdade: o tempo de anúncio não conta (o anúncio não ensina nada ao algoritmo sobre o nicho)."""
    pages = []
    for vid in ids:
        if job.stopped():
            break
        page = _open(ctx, f"https://www.youtube.com/watch?v={vid}")
        if not page:
            continue
        try:
            page.bring_to_front()   # o Chrome só dá o play em aba que já ficou na frente
            page.evaluate(_PLAY)
        except Exception:
            pass
        pages.append((vid, page))
    sugg = {}
    for vid, page in pages:
        data = _initial(page)
        col = _Collector()
        col.walk(data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("secondaryResults", {}))
        col.found.pop(vid, None)
        sugg[vid] = [(k, v["title"]) for k, v in col.found.items()]
    content = {vid: 0.0 for vid, _ in pages}   # segundos de vídeo (sem anúncio) já assistidos em cada aba
    ads = set()
    deadline, last = time.time() + seconds + WATCH_EXTRA_S, time.time()
    while pages and time.time() < deadline and not job.stopped():
        time.sleep(2)
        now = time.time()
        step, last = now - last, now
        for vid, page in pages:
            try:
                st = page.evaluate(_TICK)
            except Exception:
                continue
            if st["ad"]:
                ads.add(vid)
                if st["skip"]:
                    try:
                        page.locator(_SKIP).locator("visible=true").first.click(timeout=1500)
                        if stats is not None:
                            stats["skipped"] = stats.get("skipped", 0) + 1
                    except Exception:
                        pass
            elif st["playing"]:
                content[vid] += step
        if all(t >= seconds for t in content.values()):
            break
    if stats is not None:
        stats["ads"] = stats.get("ads", 0) + len(ads)
        stats["content_s"] = stats.get("content_s", 0) + round(sum(content.values()))
    for _, page in pages:
        try:
            page.close()
        except Exception:
            pass
    return sugg


def _search(ctx, query: str) -> list[tuple[str, str]]:
    from urllib.parse import quote_plus
    page = _open(ctx, f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    if not page:
        return []
    col = _Collector()
    col.walk(_initial(page).get("contents", {}))
    page.close()
    return [(k, v["title"]) for k, v in col.found.items()]


def _dark_map(ids: list[str]) -> dict[str, bool | None]:
    """dark/não dark de cada vídeo pelo canal (None = canal ainda não classificado)."""
    if not ids:
        return {}
    rows = db.rows(f"""SELECT v.video_id, c.dark AS channel_dark, c.dark_conf AS channel_dark_conf,
                              c.dark_manual AS channel_dark_manual, c.format AS channel_format,
                              (SELECT MAX(v2.ai_label) FROM videos v2 WHERE v2.channel_id = v.channel_id) AS channel_ai
                       FROM videos v LEFT JOIN channels c ON c.channel_id = v.channel_id
                       WHERE v.video_id IN ({','.join('?' * len(ids))})""", ids)
    out = {}
    for r in rows:
        known = r["channel_dark"] is not None or r["channel_dark_manual"] is not None or r["channel_format"]
        out[r["video_id"]] = analytics.is_dark(r) if known else None
    return out


def run(job: jobs.Job, profile_id: int, seed: str, mode: str, show_browser: bool) -> dict:
    p = db.row("SELECT * FROM profiles WHERE id=?", (profile_id,))
    if not p:
        raise RuntimeError("Perfil não encontrado.")
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("O garimpo precisa da chave da API do YouTube (Configurações).")
    if not ai.enabled():
        raise RuntimeError("O garimpo precisa da IA para escolher o que abrir (Configurações).")
    pdir = Path(p["dir"])
    if chrome_profiles.profile_in_use(pdir):
        raise RuntimeError("Esse perfil está aberto numa janela do Chrome. Feche-a e tente de novo.")
    rounds, per_round, watch_s, n_channels, per_channel = MODES.get(mode, MODES["normal"])
    seed = (seed or "").strip()
    seed_vid = youtube_web.parse_video_id(seed) if seed else None
    query = None if seed_vid else (seed or p["niche"] or "").strip()
    if not seed_vid and not query:
        raise RuntimeError("Cole o link de um vídeo dark do nicho ou escreva o tema (ou defina o nicho do perfil).")

    # ---------------------------------------------------------------- 1. o nicho (o critério de escolha)
    job.update(0.02, "IA entendendo o nicho...")
    if seed_vid:
        info = (youtube_api.fetch_videos([seed_vid], key) or [None])[0]
        if not info:
            raise RuntimeError("Não encontrei esse vídeo no YouTube. Confira o link.")
        prof = ai.seed_profile(seed_vid, info["title"], info.get("channel_title") or "", info.get("description") or "",
                               info.get("tags") or [], research.lang_code(info.get("lang"), info["title"]))
        label = info["title"]
    else:
        lang = ai.LANGUAGES[research.lang_code(None, query)][2]
        text = "O editor pesquisou: " + query
        prof = ai.research_brief("kw:" + hashlib.sha1(f"{lang}|{text.lower()}".encode()).hexdigest()[:16],
                                 "keyword", text, lang)
        label = query
    topic = (f"o NICHO de um canal dark: {prof['theme']} (formato: {prof['format']}). Vale qualquer vídeo desse nicho "
             f"para o mesmo público, mesmo com outro assunto ou outra premissa: nota 2 = mesmo nicho, 3 = mesma "
             f"premissa. Nota 1 = só a área ampla." + (f" Nicho do perfil: {p['niche']}." if p["niche"] else ""))

    started = jobs.now_iso()
    with db.tx() as con:
        run_id = con.execute("INSERT INTO runs(profile_id, started_at, status, source) VALUES(?,?, 'running', 'garimpo')",
                             (profile_id, started)).lastrowid

    found: dict[str, dict] = {}   # dark e do nicho (vão para Descobrir)
    ad_stats: dict = {}           # anúncios vistos/pulados e segundos de vídeo de verdade
    seen: set[str] = set()        # já julgados (não paga duas vezes)
    watched: list[str] = []
    visited: set[str] = set()     # canais visitados

    def choose(cands: list[tuple[str, str]]) -> list[str]:
        """Do que apareceu: o que é do nicho (juiz) e dark (classificação do canal). Grava em Descobrir na hora."""
        new = list(dict.fromkeys(v for v, _ in cands if v not in seen))
        seen.update(new)
        if not new or job.stopped():
            return []
        meta = {m["video_id"]: m for m in youtube_api.fetch_videos(new, key)}
        items = [(v, m["title"], f"{(m.get('channel_title') or '?')[:40]} | {round((m.get('duration_s') or 0) / 60)} min")
                 for v in new if (m := meta.get(v)) and (m.get("duration_s") or 0) > config.SHORT_MAX_SECONDS]
        notes = ai.judge_relevance(topic, items) if items else {}
        good = [v for v, *_ in items if notes.get(v, 0) >= MIN_RELEVANCE]
        if not good:
            return []
        ts = jobs.now_iso()
        with db.tx() as con:
            for v in good:
                con.execute("INSERT OR IGNORE INTO videos(video_id, title, first_seen_at) VALUES(?,?,?)",
                            (v, meta[v]["title"], ts))
        jobs.enrich(None, good, key)                    # números e canais no banco
        jobs.classify_new_channels(video_ids=good)      # dark ou não (uma vez por canal, fica guardado)
        dark = _dark_map(good)
        keep = [v for v in good if dark.get(v) is not False]
        with db.tx() as con:
            for v in keep:
                if v not in found:
                    m = meta[v]
                    hours = max((time.time() - _ts(m.get("published_at"))) / 3600, 1) if m.get("published_at") else None
                    found[v] = {"rel": notes[v], "channel_id": m.get("channel_id"), "views": m.get("views") or 0,
                                "vph": (m.get("views") or 0) / hours if hours else 0}
                    con.execute("INSERT OR IGNORE INTO sightings(run_id, video_id, position, surface) VALUES(?,?,?, 'garimpo')",
                                (run_id, v, len(found)))
        return sorted(keep, key=lambda v: (-found[v]["rel"], -found[v]["vph"]))

    def pick(cands: list[str], n: int) -> list[str]:
        """Os próximos a abrir: não assistidos, no máximo 1 por canal."""
        out, chans = [], set()
        for v in cands:
            ch = found.get(v, {}).get("channel_id")
            if v in watched or v in out or (ch and ch in chans):
                continue
            out.append(v)
            chans.add(ch)
            if len(out) >= n:
                break
        return out

    note = None
    try:
        from playwright.sync_api import sync_playwright
        args = list(_ARGS) + ([] if show_browser else ["--window-position=-32000,-32000"])
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(pdir), channel="chrome", headless=False, viewport={"width": 1400, "height": 900},
                args=args, ignore_default_args=["--enable-automation"])
            try:
                # ---------------------------------------------------------------- 2. ponto de partida
                if seed_vid:
                    choose([(seed_vid, label)])   # o vídeo de partida também conta (e o canal dele entra na visita)
                    frontier = [seed_vid]
                    choose_first = []
                else:
                    job.update(0.05, f"Pesquisando \"{query}\" no YouTube do perfil...")
                    choose_first = choose(_search(ctx, query))
                    frontier = pick(choose_first, per_round)
                    if not frontier:
                        raise RuntimeError("A busca no perfil não trouxe vídeos dark desse nicho. Tente outro termo "
                                           "ou cole o link de um vídeo dark do nicho.")

                # ---------------------------------------------------------------- 3. rodadas
                pool = list(choose_first)   # candidatos ainda não abertos, do melhor para o pior
                # Quando os sugeridos secam (perfil frio), faz o que o editor faz: pesquisa o tema ou um título.
                refill = iter(dict.fromkeys(prof["queries"] + prof["variants"][:3]))

                def top_up(front: list[str]) -> list[str]:
                    while len(front) < per_round and not job.stopped():
                        q = next(refill, None)
                        if q is None:
                            break
                        job.update(None, f"Pesquisando \"{q}\" no perfil para achar mais vídeos do nicho...")
                        pool.extend(v for v in choose(_search(ctx, q)) if v not in pool)
                        front = pick(pool, per_round)
                    return front

                for rnd in range(1, rounds + 1):
                    if rnd > 1:
                        frontier = top_up(frontier)
                    if not frontier or job.stopped():
                        break
                    base = 0.08 + 0.72 * (rnd - 1) / rounds
                    job.update(base, f"Rodada {rnd}/{rounds}: assistindo {len(frontier)} vídeos do nicho "
                                     f"({watch_s}s, juntos e sem som) · {len(found)} achados")
                    sugg = _watch(ctx, frontier, watch_s, job, ad_stats)
                    watched.extend(frontier)
                    cands = [x for lst in sugg.values() for x in lst]
                    job.update(base + 0.72 / rounds * 0.5,
                               f"Rodada {rnd}/{rounds}: IA escolhendo os sugeridos dark do nicho ({len(cands)} vistos)...")
                    kept = choose(cands)
                    pool[:] = kept + [v for v in pool if v not in kept and v not in watched]

                    # canais: os mais fortes da rodada que ainda não foram visitados
                    chans = []
                    for v in kept + frontier:
                        ch = found.get(v, {}).get("channel_id")
                        if ch and ch not in visited and ch not in chans:
                            chans.append(ch)
                    for ch in chans[:n_channels]:
                        if job.stopped():
                            break
                        visited.add(ch)
                        job.update(None, f"Rodada {rnd}/{rounds}: entrando num canal do nicho e assistindo os mais vistos...")
                        page = _open(ctx, f"https://www.youtube.com/channel/{ch}/videos")
                        if page:
                            page.wait_for_timeout(3000)
                            page.close()
                        ups = choose(youtube_api.fetch_uploads(ch, key, CHANNEL_UPLOADS))
                        ups += [v for v, f in found.items() if f["channel_id"] == ch and v not in ups]
                        best = sorted([v for v in ups if v not in watched], key=lambda v: -found[v]["views"])[:per_channel]
                        if best:
                            _watch(ctx, best, watch_s, job, ad_stats)
                            watched.extend(best)
                    frontier = pick(pool, per_round)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass

        with db.tx() as con:
            con.execute("UPDATE runs SET finished_at=?, status='done', logged_in=0, videos_found=? WHERE id=?",
                        (jobs.now_iso(), len(found), run_id))
        if found and not job.stopped():
            jobs.check_ai_labels(job, lo=0.82, hi=0.86)

        # ---------------------------------------------------------------- 4. a home, já aquecida
        home = None
        if not job.stopped():
            job.update(0.87, "Coletando a home do perfil (já aquecida no nicho)...")
            time.sleep(2)   # o Chrome solta o perfil um instante depois de fechar
            try:
                home = jobs.collect(job, profile_id, HOME_SCROLLS, show_browser, "home")
            except Exception as e:   # o garimpo já está salvo; a home é um extra
                note = f"A coleta da home no fim falhou: {e}"
        msg = (f"Garimpo de \"{label[:60]}\": {len(watched)} vídeos assistidos, {len(visited)} canais visitados, "
               f"{len(found)} vídeos dark do nicho achados" + (f", home com {home['videos']} vídeos" if home else "") + "."
               + (f" Anúncios em {ad_stats['ads']} vídeos ({ad_stats.get('skipped', 0)} pulados); o tempo deles não contou."
                  if ad_stats.get("ads") else ""))
        job.update(1.0, msg)
        return {"run_id": run_id, "videos": len(found), "watched": len(watched),
                "note": (msg + (f" {note}" if note else "")) if not job.stopped() else
                f"Garimpo cancelado: {len(found)} vídeos guardados."}
    except Exception as e:
        with db.tx() as con:
            con.execute("UPDATE runs SET finished_at=?, status=?, error=?, videos_found=? WHERE id=?",
                        (jobs.now_iso(), "done" if found else "error", str(e), len(found), run_id))
        raise


def _ts(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
