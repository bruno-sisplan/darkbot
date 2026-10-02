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

from .scraper import _Collector, _dig

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/141.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
PAUSE_S = 0.15  # pausa por página, em cada thread (as páginas abrem em paralelo)
WORKERS = 6     # páginas da pesquisa abertas ao mesmo tempo

_INITIAL = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)
_CLIENT_VERSION = re.compile(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"')
_API_KEY = re.compile(r'"INNERTUBE_API_KEY":"([^"]+)"')
_CFG: dict[str, str] = {}   # versão do cliente web e chave interna, lidas da 1ª página (para o "carregar mais")
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
    if "ver" not in _CFG:
        if (v := _CLIENT_VERSION.search(html)):
            _CFG["ver"] = v.group(1)
        if (k := _API_KEY.search(html)):
            _CFG["key"] = k.group(1)
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


def _token(node) -> str | None:
    """Token do "carregar mais" (continuationItemRenderer) dentro do bloco, se houver."""
    if isinstance(node, dict):
        cir = node.get("continuationItemRenderer")
        if isinstance(cir, dict):
            t = (_dig(cir, "continuationEndpoint", "continuationCommand", "token")
                 or _dig(cir, "button", "buttonRenderer", "command", "continuationCommand", "token"))
            if t:
                return t
        for v in node.values():
            if isinstance(v, (dict, list)) and (t := _token(v)):
                return t
    elif isinstance(node, list):
        for v in node:
            if (t := _token(v)):
                return t
    return None


def _more(c: httpx.Client, endpoint: str, token: str, hl: str, gl: str) -> dict | None:
    """Próxima página (o mesmo pedido que o site faz ao rolar): /youtubei/v1/search ou /youtubei/v1/next."""
    body = {"context": {"client": {"clientName": "WEB", "clientVersion": _CFG.get("ver", "2.20251001.00.00"),
                                   "hl": hl, "gl": gl}}, "continuation": token}
    try:
        r = c.post(f"https://www.youtube.com/youtubei/v1/{endpoint}", json=body,
                   params={"key": _CFG["key"], "prettyPrint": "false"} if _CFG.get("key") else {"prettyPrint": "false"},
                   headers={"Accept-Language": f"{hl},{hl.split('-')[0]};q=0.9"})
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as e:
        print(f"[youtube_web] carregar mais ({endpoint}): {e}")
        return None
    finally:
        time.sleep(PAUSE_S)


def _paginate(c: httpx.Client, endpoint: str, first: dict, col: _Collector, pages: int, hl: str, gl: str) -> None:
    """Lê mais `pages - 1` páginas a partir do bloco da 1ª, juntando no mesmo coletor."""
    token = _token(first)
    for _ in range(pages - 1):
        if not token:
            break
        data = _more(c, endpoint, token, hl, gl)
        if not data:
            break
        before = len(col.found)
        col.walk(data.get("onResponseReceivedCommands") or data.get("onResponseReceivedEndpoints") or data)
        token = _token(data)
        if len(col.found) == before:   # página sem vídeo novo: acabou
            break


def suggest(c: httpx.Client, term: str, hl: str = "pt-BR", gl: str = "BR") -> list[str]:
    """O que a busca do YouTube completa quando alguém começa a digitar `term` naquele país (autocompletar do site).
    Muitas sugestões = muita gente buscando aquilo lá."""
    try:
        r = c.get("https://suggestqueries.google.com/complete/search",
                  params={"client": "firefox", "ds": "yt", "q": term, "hl": hl, "gl": gl})
        data = r.json() if r.status_code == 200 else []
        return [s for s in (data[1] if len(data) > 1 else []) if isinstance(s, str) and s.strip()]
    except (httpx.HTTPError, ValueError) as e:
        print(f"[youtube_web] autocompletar: {e}")
        return []
    finally:
        time.sleep(PAUSE_S)


def related(c: httpx.Client, video_id: str, hl: str = "pt-BR", gl: str = "BR",
            pages: int = 1) -> tuple[dict, list[tuple[str, str]]]:
    """(info do vídeo, [(id, título) dos sugeridos na ordem da barra lateral]). hl/gl = idioma e país do visitante:
    abrir um vídeo em inglês como brasileiro faz o YouTube completar com o que é popular no Brasil.
    pages > 1 = continua a barra lateral (uns 20 sugeridos a mais por página)."""
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
    side = data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("secondaryResults", {})
    col.walk(side)
    if pages > 1:
        _paginate(c, "next", side, col, pages, hl, gl)
    col.found.pop(video_id, None)
    return info, [(vid, v["title"]) for vid, v in col.found.items()]


def search(c: httpx.Client, query: str, sort: str = "relevancia", upload: str | None = None,
           hl: str = "pt-BR", gl: str = "BR", pages: int = 1) -> list[tuple[str, str]]:
    """Resultados da busca (uns 20 vídeos por página), sem shorts. hl/gl = idioma e país da busca.
    pages > 1 = rola os resultados (o mesmo "carregar mais" do site)."""
    data = _initial_data(c, "https://www.youtube.com/results",
                         {"search_query": query, "sp": _sp(sort, upload), "hl": hl, "gl": gl},
                         headers={"Accept-Language": f"{hl},{hl.split('-')[0]};q=0.9"})
    if not data:
        return []
    col = _Collector()
    col.walk(data.get("contents", {}))
    if pages > 1:
        _paginate(c, "search", data.get("contents", {}), col, pages, hl, gl)
    return [(vid, v["title"]) for vid, v in col.found.items()]


_AUDIO = re.compile(r'"audioTrack":\{"displayName":"([^"]*)","id":"([A-Za-z]{2,3})[^"]*"')


def audio_langs(c: httpx.Client, video_id: str) -> dict[str, str]:
    """Faixas de áudio do vídeo: {idioma: "original" | "dublado"}. O YouTube (ou o canal) pode dublar o vídeo em
    outras línguas: quem fala essa língua ouve o vídeo nela, então ali o vídeo JÁ EXISTE (não é mercado livre)."""
    try:
        html = c.get("https://www.youtube.com/watch", params={"v": video_id, "hl": "en"},
                     headers={"Accept-Language": "en"}).text
    except httpx.HTTPError as e:
        print(f"[youtube_web] faixas de áudio de {video_id}: {e}")
        return {}
    finally:
        time.sleep(PAUSE_S)
    out: dict[str, str] = {}
    for name, code in _AUDIO.findall(html):
        code = code.lower()
        if "original" in name.lower():
            out[code] = "original"
        else:
            out.setdefault(code, "dublado")
    return out
