"""Raspa a home do YouTube usando um perfil treinado.

Em vez de ler o HTML (que muda toda hora), lemos o JSON interno do YouTube:
- `ytInitialData` do carregamento inicial
- as respostas de `/youtubei/v1/browse` que chegam a cada scroll
Daqui só precisamos dos IDs (e do título como reserva); os números exatos vêm da API oficial.
"""
from pathlib import Path
from typing import Callable


from . import config

# Blocos de anúncio: ignorados por inteiro.
_AD_KEYS = {
    "adSlotRenderer", "promotedSparklesWebRenderer", "promotedVideoRenderer",
    "displayAdRenderer", "inFeedAdLayoutRenderer", "statementBannerRenderer",
}
# Shorts: o foco é vídeo longo, então a prateleira de shorts é ignorada.
_SHORTS_KEYS = {"shortsLockupViewModel", "reelItemRenderer", "reelShelfRenderer"}


def _text(node) -> str:
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return node["simpleText"]
    if "runs" in node:
        return "".join(r.get("text", "") for r in node["runs"])
    if "content" in node:
        return node["content"]
    return ""


def _dig(node, *keys):
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


class _Collector:
    def __init__(self):
        self.found: dict[str, dict] = {}

    def _add(self, video_id, title, surface):
        if not isinstance(video_id, str) or len(video_id) != 11 or video_id in self.found:
            return
        self.found[video_id] = {"title": title or "", "surface": surface, "position": len(self.found) + 1}

    def walk(self, node) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in _AD_KEYS or not isinstance(val, (dict, list)):
                    continue
                if key == "videoRenderer" and isinstance(val, dict):
                    self._add(val.get("videoId"), _text(val.get("title")), "home")
                elif key == "lockupViewModel" and isinstance(val, dict):
                    if val.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":
                        title = _dig(val, "metadata", "lockupMetadataViewModel", "title", "content")
                        self._add(val.get("contentId"), title, "home")
                    else:
                        continue  # playlists/mixes: não entra
                elif key in _SHORTS_KEYS:
                    continue  # shorts: não entram
                self.walk(val)
        elif isinstance(node, list):
            for item in node:
                self.walk(item)


def collect_home(
    profile_dir: Path,
    scrolls: int = config.DEFAULT_SCROLLS,
    show_browser: bool = False,
    on_progress: Callable[[int, int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    page: str = "home",
) -> dict:
    """Abre a home com o perfil, rola `scrolls` vezes e devolve os vídeos que o algoritmo entregou."""
    from playwright.sync_api import sync_playwright  # só aqui: o Playwright pesa para carregar
    col = _Collector()
    pending = []
    # 'home' = página inicial (o que o algoritmo empurra); 'history' = histórico (o que o perfil assistiu)
    url = "https://www.youtube.com/feed/history" if page == "history" else "https://www.youtube.com/"

    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        # Sem isso o Chrome "congela" a página quando a janela está fora da tela.
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]
    if not show_browser:
        # Janela real (evita detecção de headless), só que fora da tela.
        args.append("--window-position=-32000,-32000")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=args,
            ignore_default_args=["--enable-automation"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on(
                "response",
                lambda r: pending.append(r) if "/youtubei/v1/browse" in r.url else None,
            )

            def drain():
                while pending:
                    resp = pending.pop(0)
                    try:
                        col.walk(resp.json())
                    except Exception:
                        pass

            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)
            initial = page.evaluate("() => window.ytInitialData || null")
            if initial:
                col.walk(initial)
            logged_in = page.locator("#avatar-btn").count() > 0

            stale = 0
            for i in range(scrolls):
                if should_stop and should_stop():  # cancelado: fica com o que já rolou
                    break
                before = len(col.found)
                page.mouse.wheel(0, 6000)
                page.wait_for_timeout(config.SCROLL_WAIT_MS)
                drain()
                stale = stale + 1 if len(col.found) == before else 0
                if on_progress:
                    on_progress(i + 1, scrolls, len(col.found))
                if stale >= config.STALE_SCROLLS_TO_STOP:  # parou de carregar coisa nova
                    break
            drain()
        finally:
            ctx.close()

    return {"logged_in": logged_in, "videos": col.found}
