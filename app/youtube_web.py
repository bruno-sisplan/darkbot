"""Leitura das páginas públicas do YouTube sem navegador (rápido, sem cota da API).

Usado na pesquisa de mercado: vídeos sugeridos de um vídeo e resultados de busca. É a visão de um
visitante deslogado, o que para pesquisa é bom: não vem enviesado pelo histórico de ninguém.
Os IDs vêm do mesmo JSON interno que o scraper da home usa (`ytInitialData`).
"""
import base64
import json
import re
import time

import httpx

from .scraper import _Collector

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/141.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
PAUSE_S = 0.15  # pausa por página, em cada thread (as páginas abrem em paralelo)
WORKERS = 6     # páginas da pesquisa abertas ao mesmo tempo

_INITIAL = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)
_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")

# Parâmetro `sp` da busca (protobuf em base64): ordem + filtros (data de envio, tipo = vídeo).
_SORT = {"relevancia": 0, "data": 2, "views": 3}
_UPLOAD = {"hora": 1, "hoje": 2, "semana": 3, "mes": 4, "ano": 5}


def client() -> httpx.Client:
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    return httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True, limits=limits)


def parse_video_id(text: str) -> str | None:
    text = (text or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = _ID.search(text)
    return m.group(1) if m else None


def _initial_data(c: httpx.Client, url: str, params: dict | None = None, headers: dict | None = None) -> dict | None:
    try:
        resp = c.get(url, params=params, headers=headers)
        html = resp.text
    except httpx.HTTPError as e:
        print(f"[youtube_web] falha em {url}: {e}")
        return None
    finally:
        time.sleep(PAUSE_S)
    m = _INITIAL.search(html)
    if not m:
        # Consentimento, "tráfego incomum" etc.: fica no log para diagnosticar.
        print(f"[youtube_web] sem ytInitialData ({resp.status_code}) em {resp.url}")
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _sp(sort: str, upload: str | None) -> str:
    filters = bytes([0x08, _UPLOAD[upload]]) if upload else b""
    filters += bytes([0x10, 0x01])  # só vídeos (sem canais/playlists)
    raw = (bytes([0x08, _SORT[sort]]) if _SORT[sort] else b"") + bytes([0x12, len(filters)]) + filters
    return base64.b64encode(raw).decode()


def related(c: httpx.Client, video_id: str, hl: str = "pt-BR", gl: str = "BR") -> tuple[dict, list[tuple[str, str]]]:
    """(info do vídeo, [(id, título) dos sugeridos na ordem da barra lateral]). hl/gl = idioma e país do visitante:
    abrir um vídeo em inglês como brasileiro faz o YouTube completar com o que é popular no Brasil."""
    data = _initial_data(c, "https://www.youtube.com/watch", {"v": video_id, "hl": hl, "gl": gl},
                         headers={"Accept-Language": f"{hl},{hl.split('-')[0]};q=0.9"})
    if not data:
        return {}, []
    info = {}
    try:
        primary = data["contents"]["twoColumnWatchNextResults"]["results"]["results"]["contents"]
        for block in primary:
            if "videoPrimaryInfoRenderer" in block:
                info["title"] = "".join(r.get("text", "") for r in block["videoPrimaryInfoRenderer"]["title"]["runs"])
            if "videoSecondaryInfoRenderer" in block:
                owner = block["videoSecondaryInfoRenderer"]["owner"]["videoOwnerRenderer"]["title"]["runs"]
                info["channel"] = "".join(r.get("text", "") for r in owner)
    except (KeyError, TypeError):
        pass
    col = _Collector()
    col.walk(data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("secondaryResults", {}))
    col.found.pop(video_id, None)
    return info, [(vid, v["title"]) for vid, v in col.found.items()]


def search(c: httpx.Client, query: str, sort: str = "relevancia", upload: str | None = None,
           hl: str = "pt-BR", gl: str = "BR") -> list[tuple[str, str]]:
    """Primeira página de resultados (cerca de 20 vídeos), sem shorts. hl/gl = idioma e país da busca."""
    data = _initial_data(c, "https://www.youtube.com/results",
                         {"search_query": query, "sp": _sp(sort, upload), "hl": hl, "gl": gl},
                         headers={"Accept-Language": f"{hl},{hl.split('-')[0]};q=0.9"})
    if not data:
        return []
    col = _Collector()
    col.walk(data.get("contents", {}))
    return [(vid, v["title"]) for vid, v in col.found.items()]
