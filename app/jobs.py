"""Tarefas em segundo plano (coleta, importação) com progresso, para a interface nunca travar."""
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ai, ai_label, chrome_profiles, config, db, scraper, youtube_api

_jobs: dict[str, "Job"] = {}
_lock = threading.Lock()


def youtube_api_key() -> str:
    return db.get_setting("youtube_api_key") or ""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Job:
    def __init__(self, kind: str, label: str, key: str | None = None, cancellable: bool = False):
        self.id = uuid.uuid4().hex[:10]
        self.cancellable = cancellable
        self.cancelled = False    # pedido de cancelar: a tarefa para no próximo ponto seguro e guarda o que já fez
        self.kind = kind
        self.label = label
        self.key = key            # evita duas tarefas iguais ao mesmo tempo (ex.: mesmo perfil)
        self.status = "running"   # running | done | error
        self.progress = 0.0
        self.message = "Iniciando..."
        self.result = None
        self.error = None
        self.started = time.time()

    def update(self, progress: float | None = None, message: str | None = None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
            "progress": self.progress, "message": self.message, "result": self.result,
            "error": self.error, "elapsed": round(time.time() - self.started, 1),
            "cancellable": self.cancellable, "cancelled": self.cancelled,
        }

    def stopped(self) -> bool:
        return self.cancelled


def start(kind: str, label: str, fn, *args, key: str | None = None, cancellable: bool = False) -> Job:
    with _lock:
        if key and any(j.key == key and j.status == "running" for j in _jobs.values()):
            raise RuntimeError("Já existe uma tarefa rodando para esse item.")
        job = Job(kind, label, key, cancellable)
        _jobs[job.id] = job

    def runner():
        try:
            job.result = fn(job, *args)
            job.status = "done"
            job.progress = 1.0
        except Exception as e:  # a mensagem vai para a interface
            job.status = "error"
            job.error = str(e) or e.__class__.__name__
            traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cancel(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job.status != "running" or not job.cancellable:
        return False
    job.cancelled = True
    job.update(message="Cancelando: guardando o que já foi feito...")
    return True


def active() -> list[dict]:
    cutoff = time.time() - 30
    return [j.to_dict() for j in _jobs.values() if j.status == "running" or j.started > cutoff]


# ---------------------------------------------------------------------------
# Importação de perfil
# ---------------------------------------------------------------------------

def import_profile(job: Job, profile_id: int, chrome_folder: str) -> dict:
    p = db.row("SELECT * FROM profiles WHERE id = ?", (profile_id,))
    job.update(0.1, "Copiando perfil do Chrome...")
    try:
        chrome_profiles.import_profile(chrome_folder, Path(p["dir"]))
    except Exception:
        with db.tx() as con:
            con.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        raise
    job.update(1.0, "Perfil importado")
    return {"profile_id": profile_id}


# ---------------------------------------------------------------------------
# Coleta: raspa a home -> salva -> enriquece pela API
# ---------------------------------------------------------------------------

def _stale(ts: str | None, hours: float) -> bool:
    if not ts:
        return True
    try:
        t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - t > timedelta(hours=hours)


def enrich(job: Job | None, video_ids: list[str], api_key: str) -> dict:
    """Busca números exatos só do que está desatualizado (economiza cota)."""
    existing = {
        r["video_id"]: r for r in db.rows(
            f"SELECT video_id, updated_at, channel_id FROM videos WHERE video_id IN ({','.join('?' * len(video_ids))})",
            video_ids,
        )
    } if video_ids else {}
    todo = [v for v in video_ids if _stale((existing.get(v) or {}).get("updated_at"), config.VIDEO_REFRESH_HOURS)]

    if job:
        job.update(0.75, f"Buscando números de {len(todo)} vídeos na API...")
    vids = youtube_api.fetch_videos(todo, api_key) if todo else []
    ts = now_iso()
    with db.tx() as con:
        for v in vids:
            con.execute(
                """UPDATE videos SET title=?, channel_id=?, channel_title=?, published_at=?, lang=?,
                   duration_s=?, views=?, likes=?, comments=?, description=?, tags=?,
                   is_short = CASE WHEN is_short = 1 OR ? <= ? THEN 1 ELSE 0 END,
                   updated_at=? WHERE video_id=?""",
                (v["title"], v["channel_id"], v["channel_title"], v["published_at"], v["lang"],
                 v["duration_s"], v["views"], v["likes"], v["comments"], v["description"],
                 json.dumps(v["tags"], ensure_ascii=False),
                 v["duration_s"] if v["duration_s"] is not None else 9999, config.SHORT_MAX_SECONDS,
                 ts, v["video_id"]),
            )
            if v["views"] is not None:
                con.execute(
                    "INSERT OR IGNORE INTO video_stats(video_id, captured_at, views) VALUES(?,?,?)",
                    (v["video_id"], ts, v["views"]),
                )

    channel_ids = {v["channel_id"] for v in vids if v["channel_id"]}
    channel_ids |= {r["channel_id"] for r in existing.values() if r["channel_id"]}
    known = {
        r["channel_id"]: r["updated_at"] for r in db.rows(
            f"SELECT channel_id, updated_at FROM channels WHERE channel_id IN ({','.join('?' * len(channel_ids))})",
            list(channel_ids),
        )
    } if channel_ids else {}
    ch_todo = [c for c in channel_ids if _stale(known.get(c), config.CHANNEL_REFRESH_HOURS)]

    if job:
        job.update(0.9, f"Buscando dados de {len(ch_todo)} canais...")
    chans = youtube_api.fetch_channels(ch_todo, api_key) if ch_todo else []
    with db.tx() as con:
        for c in chans:
            con.execute(
                """INSERT INTO channels(channel_id, title, handle, subs, video_count, total_views,
                   published_at, thumbnail, country, description, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title, handle=excluded.handle,
                   subs=excluded.subs, video_count=excluded.video_count, total_views=excluded.total_views,
                   published_at=excluded.published_at, thumbnail=excluded.thumbnail,
                   country=excluded.country, description=excluded.description, updated_at=excluded.updated_at""",
                (c["channel_id"], c["title"], c["handle"], c["subs"], c["video_count"], c["total_views"],
                 c["published_at"], c["thumbnail"], c["country"], c["description"], ts),
            )
    return {"videos_updated": len(vids), "channels_updated": len(chans)}


def collect(job: Job, profile_id: int, scrolls: int, show_browser: bool, source: str = "home") -> dict:
    p = db.row("SELECT * FROM profiles WHERE id = ?", (profile_id,))
    if not p:
        raise RuntimeError("Perfil não encontrado.")
    pdir = Path(p["dir"])
    if chrome_profiles.profile_in_use(pdir):
        raise RuntimeError("Esse perfil está aberto numa janela do Chrome. Feche-a e tente de novo.")

    started = now_iso()
    with db.tx() as con:
        run_id = con.execute(
            "INSERT INTO runs(profile_id, started_at, status, source) VALUES(?,?, 'running', ?)",
            (profile_id, started, source)
        ).lastrowid

    try:
        job.update(0.02, "Abrindo o YouTube com o perfil...")

        where = "o histórico" if source == "history" else "a home"

        def progress(i, total, found):
            job.update(0.05 + 0.65 * i / total, f"Rolando {where} ({i}/{total}) · {found} vídeos")

        res = scraper.collect_home(pdir, scrolls=scrolls, show_browser=show_browser, on_progress=progress,
                                   should_stop=job.stopped, page=source)
        found = res["videos"]
        if source == "history":
            for info in found.values():
                if info["surface"] == "home":
                    info["surface"] = "history"
        if not found:
            hint = "" if res["logged_in"] else (" O perfil não está logado e ainda não tem histórico. Entre numa conta ('Entrar na conta') ou assista alguns vídeos do nicho nele ('Treinar o perfil'): deslogado também funciona, o YouTube recomenda pelo histórico do navegador.")
            raise RuntimeError(f"{where.capitalize()} não trouxe nenhum vídeo." + hint)

        with db.tx() as con:
            for vid, info in found.items():
                con.execute(
                    """INSERT INTO videos(video_id, title, is_short, first_seen_at) VALUES(?,?,?,?)
                       ON CONFLICT(video_id) DO UPDATE SET
                       is_short = CASE WHEN excluded.is_short = 1 THEN 1 ELSE videos.is_short END""",
                    (vid, info["title"], 1 if info["surface"] == "shorts" else 0, started),
                )
                con.execute(
                    "INSERT OR IGNORE INTO sightings(run_id, video_id, position, surface) VALUES(?,?,?,?)",
                    (run_id, vid, info["position"], info["surface"]),
                )

        api_key = youtube_api_key()
        note = None
        if api_key:
            enrich(job, list(found), api_key)
        else:
            note = "Sem chave da API: salvei só os títulos. Adicione a chave em Configurações para ver os números."

        if job.stopped():
            note = f"Coleta cancelada: {len(found)} vídeos guardados." + (f" {note}" if note else "")
        else:
            check_ai_labels(job)
        if api_key and ai.enabled() and not job.stopped():
            job.update(0.95, "IA classificando os canais novos...")
            classify_new_channels()

        if not p["niche"] and ai.enabled() and not job.stopped():
            niche = _detect_profile_niche(job, profile_id, found)
            if niche:
                note = f"Nicho detectado pela IA: {niche}" + (f". {note}" if note else "")

        with db.tx() as con:
            con.execute(
                "UPDATE runs SET finished_at=?, status='done', logged_in=?, videos_found=? WHERE id=?",
                (now_iso(), int(res["logged_in"]), len(found), run_id),
            )
            con.execute("UPDATE profiles SET last_run_at=? WHERE id=?", (now_iso(), profile_id))
        job.update(1.0, f"{len(found)} vídeos coletados")
        return {"run_id": run_id, "videos": len(found), "logged_in": res["logged_in"], "note": note}
    except Exception as e:
        with db.tx() as con:
            con.execute(
                "UPDATE runs SET finished_at=?, status='error', error=? WHERE id=?", (now_iso(), str(e), run_id)
            )
        raise


LABEL_PER_CHANNEL = 2  # vídeos verificados por canal: o selo importa no nível do canal


def check_ai_labels(job: Job | None, lo: float = 0.9, hi: float = 0.95) -> int:
    """Selo de IA: verifica só o necessário. Canal que já tem um vídeo com selo é pulado; dos outros,
    verifica até LABEL_PER_CHANNEL vídeos (os mais vistos). Cada vídeo é verificado uma vez só."""
    rows = db.rows(
        """SELECT v.video_id, v.channel_id,
                  (SELECT MAX(v2.ai_label) FROM videos v2 WHERE v2.channel_id = v.channel_id) AS ch_ai,
                  (SELECT COUNT(*) FROM videos v2 WHERE v2.channel_id = v.channel_id AND v2.ai_label IS NOT NULL) AS checked
           FROM videos v
           WHERE v.ai_label IS NULL AND v.is_short = 0
             AND (v.video_id IN (SELECT video_id FROM sightings) OR v.video_id IN (SELECT video_id FROM research_videos))
           ORDER BY v.channel_id, v.views DESC"""
    )
    ids, per_channel = [], {}
    for r in rows:
        if r["channel_id"] is None:      # sem dados da API ainda: verifica o vídeo
            ids.append(r["video_id"])
            continue
        if r["ch_ai"] == 1:
            continue
        n = per_channel.get(r["channel_id"], r["checked"])
        if n < LABEL_PER_CHANNEL:
            ids.append(r["video_id"])
            per_channel[r["channel_id"]] = n + 1
    if not ids:
        return 0

    def progress(i, total):
        if job:
            job.update(lo + (hi - lo) * i / total, f"Verificando selo de IA ({i}/{total})...")

    labels = ai_label.check_videos(ids, progress, job.stopped if job else None)
    with db.tx() as con:
        con.executemany("UPDATE videos SET ai_label=? WHERE video_id=?", [(v, k) for k, v in labels.items()])
    return len(labels)


def _fill_channel_descriptions(ids: list[str]) -> None:
    """Descrição dos canais que ainda não têm (1 unidade de cota a cada 50): a IA precisa dela para não errar."""
    key = youtube_api_key()
    if not ids or not key:
        return
    chans = youtube_api.fetch_channels(ids, key)
    with db.tx() as con:
        con.executemany("UPDATE channels SET description=? WHERE channel_id=?",
                        [(c["description"] or "", c["channel_id"]) for c in chans])


def classify_new_channels(everything: bool = False, job: Job | None = None, video_ids: list[str] | None = None) -> int:
    """A IA (Haiku) classifica os canais: dark ou não, confiança, formato e tema. Uma vez por canal.

    everything=True reclassifica todos os que a IA classificou com a versão antiga (as correções manuais ficam).
    """
    cond = "c.dark_manual IS NULL AND (c.class_v IS NULL OR c.class_v < ?)" if everything else "c.dark IS NULL"
    params = (ai.CHANNELS_VERSION,) if everything else ()
    if video_ids is not None:   # só os canais desses vídeos (ex.: os relevantes de uma pesquisa)
        if not video_ids:
            return 0
        cond += " AND c.channel_id IN (SELECT channel_id FROM videos WHERE video_id IN (%s))" % ",".join("?" * len(video_ids))
        params = params + tuple(video_ids)
    rows = db.rows(
        f"""SELECT c.channel_id, c.title, c.description, c.subs, v.title AS vtitle, v.ai_label FROM channels c
            JOIN videos v ON v.channel_id = c.channel_id
            WHERE {cond} AND v.title IS NOT NULL
            ORDER BY c.channel_id, v.views DESC""", params,
    )
    chans: dict[str, dict] = {}
    for r in rows:
        c = chans.setdefault(r["channel_id"], {"channel_id": r["channel_id"], "title": r["title"], "titles": [],
                                               "description": r["description"], "subs": r["subs"], "ai": 0})
        c["ai"] = max(c["ai"], r["ai_label"] or 0)
        if len(c["titles"]) < 3:
            c["titles"].append(r["vtitle"])
    if not chans:
        return 0
    if job:
        job.update(0.1, f"Buscando a descrição de {len(chans)} canais...")
    missing = [c["channel_id"] for c in chans.values() if c["description"] is None]
    if missing:
        _fill_channel_descriptions(missing)
        desc = {r["channel_id"]: r["description"] for r in db.rows(
            "SELECT channel_id, description FROM channels WHERE channel_id IN (%s)" % ",".join("?" * len(missing)),
            missing)}
        for cid in missing:
            chans[cid]["description"] = desc.get(cid)
    if job:
        job.update(0.3, f"IA classificando {len(chans)} canais...")
    try:
        return ai.classify_channels(list(chans.values()))
    except ai.AIError as e:
        if job:
            raise
        print(f"[ia] classificar canais: {e}")
        return 0


def reclassify_channels(job: Job) -> dict:
    n = classify_new_channels(everything=True, job=job)
    job.update(1.0, f"{n} canais reclassificados")
    return {"channels": n, "note": f"{n} canais reclassificados com o critério novo."}


def _detect_profile_niche(job: Job, profile_id: int, found: dict) -> str | None:
    """Primeira coleta de um perfil sem nicho: a IA lê os títulos da home e preenche nicho e tipo (uma vez só)."""
    job.update(0.95, "IA detectando o nicho do perfil...")
    ordered = sorted(found.items(), key=lambda kv: kv[1]["position"])
    titles = [info["title"] for _, info in ordered if info["surface"] != "shorts"]
    try:
        guess = ai.detect_niche(f"profile:{profile_id}", titles)
    except ai.AIError as e:
        print(f"[ia] nicho do perfil {profile_id}: {e}")
        return None
    with db.tx() as con:
        con.execute("UPDATE profiles SET niche=?, kind=?, niche_auto=1 WHERE id=? AND (niche IS NULL OR niche='')",
                    (guess["niche"], guess["kind"], profile_id))
    return guess["niche"]


def refresh_numbers(job: Job) -> dict:
    """Reenriquece todos os vídeos já vistos (útil depois de colocar a chave da API)."""
    api_key = youtube_api_key()
    if not api_key:
        raise RuntimeError("Adicione a chave da API do YouTube em Configurações.")
    ids = [r["video_id"] for r in db.rows("SELECT video_id FROM videos")]
    return enrich(job, ids, api_key)
