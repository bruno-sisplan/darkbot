# darkbot

Radar de nichos para canais dark do YouTube (app desktop Python: FastAPI + pywebview + Playwright + SQLite).

**Antes de qualquer tarefa, leia `docs/CONTEXTO.md`.** Ele tem o histórico completo: visão do usuário, decisões e motivos, gosto visual, estado atual, como rodar e testar, problemas conhecidos e o roadmap (seção 9 = onde paramos).

Regras rápidas:
- Conversar em português (BR).
- Configuração hardcoded em `app/config.py`, sem .env. Nunca commitar chaves de API.
- Visual soft/clean/arredondado, paleta Rocketseat (tokens em `app/ui/style.css`); conferir mudanças de UI com screenshot no modo `--demo`.
- IA econômica: números filtram, IA só interpreta outliers; Haiku para massa, Sonnet para síntese; cachear resultados.
- O .exe com auto-update fica por último.
- Ao terminar algo relevante, atualizar a seção 9 de `docs/CONTEXTO.md`.
