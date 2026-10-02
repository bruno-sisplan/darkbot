"""Pesquisa de mercado: como uma pessoa garimpando o próximo vídeo para modelar.

Parte de um vídeo de referência (navega pelos sugeridos) ou de palavras-chave (busca os melhores e os mais
recentes). Depois puxa os números pela API, confere o selo de IA, classifica os canais, lê os comentários dos
vídeos principais e, se pedido, gera o relatório com o Sonnet. Tudo fica guardado para reaproveitar
(ex.: gerar títulos e descrições depois); nada é reprocessado.
"""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import ai, analytics, config, db, jobs, titles, viral, youtube_api, youtube_web

# Buscas feitas para cada palavra-chave: (ordem, período, rótulo).
SEARCHES = [
    ("data", "semana", "busca:recente"),      # o que acabou de sair
    ("views", "mes", "busca:top-mes"),        # o que mais explodiu no mês
    ("views", "ano", "busca:top-ano"),        # as referências do ano
]
FOREIGN_SEARCHES = SEARCHES[:2]   # em outros idiomas: o recente e o top do mês (o que importa para modelar agora)
FOREIGN_QUERIES = 3               # buscas por idioma estrangeiro
HISTORY_SEEDS = 5                 # vídeos do histórico que têm os sugeridos abertos
DEEP_ROUNDS = 3             # camadas de "sugeridos dos sugeridos" (só a partir dos vídeos relevantes)
PAGES_PER_ROUND = 12        # vídeos relevantes que têm os sugeridos abertos em cada camada (os que mais viralizam)
COMPETITOR_CHANNELS = 15    # canais concorrentes que têm os uploads recentes lidos (1 unidade de cota cada)
COMPETITOR_UPLOADS = 30
# Páginas lidas de cada lista (o "carregar mais" do site, sem cota): ~20 vídeos por página.
SEARCH_PAGES = {"views": 3, "data": 2, "relevancia": 2}
FOREIGN_PAGES = 2
SEED_RELATED_PAGES = 3      # sugeridos do vídeo de partida
RELATED_PAGES = 2           # sugeridos de cada vídeo relevante nas camadas
LEARN_QUERIES = 8           # buscas novas aprendidas com o que está viralizando (bola de neve)
COMMENT_VIDEOS = 6          # vídeos que têm os comentários lidos
COMMENTS_PER_VIDEO = 100
REPORT_VIDEOS = 30          # vídeos que entram no relatório
REPORT_COMMENTS = 15        # comentários por vídeo que entram no relatório


def _vph(m: dict | None) -> float:
    """Views por hora desde a postagem (números da API)."""
    if not m or m.get("views") is None or not m.get("published_at"):
        return 0.0
    h = viral.hours_since(m["published_at"]) or 0
    return m["views"] / max(h, 1)


def _judge_topic(prof: dict, extra: str = "") -> str:
    """Critério do juiz em dois níveis: a premissa (nota 3) e o MESMO ASSUNTO com outra premissa (nota 2).
    Só "o mesmo público até assiste" não basta (era isso que enchia Descobrir de coisa fora do nicho)."""
    return (f"NOTA 3 (concorrente direto): {prof['topic']} (premissa: {prof['angle']}; formato: {prof['format']}). "
            f"NOTA 2 (mesmo nicho): vídeo sobre o MESMO ASSUNTO ({prof['theme']}) com outra premissa ou outro formato, ou "
            f"sobre uma variação equivalente que o público do nicho trata como a mesma coisa (ex.: amish e menonitas). "
            f"Assunto diferente que só lembra o tema (outro grupo sem relação, outro objeto, notícia geral) = 1 ou 0. "
            f"{extra}").strip()


def niche_topic(niche: str, examples: list[str]) -> str:
    """Critério do juiz para o nicho de um PERFIL. O nicho é o ASSUNTO (ex.: amish): qualquer vídeo cujo assunto
    principal é esse vale nota 2, seja qual for a premissa. Os vídeos que o editor já usou como referência só definem a
    nota 3 (antes eles viravam o critério inteiro e "comida amish" ficava fora de um nicho "amish")."""
    ex = "; ".join(f"\"{t}\"" for t in examples[:12])
    return (f"O NICHO do perfil é o assunto: {niche}. "
            f"NOTA 3: mesmo assunto E mesma premissa/formato dos vídeos que o editor já usa como referência"
            + (f" ({ex})" if ex else "") + ". "
            f"NOTA 2: QUALQUER vídeo cujo assunto principal é {niche}, com qualquer premissa (vida, costumes, comida, casa, "
            f"trabalho, história, curiosidades, notícias), ou sobre uma variação equivalente que o público desse nicho trata "
            f"como a mesma coisa (ex.: amish e menonitas). "
            f"Se o título trata de {niche} (ou da variação equivalente), a nota é no mínimo 2, mesmo que o canal seja de "
            f"pessoa. NOTA 1: só lembra o assunto (outro grupo, lugar ou objeto parecido, sem ser {niche}). "
            f"NOTA 0: outro assunto.")


def niche_check(job: jobs.Job | None, profile_id: int, video_ids: list[str] | None = None) -> int:
    """Confere com a IA se os vídeos são do NICHO do perfil (uma vez por vídeo). Perfil coringa ou sem nicho: nada."""
    p = db.row("SELECT kind, niche FROM profiles WHERE id=?", (profile_id,))
    niche = ((p or {}).get("niche") or "").strip()
    if not p or p["kind"] == "coringa" or not niche or not ai.enabled():
        return 0
    key = analytics.niche_key(profile_id)   # o nicho + os exemplos: mudar qualquer um refaz a conferência
    if video_ids is None:
        video_ids = [r["video_id"] for r in db.rows(
            "SELECT DISTINCT s.video_id FROM sightings s JOIN runs r ON r.id = s.run_id WHERE r.profile_id = ?", (profile_id,))]
    done = {r["video_id"] for r in db.rows("SELECT video_id FROM niche_fit WHERE profile_id=? AND niche=?",
                                           (profile_id, key))}
    todo = [v for v in dict.fromkeys(video_ids) if v not in done]
    if not todo:
        return 0
    rows = db.rows(f"""SELECT v.video_id, v.title, v.channel_title, v.duration_s FROM videos v
                       WHERE v.title IS NOT NULL AND v.is_short = 0 AND v.video_id IN ({','.join('?' * len(todo))})""", todo)
    if not rows:
        return 0
    if job:
        job.update(None, f"IA conferindo se {len(rows)} vídeos são do nicho do perfil ({niche})...")
    notes = ai.judge_relevance(niche_topic(niche, analytics.niche_examples(profile_id)), [
        (r["video_id"], r["title"], f"{(r['channel_title'] or '?')[:40]} | {round((r['duration_s'] or 0) / 60)} min")
        for r in rows])
    with db.tx() as con:
        con.executemany("INSERT OR REPLACE INTO niche_fit(profile_id, video_id, niche, fit) VALUES(?,?,?,?)",
                        [(profile_id, r["video_id"], key, notes.get(r["video_id"], 0)) for r in rows])
    return len(rows)


def collect_and_check(job: jobs.Job, profile_id: int, scrolls: int, show_browser: bool, source: str = "home") -> dict:
    """Coleta (home ou histórico) + confere o nicho do que veio (a home de um perfil frio traz de tudo)."""
    res = jobs.collect(job, profile_id, scrolls, show_browser, source)
    if not job.stopped():
        ids = [r["video_id"] for r in db.rows("SELECT video_id FROM sightings WHERE run_id=?", (res["run_id"],))]
        try:
            n = niche_check(job, profile_id, ids)
            if n:
                res["note"] = ((res.get("note") or "") + f" Nicho conferido em {n} vídeos.").strip()
        except ai.AIError as e:
            print(f"[coleta] conferir nicho: {e}")
    return res


def _known_not_dark(channel_ids: set) -> set:
    """Canais que já se sabe que NÃO são dark (classificação da IA ou marcação do editor)."""
    ids = [c for c in channel_ids if c]
    if not ids:
        return set()
    rows = db.rows(f"""SELECT channel_id, dark AS channel_dark, dark_conf AS channel_dark_conf,
                              dark_manual AS channel_dark_manual, format AS channel_format, 0 AS channel_ai
                       FROM channels WHERE channel_id IN ({','.join('?' * len(ids))})
                         AND (dark IS NOT NULL OR dark_manual IS NOT NULL)""", ids)
    return {r["channel_id"] for r in rows if analytics.is_dark(r) is False}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def channel_lang() -> str:
    return db.get_setting("channel_lang") or "português do Brasil"


def create(kind: str, seed: str, label: str, langs: list[str] | None = None, profile_id: int | None = None) -> int:
    with db.tx() as con:
        return con.execute(
            "INSERT INTO research(kind, seed, label, status, created_at, langs, profile_id) "
            "VALUES(?,?,?, 'running', ?, ?, ?)",
            (kind, seed, label, now_iso(), json.dumps(langs or ["pt"]), profile_id),
        ).lastrowid


def lang_code(lang: str | None, title: str = "") -> str:
    """Código de ai.LANGUAGES a partir do idioma da API (ex.: 'en-US' -> 'en'); sem idioma, adivinha pelo título."""
    code = (lang or "").split("-")[0].lower()
    if code in ai.LANGUAGES:
        return code
    return "pt" if _PT_HINT.search(title or "") else "en"


class _Pool:
    """Candidatos da pesquisa: id -> como foi achado + título (para o juiz) + nota de relevância."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def add(self, vid, title, via, depth, keyword=None) -> bool:
        if not vid or vid in self.items:
            return False
        self.items[vid] = {"title": title or "", "via": via, "depth": depth, "keyword": keyword,
                           "position": len(self.items) + 1, "relevance": None, "expanded": False}
        return True

    def unjudged(self):
        return [(vid, it["title"]) for vid, it in self.items.items() if it["relevance"] is None]

    def relevant(self, min_r=2):
        return {vid: it for vid, it in self.items.items() if (it["relevance"] or 0) >= min_r}


def run(job: jobs.Job, research_id: int, want_report: bool) -> dict:
    r = db.row("SELECT * FROM research WHERE id=?", (research_id,))
    pool = _Pool()
    try:
        _discover(job, r, research_id, pool)
        found = {vid: it for vid, it in pool.items.items() if (it["relevance"] or 0) >= 1}
        if not found:
            raise RuntimeError("A pesquisa foi cancelada antes de achar vídeos." if job.stopped()
                               else "A pesquisa não achou vídeos relevantes para esse tema.")
        _save(research_id, found)
        _enrich(job, list(found), lambda: _apply_period(research_id, r.get("max_age_days")))
        if not job.stopped():
            # Etapas independentes rodando juntas: classificar canais + traduzir; depois os comentários
            # (que dependem de saber quais canais são dark).
            # Tradução não é automática (é o que mais custava): fica no botão "Traduzir títulos" e na prévia.
            if ai.enabled():
                job.update(0.8, "IA classificando os canais dos vídeos relevantes...")
                vp = viral.get()
                cands = [x["video_id"] for x in db.rows(
                    f"SELECT video_id, views, published_at FROM videos WHERE video_id IN ({','.join('?' * len(found))})",
                    list(found)) if (x["views"] or 0) >= vp["min_views"] * 0.5
                    and (viral.hours_since(x["published_at"]) or 1e9) <= vp["max_days"] * 24]
                jobs.classify_new_channels(video_ids=cands)
        if want_report and not job.stopped():   # comentários só servem ao relatório (que é sob demanda)
            _fetch_comments(job, research_id)

        note = None
        if want_report and ai.enabled() and not job.stopped():
            job.update(0.9, "IA escrevendo o relatório (pode levar 1 a 2 minutos)...")
            try:
                make_report(research_id)
            except (ai.AIError, RuntimeError) as e:
                note = f"Pesquisa salva, mas o relatório falhou: {e}"

        videos = analytics.research_videos(research_id)
        status = "cancelled" if job.stopped() else "done"
        with db.tx() as con:
            con.execute("UPDATE research SET status=?, finished_at=?, videos_found=? WHERE id=?",
                        (status, now_iso(), len(videos), research_id))
        send_to_discoveries(research_id)   # tudo num lugar só: os achados aparecem em Descobrir
        if job.stopped():
            note = f"Pesquisa cancelada: {len(videos)} vídeos guardados."
        direct = sum(1 for v in videos if (v.get("relevance") or 0) >= 3)
        job.update(1.0, f"{len(videos)} vídeos relevantes ({direct} concorrentes diretos)")
        return {"research_id": research_id, "videos": len(videos), "note": note}
    except Exception as e:
        with db.tx() as con:
            con.execute("UPDATE research SET status='error', finished_at=?, error=? WHERE id=?",
                        (now_iso(), str(e), research_id))
        raise


def _discover(job: jobs.Job, r: dict, research_id: int, pool: _Pool) -> None:
    """Garimpo em camadas, como um pesquisador: entende o tema, busca variações em vários idiomas, julga a
    relevância de tudo, aprofunda pelos sugeridos SÓ dos relevantes e olha os uploads recentes dos concorrentes."""
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("A pesquisa precisa da chave da API do YouTube (Configurações).")
    langs: list[str] = json.loads(r["langs"] or '["pt"]') or ["pt"]
    keywords: list[str] = json.loads(r["keywords"] or "[]")
    variants: list[str] = []
    primary = langs[0] if langs else "pt"
    seeds: list[str] = []          # vídeos de partida (sugeridos abertos já na 1ª rodada)
    topic = ""
    max_days = r.get("max_age_days")
    vp = viral.get()
    # Abaixo disso o vídeo não vira oportunidade tão cedo: nem gasta IA (bem abaixo do mínimo e sem ritmo).
    floor_views, floor_vph = vp["min_views"] * 0.3, 30
    meta: dict[str, dict] = {}     # números da API de cada candidato (1 unidade de cota a cada 50 vídeos)

    def prefilter(todo: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
        """Antes de pagar a IA: data e duração pela API (quase de graça). Short, vídeo removido e o que está fora do
        período saem na hora (sairiam no fim de qualquer jeito). O resto vai para o juiz com canal e duração."""
        need = [vid for vid, _ in todo if vid not in meta]
        for m in youtube_api.fetch_videos(need, key) if need else []:
            meta[m["video_id"]] = m
        # Canal que já se sabe NÃO dark (classificado antes ou marcado pelo editor): com "só dark" nos parâmetros,
        # o vídeo nunca aparece; não paga IA por ele.
        not_dark = _known_not_dark({(meta.get(v) or {}).get("channel_id") for v, _ in todo}) if vp["only_dark"] else set()
        keep = []
        for vid, title in todo:
            m = meta.get(vid)
            age = analytics._age_days(m.get("published_at")) if m else None
            if not m or (m.get("duration_s") or 0) <= config.SHORT_MAX_SECONDS or (max_days and (age or 0) > max_days) \
                    or ((m.get("views") or 0) < floor_views and _vph(m) < floor_vph) or m.get("channel_id") in not_dark:
                pool.items[vid]["relevance"] = 0
                continue
            keep.append((vid, m.get("title") or title,
                         f"{(m.get('channel_title') or '?')[:40]} | {round((m.get('duration_s') or 0) / 60)} min"))
        return keep

    def judge(stage: str) -> None:
        todo = pool.unjudged()
        if not todo or job.stopped():
            return
        found_n = len(todo)
        todo = prefilter(todo)
        if not todo:
            return
        job.update(None, f"IA separando o que tem a ver ({len(todo)} vídeos no período, de {found_n} achados · {stage})...")
        if not ai.enabled():
            for vid, *_ in todo:
                pool.items[vid]["relevance"] = 2
            return
        notes = ai.judge_relevance(topic, todo)
        for vid, *_ in todo:
            pool.items[vid]["relevance"] = notes.get(vid, 0)

    def save_topic(prof: dict) -> None:
        with db.tx() as con:
            con.execute("UPDATE research SET topic=? WHERE id=?", (json.dumps(
                {k: prof[k] for k in ("theme", "format", "angle", "topic", "variants")}, ensure_ascii=False),
                research_id))

    with youtube_web.client() as c:
        # ---------------------------------------------------------------- 1. entender o ponto de partida
        if r["kind"] == "video":
            job.update(0.02, "Lendo o vídeo de referência...")
            info = (youtube_api.fetch_videos([r["seed"]], key) or [{}])[0]
            if not info:
                raise RuntimeError("Não encontrei esse vídeo no YouTube. Confira o link.")
            primary = lang_code(info.get("lang"), info.get("title"))
            with db.tx() as con:
                con.execute("UPDATE research SET label=? WHERE id=?", (info["title"], research_id))
            pool.add(r["seed"], info["title"], "semente", 0)
            pool.items[r["seed"]]["relevance"] = 3
            seeds = [r["seed"]]
            if ai.enabled():
                job.update(0.05, "IA entendendo o tema, o formato e o ângulo do vídeo...")
                prof = ai.seed_profile(r["seed"], info["title"], info.get("channel_title") or "",
                                       info.get("description") or "", info.get("tags") or [], primary)
                topic = _judge_topic(prof, f"Vídeo de referência: \"{info['title']}\".")
                keywords, variants = prof["queries"][:6], prof["variants"][:8]
                save_topic(prof)
            else:
                keywords = [info["title"]]
                topic = f"vídeos parecidos com \"{info['title']}\""
        elif r["kind"] == "history":
            job.update(0.03, "Lendo o histórico do perfil...")
            hist = db.rows(
                """SELECT v.video_id, v.title, v.lang FROM sightings s JOIN runs ru ON ru.id = s.run_id
                   JOIN videos v ON v.video_id = s.video_id
                   WHERE ru.profile_id = ? AND ru.source = 'history' AND ru.status = 'done'
                     AND v.is_short = 0 AND v.title IS NOT NULL
                   GROUP BY v.video_id ORDER BY MAX(ru.id) DESC, MIN(s.position) LIMIT 40""",
                (r["profile_id"],))
            if not hist:
                raise RuntimeError("Esse perfil ainda não tem histórico coletado. Use 'Coletar histórico' no card do perfil.")
            for h in hist:
                pool.add(h["video_id"], h["title"], "historico", 0)
            seeds = [h["video_id"] for h in hist[:HISTORY_SEEDS]]
            topic = ("vídeos do mesmo nicho que o editor assistiu recentemente: "
                     + "; ".join(h["title"] for h in hist[:12]))
            if ai.enabled():
                job.update(0.05, "IA achando o centro do nicho pelo histórico...")
                text = "Vídeos assistidos (os do topo são os mais recentes):\n" + "\n".join(f"- {h['title']}" for h in hist)
                try:
                    prof = ai.research_brief(f"history:{research_id}", "history", text, ai.LANGUAGES[primary][2])
                    topic = _judge_topic(prof)
                    keywords, variants = prof["queries"][:6], prof["variants"][:4]
                    save_topic(prof)
                except ai.AIError as e:
                    print(f"[pesquisa] briefing do histórico: {e}")
        else:
            topic = "vídeos sobre: " + ", ".join(keywords)
            if ai.enabled() and keywords:
                job.update(0.04, "IA montando o briefing da pesquisa (tema, formato, buscas do público)...")
                lang_name = ai.LANGUAGES[primary][2]
                text = "O editor pesquisou: " + "; ".join(keywords)
                target = "kw:" + hashlib.sha1(f"{lang_name}|{text.lower()}".encode()).hexdigest()[:16]
                try:
                    prof = ai.research_brief(target, "keyword", text, lang_name)
                    topic = _judge_topic(prof, f"O editor pesquisou: {', '.join(keywords)}.")
                    keywords = list(dict.fromkeys(keywords + prof["queries"]))[:8]   # as do editor vêm primeiro
                    variants = prof["variants"][:6]
                    save_topic(prof)
                except ai.AIError as e:
                    print(f"[pesquisa] briefing: {e}")

        with db.tx() as con:
            con.execute("UPDATE research SET keywords=? WHERE id=?",
                        (json.dumps(keywords + variants, ensure_ascii=False), research_id))

        # ---------------------------------------------------------------- 2. buscas (idioma do vídeo + os escolhidos)
        hl, gl, _ = ai.LANGUAGES[primary]
        searches, foreign_searches, var_upload = search_plan(r.get("max_age_days"))
        plan = [(primary, v, ("relevancia", var_upload, "busca:variacao")) for v in variants]
        plan += [(primary, kw, s) for kw in keywords for s in searches]
        others = [l for l in langs if l != primary]
        if others and ai.enabled() and not job.stopped():
            job.update(0.08, f"IA adaptando títulos e buscas para {len(others)} idioma(s)...")
            try:
                local = ai.localize_queries(variants[:3] + keywords[:3], others)
            except ai.AIError as e:
                print(f"[pesquisa] buscas em outros idiomas: {e}")
                local = {}
            for lang, qs in local.items():
                plan += [(lang, q, ("relevancia", var_upload, "busca:variacao")) for q in qs[:3]]
                plan += [(lang, q, s) for q in qs[3:6] for s in foreign_searches]

        def do_search(item):
            lang, kw, (sort, upload, _via) = item
            lhl, lgl, _n = ai.LANGUAGES.get(lang, ai.LANGUAGES["pt"])
            pages = SEARCH_PAGES.get(sort, 2) if lang == primary else FOREIGN_PAGES
            return youtube_web.search(c, kw, sort, upload, lhl, lgl, pages=pages)

        def related_of(vid: str, pages: int):
            """Sugeridos abertos como um visitante do país do vídeo (o mercado dele, não o da pesquisa)."""
            m = meta.get(vid) or {}
            code = lang_code(m.get("lang"), m.get("title") or "") if m else primary
            vhl, vgl, _n = ai.LANGUAGES.get(code, ai.LANGUAGES[primary])
            return youtube_web.related(c, vid, vhl, vgl, pages=pages)[1]

        job.update(0.1, f"Rodando {len(plan)} buscas e abrindo os sugeridos...")
        jobs_list = [("rel", s) for s in seeds] + [("search", p) for p in plan]

        def gather(item):
            kind, payload = item
            return youtube_web.related(c, payload, hl, gl, pages=SEED_RELATED_PAGES)[1] if kind == "rel" \
                else do_search(payload)

        for (kind, payload), results in zip(jobs_list, _parallel(job, jobs_list, gather)):
            for vid, title in results:
                if kind == "rel":
                    pool.add(vid, title, "sugerido", 1)
                else:
                    pool.add(vid, title, payload[2][2], 1, payload[1])
        for s in seeds:
            pool.items[s]["expanded"] = True

        # ---------------------------------------------------------------- 3. juiz + buscas aprendidas + camadas
        judge("1ª camada")

        # Bola de neve: o que está viralizando na 1ª camada ensina o que buscar a seguir (como um pesquisador faz).
        hot = sorted([v for v, it in pool.items.items() if (it["relevance"] or 0) >= 2 and v in meta],
                     key=lambda v: -_vph(meta[v]))[:30]
        if hot and ai.enabled() and not job.stopped():
            job.update(0.14, "IA aprendendo com o que está viralizando: buscas novas...")
            done = list(dict.fromkeys(kw for _l, kw, _s in plan))
            try:
                learned = ai.learn_queries(
                    topic, done, [(lang_code(meta[v].get("lang"), meta[v]["title"]), meta[v]["title"], round(_vph(meta[v])))
                                  for v in hot], list(dict.fromkeys([primary] + langs)), LEARN_QUERIES)
            except ai.AIError as e:
                print(f"[pesquisa] buscas aprendidas: {e}")
                learned = []
            if learned and not job.stopped():
                lplan = [(l, q, (sort, var_upload, "busca:aprendida")) for l, q in learned
                         for sort in ("views", "relevancia")]
                job.update(0.15, f"Rodando {len(lplan)} buscas aprendidas: {', '.join(q for _l, q in learned[:4])}...")
                for item, results in zip(lplan, _parallel(job, lplan, do_search)):
                    for vid, title in results:
                        pool.add(vid, title, "busca:aprendida", 1, item[1])
                keywords += [q for _l, q in learned]
                with db.tx() as con:
                    con.execute("UPDATE research SET keywords=? WHERE id=?",
                                (json.dumps(keywords + variants, ensure_ascii=False), research_id))
                judge("buscas aprendidas")

        for depth in range(2, 2 + DEEP_ROUNDS):
            if job.stopped():
                break
            # Abre primeiro os sugeridos dos que mais viralizam agora (é onde o algoritmo está empurrando).
            frontier = sorted(
                [(vid, it) for vid, it in pool.items.items() if not it["expanded"] and (it["relevance"] or 0) >= 2],
                key=lambda x: (-_vph(meta.get(x[0])), -(x[1]["relevance"] or 0)))[:PAGES_PER_ROUND]
            if not frontier:
                break
            job.update(0.15 + 0.08 * (depth - 1), f"Entrando nos sugeridos de {len(frontier)} vídeos relevantes "
                                                   f"(camada {depth})...")
            for vid, _ in frontier:
                pool.items[vid]["expanded"] = True
            for results in _parallel(job, [vid for vid, _ in frontier], lambda v: related_of(v, RELATED_PAGES)):
                for vid, title in results:
                    pool.add(vid, title, "sugerido", depth)
            judge(f"camada {depth}")

    # ---------------------------------------------------------------- 4. uploads recentes dos concorrentes
    if job.stopped():
        return
    rel = pool.relevant(2)
    job.update(0.42, "Identificando os canais concorrentes...")
    need = [vid for vid in rel if vid not in meta]   # quase tudo já veio no pré-filtro
    for m in youtube_api.fetch_videos(need, key) if need else []:
        meta[m["video_id"]] = m
    count: dict[str, int] = {}
    for vid in rel:
        m = meta.get(vid) or {}
        if m.get("channel_id"):   # concorrente direto vale mais; vídeo explodindo agora vale mais ainda
            w = (2 if rel[vid]["relevance"] >= 3 else 1) * (2 if _vph(m) >= 100 else 1)
            count[m["channel_id"]] = count.get(m["channel_id"], 0) + w
    top_channels = [cid for cid, _ in sorted(count.items(), key=lambda x: -x[1])[:COMPETITOR_CHANNELS]]
    if top_channels and not job.stopped():
        job.update(0.45, f"Lendo os uploads recentes de {len(top_channels)} canais concorrentes...")
        with ThreadPoolExecutor(len(top_channels)) as ex:
            uploads = list(ex.map(lambda cid: youtube_api.fetch_uploads(cid, key, COMPETITOR_UPLOADS), top_channels))
        for ups in uploads:
            for vid, title in ups:
                pool.add(vid, title, "canal:recente", 1)
        judge("uploads dos concorrentes")


def search_plan(max_age_days: int | None):
    """Buscas pelo período dos parâmetros: (buscas no idioma principal, buscas nos outros idiomas, filtro das variações).

    Tudo com o filtro de data do YouTube no período e o MAIS VISTO primeiro: o que está viralizando agora.
    Para períodos curtos entra também "hoje" por views (o que está explodindo nas últimas horas)."""
    up = viral.upload_filter(max_age_days)
    if up is None:
        return SEARCHES, FOREIGN_SEARCHES, None
    s = [("views", up, "busca:top"), ("data", up, "busca:recente"), ("relevancia", up, "busca:relevante")]
    if max_age_days and max_age_days <= 7 and up != "hoje":
        s.insert(1, ("views", "hoje", "busca:top-hoje"))
    return s, s[:2], up


def _apply_period(research_id: int, max_age_days: int | None) -> None:
    """Tira da pesquisa os vídeos publicados antes do período escolhido (o vídeo de referência fica)."""
    if not max_age_days:
        return
    with db.tx() as con:
        con.execute(
            """DELETE FROM research_videos WHERE research_id = ? AND via != 'semente' AND video_id IN
               (SELECT video_id FROM videos WHERE published_at IS NOT NULL AND
                julianday('now') - julianday(published_at) > ?)""", (research_id, max_age_days))
        db.purge_orphans(con)


def send_to_discoveries(research_id: int) -> dict:
    """A pesquisa vira uma coleta (marcada como pesquisa) do perfil dela: os vídeos do tema aparecem em Descobrir,
    onde os parâmetros de viral do editor filtram e ordenam. Refazer atualiza a mesma coleta."""
    r = db.row("SELECT * FROM research WHERE id=?", (research_id,))
    # Só o mesmo nicho (nota 2 = mesmo assunto, 3 = mesma premissa). Nota 1 ("só lembra o tema") enchia Descobrir
    # de coisa fora do nicho.
    good = {v["video_id"] for v in analytics.research_videos(research_id) if (v.get("relevance") or 2) >= 2}
    vids = [v for v in db.rows("SELECT video_id, position FROM research_videos WHERE research_id=? ORDER BY position",
                               (research_id,)) if v["video_id"] in good]
    old = db.row("SELECT id FROM runs WHERE research_id=?", (research_id,))
    ts = now_iso()
    with db.tx() as con:
        if old:
            run_id = old["id"]
            con.execute("DELETE FROM sightings WHERE run_id=?", (run_id,))
            con.execute("UPDATE runs SET finished_at=?, videos_found=? WHERE id=?", (ts, len(vids), run_id))
        else:
            run_id = con.execute(
                "INSERT INTO runs(profile_id, started_at, finished_at, status, logged_in, videos_found, source, research_id) "
                "VALUES(?, ?, ?, 'done', 1, ?, 'research', ?)", (r["profile_id"], ts, ts, len(vids), research_id)).lastrowid
        con.executemany("INSERT OR IGNORE INTO sightings(run_id, video_id, position, surface) VALUES(?,?,?, 'research')",
                        [(run_id, v["video_id"], i) for i, v in enumerate(vids, 1)])
    if r["profile_id"] and vids:
        try:
            niche_check(None, r["profile_id"], [v["video_id"] for v in vids])
        except ai.AIError as e:
            print(f"[pesquisa] conferir nicho: {e}")
    return {"run_id": run_id, "videos": len(vids), "existing": bool(old)}


def _save(research_id: int, found: dict) -> None:
    ts = now_iso()
    with db.tx() as con:
        for vid, f in found.items():
            con.execute("INSERT OR IGNORE INTO videos(video_id, title, first_seen_at) VALUES(?,?,?)",
                        (vid, f.get("title") or None, ts))
            con.execute(
                "INSERT OR IGNORE INTO research_videos(research_id, video_id, via, depth, keyword, position, relevance) "
                "VALUES(?,?,?,?,?,?,?)",
                (research_id, vid, f["via"], f["depth"], f["keyword"], f["position"], f.get("relevance")),
            )


def _enrich(job: jobs.Job, ids: list[str], after_numbers=None) -> None:
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("A pesquisa precisa da chave da API do YouTube (Configurações).")
    job.update(0.5, f"Buscando números de {len(ids)} vídeos...")
    jobs.enrich(None, ids, key)
    if after_numbers:
        after_numbers()   # ex.: corta o que está fora do período antes de abrir páginas à toa
    if job.stopped():
        return
    job.update(0.6, "Verificando selo de IA...")
    jobs.check_ai_labels(job, lo=0.6, hi=0.75)


def _parallel(job: jobs.Job, items: list, fn, on_done=None) -> list:
    """Roda fn(item) em paralelo (páginas do YouTube) e devolve na ordem dos itens. Respeita o cancelar."""
    def safe(item):
        if job.stopped():
            return []
        try:
            return fn(item)
        finally:
            if on_done:
                on_done()
    with ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        return list(pool.map(safe, items))


def _top(research_id: int, n: int) -> list[dict]:
    vids = [v for v in analytics.research_videos(research_id) if v["score"] is not None]
    return sorted(vids, key=lambda v: v["score"], reverse=True)[:n]


def _fetch_comments(job: jobs.Job, research_id: int) -> None:
    """Comentários dos vídeos com mais oportunidade (cada vídeo uma vez só; 1 unidade de cota por vídeo)."""
    key = jobs.youtube_api_key()
    p = viral.get()
    todo = [v for v in _top(research_id, COMMENT_VIDEOS * 4)
            if v["via"] == "semente" or ((v.get("relevance") or 2) >= 2 and v["is_dark"])]
    todo = sorted(todo, key=lambda v: (v["via"] != "semente", not viral.passes(v, p)))[:COMMENT_VIDEOS]
    fetched = {r["video_id"] for r in db.rows(
        "SELECT video_id FROM videos WHERE comments_fetched_at IS NOT NULL AND video_id IN (%s)"
        % ",".join("?" * len(todo)), [v["video_id"] for v in todo])} if todo else set()
    todo = [v for v in todo if v["video_id"] not in fetched]
    if not todo or job.stopped():
        return
    job.update(0.85, f"Lendo comentários de {len(todo)} vídeos (em paralelo)...")
    with ThreadPoolExecutor(len(todo)) as pool:
        all_cms = list(pool.map(lambda v: youtube_api.fetch_comments(v["video_id"], key, COMMENTS_PER_VIDEO), todo))
    for v, cms in zip(todo, all_cms):
        with db.tx() as con:
            con.executemany(
                "INSERT OR IGNORE INTO comments(comment_id, video_id, text, likes, replies, published_at) "
                "VALUES(:comment_id, :video_id, :text, :likes, :replies, :published_at)", cms,
            )
            con.execute("UPDATE videos SET comments_fetched_at=? WHERE video_id=?", (now_iso(), v["video_id"]))


def top_comments(video_id: str, n: int) -> list[dict]:
    return db.rows("SELECT text, likes FROM comments WHERE video_id=? ORDER BY likes DESC LIMIT ?", (video_id, n))


def _fmt_n(x) -> str:
    return "?" if x is None else f"{x:,}".replace(",", ".")


def build_payload(research_id: int) -> str:
    """O mínimo que o Sonnet precisa, já mastigado: tabela dos melhores, padrões de título e comentários."""
    r = db.row("SELECT * FROM research WHERE id=?", (research_id,))
    all_videos = analytics.research_videos(research_id)
    # Só o que tem a ver com o tema (nota 2 ou 3 do juiz; pesquisas antigas não têm nota e entram).
    p = viral.get()
    on_topic = [v for v in all_videos if (v.get("relevance") or 2) >= 2 and viral.passes(v, p)]
    below = not on_topic   # nada bate a régua: o relatório usa os melhores mesmo assim, e a IA fica sabendo
    on_topic = on_topic or [v for v in all_videos if (v.get("relevance") or 2) >= 2 and v["potential"]] or all_videos
    dark = [v for v in on_topic if v["is_dark"]] or on_topic
    top = sorted([v for v in dark if v["score"] is not None], key=lambda v: v["score"], reverse=True)[:REPORT_VIDEOS]
    if len(top) < 5:
        raise RuntimeError("Poucos vídeos com números para um relatório (a pesquisa precisa da API do YouTube).")

    lines = [
        f"# Pesquisa: {r['label']}",
        f"Origem: {'vídeo de referência [' + r['seed'] + ']' if r['kind'] == 'video' else 'histórico do perfil (o que o editor assistiu)' if r['kind'] == 'history' else 'palavras-chave'}",
        *([f"O que conta como concorrente: {t['topic']}", f"Tema: {t['theme']} · formato: {t['format']} · "
           f"premissa: {t['angle']}"] if (t := json.loads(r["topic"]) if r.get("topic") else None) else []),
        f"Buscas usadas: {', '.join(json.loads(r['keywords'] or '[]')) or '-'}",
        f"Idiomas pesquisados: {', '.join(ai.LANGUAGES[l][2] for l in (json.loads(r['langs'] or 'null') or ['pt']) if l in ai.LANGUAGES)}",
        f"Idioma do canal do editor: {channel_lang()}",
        f"Régua de viral do editor (o que conta como viralizando agora): {viral.describe(p)}",
        f"Vídeos encontrados: {len(all_videos)} (dark: {len([v for v in all_videos if v['is_dark']])}; "
        f"no tema e dentro da régua: {0 if below else len(on_topic)}).",
        ("ATENÇÃO: nenhum vídeo bate a régua do editor; abaixo estão os melhores do tema mesmo assim. Diga isso no "
         "summary e seja cauteloso." if below else
         f"Abaixo, os {len(top)} que mais ganham views por hora dentro da régua (do mais forte para o mais fraco)."),
        "",
        "## Vídeos (id | título | canal | idioma | relevância 3=direto 2=tema | formato do canal | selo IA | views "
        "| views por hora | inscritos | mult | idade em horas | duração min)",
    ]
    for v in top:
        lines.append(" | ".join([
            v["video_id"], ((v["title"] or "") + (f" (tradução: {v['title_pt']})" if v.get("title_pt")
                                                   and v["title_pt"] != v["title"] else "")).replace("|", "/"),
            (v["channel_title"] or "").replace("|", "/"), (v["lang"] or "?"), str(v.get("relevance") or "?"),
            ai.FORMAT_LABELS.get(v["channel_format"] or "", "?"), "sim" if v["channel_ai"] else "não",
            _fmt_n(v["views"]), _fmt_n(v.get("views_hour")), _fmt_n(v["subs"]), f"{v['multiplier']}x",
            str(round(v.get("age_hours") or 0)), str(round((v["duration_s"] or 0) / 60)),
        ]))

    pat = titles.analyze(dark)
    if pat.get("ok"):
        lines += ["", f"## Padrões de título (outliers = top {pat['n_top']} de {pat['total']}, "
                      f"multiplicador ≥ {pat['cut']}x)",
                  f"Tamanho mediano: {pat['length']['chars_top']} caracteres nos outliers vs "
                  f"{pat['length']['chars_rest']} no resto."]
        for f in pat["features"][:6]:
            lines.append(f"- {f['label']}: {f['pct_top']}% dos outliers vs {f['pct_rest']}% do resto")
        if pat["words"]:
            lines.append("Palavras que puxam: " + ", ".join(w["term"] for w in pat["words"][:15]))
        if pat["openings"]:
            lines.append("Aberturas comuns: " + ", ".join(o["term"] for o in pat["openings"][:8]))

    with_comments = [v for v in top if v["comments_saved"]][:COMMENT_VIDEOS]
    if with_comments:
        lines += ["", "## Comentários do público (mais curtidos)"]
        for v in with_comments:
            lines.append(f"### [{v['video_id']}] {v['title']}")
            for cm in top_comments(v["video_id"], REPORT_COMMENTS):
                text = " ".join(cm["text"].split())[:220]
                lines.append(f"- ({cm['likes']} curtidas) {text}")
    return "\n".join(lines)


def make_report(research_id: int, refresh: bool = False) -> dict:
    return ai.research_report(research_id, build_payload(research_id), channel_lang(), refresh=refresh)


_PT_HINT = re.compile(r"[ãõçêâ]|\b(que|não|você|como|para|uma|dos|das|mais|isso|sobre)\b", re.I)


def is_foreign(v: dict) -> bool:
    lang = (v.get("lang") or "").lower()
    if lang:
        return not lang.startswith("pt")
    return not _PT_HINT.search(v.get("title") or "")


def translate_foreign(video_ids: list[str]) -> int:
    """Traduz (uma vez) os títulos que não estão em português."""
    if not video_ids:
        return 0
    rows = db.rows("SELECT video_id, title, lang FROM videos WHERE title_pt IS NULL AND title IS NOT NULL "
                   "AND video_id IN (%s)" % ",".join("?" * len(video_ids)), video_ids)
    todo = [r for r in rows if is_foreign(r)]
    if not todo:
        return 0
    try:
        return ai.translate_titles(todo)
    except ai.AIError as e:
        print(f"[pesquisa] tradução: {e}")
        return 0


def report_job(job: jobs.Job, research_id: int) -> dict:
    """Relatório sob demanda: lê os comentários dos melhores vídeos (se ainda não leu) e escreve."""
    _fetch_comments(job, research_id)
    job.update(0.2, "IA escrevendo o relatório (pode levar 1 a 2 minutos)...")
    make_report(research_id, refresh=True)
    job.update(1.0, "Relatório pronto")
    return {"research_id": research_id}
