"""API local que a interface consome. Só lê dados prontos do banco; trabalho pesado vai para `jobs`."""
import os
import re
import shutil
import unicodedata
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, chrome_profiles, config, db, jobs, titles, youtube_api
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
    if body.chrome_folder and chrome_profiles.chrome_running():
        raise HTTPException(409, "O Chrome está aberto. Feche todas as janelas (ou use 'Fechar o Chrome') e tente de novo.")
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
            "UPDATE profiles SET name=?, kind=?, niche=? WHERE id=?",
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


@app.post("/api/profiles/{pid}/collect")
def collect(pid: int, body: CollectIn):
    p = db.row("SELECT name FROM profiles WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Perfil não encontrado.")
    try:
        job = jobs.start(
            "collect", f"Coletando · {p['name']}", jobs.collect, pid,
            max(1, min(body.scrolls, config.MAX_SCROLLS)), body.show_browser, key=f"profile:{pid}",
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.to_dict()


@app.post("/api/chrome/close")
def chrome_close():
    if not chrome_profiles.close_chrome():
        raise HTTPException(500, "Não consegui fechar o Chrome. Feche manualmente.")
    return {"ok": True}


@app.get("/api/chrome-profiles")
def chrome_list():
    return {
        "chrome_found": chrome_profiles.find_chrome() is not None,
        "chrome_running": chrome_profiles.chrome_running(),
        "profiles": chrome_profiles.list_chrome_profiles(),
    }


# ---------------------------------------------------------------- dados

@app.get("/api/videos")
def videos(profile_id: int | None = None):
    return analytics.videos(profile_id)


@app.get("/api/channels")
def channels(profile_id: int | None = None):
    return analytics.channels(profile_id)


@app.get("/api/titles")
def title_patterns(profile_id: int | None = None, type: str = "all", max_age: float = 0, outlier: str = "top20"):
    return titles.patterns(profile_id, type, max_age, outlier)


@app.get("/api/overview")
def overview():
    return analytics.overview()


@app.get("/api/runs")
def runs(limit: int = 30):
    return db.rows(
        """SELECT r.*, p.name AS profile_name FROM runs r LEFT JOIN profiles p ON p.id = r.profile_id
           ORDER BY r.id DESC LIMIT ?""",
        (limit,),
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


@app.get("/api/settings")
def get_settings():
    saved = db.get_setting("youtube_api_key") or ""
    key = saved or config.YOUTUBE_API_KEY
    return {
        "youtube_api_key_set": bool(key),
        "youtube_api_key_hint": f"…{key[-4:]}" if key else "",
        "youtube_api_key_source": "salva" if saved else ("embutida" if key else ""),
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
    return get_settings()


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
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})
