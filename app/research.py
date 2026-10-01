"""Pesquisa de mercado: como uma pessoa garimpando o próximo vídeo para modelar.

Parte de um vídeo de referência (navega pelos sugeridos) ou de palavras-chave (busca os melhores e os mais
recentes). Depois puxa os números pela API, confere o selo de IA, classifica os canais, lê os comentários dos
vídeos principais e, se pedido, gera o relatório com o Sonnet. Tudo fica guardado para reaproveitar
(ex.: gerar títulos e descrições depois); nada é reprocessado.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import ai, analytics, config, db, jobs, titles, youtube_api, youtube_web

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
PAGES_PER_ROUND = 10        # vídeos relevantes que têm os sugeridos abertos em cada camada
COMPETITOR_CHANNELS = 8     # canais concorrentes que têm os uploads recentes lidos (1 unidade de cota cada)
COMPETITOR_UPLOADS = 20
COMMENT_VIDEOS = 6          # vídeos que têm os comentários lidos
COMMENTS_PER_VIDEO = 100
REPORT_VIDEOS = 30          # vídeos que entram no relatório
REPORT_COMMENTS = 15        # comentários por vídeo que entram no relatório


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
                jobs.classify_new_channels(video_ids=[v for v, f in found.items() if (f.get("relevance") or 0) >= 2])
        if not job.stopped():
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
                topic = (f"{prof['topic']} (tema: {prof['theme']}; formato: {prof['format']}; "
                         f"ângulo: {prof['angle']}; vídeo de referência: \"{info['title']}\")")
                keywords, variants = prof["queries"][:6], prof["variants"][:8]
                with db.tx() as con:
                    con.execute("UPDATE research SET topic=? WHERE id=?", (json.dumps(
                        {k: prof[k] for k in ("theme", "format", "angle", "topic", "variants")}, ensure_ascii=False),
                        research_id))
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
            if not keywords and ai.enabled():
                job.update(0.05, "IA achando o centro do nicho pelo histórico...")
                keywords = ai.history_keywords(f"history:{research_id}", [h["title"] for h in hist])
            topic = ("vídeos do mesmo nicho que o editor assistiu recentemente: "
                     + "; ".join(h["title"] for h in hist[:12]))
        else:
            topic = "vídeos sobre: " + ", ".join(keywords)

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
            return youtube_web.search(c, kw, sort, upload, lhl, lgl)

        job.update(0.1, f"Rodando {len(plan)} buscas e abrindo os sugeridos...")
        jobs_list = [("rel", s) for s in seeds] + [("search", p) for p in plan]

        def gather(item):
            kind, payload = item
            return youtube_web.related(c, payload, hl, gl)[1] if kind == "rel" else do_search(payload)

        for (kind, payload), results in zip(jobs_list, _parallel(job, jobs_list, gather)):
            for vid, title in results:
                if kind == "rel":
                    pool.add(vid, title, "sugerido", 1)
                else:
                    pool.add(vid, title, payload[2][2], 1, payload[1])
        for s in seeds:
            pool.items[s]["expanded"] = True

        # ---------------------------------------------------------------- 3. juiz + aprofundar pelos relevantes
        def judge(stage: str):
            todo = pool.unjudged()
            if not todo or job.stopped():
                return
            job.update(None, f"IA separando o que tem a ver ({len(todo)} vídeos · {stage})...")
            if not ai.enabled():
                for vid, _ in todo:
                    pool.items[vid]["relevance"] = 2
                return
            notes = ai.judge_relevance(topic, todo)
            for vid, _ in todo:
                pool.items[vid]["relevance"] = notes.get(vid, 0)

        judge("1ª camada")
        for depth in range(2, 2 + DEEP_ROUNDS):
            if job.stopped():
                break
            frontier = sorted(
                [(vid, it) for vid, it in pool.items.items() if not it["expanded"] and (it["relevance"] or 0) >= 2],
                key=lambda x: (-(x[1]["relevance"] or 0), x[1]["position"]))[:PAGES_PER_ROUND]
            if not frontier:
                break
            job.update(0.15 + 0.08 * (depth - 1), f"Entrando nos sugeridos de {len(frontier)} vídeos relevantes "
                                                   f"(camada {depth})...")
            for vid, _ in frontier:
                pool.items[vid]["expanded"] = True
            for results in _parallel(job, [vid for vid, _ in frontier], lambda v: youtube_web.related(c, v, hl, gl)[1]):
                for vid, title in results:
                    pool.add(vid, title, "sugerido", depth)
            judge(f"camada {depth}")

    # ---------------------------------------------------------------- 4. uploads recentes dos concorrentes
    if job.stopped():
        return
    rel = pool.relevant(2)
    job.update(0.42, "Identificando os canais concorrentes...")
    meta = {v["video_id"]: v for v in youtube_api.fetch_videos(list(rel), key)}
    count: dict[str, int] = {}
    for vid in rel:
        cid = (meta.get(vid) or {}).get("channel_id")
        if cid:
            count[cid] = count.get(cid, 0) + (2 if rel[vid]["relevance"] >= 3 else 1)
    top_channels = [cid for cid, _ in sorted(count.items(), key=lambda x: -x[1])[:COMPETITOR_CHANNELS]]
    if top_channels and not job.stopped():
        job.update(0.45, f"Lendo os uploads recentes de {len(top_channels)} canais concorrentes...")
        with ThreadPoolExecutor(len(top_channels)) as ex:
            uploads = list(ex.map(lambda cid: youtube_api.fetch_uploads(cid, key, COMPETITOR_UPLOADS), top_channels))
        for ups in uploads:
            for vid, title in ups:
                pool.add(vid, title, "canal:recente", 1)
        todo = pool.unjudged()
        if todo and ai.enabled():
            job.update(0.47, f"IA separando o que tem a ver ({len(todo)} uploads dos concorrentes)...")
            notes = ai.judge_relevance(topic, todo)
            for vid, _ in todo:
                pool.items[vid]["relevance"] = notes.get(vid, 0)


def search_plan(max_age_days: int | None):
    """Buscas por período: (buscas no idioma principal, buscas nos outros idiomas, filtro das variações)."""
    if max_age_days and max_age_days <= 7:
        s = [("data", "semana", "busca:recente"), ("views", "semana", "busca:top-semana"),
             ("relevancia", "semana", "busca:relevante")]
        return s, s[:2], "semana"
    if max_age_days and max_age_days <= 31:
        s = [("data", "semana", "busca:recente"), ("views", "mes", "busca:top-mes"),
             ("relevancia", "mes", "busca:relevante")]
        return s, s[:2], "mes"
    if max_age_days and max_age_days <= 366:
        return SEARCHES, FOREIGN_SEARCHES, "ano"
    return SEARCHES, FOREIGN_SEARCHES, None


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
    todo = [v for v in _top(research_id, COMMENT_VIDEOS * 3)
            if v["via"] == "semente" or ((v.get("relevance") or 2) >= 2 and v["is_dark"])]
    todo = todo[:COMMENT_VIDEOS]
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
    on_topic = [v for v in all_videos if (v.get("relevance") or 2) >= 2 and v["potential"]] or \
        [v for v in all_videos if (v.get("relevance") or 2) >= 2] or all_videos
    dark = [v for v in on_topic if v["is_dark"]] or on_topic
    top = sorted([v for v in dark if v["score"] is not None], key=lambda v: v["score"], reverse=True)[:REPORT_VIDEOS]
    if len(top) < 5:
        raise RuntimeError("Poucos vídeos com números para um relatório (a pesquisa precisa da API do YouTube).")

    lines = [
        f"# Pesquisa: {r['label']}",
        f"Origem: {'vídeo de referência [' + r['seed'] + ']' if r['kind'] == 'video' else 'histórico do perfil (o que o editor assistiu)' if r['kind'] == 'history' else 'palavras-chave'}",
        *([f"O que o editor procura (definido a partir do vídeo de referência): {json.loads(r['topic'])['topic']}"]
          if r.get("topic") else []),
        f"Buscas usadas: {', '.join(json.loads(r['keywords'] or '[]')) or '-'}",
        f"Idiomas pesquisados: {', '.join(ai.LANGUAGES[l][2] for l in json.loads(r['langs'] or '[\"pt\"]') if l in ai.LANGUAGES)}",
        f"Idioma do canal do editor: {channel_lang()}",
        f"Período: {'últimos ' + str(r['max_age_days']) + ' dias' if r.get('max_age_days') else 'qualquer data'}",
        f"Vídeos encontrados: {len(all_videos)} (dark: {len([v for v in all_videos if v['is_dark']])}; "
        f"com potencial e no tema: {len(on_topic)}). "
        f"Abaixo, os {len(top)} com mais oportunidade (multiplicador ponderado pela recência).",
        "",
        "## Vídeos (id | título | canal | idioma | relevância 3=direto 2=tema | formato do canal | selo IA | views "
        "| inscritos | mult | idade em dias | views/dia | duração min)",
    ]
    for v in top:
        lines.append(" | ".join([
            v["video_id"], ((v["title"] or "") + (f" (tradução: {v['title_pt']})" if v.get("title_pt")
                                                   and v["title_pt"] != v["title"] else "")).replace("|", "/"),
            (v["channel_title"] or "").replace("|", "/"), (v["lang"] or "?"), str(v.get("relevance") or "?"),
            ai.FORMAT_LABELS.get(v["channel_format"] or "", "?"), "sim" if v["channel_ai"] else "não",
            _fmt_n(v["views"]), _fmt_n(v["subs"]), f"{v['multiplier']}x", str(round(v["age_days"] or 0)),
            _fmt_n(v["views_day"]), str(round((v["duration_s"] or 0) / 60)),
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
    job.update(0.2, "IA escrevendo o relatório (pode levar 1 a 2 minutos)...")
    make_report(research_id, refresh=True)
    job.update(1.0, "Relatório pronto")
    return {"research_id": research_id}


def variations_payload(video_id: str) -> str:
    """Dados para a IA estimar a chance de cada variação viralizar: o vídeo, vídeos parecidos com números reais
    (das pesquisas que têm esse vídeo), idiomas onde já foi feito (Método Malandro) e comentários do público."""
    from . import malandro
    v = analytics.video_detail(video_id)
    if not v:
        raise RuntimeError("Vídeo não encontrado.")
    lines = [
        f"# Vídeo que viralizou: {v['title']}",
        f"Canal: {v['channel_title']} ({_fmt_n(v['subs'])} inscritos) · {_fmt_n(v['views'])} views · "
        f"viralizou {v['multiplier']}x · postado há {round(v['age_days'] or 0)} dias · idioma {v['lang'] or '?'}",
    ]
    prof = ai.cached(ai.SEED_KIND, f"video:{video_id}")
    if prof:
        lines.append(f"Assunto: {prof['theme']} · Tipo: {prof['format']} · Gancho: {prof['angle']}")

    rids = [r["research_id"] for r in db.rows("SELECT DISTINCT research_id FROM research_videos WHERE video_id=?",
                                              (video_id,))]
    similar: dict[str, dict] = {}
    for rid in rids:
        for x in analytics.research_videos(rid):
            if (x.get("relevance") or 2) >= 2 and x["video_id"] != video_id and x["multiplier"] is not None:
                similar[x["video_id"]] = x
    top = sorted(similar.values(), key=lambda x: -(x["score"] or 0))[:30]
    if top:
        lines += ["", "## Vídeos parecidos (título | idioma | viralizou | views | dias desde que postou)"]
        lines += [f"- {x['title']} | {x['lang'] or '?'} | {x['multiplier']}x | {_fmt_n(x['views'])} | "
                  f"{round(x['age_days'] or 0)}" for x in top]
    else:
        lines += ["", "(Sem vídeos parecidos pesquisados ainda: estime com cuidado.)"]

    mal = malandro.get(video_id)
    if mal:
        lines += ["", "## Em que idiomas esse vídeo já foi feito (Método Malandro)"]
        lines += [f"- {l['name']}: {l['channels']} canal(is) fizeram ({l['status']})" for l in mal["langs"]]

    cms = top_comments(video_id, 12)
    if cms:
        lines += ["", "## Comentários mais curtidos do vídeo"]
        lines += [f"- ({c['likes']}) {' '.join(c['text'].split())[:200]}" for c in cms]
    return "\n".join(lines)
