"""Gera o darkbot.exe (um arquivo só, abre rápido).

    .venv\\Scripts\\python tools\\build_exe.py

1. PyInstaller monta o app numa pasta (onedir: abre rápido, nada é descompactado a cada abertura).
2. A pasta vira um zip, que vai DENTRO de um lançador pequeno em C# (compilado com o .NET do Windows).
3. Na primeira vez o lançador descompacta em %LOCALAPPDATA%\\darkbot\\app\\<versão>; depois só abre.

Chaves nunca vão no .exe: o app/secrets.py é excluído e o script confere o pacote antes de terminar.
Saída: dist\\darkbot.exe
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ICON = ROOT / "tools" / "darkbot.ico"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NET = CSC.parent


def make_icon():
    """Ícone do app (roxo Rocketseat com o radar), em vários tamanhos."""
    from PIL import Image, ImageDraw
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=(int(153 + (130 - 153) * t), int(109 + (87 - 109) * t), int(255 + (229 - 255) * t), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, S - 8, S - 8], radius=58, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    c, w = S // 2, 15
    d.arc([c - 78, c - 78, c + 78, c + 78], start=0, end=270, fill="white", width=w)
    d.arc([c - 44, c - 44, c + 44, c + 44], start=0, end=270, fill="white", width=w)
    d.ellipse([c - 11, c - 11, c + 11, c + 11], fill="white")
    d.line([c, c, c + 64, c - 64], fill="white", width=w)
    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def version() -> str:
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', (ROOT / "app" / "config.py").read_text(encoding="utf-8"))
    return m.group(1)


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd)[:220], flush=True)
    subprocess.run(cmd, check=True, **kw)


def main():
    if not ICON.exists():
        make_icon()
    pyi_dist, work = BUILD / "pyi-dist", BUILD / "pyi-work"
    shutil.rmtree(pyi_dist, ignore_errors=True)

    # 1) app em pasta (onedir), janela sem console
    run([sys.executable, "-m", "PyInstaller", str(ROOT / "main.py"), "--name", "darkbot", "--onedir", "--windowed",
         "--noconfirm", "--clean", "--icon", str(ICON),
         "--distpath", str(pyi_dist), "--workpath", str(work), "--specpath", str(BUILD),
         "--add-data", f"{ROOT / 'app' / 'ui'};app/ui",
         "--exclude-module", "app.secrets",            # chaves NUNCA vão no .exe
         "--exclude-module", "tkinter", "--exclude-module", "PIL", "--exclude-module", "numpy",
         "--collect-submodules", "uvicorn",
         "--collect-submodules", "anthropic", "--collect-submodules", "openai",   # importados sob demanda
         "--hidden-import", "anthropic", "--hidden-import", "openai",
         "--collect-all", "webview",
         ], cwd=ROOT)
    app_dir = pyi_dist / "darkbot"

    # 2) conferência de segurança: nenhuma chave dentro do pacote
    secrets = ROOT / "app" / "secrets.py"
    keys = re.findall(r'"([^"]{20,})"', secrets.read_text(encoding="utf-8")) if secrets.exists() else []
    for f in app_dir.rglob("*"):
        if f.is_file() and f.stat().st_size < 60_000_000:
            data = f.read_bytes()
            for k in keys:
                if k.encode() in data:
                    sys.exit(f"ERRO: chave encontrada dentro do pacote ({f}). Build cancelado.")
            if f.name.startswith("secrets") and "app" in f.parts:
                sys.exit(f"ERRO: {f} entrou no pacote. Build cancelado.")
    if not list(app_dir.rglob("node.exe")):
        sys.exit("ERRO: o Playwright (node.exe) não entrou no pacote.")
    if not list(app_dir.rglob("app/ui/index.html")):
        sys.exit("ERRO: a interface (app/ui) não entrou no pacote.")
    print("ok: sem chaves, Playwright e interface presentes", flush=True)

    # 3) zip da pasta
    payload = BUILD / "payload.zip"
    payload.unlink(missing_ok=True)
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app_dir).as_posix())
    digest = hashlib.sha1(payload.read_bytes()).hexdigest()[:8]
    ver = f"{version()}-{digest}"

    # 4) lançador em C# com o zip dentro
    src = (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8")
    asm = ".".join((version().split(".") + ["0", "0", "0"])[:4])
    cs = BUILD / "launcher.cs"
    cs.write_text(src.replace("__VERSION__", ver).replace("__ASMVERSION__", asm), encoding="utf-8")
    DIST.mkdir(exist_ok=True)
    out = DIST / "darkbot.exe"
    run([str(CSC), "/nologo", "/target:winexe", "/optimize+", f"/out:{out}", f"/win32icon:{ICON}",
         f"/resource:{payload},payload.zip",
         f"/reference:{NET / 'System.IO.Compression.dll'}", f"/reference:{NET / 'System.IO.Compression.FileSystem.dll'}",
         "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll", str(cs)])
    print(f"\npronto: {out}  ({out.stat().st_size / 1e6:.0f} MB, versão {ver})")


if __name__ == "__main__":
    main()
