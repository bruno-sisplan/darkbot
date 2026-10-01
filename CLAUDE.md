# darkbot

Radar de nichos para canais dark do YouTube (app desktop Python: FastAPI + pywebview + Playwright + SQLite).

**Antes de qualquer tarefa, leia `docs/CONTEXTO.md`.** Ele tem o histórico completo: visão do usuário, decisões e motivos, gosto visual, estado atual, como rodar e testar, problemas conhecidos e o roadmap (seção 9 = onde paramos).

Regras rápidas:
- Conversar em português (BR).
- Parâmetros fixos em `app/config.py`, sem .env. As chaves de API ficam na aba Configurações do app (banco local). Nunca commitar chaves: `app/secrets.py` e `MINHAS_CHAVES.txt` são ignorados pelo git.
- Visual soft/clean/arredondado, paleta Rocketseat (tokens em `app/ui/style.css`); conferir mudanças de UI com screenshot no modo `--demo`.
- IA econômica: números filtram, IA só interpreta; modelo rápido para massa, inteligente para síntese; cachear resultados; respostas compactas; nada automático que gaste sem o usuário pedir. Claude ou ChatGPT, escolhido em Configurações.
- Linguagem simples na interface, com explicação ao passar o mouse em tudo (ver seção 4 do CONTEXTO).
- O .exe sai de `tools/build_exe.py` (ver `COMO_GERAR_VERSAO.txt`). Falta o auto-update.
- Não reiniciar o app que o usuário está usando sem ele pedir; testar em servidor separado (outra porta) e em cópia do banco.
- Ao terminar algo relevante, atualizar a seção 9 de `docs/CONTEXTO.md`.
