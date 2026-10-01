"""Ponto de entrada: sobe a API local e abre a janela do app.

    python main.py            -> janela nativa
    python main.py --browser  -> abre no navegador (útil para desenvolver a interface)
    python main.py --demo     -> usa o banco de demonstração (tools/seed_demo.py)
"""
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

if "--demo" in sys.argv:  # precisa vir antes de importar o app (define a pasta de dados)
    os.environ["DARKBOT_HOME"] = os.path.join(os.environ.get("LOCALAPPDATA", ""), "darkbot-demo")
    os.environ["DARKBOT_DEMO"] = "1"

from app import db
from app.paths import DATA_DIR
from app.server import app

# Sem console (pythonw / .exe), stdout e stderr são None e o log do uvicorn quebra. Manda tudo para um arquivo.
if sys.stdout is None or sys.stderr is None:
    _log = open(DATA_DIR / "darkbot.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(port: int, timeout: float = 10) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)


def main() -> None:
    db.init()
    db.recover_interrupted()
    port = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--port=")), 0)) or _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_up(port)
    url = f"http://127.0.0.1:{port}/"

    if "--serve" in sys.argv:  # só o servidor, sem janela (testes)
        print(f"darkbot rodando em {url}", flush=True)
        thread.join()
        return

    if "--browser" in sys.argv:
        print(f"darkbot rodando em {url}")
        webbrowser.open(url)
        thread.join()
        return

    try:
        import webview

        webview.create_window(
            "darkbot", url, width=1440, height=900, min_size=(1100, 680), background_color="#09090A",
        )
        webview.start()
    except Exception:
        # Sem WebView2 (ou falhou ao abrir a janela): usa o navegador em vez de quebrar.
        import traceback
        traceback.print_exc()
        webbrowser.open(url)
        thread.join()
        return
    server.should_exit = True


if __name__ == "__main__":
    main()
