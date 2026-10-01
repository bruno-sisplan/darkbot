# darkbot

Radar de nichos para canais dark no YouTube. Usa perfis do Chrome já treinados num nicho, rola a home, registra o que o algoritmo entrega e ranqueia os outliers (views ÷ inscritos).

## Rodar

Requisitos: Windows, Python 3.12+ e Google Chrome instalado.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

- `darkbot.bat`: abre o app (banco real)
- `darkbot-demo.bat`: abre com dados de demonstração (gerados por `.venv\Scripts\python tools\seed_demo.py`)
- `python main.py --browser`: abre no navegador em vez da janela

As chaves (YouTube, Anthropic, OpenAI) são colocadas na aba **Configurações** do app. Os dados ficam em `%LOCALAPPDATA%\darkbot`.

## Gerar o .exe

```
.venv\Scripts\pip install pyinstaller pillow
.venv\Scripts\python toolsuild_exe.py
```

Sai em `dist\darkbot.exe` (um arquivo só, ~60 MB). Na primeira vez que abre, ele se prepara em `%LOCALAPPDATA%\darkbotpp\<versão>` (2 a 3 s); depois abre em ~1,5 s. Nenhuma chave vai dentro do .exe (o build confere). Quem recebe precisa de Windows 10/11 64 bits e do Google Chrome.
