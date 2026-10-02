"""Método Malandro: em que línguas ninguém fez este vídeo ainda.

Para cada língua, a IA escreve como um nativo intitularia o MESMO vídeo; o darkbot busca no YouTube daquele
país, a IA julga quais resultados são o mesmo vídeo modelado (e em que língua estão), e cada língua vira:
livre (ninguém fez), pouco explorada (1 a 2 canais) ou saturada (3 ou mais). Nas livres, o título sugerido
já sai pronto naquela língua. O resultado é guardado (um por vídeo) e não é refeito sem pedir.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import ai, db, jobs, youtube_api, youtube_web

LANGS = list(ai.LANGUAGES)       # todas as línguas do radar
SATURATED_CHANNELS = 3           # a partir de quantos canais a língua está saturada
SHOW_PER_LANG = 6                # vídeos guardados por língua (os melhores)


def _status(channels: int) -> str:
    return "livre" if channels == 0 else "saturada" if channels >= SATURATED_CHANNELS else "pouca"


def _fix_original(res: dict) -> dict:
    """O idioma do vídeo original já tem o próprio vídeo: conta como 1 canal (nunca "ninguém fez").
    Corrige também os resultados guardados antes desta regra."""
    for l in res.get("langs", []):
        if l.get("original") and l.get("status") == "livre":
            l["channels"] = max(1, l.get("channels") or 0)
            l["status"] = _status(l["channels"])
    res["free"] = [l["code"] for l in res.get("langs", []) if l["status"] == "livre"]
    return res


def get(video_id: str) -> dict | None:
    r = db.row("SELECT result FROM malandro WHERE video_id=?", (video_id,))
    return _fix_original(json.loads(r["result"])) if r else None


# Línguas com alfabeto próprio: se o título não tem esse alfabeto, não é dessa língua (a IA às vezes erra).
_SCRIPTS = {
    "hi": re.compile(r"[ऀ-ॿ]"), "ja": re.compile(r"[぀-ヿ一-鿿]"),
    "ko": re.compile(r"[가-힯]"), "ru": re.compile(r"[Ѐ-ӿ]"), "ar": re.compile(r"[؀-ۿ]"),
}


def fix_lang(judged: str, title: str, api_lang: str | None) -> str:
    """Idioma do vídeo: o da API (quando o canal informa) > o da IA, conferido pelo alfabeto do título."""
    api = (api_lang or "").split("-")[0].lower()
    if api in ai.LANGUAGES:
        return api
    if judged in _SCRIPTS and not _SCRIPTS[judged].search(title):
        return "xx"   # a IA chutou uma língua de outro alfabeto para um título em letras latinas
    return judged


def _age_days(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - t).total_seconds() / 86400, 0.25)


def run(job: jobs.Job, video_id: str) -> dict:
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("O Método Malandro precisa da chave da API do YouTube (Configurações).")
    if not ai.enabled():
        raise RuntimeError("O Método Malandro precisa da IA (chave da Anthropic).")

    job.update(0.03, "Lendo o vídeo...")
    info = (youtube_api.fetch_videos([video_id], key) or [None])[0]
    if not info:
        raise RuntimeError("Não encontrei esse vídeo no YouTube.")
    seed_lang = (info.get("lang") or "").split("-")[0].lower() or None
    prof = ai.seed_profile(video_id, info["title"], info.get("channel_title") or "", info.get("description") or "",
                           info.get("tags") or [], seed_lang or "?")
    reference = f"\"{info['title']}\" — {prof['topic']} (ângulo: {prof['angle']})"

    job.update(0.12, "IA escrevendo o título nativo em cada língua...")
    local = ai.malandro_titles(video_id, info["title"], prof["topic"], LANGS)

    # Busca em cada país: o título nativo (relevância) + a busca curta (mais vistos do ano).
    plan = []
    for lang in LANGS:
        loc = local.get(lang) or {}
        hl, gl, _ = ai.LANGUAGES[lang]
        if loc.get("title"):
            plan.append((lang, loc["title"], "relevancia", None, hl, gl))
        if loc.get("query"):
            plan.append((lang, loc["query"], "views", "ano", hl, gl))
    job.update(0.2, f"Procurando o vídeo em {len(LANGS)} países ({len(plan)} buscas)...")
    found: dict[str, str] = {}
    with youtube_web.client() as c, ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        results = list(pool.map(lambda p: youtube_web.search(c, p[1], p[2], p[3], p[4], p[5]), plan))
    for res in results:
        for vid, title in res:
            if vid != video_id:
                found.setdefault(vid, title)
    if job.stopped():
        raise RuntimeError("Cancelado.")

    job.update(0.5, f"IA conferindo quais dos {len(found)} vídeos são o mesmo vídeo modelado...")
    notes = ai.judge_same_video(reference, list(found.items()))
    same = {vid: n for vid, n in notes.items() if n[0] >= 2}

    job.update(0.75, "Buscando os números dos concorrentes...")
    vids = {v["video_id"]: v for v in youtube_api.fetch_videos(list(same), key)}
    chans = {c["channel_id"]: c for c in youtube_api.fetch_channels(
        list({v["channel_id"] for v in vids.values() if v.get("channel_id")}), key)}

    def card(vid):
        v, (r, lang) = vids[vid], same[vid]
        lang = fix_lang(lang, v.get("title") or "", v.get("lang"))
        subs = (chans.get(v.get("channel_id")) or {}).get("subs")
        age = _age_days(v.get("published_at"))
        mult = round(v["views"] / max(subs, 100), 2) if v.get("views") is not None and subs is not None else None
        return {"video_id": vid, "title": v["title"], "channel_id": v.get("channel_id"),
                "channel_title": v.get("channel_title"), "views": v.get("views"), "subs": subs, "multiplier": mult,
                "age_days": round(age, 1) if age else None, "relevance": r, "lang": lang}

    cards = [card(vid) for vid in same if vid in vids]
    langs_out = []
    for lang in LANGS:
        direct = [c for c in cards if c["lang"] == lang and c["relevance"] >= 3]
        theme = [c for c in cards if c["lang"] == lang and c["relevance"] == 2]
        channels = len({c["channel_id"] for c in direct}) + (1 if lang == seed_lang else 0)   # + o próprio original
        status = _status(channels)
        best = sorted(direct + theme, key=lambda c: -(c["multiplier"] or 0))[:SHOW_PER_LANG]
        langs_out.append({
            "code": lang, "name": ai.LANGUAGES[lang][2], "status": status, "direct": len(direct),
            "channels": channels, "theme": len(theme), "videos": best,
            "suggested_title": (local.get(lang) or {}).get("title"), "query": (local.get(lang) or {}).get("query"),
            "original": lang == seed_lang,
        })
    result = {
        "video_id": video_id, "title": info["title"], "seed_lang": seed_lang, "topic": prof["topic"],
        "langs": langs_out, "free": [l["code"] for l in langs_out if l["status"] == "livre"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with db.tx() as con:
        con.execute("INSERT INTO malandro(video_id, result, created_at) VALUES(?,?,?) "
                    "ON CONFLICT(video_id) DO UPDATE SET result=excluded.result, created_at=excluded.created_at",
                    (video_id, json.dumps(result, ensure_ascii=False), result["created_at"]))
    job.update(1.0, f"{len(result['free'])} línguas livres")
    return {"video_id": video_id, "free": len(result["free"]),
            "note": f"Método Malandro: {len(result['free'])} línguas onde ninguém fez esse vídeo."}
