"""YouTube Data API v3: números exatos dos vídeos e canais. Custa 1 unidade de cota a cada 50 itens."""
import re

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


def fetch_videos(ids, key: str) -> list[dict]:
    out = []
    with httpx.Client(timeout=30) as client:
        for chunk in _chunks(ids):
            data = _get(client, "videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "key": key,
                "maxResults": 50,
            })
            for it in data.get("items", []):
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
                })
    return out


def fetch_channels(ids, key: str) -> list[dict]:
    out = []
    with httpx.Client(timeout=30) as client:
        for chunk in _chunks(ids):
            data = _get(client, "channels", {
                "part": "snippet,statistics",
                "id": ",".join(chunk),
                "key": key,
                "maxResults": 50,
            })
            for it in data.get("items", []):
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
                })
    return out


def check_key(key: str) -> None:
    """Chamada barata (1 unidade) só para validar a chave."""
    with httpx.Client(timeout=15) as client:
        _get(client, "videos", {"part": "id", "id": "dQw4w9WgXcQ", "key": key})
