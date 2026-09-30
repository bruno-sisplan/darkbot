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

Chaves e parâmetros ficam em `app/config.py`. Os dados ficam em `%LOCALAPPDATA%\darkbot`.
