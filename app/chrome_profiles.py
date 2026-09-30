"""Perfis de navegador: listar perfis do Chrome, importar (copiar) para o darkbot e abrir para login/treino.

As recomendações do YouTube vêm do histórico da conta Google. Importar um perfil = levar a sessão
logada daquela conta para uma pasta própria do darkbot, que o scraper usa sem mexer no Chrome do dia a dia.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

# Pastas de cache que não precisam ser copiadas (deixam a importação lenta e pesada).
_IGNORE = shutil.ignore_patterns(
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "GrShaderCache", "GraphiteDawnCache", "ShaderCache", "Service Worker", "blob_storage",
    "optimization_guide*", "Download Service", "*.tmp", "LOCK", "lockfile",
)


def find_chrome() -> str | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def chrome_user_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def list_chrome_profiles() -> list[dict]:
    ud = chrome_user_data()
    try:
        state = json.loads((ud / "Local State").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cache = state.get("profile", {}).get("info_cache", {})
    out = []
    for folder, info in cache.items():
        if (ud / folder).is_dir():
            out.append({
                "folder": folder,
                "name": info.get("name") or folder,
                "email": info.get("user_name") or "",
            })
    return sorted(out, key=lambda p: p["folder"])


def chrome_running() -> bool:
    try:
        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "chrome.exe" in res.stdout.lower()
    except OSError:
        return False


def close_chrome(timeout: float = 8) -> bool:
    """Fecha o Chrome (primeiro educadamente; se não fechar, força). Ele restaura as abas ao reabrir."""
    import time
    flags = subprocess.CREATE_NO_WINDOW
    subprocess.run(["taskkill", "/IM", "chrome.exe"], capture_output=True, creationflags=flags)
    end = time.time() + timeout
    while time.time() < end:
        if not chrome_running():
            return True
        time.sleep(0.4)
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, creationflags=flags)
    time.sleep(1)
    return not chrome_running()


def import_profile(chrome_folder: str, dest: Path) -> None:
    """Copia um perfil do Chrome para `dest` (vira o perfil 'Default' de um user-data-dir próprio)."""
    ud = chrome_user_data()
    src = ud / chrome_folder
    if not src.is_dir():
        raise ValueError(f"Perfil do Chrome não encontrado: {chrome_folder}")
    if chrome_running():
        raise RuntimeError("Feche o Google Chrome (todas as janelas) antes de importar o perfil.")

    dest.mkdir(parents=True, exist_ok=True)
    # O 'Local State' guarda a chave que descriptografa os cookies (a sessão logada).
    shutil.copy2(ud / "Local State", dest / "Local State")
    try:
        shutil.copytree(src, dest / "Default", ignore=_IGNORE, dirs_exist_ok=True)
    except shutil.Error as e:
        failed = [str(err[0]) for err in e.args[0]]
        if any("Cookies" in f for f in failed):
            raise RuntimeError("Não consegui copiar os cookies (Chrome ainda aberto?). Feche o Chrome e tente de novo.")


def profile_in_use(profile_dir: Path) -> bool:
    """O Chrome mantém 'lockfile' travado enquanto o perfil está aberto."""
    lock = profile_dir / "lockfile"
    if not lock.exists():
        return False
    try:
        lock.unlink()
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def open_for_login(profile_dir: Path) -> None:
    """Abre um Chrome normal (sem automação) nesse perfil, para logar na conta ou treinar o algoritmo."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Google Chrome não encontrado neste PC.")
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([
        chrome,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.youtube.com/",
    ])
