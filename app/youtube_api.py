"""YouTube Data API v3: números exatos dos vídeos e canais. Custa 1 unidade de cota a cada 50 itens."""
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeAPIError(RuntimeError):
    pass


def _chunks(items, size=50):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    r = client.get(f"{BASE}/{path}", params=params)
    if r.status_code != 200:
        try:
            err = r.json()["error"]
            reason = err["errors"][0].get("reason", "")
            msg = err.get("message", "")
        except (ValueError, KeyError, IndexError):
            reason, msg = "", r.text[:200]
        if reason == "quotaExceeded":
            raise YouTubeAPIError("Cota diária da API do YouTube esgotada. Renova à meia-noite (horário do Pacífico).")
        if reason in ("keyInvalid", "badRequest") or "API key" in msg:
            raise YouTubeAPIError("Chave da API do YouTube inválida. Confira em Configurações.")
        raise YouTubeAPIError(f"Erro da API do YouTube ({r.status_code}): {msg}")
    return r.json()


def parse_duration(iso: str | None) -> int | None:
    if not iso:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _int(v):
    return int(v) if v is not None else None


API_WORKERS = 4  # lotes de 50 em paralelo (a cota é a mesma; só fica mais rápido)


def _fetch_items(path: str, part: str, ids, key: str) -> list[dict]:
    def one(chunk):
        with httpx.Client(timeout=30) as client:
            return _get(client, path, {"part": part, "id": ",".join(chunk), "key": key, "maxResults": 50}).get("items", [])

    chunks = list(_chunks(ids))
    if len(chunks) <= 1:
        return [it for c in chunks for it in one(c)]
    with ThreadPoolExecutor(API_WORKERS) as pool:
        return [it for items in pool.map(one, chunks) for it in items]


def fetch_videos(ids, key: str) -> list[dict]:
    out = []
    for it in _fetch_items("videos", "snippet,statistics,contentDetails", ids, key):
        sn, st = it.get("snippet", {}), it.get("statistics", {})
        out.append({
            "video_id": it["id"],
            "title": sn.get("title"),
            "channel_id": sn.get("channelId"),
            "channel_title": sn.get("channelTitle"),
            "published_at": sn.get("publishedAt"),
            "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
            "duration_s": parse_duration(it.get("contentDetails", {}).get("duration")),
            "views": _int(st.get("viewCount")),
            "likes": _int(st.get("likeCount")),
            "comments": _int(st.get("commentCount")),
            "description": (sn.get("description") or "")[:2000],
            "tags": sn.get("tags") or [],
        })
    return out


def fetch_channels(ids, key: str) -> list[dict]:
    out = []
    for it in _fetch_items("channels", "snippet,statistics", ids, key):
        sn, st = it.get("snippet", {}), it.get("statistics", {})
        thumbs = sn.get("thumbnails", {})
        out.append({
            "channel_id": it["id"],
            "title": sn.get("title"),
            "handle": sn.get("customUrl"),
            "published_at": sn.get("publishedAt"),
            "country": sn.get("country"),
            "thumbnail": (thumbs.get("default") or {}).get("url"),
            "subs": None if st.get("hiddenSubscriberCount") else _int(st.get("subscriberCount")),
            "video_count": _int(st.get("videoCount")),
            "total_views": _int(st.get("viewCount")),
            "description": (sn.get("description") or "")[:600],
        })
    return out


def fetch_uploads(channel_id: str, key: str, limit: int = 20) -> list[tuple[str, str]]:
    """Últimos vídeos enviados pelo canal (1 unidade de cota): [(id, título)], do mais novo ao mais antigo."""
    if not channel_id or not channel_id.startswith("UC"):
        return []
    with httpx.Client(timeout=30) as client:
        try:
            data = _get(client, "playlistItems", {"part": "snippet", "playlistId": "UU" + channel_id[2:],
                                                  "maxResults": min(limit, 50), "key": key})
        except YouTubeAPIError as e:
            if "Cota" in str(e) or "inválida" in str(e):
                raise
            return []
    out = []
    for it in data.get("items", []):
        sn = it.get("snippet", {})
        vid = (sn.get("resourceId") or {}).get("videoId")
        if vid:
            out.append((vid, sn.get("title") or ""))
    return out


def fetch_comments(video_id: str, key: str, limit: int = 100) -> list[dict]:
    """Comentários mais relevantes (1 unidade de cota por página de 100). Vídeo sem comentários -> []."""
    with httpx.Client(timeout=30) as client:
        try:
            data = _get(client, "commentThreads", {
                "part": "snippet", "videoId": video_id, "key": key, "order": "relevance",
                "textFormat": "plainText", "maxResults": min(limit, 100),
            })
        except YouTubeAPIError as e:
            if "Cota" in str(e) or "inválida" in str(e):
                raise
            return []  # comentários desativados, vídeo privado etc.
    out = []
    for it in data.get("items", []):
        top = it["snippet"]["topLevelComment"]
        sn = top["snippet"]
        out.append({
            "comment_id": top["id"], "video_id": video_id, "text": sn.get("textDisplay") or "",
            "likes": _int(sn.get("likeCount")), "replies": _int(it["snippet"].get("totalReplyCount")),
            "published_at": sn.get("publishedAt"),
        })
    return out


def check_key(key: str) -> None:
    """Chamada barata (1 unidade) só para validar a chave."""
    with httpx.Client(timeout=15) as client:
        _get(client, "videos", {"part": "id", "id": "dQw4w9WgXcQ", "key": key})
