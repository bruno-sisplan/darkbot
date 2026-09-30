"""Onde o darkbot guarda dados (banco, perfis) e onde ficam os arquivos do app."""
import os
import sys
from pathlib import Path


def _data_dir() -> Path:
    base = os.environ.get("DARKBOT_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "darkbot"
    )
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _data_dir()
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "darkbot.db"

# Quando empacotado com PyInstaller, os arquivos ficam em sys._MEIPASS.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
UI_DIR = APP_DIR / "app" / "ui"
