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
| **Sem shorts** | Pedido explícito do usuário: "não pode trazer shorts". O scraper ignora a prateleira de shorts, e `analytics.videos()` filtra `is_short = 0` (todas as telas leem daí). Vídeo com até 180s pela API também conta como short. |

### Pontos em aberto já discutidos (sem decisão final)

- **Chaves no GitHub (resolvido em 30/09/2026):** as chaves ficam em `app/secrets.py`, ignorado pelo git e também hardcoded. O `config.py` importa de lá; se o arquivo não existir, as chaves ficam vazias. Numa máquina nova, crie o `app/secrets.py` com `YOUTUBE_API_KEY` e `ANTHROPIC_API_KEY`.
- **Token do auto-update:** qualquer token embutido no exe pode ser extraído. Duas opções foram recomendadas: (a) código num repo privado e os executáveis num repo **público** só de releases, sem token; ou (b) token *fine-grained* **somente leitura** de um único repo. As chaves do YouTube e do Claude também não deveriam ficar dentro do exe distribuído: com o Supabase, elas passam a ficar no banco, protegidas por RLS e liberadas só depois do login.

## 4. Gosto visual do usuário (importante)

- Quer um app **bonito**: **campos pequenos, soft, clean, arredondado**. "Não me venha com grosserias nem coisas quadradas."
- Primeira referência: um app chamado "Invisible Studio", com sidebar com seções em caixa-alta miúda, chips/pílulas para seleção, botão principal com brilho e cards arredondados.
- Paleta final: **estilo rocketseat.com.br**. Fundo quase preto (`#09090A` / `#121214`), **roxo `#8257E5` / `#996DFF`** como destaque (com degradê e brilho suave) e **verde neon `#04D361`** para sinais positivos.
- Todas as cores ficam como tokens no `:root` de `app/ui/style.css`. Para mudar a paleta, mexa só ali.
- **Linguagem simples em tudo** (pedido do usuário: "para pessoas com QI menor entenderem"). Nada de termo técnico na tela. Vocabulário fixo: multiplicador → **"Viralizou"** (antes "Bombou"; o usuário pediu "viralizou e assim sucessivamente") (10× = 10 vezes mais views que inscritos); oportunidade → **"Nota"** / "nota para copiar"; outlier → "os que mais bombaram"; mediano → "normalmente"; saturação → **"Concorrência"**; relevância 3/2/1 → **"Mesmo formato" / "Mesmo assunto" / "Parecido"**; potencial → **"Só os bons" / "Mostrar todos"**; selo IA → "Feito com IA"; idade → "Postado há"; crescendo → "Ganhou por dia"; visto → "Apareceu". Todo título, coluna, indicador e marcação pequena tem `title` explicando em uma frase (ex.: "Idioma do vídeo: Espanhol", "Canal criado há 2 meses"). Explicações longas ficam em `TIP` no app.js; os nomes dos idiomas em `LANG_NAME`; os tipos de canal em `FORMAT_TIP`.
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
3. Lê o `ytInitialData`, rola N vezes e lê cada resposta `/youtubei/v1/browse`. Extrai `videoRenderer` e `lockupViewModel` (só vídeo, ignora playlists e mixes). Ignora anúncios e shorts. Para de rolar depois de 3 scrolls sem vídeo novo.
4. Salva os vídeos e as aparições.
5. Se houver chave da API, busca os números: vídeos só se a última atualização tiver mais de 6h, canais só se tiver mais de 24h (economia de cota).

### Telas

- **Descobertas:** vídeos ranqueados por **multiplicador** (views ÷ inscritos), com views/dia, "crescendo" (views/dia entre as duas últimas coletas), inscritos, idade e "visto N×". Filtros: data de publicação, inscritos, idade do canal, multiplicador mínimo e busca. Marcações: "Canal novo" (≤ 6 meses) e "Recente" (≤ 7 dias). Quatro indicadores no topo. Clicar abre o vídeo no navegador.
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

1. Coloque a chave do YouTube em `YOUTUBE_API_KEY` no `app/secrets.py` (fora do git), ou salve pela tela Configurações.
2. Abra com `darkbot.bat` (banco real, não o de demo).
3. **Perfis → Adicionar perfil → Importar do Chrome.** Escolha um perfil já treinado num nicho. Se o Chrome estiver aberto, use "Fechar o Chrome".
4. **Coletar agora.** Na primeira vez, marque "ver navegador" para acompanhar.
5. Confira:
   - O perfil **continuou logado** depois de importado? No histórico de coletas aparece "sem login" quando não está.
   - Quantos vídeos vieram, e se os números fazem sentido.
   - Se as telas Descobertas, Canais e Títulos se preenchem.

**Se a sessão não sobreviver à cópia:** o Chrome criptografa os cookies com DPAPI e com a "app-bound encryption" (Chrome 127+). A cópia leva junto o `Local State`, que tem a chave, e o app usa o `chrome.exe` real, então deveria funcionar, mas não foi confirmado. **Plano B:** "Abrir p/ login" nesse perfil do darkbot e logar na conta do nicho uma vez; a sessão fica salva. As recomendações vêm do histórico da **conta Google**, então logar na mesma conta traz a mesma home.

## 8. Problemas conhecidos, cuidados técnicos e o que não foi testado

- **Importar com o Chrome aberto:** o Chrome só trava os cookies do perfil que está **aberto**; os outros perfis podem ser copiados com ele rodando (testado em 30/09/2026). O app verifica perfil por perfil (`chrome_profile_open`, que tenta abrir o arquivo `Cookies`), marca "Aberto agora" na lista e só pede para fechar as janelas daquele perfil. O antigo botão "Fechar o Chrome" foi removido a pedido do usuário.
- **Um perfil só pode estar aberto num lugar por vez.** Feche a janela "Abrir p/ login" antes de coletar; o app avisa.
- **Home deslogada vem vazia** (comportamento atual do YouTube para quem não tem histórico). A coleta avisa quando o perfil não está logado.
- **O Chrome 136+ bloqueia automação na pasta padrão de perfis.** Por isso o app sempre copia o perfil para a pasta própria dele.
- **O Google bloqueia login em navegador automatizado.** Por isso "Abrir p/ login" abre o Chrome normal (subprocess), sem Playwright.
- **Headless é detectado pelo YouTube.** Por isso a janela real fica fora da tela.
- **Não testado:** coleta completa numa home real logada, importação de perfil com sucesso, enriquecimento com uma chave real e o "crescimento" com coletas reais em dias diferentes.
- `titles.py` usa lista de stopwords em PT, EN e ES. O corte de outlier é por percentil ou multiplicador mínimo.

## 9. Onde paramos e próximos passos (em ordem)

**Última coisa feita:** ambiente montado na segunda máquina (venv com Python 3.13, demo gerada, app conferido por screenshot), chaves movidas para `app/secrets.py` (fora do git), **shorts removidos de tudo** importação sem precisar fechar o Chrome (só o perfil escolhido não pode estar aberto) e correção do `darkbot.bat`: com `pythonw` o stdout é None, o log do uvicorn quebrava e o app fechava em silêncio. Agora, sem console, a saída vai para `%LOCALAPPDATA%\darkbot\darkbot.log`.

**IA (Claude), primeira parte feita em 30/09/2026:**
- `app/ai.py`: cliente, tabela `ai_results` (uma análise por tipo + alvo, **nunca reprocessa**, só com `refresh=True`), custo em US$ de cada chamada e total mostrado em Configurações. A chave fica em `ANTHROPIC_API_KEY` no `app/secrets.py`. O usuário tem US$ 5 de crédito: economia máxima, mas "sem burrice".
- Modelos (em `config.py`): **Haiku 4.5** (`claude-haiku-4-5`) para tarefas objetivas e **Sonnet 5.5** (`claude-sonnet-5-5`) para análise e síntese, decisão do usuário. Nada de Opus. Respostas estruturadas via `client.messages.parse` + Pydantic.
- **Detecção de nicho:** (1) no modal de importação, pelo histórico local do Chrome (`youtube_history_titles`), se tiver 15 ou mais títulos; (2) na primeira coleta de um perfil sem nicho, pelos títulos da home (a fonte mais confiável: o histórico local dos perfis treinados costuma vir quase vazio, porque o histórico é da conta Google). Custo medido: cerca de US$ 0,002 por detecção.
- Próximos recursos de IA: botão "Analisar" por vídeo (Sonnet, esforço baixo), sugestões de títulos e relatório do nicho. Usar `_run()` com um `kind` versionado (ex.: `video:v1`).

**Selo "gerado por IA" (30/09/2026):** a maioria dos canais dark declara o selo de conteúdo alterado ou sintético. A API oficial **não** devolve isso para vídeos de terceiros (`status.containsSyntheticMedia` não vem), então `app/ai_label.py` lê a página do vídeo com httpx (sem navegador, sem cota, 4 em paralelo, cerca de 40s para 190 vídeos) e procura o link `answer/15447836` (IA). O link `answer/15569972` é dublagem automática e é ignorado. O resultado fica em `videos.ai_label` (1, 0 ou NULL = não verificado), cada vídeo é verificado uma vez só, na etapa final da coleta. Canal = "IA" se algum vídeo dele tem o selo. Descobertas tem o filtro "Selo IA: Canais com selo", e há a marcação "IA" em vídeos e canais. Na demo: 11 canais com selo, todos dark. O selo é um sinal forte, mas não o único: dark sem selo passa batido. Ainda em aberto: classificar o formato do canal com o Haiku (narração, playlist ou compilação, com rosto) e decidir se playlists de música contam como dark para o usuário.

**Pesquisa de mercado (30/09/2026), página "Pesquisa IA":** o usuário quer uma análise "extremamente aprofundada e profissional", para o editor usar como verdade: uma pessoa fazendo pesquisa de mercado atrás do próximo vídeo para modelar. Recência é essencial ("quanto mais recente, mais chance do modelado dar certo"). Tudo fica guardado para o futuro gerador de título e descrição.
- `app/youtube_web.py`: páginas públicas sem navegador (httpx + `ytInitialData`). `related()` traz os sugeridos de um vídeo; `search()` usa o parâmetro `sp` montado na mão (ordem: relevância, data ou views; período: semana, mês ou ano; só vídeos). É a visão deslogada, o que é bom para pesquisa.
- `app/research.py`: (1) a partir de um vídeo: sugeridos + sugeridos dos 8 primeiros (2º nível) + o Haiku gera 4 buscas a partir do título; (2) a partir de palavras-chave: até 6. Cada busca roda 3 vezes (semana por data, mês por views, ano por views). Depois: números pela API, selo de IA, classificação dos canais pelo Haiku (dark, formato, tema; uma vez por canal, lotes de 40 em paralelo), comentários (API `commentThreads`, 100 mais relevantes, 6 vídeos com mais oportunidade, uma vez por vídeo) e o relatório.
- **Oportunidade** = multiplicador × peso de recência (≤30d = 1; ≤90d = 0,7; ≤1 ano = 0,4; mais velho = 0,15), em `analytics.opportunity`.
- **Relatório** (`ai.research_report`, Sonnet 5.5, esforço médio, `report:v1`): diagnóstico, oportunidade e saturação, o que funciona, fórmulas de título, pedidos do público (com trecho do comentário), 5 vídeos para modelar agora, 5 ideias prontas (título, 2 alternativos, gancho, estrutura, descrição, tags, referências, por que agora), palavras-chave e o que evitar. O payload (`research.build_payload`) traz os 30 melhores dark em tabela, o resumo do `titles.analyze` e 15 comentários por vídeo. O relatório fica em cache; "Refazer" pede confirmação.
- Tabelas: `research`, `research_videos` (via: semente, sugerido ou busca:*), `comments`; colunas `videos.comments_fetched_at` e `channels.dark/format/theme`.
- Interface: lista de pesquisas + detalhe (relatório, vídeos com filtros Só dark / Selo IA / idade, comentários lidos). Um botão de lupa em cada vídeo (Descobertas, Pesquisa, Modele agora) inicia uma pesquisa a partir dele: é a navegação entre vídeos. Palavras-chave do relatório são clicáveis e viram nova pesquisa. Campos das ideias são copiáveis ao clicar.
- Descobertas: filtro "Tipo de canal: Todos / Só dark / Selo IA" e marcação do formato do canal. Perfis: lápis no card para corrigir nicho e tipo.

**Cancelar e excluir (30/09/2026):**
- Coleta e pesquisa podem ser **canceladas** (botão na tarefa, `POST /api/jobs/{id}/cancel`): a tarefa para no próximo ponto seguro e guarda o que já fez. A pesquisa cancelada ainda busca os números pela API (é rápido e sem eles nada serve), mas pula selo de IA, classificação, comentários e relatório. Fica com status `cancelled` e dá para gerar o relatório depois.
- **Excluir coleta** (lixeira no histórico, `DELETE /api/runs/{id}`) e **excluir pesquisa** apagam tudo o que só existia nelas via `db.purge_orphans` (vídeos, números, comentários, canais, cache de IA por vídeo). O que aparece em outra coleta ou pesquisa fica. Se o perfil ficar sem coletas, o nicho preenchido pela IA (`profiles.niche_auto=1`) some e é detectado de novo; o nicho editado à mão fica.
- O cache do relatório é apagado junto com a pesquisa, porque o SQLite reaproveita o id. O gasto com IA fica num registro próprio (`ai_usage`), que não diminui quando algo é apagado.
- Ao abrir, `db.recover_interrupted()` marca coleta ou pesquisa que ficou "rodando" (app fechado no meio) como interrompida.
- A interface é servida com `?v=<mtime>` em app.js e style.css, porque o WebView guardava a versão velha em cache.
- `youtube_web` registra no log quando uma página volta sem `ytInitialData` (consentimento ou bloqueio).

**Prévia, descarte, idiomas e histórico (30/09/2026):**
- **Critério de dark (do usuário):** dark = canal ANÔNIMO produzido em escala (narração IA ou locutor, imagens IA ou banco, animação). **Canal de música NUNCA é dark** (playlists, lofi, sons para dormir, louvores etc.; decisão explícita do usuário: `musica` está em `NOT_DARK_FORMATS`). NÃO é dark: youtuber com personalidade (comentário, análise, react, gameplay), cortes de pessoa real, criador que aparece, artista, TV ou marca. O classificador v1 errava muito (marcava "compilação" como dark); o **v2** (`channels:v2`, `CHANNELS_VERSION=2`) usa a descrição do canal (buscada na API, 1 unidade a cada 50), o selo de IA, os inscritos, um critério estrito, a confiança e as **correções do editor como exemplos** (`_corrections`). Formatos novos: `comentario` (Youtuber) e `cortes`. `analytics.is_dark`: correção manual > formato com pessoa real = não > IA com confiança alta ou média > selo de IA (enquanto não classificado). Reclassificar: botão em Configurações (cerca de US$ 0,0006 por canal).
- **Correções:** "Não é dark" / "É dark" / "Desfazer" (`channels.dark_manual`) e "Ocultar vídeo" (`videos.hidden`, com "Mostrar de novo" em Configurações), nas linhas (ao passar o mouse) e na prévia.
- **Prévia do vídeo** (clicar em qualquer vídeo): painel lateral com player embutido (youtube-nocookie, autoplay mudo), tradução, métricas, canal (descrição, estado dark e correção), análise com IA (`ai.analyze_video`, Sonnet esforço baixo, **com a thumbnail**, cerca de US$ 0,02, uma vez por vídeo, `analysis:v1`), comentários (buscados na hora se faltarem, 1 unidade de cota), descrição e tags. Ações: abrir no YouTube, copiar link, pesquisar a partir deste, ocultar.
- **Descrição e tags dos vídeos** agora são guardadas no enriquecimento (servem para o gerador de descrição).
- **Idiomas:** 13 idiomas (`ai.LANGUAGES`, com hl/gl). Seletor na barra de nicho e no modal de pesquisa (fica no localStorage). O Haiku adapta as buscas para cada idioma (`localize_queries`, como um nativo pesquisaria). Idiomas estrangeiros: 3 buscas × (semana, top do mês). Títulos estrangeiros são traduzidos automaticamente no fim da pesquisa (`translate_titles`, `videos.title_pt`) e sob demanda ("Traduzir títulos"). Marcação de idioma nas linhas. **Idioma do canal** (Configurações, `settings.channel_lang`): títulos, ganchos, descrições e tags do relatório e da análise saem nele; o estrangeiro vira referência adaptada.
- **Histórico do YouTube:** "Coletar histórico" no card do perfil (scraper em `/feed/history`, `runs.source='history'`, surface `history`). Descobertas filtra por Origem (home ou histórico) e marca "Assistido". Pesquisa modo "Histórico do perfil": usa os 40 vídeos mais recentes do histórico, abre os sugeridos de 5 e o Haiku acha o centro do nicho (`history_keywords`).
- **Descobertas:** barra "Pesquisar um nicho, tema, título ou palavras-chave" com idiomas (vira pesquisa de mercado). Botão "Coletas" (lista com data e hora, ver só uma, excluir em lote). Filtro "Coleta". **Cabeçalho da tabela fixo** (`overflow: clip` + `position: sticky`).
- **Perfil:** "Treinar nicho" abre o Chrome do perfil já na busca do YouTube (`/api/profiles/{id}/train`).
- Testado numa cópia do banco real: o v2 acertou todos os casos que o usuário apontou (Afonso Padilha, Cheff Ottro, Leo 1, Boldt, EnderBits, Jaxs, Yoshizin, Evento Nexus = não dark); a pesquisa PT+EN+ES trouxe 260 vídeos de 6 idiomas e traduziu 199 títulos.

**Velocidade (30/09/2026):** o usuário pediu paralelismo "em tudo". Usamos threads, não processos: o trabalho é quase todo espera de rede, e threads compartilham as conexões e o banco (SQLite em WAL, cada thread com a própria conexão).
- Selo de IA: fila contínua com 16 em paralelo (`ai_label.WORKERS`), cerca de 20 vídeos/s, e no máximo 2 vídeos por canal (`jobs.LABEL_PER_CHANNEL`), pulando canal que já tem selo. **Não** ler a página em pedaços varrendo a string acumulada: foi testado e ficou 5x mais lento.
- Pesquisa: sugeridos e buscas em paralelo (`youtube_web.WORKERS = 6`, `research._parallel`, que mantém a ordem dos resultados e respeita o cancelar). API do YouTube: lotes de 50 em paralelo (`youtube_api.API_WORKERS = 4`). IA: lotes menores e 8 em paralelo (`ai.AI_WORKERS`). Classificação dos canais e tradução rodam juntas; os comentários (que dependem de saber quem é dark) vêm depois, em paralelo.
- Medido na mesma pesquisa (vídeo semente, cerca de 345 vídeos, com relatório): **270s → 91s** (cerca de 40s são o Sonnet escrevendo o relatório). A rolagem da home não paraleliza (espera o YouTube), mas perfis diferentes coletam ao mesmo tempo.

**Pesquisa em profundidade com juiz de relevância (30/09/2026):** a versão anterior a partir de vídeo trazia lixo (novelinha, militares, reciclagem). Causas: abria os sugeridos dos sugeridos sem filtrar, e como visitante `pt-BR` mesmo para vídeo em inglês, então o YouTube completava com o popular no Brasil. Novo motor (`research._discover`):
1. Vídeo-semente: dados pela API; idioma do vídeo = idioma principal da pesquisa (`lang_code`). O Haiku monta o perfil (`ai.seed_profile`, `seed:v1`): tema, formato, ângulo, `topic` (o que conta como concorrente direto), 6 buscas e **8 variações do título trocando os detalhes** (ex.: "Japanese Engineers Tore Down an American Tractor"). Fica salvo em `research.topic`.
2. Buscas: variações (relevância) + buscas × (semana, top do mês, top do ano) no idioma do vídeo; nos outros idiomas escolhidos, variações e buscas adaptadas (`localize_queries`). Sugeridos abertos com hl/gl do idioma do vídeo.
3. **Juiz de relevância** (`ai.judge_relevance`, Haiku, lotes de 60 em paralelo): 3 = concorrente direto (tema + formato), 2 = mesmo tema, 1 = mesma área, 0 = descartado. Fica em `research_videos.relevance`.
4. **Profundidade:** até 3 camadas extras de "sugeridos dos sugeridos", só a partir dos relevantes (nota 3 primeiro), 10 vídeos por camada, julgando cada camada.
5. **Concorrentes:** os 8 canais com mais vídeos relevantes têm os 20 uploads mais recentes lidos (`youtube_api.fetch_uploads`, 1 unidade cada) e julgados.
- Só entra o que tem nota ≥ 1. A lista mostra "Do tema" (≥ 2) por padrão, com filtro Diretos / Do tema / Com tangentes. O relatório usa nota ≥ 2. Histórico e palavras-chave passam pelo mesmo motor (com `topic` próprio).
- Teste com o vídeo do trator (BwSNvnhu0J0, PT/EN/ES/FR): antes 519 vídeos com ruído; agora 184 relevantes, 22 diretos, zero fora do tema, incluindo "Canadian Engineers Tore Down a Chinese Tractor" com 62× em 3 dias. Levou 114s e custou US$ 0,24 com relatório.
- **Enviar para Descobertas** (`POST /api/research/{id}/to-discoveries`): cria uma coleta (`runs.source='research'`, `runs.research_id`, sem perfil) com os vídeos de nota ≥ 2. Aparece em Coletas como "Pesquisa: <título>", tem Origem "Pesquisas enviadas" e a marcação "Pesquisa". Excluir a coleta não apaga a pesquisa.

**Custo por pesquisa (30/09/2026):** o usuário achou US$ 0,40 a 0,50 por pesquisa caro ("machuca se eu fizer umas 10 no dia"). Medido: classificar ~450 canais (US$ 0,19) + traduzir ~380 títulos automaticamente (US$ 0,15) + relatório (US$ 0,08). Cortes: (1) tradução **só sob demanda** (botão e prévia), em formato de lista numerada (`translate:v2`); (2) a pesquisa classifica só os canais dos vídeos com nota ≥ 2 (`classify_new_channels(video_ids=...)`); (3) respostas compactas no Haiku: número em vez de ID e campos curtos (`channels:v3` com n/d/c/f, `rel:v2` com n/r), porque o caro é a saída (US$ 5/M); (4) juiz em lotes de 100. Mesma pesquisa do trator: **US$ 0,43 → US$ 0,15** com relatório (~US$ 0,07 sem), qualidade igual (30 diretos). Regra para o futuro: na IA em massa, sempre resposta compacta e nada automático que o usuário não pediu.

**Potencial, período e saturação (30/09/2026):**
- Views/dia de vídeo com menos de 1 dia não é mais extrapolado (`views / max(idade, 1)`). Antes, 35 views em 5h viravam "140/dia".
- **Potencial** (`analytics.has_potential`): multiplicador ≥ 1× ou ≥ 1.000 views/dia (`config.POTENTIAL_*`). A pesquisa mostra "Com potencial" por padrão; o relatório e o "Enviar para Descobertas" usam só nota ≥ 2 com potencial. O usuário quer "potenciais, não ruins", ordenados do melhor para o pior (oportunidade decrescente).
- **Período configurável** (`research.max_age_days`; semana, mês, 3 meses, 1 ano ou qualquer data; fica no localStorage, com seletor no modal e na barra de nicho): as buscas usam o filtro de data do YouTube (`search_plan`), e depois dos números a pesquisa corta o que é mais velho (`_apply_period`, antes do selo de IA, e limpa os órfãos).
- **Mapa de saturação** (`analytics.saturation`, só para pesquisa a partir de vídeo): concorrentes diretos (nota 3) por idioma, com vídeos, canais, canais nos últimos 30 dias, multiplicador mediano e o melhor vídeo, mais a "Brecha" (idiomas escolhidos com menos de 2 canais nos últimos 30 dias). Teste do trator (1 mês, 4 idiomas): EN 12 canais (alta), DE 6, PT 1 canal com 174×, ES/FR nenhum. 32s, US$ 0,04 sem relatório.
- **Método Malandro** (confirmado pelo usuário): achar em que línguas **ninguém fez este vídeo ainda** e levar para lá. Ver o item próprio abaixo.

**Método Malandro (30/09/2026):** `app/malandro.py`, tabela `malandro` (um resultado JSON por vídeo, guardado; "refazer" pede confirmação), `POST/GET /api/malandro/{video_id}`. O usuário mandou um mockup de referência: radar escuro com feixe vermelho girando, pontos por língua com bandeira, número de "línguas livres" no centro, lista "Ninguém fez em" e botão "Ver os vídeos de cada língua".
- Fluxo: dados do vídeo pela API → perfil do vídeo (`seed_profile`, em cache) → `ai.malandro_titles` (como um nativo intitularia o MESMO vídeo em cada uma das 13 línguas + busca curta) → 2 buscas por país (título nativo por relevância; busca curta top do ano) → `ai.judge_same_video` (Haiku compacto: n, r = 3 mesmo vídeo / 2 mesmo tema, l = idioma do título) → números pela API (os vídeos ficam só no JSON, não entram na tabela `videos`). Idioma: API > IA, conferido pelo alfabeto do título (`fix_lang`). Língua: livre (0 canais com o mesmo vídeo), pouco explorada (1 a 2) ou saturada (3+). Nas livres, o título nativo sugerido sai pronto (copiável).
- Interface: `renderMalandro`/`malandroRadar` (SVG; bandeiras via flagcdn.com; o estilo global `svg { stroke }` é anulado dentro do `.radar`). Aparece na prévia de qualquer vídeo e na pesquisa a partir de vídeo. Grades com `minmax(0, 1fr)` para os títulos longos não estourarem.
- Teste com o trator: 11 línguas livres, EN saturada (5 canais), DE pouco explorada. ~16s, US$ 0,0085.

**Perfil em uso, "viralizou" e ideias de variações (30/09/2026):**
- **Cada perfil tem as suas coisas** (pedido do usuário). Cartão "Perfil em uso" no topo da barra lateral (`#active-profile`); a escolha fica no localStorage (`profile`). Ao abrir sem perfil válido, aparece "Qual perfil você vai usar?" (`#pick-modal`, obrigatório); com só um perfil, ele é escolhido sozinho. Descobertas, Canais e Títulos seguem o perfil (os selects `#v/c/t-profile` ficaram escondidos e recebem o perfil em uso). Pesquisas: `research.profile_id` é gravado em toda pesquisa nova; a lista filtra pelo perfil (`/api/research?profile_id=`). Pesquisas antigas sem perfil aparecem com "sem perfil · trazer para este perfil" (`POST /api/research/{id}/profile`). "Enviar para Descobertas" cria a coleta no perfil da pesquisa. Coletas (`/api/runs?profile_id=`) também filtradas.
- "Bombou" virou **"Viralizou"** em tudo (viralizam, viralizaram…).
- **Ideias de variações** (`ai.title_variations`, Sonnet esforço baixo, `variations:v1`, uma vez por vídeo): molde do título com [lacunas] + 10 títulos trocando detalhes, cada um com **chance de viralizar (0 a 100)**, o que mudou e o motivo, com base em `research.variations_payload` (vídeos parecidos com números das pesquisas que contêm o vídeo, Método Malandro e comentários). Sem dados, a chance fica no máximo em 60%. Aparece na prévia de qualquer vídeo e no topo da pesquisa a partir de vídeo. Teste: "Engenheiros Japoneses Desmontaram um Carro Chinês" → 62% "…um Trator Chinês", 58% "…um BYD", 28% "Engenheiros Brasileiros…". 13s, US$ 0,02.

**Claude ou ChatGPT + chaves na aba Configurações (30/09/2026):**
- **Escolha da IA** em Configurações → "Inteligência artificial": Claude (Anthropic) ou ChatGPT (OpenAI) (`settings.ai_provider`). O app inteiro usa a escolhida. `ai._run` continua recebendo o nível (`config.AI_MODEL_FAST`/`SMART`) e `ai.resolve_model` troca pelo modelo do provedor. O cache (`ai_results`) é o mesmo para os dois: trocar de IA não refaz o que já foi feito.
- **Modelos:** a conta da OpenAI do usuário tem modelos até `gpt-6.1-sol`. O `gpt-5-mini` **exige organização verificada** (erro 404 "must be verified"), por isso o padrão virou **`gpt-5.4-mini`** (no lugar do Haiku: num teste com 137 títulos foi o que mais concordou com o Haiku no juiz de relevância; US$ 0,75/4,50) e **`gpt-6.1-sol`** (no lugar do Sonnet: mesmo preço, US$ 2/10). `gpt-6-luna` é 10× mais barato, mas deixou passar o dobro de lixo. Os modelos novos **não aceitam** raciocínio "minimal" (alguns nem "none"): `_openai_parse` tenta o modo pedido e cai para o próximo, lembrando qual serviu (`_effort_ok`). Rápido também usa "low".
- **Preços oficiais** (30/09/2026, developers.openai.com/api/docs/pricing + tabela da Anthropic) em `config.AI_PRICES` como (entrada, cache, saída); `price_of` aceita nome com data. **Escolha de modelos nos dois provedores** (`settings.{anthropic,openai}_model_{fast,smart}`), com lista da conta e preço (`/api/ai/models?provider=`), **custo estimado por tarefa** (`/api/ai/estimate`, tokens medidos em `config.TASK_TOKENS`) e "Testar e salvar modelos" (chamada mínima antes de salvar, pega o caso da verificação). Estimativa com os padrões: pesquisa ~US$ 0,07 (Claude) / ~0,06 (OpenAI), relatório ~0,08, 10 pesquisas com relatório por dia ≈ US$ 47 (Claude) / 43 (OpenAI) por mês.
- Teste real com a chave do usuário: pesquisa "mistérios do oceano profundo" (PT+EN, 1 mês) toda no ChatGPT: 190 vídeos, 48s, US$ 0,047.
- **Chamada OpenAI:** SDK `openai` (3.x), `responses.parse(..., text_format=Pydantic, reasoning={"effort": ...})`. Tarefa rápida usa esforço "minimal"; análise usa o esforço pedido (ou "low"). Imagem vira `input_image` (detail low). Os 21 formatos Pydantic passam no esquema estrito da OpenAI (`to_strict_json_schema`). Testado com a chave real do usuário.
- **Chaves fora do código:** `config.py` não importa mais `app/secrets.py`. Na primeira abertura, `db.init` copia as chaves antigas de `secrets.py` para o banco (`settings`), e daí em diante elas são editadas e testadas na aba Configurações (YouTube, Anthropic, OpenAI). Para o .exe isso é o certo: nenhuma chave embutida. Depois que o usuário abrir o app (migração feita), o `app/secrets.py` pode ser apagado.

**.exe para distribuir (30/09/2026):** `tools/build_exe.py` gera `dist/darkbot.exe` (~62 MB, um arquivo só). O usuário pediu "não pode demorar pra abrir, um exe só, leve, completamente funcional".
- Como funciona: PyInstaller em **onedir** (abre rápido) → a pasta vira um zip **embutido num lançador em C#** (`tools/launcher.cs`, compilado com o `csc.exe` do .NET Framework do Windows). Na primeira vez o lançador descompacta em `%LOCALAPPDATA%\darkbotpp\<versão>-<hash>` com uma janelinha "Preparando o darkbot…"; depois só abre o app. Versão nova = pasta nova, e a antiga é apagada. (Um `--onefile` comum descompactaria ~150 MB a cada abertura por causa do Node.js do Playwright, ~103 MB.)
- Medido no PC do usuário, com pasta de dados limpa: 1ª abertura 2,5s até responder; depois 1,3s; janela WebView2 aberta em 1,7s.
- Abertura mais rápida também no modo dev: `anthropic`/`openai` são carregados sob demanda (`ai._Lazy`) e o Playwright só dentro de `collect_home` (import do app: 2,4s → 0,5s). Por isso o build usa `--collect-submodules anthropic/openai`.
- **Segurança:** `app/secrets.py` é importado dinamicamente (o PyInstaller não enxerga) e também excluído no build; o script **procura as chaves dentro do pacote e cancela o build** se achar. Também confere se `node.exe` e `app/ui` entraram.
- `main.py --serve` sobe só o servidor (para testes do .exe). Se a janela WebView2 falhar, o app abre no navegador em vez de quebrar.
- Testado dentro do .exe: salvar e validar as 3 chaves, listar modelos, pesquisa completa (ChatGPT), prévia, variações (Claude), Método Malandro, coleta com Playwright (abre o Chrome) e a janela.
- Quem recebe precisa de: Windows 10/11 64 bits, Google Chrome e as próprias chaves (YouTube + Anthropic ou OpenAI), colocadas em Configurações.
- Correção geral de CSS: `[hidden] { display: none !important; }` (componentes com `display` próprio ignoravam o atributo).

**Perfil deslogado (01/10/2026):** o usuário quer poder usar perfis SEM conta do YouTube. Testado: perfil novo e deslogado = home vazia (0 vídeos); depois de assistir 6 vídeos do nicho (35s cada) = 93 vídeos na home, quase todos no nicho (algum ruído regional). O YouTube recomenda pelo histórico em cookie. Cuidados: treinar DENTRO do perfil do darkbot ("Criar e logar" sem logar + "Treinar o perfil"), porque a cópia de perfil do Chrome pode perder os cookies; "Coletar o que assistiu" exige login; limpar cookies zera o perfil. Pesquisa IA, Malandro, variações, busca e sugeridos não dependem de login (sempre como visitante). A mensagem de home vazia agora sugere logar OU treinar.

**Pendente com o usuário:**
- Rodar o teste real da seção 7.

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
