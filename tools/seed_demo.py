"""Popula um banco de DEMONSTRAÇÃO (separado do real) para visualizar o darkbot.

Busca vídeos reais de nichos dark no YouTube (títulos e thumbnails de verdade) e gera números
simulados em cima deles. Os dados ficam em %LOCALAPPDATA%\\darkbot-demo e não tocam no banco real.

    .venv\\Scripts\\python tools\\seed_demo.py           (usa o cache de vídeos se já existir)
    .venv\\Scripts\\python tools\\seed_demo.py --fresh   (busca de novo no YouTube)
"""
import json
import math
import os
import random
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DARKBOT_HOME"] = os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), "darkbot-demo")

from app import db  # noqa: E402  (precisa vir depois de definir DARKBOT_HOME)
from app.paths import DATA_DIR, DB_PATH, PROFILES_DIR  # noqa: E402

PROFILES = [
    ("Mistério PT-BR", "nicho", "mistérios, casos inexplicáveis",
     ["mistérios não resolvidos", "lugares mais misteriosos do mundo", "casos inexplicáveis"]),
    ("True Crime BR", "nicho", "true crime, casos reais",
     ["caso criminal documentário", "true crime brasil", "crimes que chocaram o brasil"]),
    ("Curiosidades", "nicho", "curiosidades, fatos",
     ["curiosidades que você não sabia", "fatos incríveis sobre o mundo", "coisas que ninguém te conta"]),
    ("Coringa Dark", "coringa", "vários nichos dark",
     ["histórias de terror reais", "segredos da história", "teorias da conspiração"]),
]
CACHE = DATA_DIR / "demo_videos.json"

FAKE_CHANNELS = ["Arquivo Oculto", "Noite Escura", "Fatos Sombrios", "Caso Aberto", "Dossiê Proibido",
                 "Além do Véu", "Crônicas do Medo", "Mundo Secreto", "Enigma BR", "Lado Obscuro"]


def _text(n):
    if not isinstance(n, dict):
        return ""
    if "simpleText" in n:
        return n["simpleText"]
    if "runs" in n:
        return "".join(r.get("text", "") for r in n["runs"])
    return n.get("content", "")


def _walk(node, out, niche_idx):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "videoRenderer" and isinstance(v, dict) and v.get("videoId"):
                owner = (v.get("ownerText") or v.get("longBylineText") or {}).get("runs", [{}])[0]
                out.setdefault(v["videoId"], {
                    "title": _text(v.get("title")), "short": False, "niche": niche_idx,
                    "channel": owner.get("text"),
                    "channel_id": owner.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseId"),
                })
            elif k == "shortsLockupViewModel" and isinstance(v, dict):
                vid = (v.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {}).get("videoId")
                       or (v.get("entityId") or "").replace("shorts-shelf-item-", ""))
                title = v.get("overlayMetadata", {}).get("primaryText", {}).get("content", "")
                if len(vid) == 11:
                    out.setdefault(vid, {"title": title, "short": True, "niche": niche_idx, "channel": None, "channel_id": None})
            if isinstance(v, (dict, list)):
                _walk(v, out, niche_idx)
    elif isinstance(node, list):
        for it in node:
            _walk(it, out, niche_idx)


def scrape() -> dict:
    from playwright.sync_api import sync_playwright

    found: dict[str, dict] = {}
    tmp = DATA_DIR / "_seed_browser"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp), channel="chrome", headless=False,
            args=["--window-position=-32000,-32000", "--disable-backgrounding-occluded-windows"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0]
        for idx, (_, _, _, queries) in enumerate(PROFILES):
            for q in queries:
                page.goto(f"https://www.youtube.com/results?search_query={quote_plus(q)}", wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                before = len(found)
                _walk(page.evaluate("() => window.ytInitialData"), found, idx)
                print(f"  {q!r}: +{len(found) - before}")
        ctx.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return found


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def title_boost(title: str) -> float:
    """Dá vantagem a alguns formatos para a tela de Títulos mostrar padrões (é demo)."""
    b = 1.0
    if re.search(r"\d", title):
        b *= 1.8
    if re.search(r"\b(nunca|ninguém|proibid\w*|segredo\w*)\b", title, re.I):
        b *= 2.2
    if "?" in title:
        b *= 1.4
    if len(title) > 70:
        b *= 0.6
    return b


def main():
    random.seed(7)
    if CACHE.exists() and "--fresh" not in sys.argv:
        videos = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"Usando {len(videos)} vídeos do cache.")
    else:
        print("Buscando vídeos reais no YouTube...")
        videos = scrape()
        CACHE.write_text(json.dumps(videos, ensure_ascii=False), encoding="utf-8")
        print(f"{len(videos)} vídeos encontrados.")

    # Canais: os reais das buscas + alguns fictícios para os Shorts sem canal.
    channels: dict[str, dict] = {}
    for i, name in enumerate(FAKE_CHANNELS):
        channels[f"UCdemo{i:02d}"] = {"title": name}
    for v in videos.values():
        if not v["channel_id"]:
            cid = f"UCdemo{random.randrange(len(FAKE_CHANNELS)):02d}"
            v["channel_id"], v["channel"] = cid, channels[cid]["title"]
        channels.setdefault(v["channel_id"], {"title": v["channel"]})
    for c in channels.values():
        new = random.random() < 0.28
        c["age"] = random.uniform(25, 175) if new else random.uniform(200, 3200)
        c["subs"] = int(math.exp(random.uniform(math.log(300), math.log(40_000 if new else 2_500_000))))
        c["videos"] = max(3, int(c["age"] / random.uniform(2, 12)))

    if DB_PATH.exists():
        DB_PATH.unlink()
    for f in ("-wal", "-shm"):
        Path(str(DB_PATH) + f).unlink(missing_ok=True)
    shutil.rmtree(PROFILES_DIR, ignore_errors=True)
    PROFILES_DIR.mkdir(exist_ok=True)
    db.init()

    with db.tx() as con:
        for cid, c in channels.items():
            con.execute(
                "INSERT INTO channels VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cid, c["title"], "@" + re.sub(r"\W", "", (c["title"] or "canal")).lower(), c["subs"], c["videos"],
                 c["subs"] * random.randint(30, 400), iso(c["age"]), None, "BR", iso(0)),
            )

        profile_ids = []
        for name, kind, niche, _ in PROFILES:
            pdir = PROFILES_DIR / re.sub(r"\W+", "-", name.lower())
            pdir.mkdir(parents=True, exist_ok=True)
            profile_ids.append(con.execute(
                "INSERT INTO profiles(name, kind, niche, source, dir, last_run_at) VALUES(?,?,?,?,?,?)",
                (name, kind, niche, "demo", str(pdir), iso(0.1)),
            ).lastrowid)

        # Números simulados por vídeo (cauda longa: poucos furam muito a bolha).
        for vid, v in videos.items():
            c = channels[v["channel_id"]]
            v["age"] = min(random.choice([random.uniform(0.3, 7), random.uniform(3, 45), random.uniform(20, 300)]), c["age"])
            mult = math.exp(random.gauss(-0.3, 1.5)) * title_boost(v["title"])
            if c["age"] < 180:
                mult *= 1.8
            v["views_final"] = max(200, int(max(c["subs"], 100) * mult))
            dur = random.randint(15, 59) if v["short"] else random.randint(420, 2700)
            con.execute(
                "INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, v["title"], v["channel_id"], c["title"], iso(v["age"]), dur, v["views_final"],
                 int(v["views_final"] * random.uniform(.015, .06)), int(v["views_final"] * random.uniform(.001, .008)),
                 int(v["short"]), "pt", iso(3), iso(0.1)),
            )

        # 3 coletas por perfil nos últimos dias; o coringa vê um pouco de tudo.
        for pidx, pid in enumerate(profile_ids):
            pool = [k for k, v in videos.items() if v["niche"] == pidx]
            if PROFILES[pidx][1] == "coringa":
                pool += random.sample(list(videos), min(len(videos) // 3, 60))
            for r, days_ago in enumerate((2.2, 1.1, 0.1)):
                run_id = con.execute(
                    "INSERT INTO runs(profile_id, started_at, finished_at, status, logged_in, videos_found) "
                    "VALUES(?,?,?, 'done', 1, 0)", (pid, iso(days_ago), iso(days_ago - 0.01)),
                ).lastrowid
                seen = random.sample(pool, int(len(pool) * random.uniform(.6, .9)))
                for pos, vid in enumerate(seen, 1):
                    con.execute("INSERT OR IGNORE INTO sightings VALUES(?,?,?,?)",
                                (run_id, vid, pos, "shorts" if videos[vid]["short"] else "home"))
                con.execute("UPDATE runs SET videos_found=? WHERE id=?", (len(seen), run_id))

        # Histórico de views (para a coluna "Crescendo").
        for vid, v in videos.items():
            for days_ago in (2.2, 1.1, 0.1):
                if days_ago < v["age"]:
                    frac = 1 - (days_ago / v["age"]) ** 0.7
                    con.execute("INSERT OR IGNORE INTO video_stats VALUES(?,?,?)",
                                (vid, iso(days_ago), max(1, int(v["views_final"] * frac))))

    print(f"Pronto: {len(PROFILES)} perfis, {len(videos)} vídeos, {len(channels)} canais em {DATA_DIR}")


if __name__ == "__main__":
    main()
