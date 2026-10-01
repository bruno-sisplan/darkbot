"""API local que a interface consome. Só lê dados prontos do banco; trabalho pesado vai para `jobs`."""
import json
import os
import re
import shutil
import unicodedata
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, analytics, chrome_profiles, config, db, jobs, malandro, proximos, research, titles, youtube_api, youtube_web
from .paths import PROFILES_DIR, UI_DIR

app = FastAPI(title="darkbot")


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:40] or "perfil"


def _new_profile_dir(name: str) -> Path:
    base = PROFILES_DIR / _slug(name)
    path, n = base, 2
    while path.exists():
        path, n = Path(f"{base}-{n}"), n + 1
    return path


# ---------------------------------------------------------------- perfis

class ProfileIn(BaseModel):
    name: str
    kind: str = "nicho"
    niche: str | None = None
    chrome_folder: str | None = None   # se vier, importa do Chrome


@app.get("/api/profiles")
def list_profiles():
    profs = db.rows(
        """SELECT p.*, (SELECT COUNT(*) FROM runs r WHERE r.profile_id = p.id AND r.status='done') AS runs,
                  (SELECT COUNT(DISTINCT s.video_id) FROM sightings s JOIN runs r ON r.id = s.run_id
                   WHERE r.profile_id = p.id) AS videos
           FROM profiles p ORDER BY p.created_at DESC"""
    )
    for p in profs:
        p["in_use"] = chrome_profiles.profile_in_use(Path(p["dir"]))
    return profs


@app.post("/api/profiles")
def create_profile(body: ProfileIn):
    if not body.name.strip():
        raise HTTPException(400, "Dê um nome ao perfil.")
    if body.chrome_folder and chrome_profiles.chrome_profile_open(body.chrome_folder):
        raise HTTPException(409, chrome_profiles._OPEN_MSG)
    pdir = _new_profile_dir(body.name)
    source = f"import:{body.chrome_folder}" if body.chrome_folder else "novo"
    with db.tx() as con:
        pid = con.execute(
            "INSERT INTO profiles(name, kind, niche, source, dir) VALUES(?,?,?,?,?)",
            (body.name.strip(), body.kind, (body.niche or "").strip() or None, source, str(pdir)),
        ).lastrowid
    if body.chrome_folder:
        job = jobs.start("import", f"Importando {body.name}", jobs.import_profile, pid, body.chrome_folder)
        return {"id": pid, "job": job.to_dict()}
    pdir.mkdir(parents=True, exist_ok=True)
    return {"id": pid}


@app.patch("/api/profiles/{pid}")
def update_profile(pid: int, body: ProfileIn):
    with db.tx() as con:
        con.execute(
            "UPDATE profiles SET name=?, kind=?, niche=?, niche_auto=0 WHERE id=?",
            (body.name.strip(), body.kind, (body.niche or "").strip() or None, pid),
        )
    return {"ok": True}


@app.delete("/api/profiles/{pid}")
def delete_profile(pid: int):
    p = db.row("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Perfil não encontrado.")
    if chrome_profiles.profile_in_use(Path(p["dir"])):
        raise HTTPException(409, "Feche a janela do Chrome desse perfil antes de excluir.")
    with db.tx() as con:
        con.execute("DELETE FROM profiles WHERE id=?", (pid,))
    shutil.rmtree(p["dir"], ignore_errors=True)
    return {"ok": True}


@app.post("/api/profiles/{pid}/open")
def open_profile(pid: int):
    p = db.row("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Perfil não encontrado.")
    try:
        chrome_profiles.open_for_login(Path(p["dir"]))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class CollectIn(BaseModel):
    scrolls: int = config.DEFAULT_SCROLLS
    show_browser: bool = False
    source: str = "home"      # 'home' ou 'history'


class TrainIn(BaseModel):
    query: str | None = None


@app.post("/api/profiles/{pid}/train")
def train_profile(pid: int, body: TrainIn):
    """Abre o Chrome do perfil já na busca do nicho: o editor assiste e o algoritmo aprende."""
    p = db.row("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Perfil não encontrado.")
    if chrome_profiles.profile_in_use(Path(p["dir"])):
        raise HTTPException(409, "Esse perfil já está aberto numa janela do Chrome.")
    q = (body.query or p["niche"] or "").strip()
    if not q:
        raise HTTPException(400, "Defina o nicho do perfil (lápis no card) ou escreva o que treinar.")
    from urllib.parse import quote_plus
    try:
        chrome_profiles.open_for_login(Path(p["dir"]), f"https://www.youtube.com/results?search_query={quote_plus(q)}")
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "query": q}


@app.post("/api/profiles/{pid}/collect")
def collect(pid: int, body: CollectIn):
    p = db.row("SELECT name FROM profiles WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Perfil não encontrado.")
    try:
        job = jobs.start(
            "collect", f"{'Histórico' if body.source == 'history' else 'Coletando'} · {p['name']}", jobs.collect, pid,
            max(1, min(body.scrolls, config.MAX_SCROLLS)), body.show_browser,
            "history" if body.source == "history" else "home", key=f"profile:{pid}",
            cancellable=True,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.to_dict()


@app.get("/api/chrome-profiles")
def chrome_list():
    return {
        "chrome_found": chrome_profiles.find_chrome() is not None,
        "profiles": chrome_profiles.list_chrome_profiles(),
    }


@app.get("/api/chrome-profiles/{folder}/niche")
def chrome_niche(folder: str, email: str = "", refresh: bool = False):
    """Sugere o nicho de um perfil do Chrome pelo histórico local (uma vez; depois vem do cache)."""
    if not ai.enabled():
        return {"ok": False, "reason": "IA desligada (sem chave da Anthropic)."}
    target = f"chrome:{folder}:{email}"
    titles = [] if (ai.cached(ai.NICHE_KIND, target) and not refresh) else chrome_profiles.youtube_history_titles(folder)
    try:
        return {"ok": True, **ai.detect_niche(target, titles, refresh=refresh)}
    except ai.AIError as e:
        return {"ok": False, "reason": str(e)}


# ---------------------------------------------------------------- pesquisa de mercado

class ResearchIn(BaseModel):
    kind: str                 # 'video', 'keyword' ou 'history'
    seed: str = ""            # link/ID do vídeo ou palavras-chave (uma por linha ou separadas por vírgula)
    report: bool = True
    langs: list[str] = ["pt"]  # idiomas da busca (códigos de ai.LANGUAGES)
    profile_id: int | None = None  # para kind='history'
    max_age_days: int | None = 30  # período: só vídeos publicados nos últimos N dias (None = qualquer data)


@app.post("/api/research")
def research_start(body: ResearchIn):
    if not jobs.youtube_api_key():
        raise HTTPException(400, "A pesquisa precisa da chave da API do YouTube (Configurações).")
    langs = [l for l in body.langs if l in ai.LANGUAGES] or ["pt"]
    # Cada pesquisa pertence ao perfil em uso: só aparece nele.
    pid = body.profile_id if body.profile_id and db.row("SELECT 1 FROM profiles WHERE id=?", (body.profile_id,)) else None
    if body.kind == "video":
        vid = youtube_web.parse_video_id(body.seed)
        if not vid:
            raise HTTPException(400, "Não reconheci esse link de vídeo do YouTube.")
        rid = research.create("video", vid, "Vídeo " + vid, langs, pid)
    elif body.kind == "history":
        p = db.row("SELECT name FROM profiles WHERE id=?", (body.profile_id,))
        if not p:
            raise HTTPException(400, "Escolha um perfil.")
        rid = research.create("history", str(body.profile_id), f"Histórico · {p['name']}", langs, body.profile_id)
    else:
        kws = [k.strip() for k in re.split(r"[,\n;]", body.seed) if k.strip()][:6]
        if not kws:
            raise HTTPException(400, "Escreva pelo menos uma palavra-chave.")
        rid = research.create("keyword", ", ".join(kws), ", ".join(kws), langs, pid)
        with db.tx() as con:
            con.execute("UPDATE research SET keywords=? WHERE id=?", (json.dumps(kws, ensure_ascii=False), rid))
    with db.tx() as con:
        con.execute("UPDATE research SET max_age_days=? WHERE id=?", (body.max_age_days or None, rid))
    job = jobs.start("research", "Pesquisa de mercado", research.run, rid, body.report and ai.enabled(),
                     cancellable=True)
    return {"id": rid, "job": job.to_dict()}


@app.get("/api/research")
def research_list(profile_id: int | None = None):
    """Pesquisas do perfil em uso (e as antigas, de antes da separação por perfil, marcadas como 'sem perfil')."""
    if profile_id:
        rows = db.rows("SELECT * FROM research WHERE profile_id = ? OR profile_id IS NULL ORDER BY id DESC", (profile_id,))
    else:
        rows = db.rows("SELECT * FROM research ORDER BY id DESC")
    for r in rows:
        r["has_report"] = ai.cached(ai.REPORT_KIND, f"research:{r['id']}") is not None
        r["keywords"] = json.loads(r["keywords"] or "[]")
    return rows


@app.get("/api/research/{rid}")
def research_detail(rid: int):
    r = db.row("SELECT * FROM research WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Pesquisa não encontrada.")
    r["keywords"] = json.loads(r["keywords"] or "[]")
    r["topic"] = json.loads(r["topic"]) if r.get("topic") else None
    run = db.row("SELECT id FROM runs WHERE research_id=? ORDER BY id DESC LIMIT 1", (rid,))
    r["run_id"] = run["id"] if run else None
    videos = analytics.research_videos(rid)
    cost = db.row("SELECT cost_usd, created_at FROM ai_results WHERE kind=? AND target=?",
                  (ai.REPORT_KIND, f"research:{rid}"))
    return {
        "research": r,
        "videos": videos,
        "report": ai.cached(ai.REPORT_KIND, f"research:{rid}"),
        "report_meta": cost,
        "comments": {v["video_id"]: research.top_comments(v["video_id"], 8) for v in videos if v["comments_saved"]},
        "saturation": analytics.saturation(videos) if r["kind"] == "video" else [],
        "malandro": malandro.get(r["seed"]) if r["kind"] == "video" else None,
        "variations": ai.cached(ai.VARIATIONS_KIND, f"video:{r['seed']}") if r["kind"] == "video" else None,
        "format_labels": ai.FORMAT_LABELS,
    }


class MoveIn(BaseModel):
    profile_id: int


@app.post("/api/research/{rid}/profile")
def research_move(rid: int, body: MoveIn):
    """Leva uma pesquisa (ex.: uma antiga, sem perfil) para um perfil."""
    with db.tx() as con:
        con.execute("UPDATE research SET profile_id=? WHERE id=?", (body.profile_id, rid))
        con.execute("UPDATE runs SET profile_id=? WHERE research_id=?", (body.profile_id, rid))
    return {"ok": True}


@app.post("/api/research/{rid}/to-discoveries")
def research_to_discoveries(rid: int):
    """Transforma a pesquisa numa coleta (marcada como pesquisa) para os vídeos aparecerem em Descobertas."""
    r = db.row("SELECT * FROM research WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Pesquisa não encontrada.")
    if r["status"] == "running":
        raise HTTPException(409, "Espere a pesquisa terminar (ou cancele).")
    old = db.row("SELECT id FROM runs WHERE research_id=?", (rid,))
    if old:
        return {"run_id": old["id"], "existing": True}
    good = {v["video_id"] for v in analytics.research_videos(rid)
            if v["potential"] and (v.get("relevance") or 2) >= 2}
    vids = [v for v in db.rows("SELECT video_id, position FROM research_videos WHERE research_id=? ORDER BY position",
                               (rid,)) if v["video_id"] in good]
    if not vids:
        raise HTTPException(400, "Essa pesquisa não tem vídeos relevantes para enviar.")
    ts = research.now_iso()
    with db.tx() as con:
        run_id = con.execute(
            "INSERT INTO runs(profile_id, started_at, finished_at, status, logged_in, videos_found, source, research_id) "
            "VALUES(?, ?, ?, 'done', 1, ?, 'research', ?)", (r["profile_id"], ts, ts, len(vids), rid)).lastrowid
        con.executemany("INSERT OR IGNORE INTO sightings(run_id, video_id, position, surface) VALUES(?,?,?, 'research')",
                        [(run_id, v["video_id"], i) for i, v in enumerate(vids, 1)])
    return {"run_id": run_id, "existing": False, "videos": len(vids)}


@app.post("/api/research/{rid}/report")
def research_report(rid: int):
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    try:
        job = jobs.start("report", "Relatório da pesquisa", research.report_job, rid, key=f"report:{rid}")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.to_dict()


@app.delete("/api/research/{rid}")
def research_delete(rid: int):
    r = db.row("SELECT status FROM research WHERE id=?", (rid,))
    if r and r["status"] == "running":
        raise HTTPException(409, "Essa pesquisa ainda está rodando. Cancele antes de excluir.")
    with db.tx() as con:
        con.execute("DELETE FROM research WHERE id=?", (rid,))
        con.execute("DELETE FROM research_videos WHERE research_id=?", (rid,))
        con.execute("DELETE FROM ai_results WHERE target=?", (f"research:{rid}",))
        gone = db.purge_orphans(con)
    return {"ok": True, **gone}


# ---------------------------------------------------------------- dados

@app.get("/api/videos")
def videos(profile_id: int | None = None, run_id: int | None = None, source: str | None = None):
    return analytics.videos(profile_id, run_id, source)


@app.get("/api/videos/{video_id}")
def video_detail(video_id: str):
    """Painel de prévia: dados, canal, comentários (busca na hora se ainda não tem; 1 unidade de cota) e análise."""
    v = analytics.video_detail(video_id)
    if not v:
        raise HTTPException(404, "Vídeo não encontrado.")
    key = jobs.youtube_api_key()
    if not v["comments_fetched_at"] and key:
        try:
            cms = youtube_api.fetch_comments(video_id, key, 100)
            with db.tx() as con:
                con.executemany(
                    "INSERT OR IGNORE INTO comments(comment_id, video_id, text, likes, replies, published_at) "
                    "VALUES(:comment_id, :video_id, :text, :likes, :replies, :published_at)", cms)
                con.execute("UPDATE videos SET comments_fetched_at=? WHERE video_id=?", (research.now_iso(), video_id))
        except youtube_api.YouTubeAPIError as e:
            print(f"[preview] comentários: {e}")
    v["tags"] = json.loads(v["tags"]) if v.get("tags") else []
    v["foreign"] = research.is_foreign(v)
    return {
        "video": v,
        "comments": research.top_comments(video_id, 30),
        "analysis": ai.cached(ai.VIDEO_KIND, f"video:{video_id}"),
        "malandro": malandro.get(video_id),
        "variations": ai.cached(ai.VARIATIONS_KIND, f"video:{video_id}"),
        "format_labels": ai.FORMAT_LABELS,
    }


class AnalyzeIn(BaseModel):
    refresh: bool = False


@app.post("/api/videos/{video_id}/analyze")
def video_analyze(video_id: str, body: AnalyzeIn):
    """Análise do vídeo com a IA (Sonnet, com a thumbnail). Uma vez por vídeo; 'refresh' refaz."""
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    v = analytics.video_detail(video_id)
    if not v:
        raise HTTPException(404, "Vídeo não encontrado.")
    cms = research.top_comments(video_id, 25)
    text = "\n".join([
        f"Título: {v['title']}" + (f" (tradução: {v['title_pt']})" if v.get("title_pt") and v["title_pt"] != v["title"] else ""),
        f"Canal: {v['channel_title']} · {v['subs'] or '?'} inscritos · canal com {v['channel_age_days'] or '?'} dias "
        f"· formato: {ai.FORMAT_LABELS.get(v['channel_format'] or '', '?')} · selo IA: {'sim' if v['channel_ai'] else 'não'}",
        f"Números: {v['views'] or '?'} views · {v['likes'] or '?'} likes · {v['comments'] or '?'} comentários · "
        f"multiplicador {v['multiplier'] or '?'}x · {v['views_day'] or '?'} views/dia · publicado há "
        f"{round(v['age_days'] or 0)} dias · duração {round((v['duration_s'] or 0) / 60)} min · idioma {v['lang'] or '?'}",
        f"Descrição: {' '.join((v['description'] or '-').split())[:900]}",
        "Comentários mais curtidos:",
        *[f"- ({c['likes']}) {' '.join(c['text'].split())[:220]}" for c in cms],
    ])
    try:
        return ai.analyze_video(video_id, text, research.channel_lang(), refresh=body.refresh)
    except ai.AIError as e:
        raise HTTPException(400, str(e))


@app.get("/api/malandro/{video_id}")
def malandro_get(video_id: str):
    return {"result": malandro.get(video_id)}


@app.post("/api/malandro/{video_id}")
def malandro_run(video_id: str):
    """Roda (ou refaz) o Método Malandro do vídeo. O resultado fica guardado."""
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    try:
        return jobs.start("malandro", "Método Malandro", malandro.run, video_id, key=f"malandro:{video_id}",
                          cancellable=True).to_dict()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/videos/{video_id}/variations")
def video_variations(video_id: str, body: AnalyzeIn):
    """Ideias de variações do título com chance de viralizar (Sonnet). Uma vez por vídeo; 'refresh' refaz."""
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    try:
        return ai.title_variations(video_id, research.variations_payload(video_id), research.channel_lang(),
                                   refresh=body.refresh)
    except (ai.AIError, RuntimeError) as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- Meu canal (o "após": modelados, DNA, mapa, próximos)

class ModeledIn(BaseModel):
    profile_id: int
    video: str | None = None      # link ou ID do vídeo original
    my_title: str | None = None   # título que o editor usou (opcional)


@app.get("/api/modeled")
def modeled_list(profile_id: int):
    return proximos.modeled(profile_id)


@app.post("/api/modeled")
def modeled_add(body: ModeledIn):
    vid = youtube_web.parse_video_id(body.video) if body.video else None
    if body.video and not vid:
        raise HTTPException(400, "Link de vídeo inválido.")
    try:
        return {"id": proximos.modeled_add(body.profile_id, vid, body.my_title)}
    except (ValueError, RuntimeError, youtube_api.YouTubeAPIError) as e:
        raise HTTPException(400, str(e))


class MyTitleIn(BaseModel):
    my_title: str | None = None


@app.patch("/api/modeled/{item_id}")
def modeled_edit(item_id: int, body: MyTitleIn):
    with db.tx() as con:
        con.execute("UPDATE modeled SET my_title=? WHERE id=?", (" ".join((body.my_title or "").split()) or None, item_id))
    return {"ok": True}


@app.delete("/api/modeled/{item_id}")
def modeled_delete(item_id: int):
    with db.tx() as con:
        con.execute("DELETE FROM modeled WHERE id=?", (item_id,))
    return {"ok": True}


@app.get("/api/dna")
def dna_get(profile_id: int):
    return proximos.dna_get(profile_id)


@app.post("/api/dna/{profile_id}")
def dna_build(profile_id: int):
    """Refaz o DNA do canal a partir dos vídeos modelados (Sonnet, ~US$ 0,01)."""
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave em Configurações).")
    try:
        return proximos.dna_build(profile_id)
    except (ai.AIError, RuntimeError) as e:
        raise HTTPException(400, str(e))


class NotesIn(BaseModel):
    notes: str = ""


@app.post("/api/dna/{profile_id}/notes")
def dna_notes(profile_id: int, body: NotesIn):
    return proximos.dna_set_notes(profile_id, body.notes)


class NextIn(BaseModel):
    profile_id: int
    boldness: str = "equilibrado"   # perto, equilibrado, ousado


@app.post("/api/next")
def next_run(body: NextIn):
    """Mapa de território + próximos vídeos (buscas novas + IA). Roda em segundo plano; fica no histórico."""
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave em Configurações).")
    try:
        return jobs.start("next", "Meu canal: próximos vídeos", proximos.run, body.profile_id, body.boldness,
                          key=f"next:{body.profile_id}", cancellable=True).to_dict()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/next")
def next_list(profile_id: int):
    runs = proximos.runs(profile_id)
    return {"runs": runs, "latest": proximos.get(runs[0]["id"]) if runs else None, "kinds": proximos.KINDS,
            "boldness": {k: v[0] for k, v in proximos.BOLDNESS.items()}}


@app.get("/api/next/{run_id}")
def next_get(run_id: int):
    r = proximos.get(run_id)
    if not r:
        raise HTTPException(404, "Sugestão não encontrada.")
    return r


@app.delete("/api/next/{run_id}")
def next_delete(run_id: int):
    with db.tx() as con:
        con.execute("DELETE FROM next_runs WHERE id=?", (run_id,))
    return {"ok": True}


class QueueIn(BaseModel):
    profile_id: int
    title: str
    video_id: str | None = None
    kind: str | None = None
    note: str | None = None


@app.get("/api/queue")
def queue_list(profile_id: int):
    return proximos.queue(profile_id)


@app.post("/api/queue")
def queue_add(body: QueueIn):
    try:
        return {"id": proximos.queue_add(body.profile_id, body.title, body.video_id, body.kind, body.note)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/queue/{item_id}/done")
def queue_done(item_id: int):
    """Fiz o vídeo da fila: vira um vídeo modelado."""
    try:
        return {"modeled_id": proximos.queue_done(item_id)}
    except (ValueError, RuntimeError, youtube_api.YouTubeAPIError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/queue/{item_id}")
def queue_delete(item_id: int):
    with db.tx() as con:
        con.execute("DELETE FROM queue WHERE id=?", (item_id,))
    return {"ok": True}


class HideIn(BaseModel):
    hidden: bool = True


@app.post("/api/videos/{video_id}/hide")
def video_hide(video_id: str, body: HideIn):
    with db.tx() as con:
        con.execute("UPDATE videos SET hidden=? WHERE video_id=?", (1 if body.hidden else None, video_id))
    return {"ok": True}


@app.post("/api/videos/unhide-all")
def video_unhide_all():
    with db.tx() as con:
        n = con.execute("UPDATE videos SET hidden=NULL WHERE hidden=1").rowcount
    return {"ok": True, "videos": n}


class DarkIn(BaseModel):
    dark: bool | None = None   # True é dark, False não é, None volta para a IA


@app.post("/api/channels/{channel_id}/dark")
def channel_dark(channel_id: str, body: DarkIn):
    """Correção do editor. Vale na hora e vira exemplo para a IA classificar os próximos canais."""
    with db.tx() as con:
        con.execute("UPDATE channels SET dark_manual=? WHERE channel_id=?",
                    (None if body.dark is None else int(body.dark), channel_id))
    return {"ok": True}


@app.post("/api/channels/reclassify")
def channels_reclassify():
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    try:
        return jobs.start("reclassify", "Reclassificando canais", jobs.reclassify_channels, key="reclassify").to_dict()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


class TranslateIn(BaseModel):
    ids: list[str]


@app.post("/api/translate")
def translate(body: TranslateIn):
    if not ai.enabled():
        raise HTTPException(400, "IA desligada (sem chave da Anthropic).")
    n = research.translate_foreign(body.ids[:400])
    rows = db.rows("SELECT video_id, title_pt FROM videos WHERE title_pt IS NOT NULL AND video_id IN (%s)"
                   % ",".join("?" * len(body.ids[:400])), body.ids[:400]) if body.ids else []
    return {"translated": n, "titles": {r["video_id"]: r["title_pt"] for r in rows}}


@app.get("/api/languages")
def languages():
    return [{"code": k, "name": v[2]} for k, v in ai.LANGUAGES.items()]


@app.get("/api/channels")
def channels(profile_id: int | None = None):
    return analytics.channels(profile_id)


@app.get("/api/titles")
def title_patterns(profile_id: int | None = None, max_age: float = 0, outlier: str = "top20"):
    return titles.patterns(profile_id, max_age, outlier)


@app.get("/api/overview")
def overview():
    return analytics.overview()


@app.delete("/api/runs/{run_id}")
def run_delete(run_id: int):
    """Exclui uma coleta e tudo o que só existia nela (vídeos, números, comentários, canais)."""
    r = db.row("SELECT * FROM runs WHERE id=?", (run_id,))
    if not r:
        raise HTTPException(404, "Coleta não encontrada.")
    if r["status"] == "running":
        raise HTTPException(409, "Essa coleta ainda está rodando. Cancele antes de excluir.")
    pid = r["profile_id"]
    with db.tx() as con:
        con.execute("DELETE FROM sightings WHERE run_id=?", (run_id,))
        con.execute("DELETE FROM runs WHERE id=?", (run_id,))
        gone = db.purge_orphans(con)
        left = con.execute("SELECT MAX(finished_at) FROM runs WHERE profile_id=? AND status='done'", (pid,)).fetchone()[0]
        con.execute("UPDATE profiles SET last_run_at=? WHERE id=?", (left, pid))
        if not left:
            # Sem coletas: o nicho que a IA tirou delas perde a base. Some e é detectado de novo na próxima.
            con.execute("UPDATE profiles SET niche=NULL WHERE id=? AND niche_auto=1", (pid,))
            con.execute("UPDATE profiles SET niche_auto=NULL WHERE id=?", (pid,))
            con.execute("DELETE FROM ai_results WHERE target=?", (f"profile:{pid}",))
    return {"ok": True, **gone}


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    if not jobs.cancel(job_id):
        raise HTTPException(409, "Essa tarefa não pode ser cancelada (ou já terminou).")
    return {"ok": True}


@app.get("/api/runs")
def runs(limit: int = 30, profile_id: int | None = None):
    where, params = ("WHERE r.profile_id = ?", (profile_id,)) if profile_id else ("", ())
    return db.rows(
        f"""SELECT r.*, CASE WHEN r.research_id IS NOT NULL THEN 'Pesquisa: ' || rs.label ELSE p.name END AS profile_name,
                   rs.kind AS research_kind
            FROM runs r LEFT JOIN profiles p ON p.id = r.profile_id LEFT JOIN research rs ON rs.id = r.research_id
            {where} ORDER BY r.id DESC LIMIT ?""",
        params + (limit,),
    )


@app.post("/api/refresh")
def refresh():
    try:
        return jobs.start("refresh", "Atualizando números", jobs.refresh_numbers, key="refresh").to_dict()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


# ---------------------------------------------------------------- tarefas

@app.get("/api/jobs")
def list_jobs():
    return jobs.active()


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Tarefa não encontrada.")
    return j.to_dict()


# ---------------------------------------------------------------- configurações

class SettingsIn(BaseModel):
    youtube_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ai_provider: str | None = None
    openai_model_fast: str | None = None
    openai_model_smart: str | None = None
    anthropic_model_fast: str | None = None
    anthropic_model_smart: str | None = None
    channel_lang: str | None = None


def _hint(key: str) -> str:
    return f"…{key[-4:]}" if key else ""


@app.get("/api/settings")
def get_settings():
    yt = db.get_setting("youtube_api_key") or ""
    return {
        "youtube_api_key_set": bool(yt),
        "youtube_api_key_hint": _hint(yt),
        "youtube_api_key_source": "salva" if yt else "",
        "ai_provider": ai.provider(),
        "ai_providers": ai.PROVIDERS,
        "anthropic_key_set": bool(ai.key_for("anthropic")), "anthropic_key_hint": _hint(ai.key_for("anthropic")),
        "openai_key_set": bool(ai.key_for("openai")), "openai_key_hint": _hint(ai.key_for("openai")),
        "models": {p: dict(zip(("fast", "smart"), ai.models_for(p))) for p in ai.PROVIDERS},
        "estimates": {p: ai.estimate(*ai.models_for(p)) for p in ai.PROVIDERS},
        "ai_enabled": ai.enabled(),
        "ai_usage": ai.usage(),
        "channel_lang": research.channel_lang(),
        "hidden_videos": db.row("SELECT COUNT(*) AS n FROM videos WHERE hidden=1")["n"],
        "channels_to_reclassify": db.row(
            "SELECT COUNT(*) AS n FROM channels WHERE dark_manual IS NULL AND dark IS NOT NULL "
            "AND (class_v IS NULL OR class_v < ?)", (ai.CHANNELS_VERSION,))["n"],
        "channels_manual": db.row("SELECT COUNT(*) AS n FROM channels WHERE dark_manual IS NOT NULL")["n"],
        "version": config.VERSION,
        "demo": os.environ.get("DARKBOT_DEMO") == "1",
    }


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    if body.youtube_api_key is not None:
        key = body.youtube_api_key.strip()
        if key:
            try:
                youtube_api.check_key(key)
            except youtube_api.YouTubeAPIError as e:
                raise HTTPException(400, str(e))
        db.set_setting("youtube_api_key", key)
    for p in ("anthropic", "openai"):
        val = getattr(body, f"{p}_api_key")
        if val is not None:
            val = val.strip()
            if val:
                try:
                    ai.check_key(p, val)
                except ai.AIError as e:
                    raise HTTPException(400, str(e))
            db.set_setting(f"{p}_api_key", val)
    if body.ai_provider in ai.PROVIDERS:
        db.set_setting("ai_provider", body.ai_provider)
    for p in ai.PROVIDERS:
        for tier in ("fast", "smart"):
            val = getattr(body, f"{p}_model_{tier}")
            if val and val.strip() != db.get_setting(f"{p}_model_{tier}"):
                try:
                    ai.test_model(p, val.strip())   # confirma que o modelo funciona na conta antes de salvar
                except ai.AIError as e:
                    raise HTTPException(400, f"{val}: {e}")
                db.set_setting(f"{p}_model_{tier}", val.strip())
    if body.channel_lang is not None and body.channel_lang.strip():
        db.set_setting("channel_lang", body.channel_lang.strip())
    return get_settings()


@app.get("/api/ai/models")
def ai_model_list(provider: str):
    """Modelos de texto da conta (com preço) para escolher em Configurações."""
    if provider not in ai.PROVIDERS:
        raise HTTPException(400, "Provedor inválido.")
    if not ai.key_for(provider):
        raise HTTPException(400, "Coloque a chave primeiro.")
    try:
        return ai.list_models(provider)
    except ai.AIError as e:
        raise HTTPException(400, str(e))


@app.get("/api/ai/estimate")
def ai_estimate(fast: str, smart: str):
    """Custo estimado por tarefa com esse par de modelos (atualiza na hora ao trocar a escolha)."""
    return ai.estimate(fast, smart)


class UrlIn(BaseModel):
    url: str


@app.post("/api/open-url")
def open_url(body: UrlIn):
    if not body.url.startswith("https://"):
        raise HTTPException(400, "URL inválida.")
    webbrowser.open(body.url)
    return {"ok": True}


# ---------------------------------------------------------------- interface

app.mount("/assets", StaticFiles(directory=UI_DIR), name="assets")


@app.get("/")
def index():
    # O link de app.js/style.css muda quando o arquivo muda: a janela nunca fica com a interface velha em cache.
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        html = html.replace(f"/assets/{name}\"", f"/assets/{name}?v={int((UI_DIR / name).stat().st_mtime)}\"")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
