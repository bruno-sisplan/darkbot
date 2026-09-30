# darkbot: contexto completo do projeto

Documento de passagem de bastão. Resume tudo o que foi conversado e combinado na primeira sessão de desenvolvimento (30/09/2026), para continuar o trabalho em outra máquina ou com outro Claude sem perder nada.

**Se você é o Claude lendo isto:** leia até o fim antes de mexer no código. A seção 9 diz exatamente onde paramos e o que fazer a seguir. Converse com o usuário em português.

---

## 1. Quem é o usuário e qual o problema

O usuário (Bruno) tem **canais dark no YouTube**: canais sem rosto, com narração (própria, locutor ou IA) e visual de banco de imagens, animação ou IA, em nichos como mistério, true crime, curiosidades, terror e histórias.

Para decidir **que conteúdo fazer** num canal novo, ou num que já está rodando, ele faz **análise de mercado e garimpo**. O processo manual dele hoje:

1. Abre um **perfil novo ("virgem") no Chrome** e cria uma conta no YouTube.
2. Pesquisa e assiste vídeos dark de **um nicho específico**, até o YouTube passar a recomendar **só aquele nicho** na home e nas sugestões.
3. Vira **público do próprio nicho**: acompanha a concorrência, vê o que vale modelar e o que não, a estrutura dos títulos, thumbnails, tudo.

Estratégia complementar, sugerida por um parceiro dele: um **perfil "coringa"**, uma conta que consumiu vários nichos dark. O algoritmo passa a trazer tudo que é dark, e isso serve para **achar coisa nova**. É uma estratégia que já é usada hoje.

Detalhe importante: os perfis são mantidos **sempre pré-prontos (treinados)**. A ferramenta só precisa **entrar e fazer a função dela**, sem treinar nada.

## 2. A visão (o que o usuário quer)

Palavras e ideias do próprio usuário, organizadas:

- **Automatizar e parametrizar** esse processo, para ter **tomadas de decisão rápidas**.
- **Começar amplo e ir aprofundando**, com possibilidade de **adicionar coisas pré-existentes** (canais que ele já tem rodando).
- O radar é **só o ponto de partida**: a ferramenta vai ganhar muitas funções, e várias delas vão precisar de **scraping** (por isso Python).
- **Rapidez e fluidez são essenciais.** Nada pode ser lento.
- Outra pessoa (sócio ou equipe) precisa **acessar também**.
- Integrar a **API do Claude para a IA analisar**, e talvez **skills e agentes**, mas **gastando poucos tokens**: "tem que ser econômico, mas não quero nada burro também".
- Um **.exe bonito e bem estilizado**, que se **auto-atualiza pelo GitHub**. Isso fica **POR ÚLTIMO**.
- **Configuração toda no código (hardcoded), sem .env.**

## 3. Decisões tomadas (e por quê)

| Decisão | Motivo / histórico |
|---|---|
| **Python** (não Node) | O usuário escolheu Node no início, depois corrigiu: vai precisar de muito scraping (Playwright, yt-dlp) e o Python é mais forte nisso. |
| **App desktop (.exe)**, não site na Vercel | A Vercel foi cogitada, mas as funções dela têm limite de tempo e não rodam navegador para scraping. O usuário preferiu um exe. |
| **FastAPI local + janela pywebview + interface em HTML/CSS/JS puro** | Janela nativa leve (WebView2 do Windows), sem Electron e sem etapa de build. Tudo abre rápido. |
| **A interface só lê dados prontos; o trabalho pesado roda em segundo plano** | É o que garante fluidez. As coletas rodam em threads, com barra de progresso, e a tela nunca espera o YouTube. |
| **Filtros e ordenação rodam no navegador** | Os dados são carregados uma vez e os filtros aplicam na hora. |
| **Playwright usando o Chrome instalado** (`channel="chrome"`) | Não precisa baixar outro navegador e a sessão copiada funciona com o Chrome real. |
| **Scraping lê o JSON interno do YouTube** (`ytInitialData` + respostas `/youtubei/v1/browse`), não o HTML | O HTML muda o tempo todo; o JSON é bem mais estável. |
| **O scraping descobre os vídeos, a API oficial dá os números** | A YouTube Data API custa 1 unidade de cota a cada 50 vídeos (quase de graça). Já a busca custa 100 unidades, por isso a descoberta é feita pelo scraping. |
| **SQLite local agora, Supabase depois** | Poucas pessoas vão usar, com login. Todo acesso ao banco passa por `app/db.py`, para facilitar a troca. |
| **Config hardcoded em `app/config.py`** | Pedido explícito do usuário: "tudo hardcoded, sem .env". |
| **Auto-update do exe por último** | Pedido explícito. Primeiro o básico funcionando. |
| **Visual: estilo "soft/clean", paleta Rocketseat** | Ver seção 4. |

### Pontos em aberto já discutidos (sem decisão final)

- **Chaves no GitHub:** as chaves no `config.py` vão para o repositório ao commitar. A sugestão, ainda sem resposta do usuário, é criar um `app/secrets.py` ignorado pelo git, também hardcoded, só com as chaves. **Pergunte antes de colocar chaves reais.**
- **Token do auto-update:** qualquer token embutido no exe pode ser extraído. Duas opções foram recomendadas: (a) código num repo privado e os executáveis num repo **público** só de releases, sem token; ou (b) token *fine-grained* **somente leitura** de um único repo. As chaves do YouTube e do Claude também não deveriam ficar dentro do exe distribuído: com o Supabase, elas passam a ficar no banco, protegidas por RLS e liberadas só depois do login.

## 4. Gosto visual do usuário (importante)

- Quer um app **bonito**: **campos pequenos, soft, clean, arredondado**. "Não me venha com grosserias nem coisas quadradas."
- Primeira referência: um app chamado "Invisible Studio", com sidebar com seções em caixa-alta miúda, chips/pílulas para seleção, botão principal com brilho e cards arredondados.
- Paleta final: **estilo rocketseat.com.br**. Fundo quase preto (`#09090A` / `#121214`), **roxo `#8257E5` / `#996DFF`** como destaque (com degradê e brilho suave) e **verde neon `#04D361`** para sinais positivos.
- Todas as cores ficam como tokens no `:root` de `app/ui/style.css`. Para mudar a paleta, mexa só ali.
- Depois de qualquer mudança visual, **confira com um screenshot**: Playwright abrindo `http://127.0.0.1:<porta>/` com o servidor rodando no modo demo.

## 5. O que já existe (estado em 30/09/2026)

Repositório: https://github.com/bruno-sisplan/darkbot (branch `main`).

### Estrutura

```
main.py                 entrada: sobe a API local e abre a janela (--browser, --demo, --port=N)
darkbot.bat             abre o app com o banco real (dois cliques)
darkbot-demo.bat        abre o app com o banco de demonstração
requirements.txt        fastapi, uvicorn, httpx, playwright, pywebview
app/
  config.py             chaves e parâmetros fixos (VERSION, YOUTUBE_API_KEY, ANTHROPIC_API_KEY, scrolls, cache, etc.)
  paths.py              pastas de dados (%LOCALAPPDATA%\darkbot, ou DARKBOT_HOME) e da interface (compatível com PyInstaller)
  db.py                 SQLite: schema, helpers rows/row/tx, settings
  chrome_profiles.py    lista, importa (copia), abre para login, fecha o Chrome, detecta perfil em uso
  scraper.py            Playwright: abre a home com o perfil, rola, extrai IDs do JSON interno
  youtube_api.py        YouTube Data API v3: vídeos e canais em lotes de 50, erros amigáveis
  jobs.py               tarefas em segundo plano com progresso; pipeline de coleta e enriquecimento
  analytics.py          métricas: multiplicador, views/dia, crescimento, idade do canal, vezes visto
  titles.py             padrões de título dos outliers vs. demais (sem IA)
  server.py             rotas FastAPI (/api/...) + arquivos da interface
  ui/index.html, style.css, app.js    interface (JS puro, sem build)
tools/seed_demo.py      gera o banco de DEMONSTRAÇÃO
docs/CONTEXTO.md        este arquivo
```

### Banco (SQLite)

- `profiles`: perfis (nome, tipo `nicho`/`coringa`, nicho, origem, pasta)
- `runs`: cada coleta (perfil, status, logado?, vídeos encontrados, erro)
- `videos`: dados do vídeo vindos da API
- `channels`: dados do canal vindos da API
- `sightings`: em que coleta cada vídeo apareceu e em que posição (mede "quanto o algoritmo empurra")
- `video_stats`: histórico de views por coleta (mede crescimento)
- `settings`: chave da API salva pela tela (tem prioridade sobre a do `config.py`)

### Fluxo de uma coleta

1. Confere se o perfil não está aberto no Chrome (usa o `lockfile` da pasta).
2. Abre o Chrome real com o perfil, **fora da tela** (`--window-position=-32000,-32000`). Não usa headless porque o YouTube detecta. Usa flags para o Chrome não congelar a página quando a janela não está visível.
3. Lê o `ytInitialData`, rola N vezes e lê cada resposta `/youtubei/v1/browse`. Extrai `videoRenderer`, `lockupViewModel` (só vídeo, ignora playlists e mixes), `shortsLockupViewModel` e `reelItemRenderer`. Ignora anúncios. Para de rolar depois de 3 scrolls sem vídeo novo.
4. Salva os vídeos e as aparições.
5. Se houver chave da API, busca os números: vídeos só se a última atualização tiver mais de 6h, canais só se tiver mais de 24h (economia de cota).

### Telas

- **Descobertas:** vídeos ranqueados por **multiplicador** (views ÷ inscritos), com views/dia, "crescendo" (views/dia entre as duas últimas coletas), inscritos, idade e "visto N×". Filtros: longo/short, data de publicação, inscritos, idade do canal, multiplicador mínimo e busca. Marcações: "Canal novo" (≤ 6 meses), "Recente" (≤ 7 dias) e "Short". Quatro indicadores no topo. Clicar abre o vídeo no navegador.
- **Canais:** concorrentes com melhor multiplicador, média de views/dia, inscritos, nº de vídeos, idade, aparições e vídeo destaque.
- **Títulos:** outliers (top 10% ou 20%, ou multiplicador ≥ 3× ou ≥ 10×) comparados com os demais. Mostra formatos (número, pergunta, CAPS, emoji, separador, "você", superlativo, negação) com o multiplicador mediano com e sem cada um, palavras que puxam, pares de palavras, aberturas (as duas primeiras palavras), tamanho do título e a lista dos títulos outliers.
- **Perfis:** importar do Chrome (lista os perfis do `Local State`, com botão "Fechar o Chrome") ou criar e logar. Tipo nicho ou coringa. "Abrir p/ login" abre um Chrome **normal, sem automação** (o Google bloqueia login em navegador automatizado). "Coletar agora" tem nº de scrolls e opção "ver navegador". Mostra também o histórico de coletas.
- **Configurações:** chave da API do YouTube (é validada ao salvar).
- Na sidebar, "Análise IA" e "Transcrições" aparecem com o selo **EM BREVE**.

### Modo demonstração

- `tools/seed_demo.py` busca **vídeos reais** no YouTube (12 buscas em nichos dark, cerca de 400 vídeos, com títulos e thumbnails reais) e gera **números simulados**: 4 perfis (3 nichos + 1 coringa), cerca de 80 canais e 3 coletas por perfil.
- Os dados ficam em `%LOCALAPPDATA%\darkbot-demo`, separados do banco real. O rodapé do app mostra o selo **DEMO**.
- De propósito, a demo dá vantagem a títulos com número e com palavras como "nunca", "segredo" e "proibido", para a tela de Títulos ter padrão para mostrar. **Não tire conclusões sobre nichos a partir da demo.**
- `--fresh` busca os vídeos de novo; sem ele, usa o cache `demo_videos.json`.

## 6. Como rodar

### Requisitos

- **Windows 10/11** (usa WebView2, `tasklist`/`taskkill` e as pastas do Chrome no Windows)
- **Python 3.12+** (desenvolvido no 3.14)
- **Google Chrome** instalado
- **Git**
- Chave da **YouTube Data API v3**: Google Cloud Console → criar projeto → ativar "YouTube Data API v3" → Credenciais → Chave de API. É grátis, com 10.000 unidades por dia.
- Para a próxima fase: chave da **API da Anthropic** (console.anthropic.com). É cobrada à parte. Os créditos de "sessões na nuvem" do Claude Code **não** servem para isso.

### Instalação

```
git clone https://github.com/bruno-sisplan/darkbot.git
cd darkbot
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Não precisa rodar `playwright install`: o app usa o Chrome já instalado.

### Rodar

- App com o banco real: `darkbot.bat` (dois cliques) ou `.venv\Scripts\python main.py`
- App com os dados de teste: `darkbot-demo.bat` ou `.venv\Scripts\python main.py --demo`
- No navegador em vez da janela: adicionar `--browser`
- Gerar ou regenerar a demo: `.venv\Scripts\python tools\seed_demo.py` (com `--fresh`, busca no YouTube de novo)

Dica: se precisar imprimir texto com emoji no terminal do Windows, use `PYTHONIOENCODING=utf-8`.

## 7. Como testar (o teste real que ainda FALTA)

Tudo foi testado com dados de demonstração e com um perfil deslogado. **O teste com um perfil real e treinado ainda não foi feito.** É o mais importante:

1. Coloque a chave do YouTube em `YOUTUBE_API_KEY` no `app/config.py`. **Atenção:** não commite a chave; veja a seção 3.
2. Abra com `darkbot.bat` (banco real, não o de demo).
3. **Perfis → Adicionar perfil → Importar do Chrome.** Escolha um perfil já treinado num nicho. Se o Chrome estiver aberto, use "Fechar o Chrome".
4. **Coletar agora.** Na primeira vez, marque "ver navegador" para acompanhar.
5. Confira:
   - O perfil **continuou logado** depois de importado? No histórico de coletas aparece "sem login" quando não está.
   - Quantos vídeos vieram, e se os números fazem sentido.
   - Se as telas Descobertas, Canais e Títulos se preenchem.

**Se a sessão não sobreviver à cópia:** o Chrome criptografa os cookies com DPAPI e com a "app-bound encryption" (Chrome 127+). A cópia leva junto o `Local State`, que tem a chave, e o app usa o `chrome.exe` real, então deveria funcionar, mas não foi confirmado. **Plano B:** "Abrir p/ login" nesse perfil do darkbot e logar na conta do nicho uma vez; a sessão fica salva. As recomendações vêm do histórico da **conta Google**, então logar na mesma conta traz a mesma home.

## 8. Problemas conhecidos, cuidados técnicos e o que não foi testado

- **Importação com o Chrome aberto falha**, porque o arquivo de cookies fica travado. Já tratado: o app verifica antes, avisa e oferece "Fechar o Chrome" (fecha normalmente e força se ele não fechar; o Chrome restaura as abas ao reabrir). Numa das primeiras tentativas do usuário, a importação falhou por isso e o aviso sumia rápido. Hoje os erros ficam na tela até serem fechados.
- **Um perfil só pode estar aberto num lugar por vez.** Feche a janela "Abrir p/ login" antes de coletar; o app avisa.
- **Home deslogada vem vazia** (comportamento atual do YouTube para quem não tem histórico). A coleta avisa quando o perfil não está logado.
- **O Chrome 136+ bloqueia automação na pasta padrão de perfis.** Por isso o app sempre copia o perfil para a pasta própria dele.
- **O Google bloqueia login em navegador automatizado.** Por isso "Abrir p/ login" abre o Chrome normal (subprocess), sem Playwright.
- **Headless é detectado pelo YouTube.** Por isso a janela real fica fora da tela.
- **Não testado:** coleta completa numa home real logada, importação de perfil com sucesso, enriquecimento com uma chave real e o "crescimento" com coletas reais em dias diferentes.
- `titles.py` usa lista de stopwords em PT, EN e ES. O corte de outlier é por percentil ou multiplicador mínimo.

## 9. Onde paramos e próximos passos (em ordem)

**Última coisa feita:** projeto enviado ao GitHub, correção do fluxo de importação (verificação do Chrome aberto) e criação deste documento.

**Pendente com o usuário:**
- Rodar o teste real da seção 7.
- Responder se quer o `app/secrets.py` ignorado pelo git para as chaves.

**Roadmap combinado:**

1. **Teste real + correções** do que aparecer.
2. **Análise com IA (Claude)**, com economia de tokens como requisito central:
   - **Números filtram, IA só interpreta.** A IA só vê os outliers, nunca centenas de vídeos.
   - Enviar para a IA o **resumo pronto do `titles.py`**, não os títulos crus.
   - **Haiku 4.5** (`claude-haiku-4-5-20251001`) para tarefas em massa (classificar título, extrair gancho); **Sonnet 5.5** (`claude-sonnet-5-5`) só para síntese (relatório do nicho, "o que modelar essa semana").
   - **Analisar uma vez e guardar no banco.** Nunca repetir análise do mesmo vídeo.
   - **Prompt caching** das instruções fixas e **Batch API** (metade do preço) nas análises em lote.
   - Recursos pensados: botão "Analisar" por vídeo (por que furou, estrutura do título, gancho, ideias de vídeo para modelar), relatório semanal por nicho, e sugestões de títulos no padrão dos outliers.
   - A chave vai em `ANTHROPIC_API_KEY`. Antes de implementar, consultar a referência atual da API da Anthropic (modelos, preços, caching, batch).
3. **Sugestões dos vídeos:** abrir os principais outliers e raspar a barra lateral ("a seguir"). Pega canais que a home não mostra.
4. **Coleta agendada:** coletar sozinho a cada X horas, para alimentar o "crescimento".
5. **Transcrições** com yt-dlp (gancho dos primeiros 30s, estrutura de roteiro), já prevista na sidebar como "EM BREVE".
6. **Seus canais:** cadastrar os canais que já estão rodando e comparar com a concorrência. Mais para frente, a YouTube Analytics API (retenção e CTR reais).
7. **Supabase:** dados compartilhados entre as pessoas, login por e-mail, chaves no banco protegidas por RLS. Trocar a implementação de `app/db.py`.
8. **Agentes e skills:** agentes consultando o banco por ferramentas ("me dá os 20 outliers do nicho X"), em vez de receber tudo no prompt.
9. **POR ÚLTIMO, o .exe com auto-update:** PyInstaller gerando o `darkbot.exe` (`paths.py` já está pronto para o `_MEIPASS`); GitHub Actions compilando e publicando um Release a cada tag `vX.Y.Z`; o app checa o último Release ao abrir, baixa o exe novo, renomeia o atual para `.old` (o Windows não deixa sobrescrever um exe em execução), coloca o novo no lugar e reinicia. Ver a questão do token na seção 3.

## 10. Como trabalhar com este usuário

- Fala **português (BR)**, de forma informal e direta.
- Prefere **ver funcionando**: dados de demonstração e screenshots ajudam muito.
- Visual caprichado é requisito, não detalhe (seção 4).
- Pede para seguir implementando enquanto testa depois; manda mensagens no meio do trabalho com ajustes.
- Explique termos técnicos de forma simples e dê recomendações claras em vez de listas enormes de opções.
- Não commitar chaves. Não gastar tokens à toa, nem no produto nem no desenvolvimento.
