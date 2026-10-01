"""Análises com IA (Claude ou ChatGPT, escolhido em Configurações), com economia de tokens como regra.

- Cada análise é guardada em `ai_results` por (tipo, alvo) e nunca é refeita, a não ser que peçam.
  O cache vale para os dois provedores: trocar de IA não refaz o que já foi feito.
- A IA só recebe o mínimo (títulos já filtrados, números prontos), nunca o banco cru.
- Dois níveis de modelo: "rápido" (tarefas objetivas e em massa) e "inteligente" (análise e síntese).
  Claude: Haiku / Sonnet. OpenAI: os modelos escolhidos em Configurações (padrão gpt-5-mini / gpt-5).
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

import importlib

from pydantic import BaseModel


class _Lazy:
    """Carrega o SDK só na primeira vez que é usado (anthropic + openai levam ~2s para importar: o app abre antes)."""

    def __init__(self, name: str):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)


anthropic = _Lazy("anthropic")
openai = _Lazy("openai")

from . import config, db

AI_WORKERS = 8  # chamadas em lote rodando juntas (classificação, tradução)
PROVIDERS = {"anthropic": "Claude (Anthropic)", "openai": "ChatGPT (OpenAI)"}

_clients: dict[str, object] = {}


class AIError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Configuração (tudo vem da aba Configurações; nada embutido no código)
# ---------------------------------------------------------------------------

def provider() -> str:
    p = db.get_setting("ai_provider") or "anthropic"
    return p if p in PROVIDERS else "anthropic"


def key_for(p: str) -> str:
    return db.get_setting(f"{p}_api_key") or ""


def api_key() -> str:
    return key_for(provider())


def enabled() -> bool:
    return bool(api_key())


DEFAULT_MODELS = {"anthropic": (config.AI_MODEL_FAST, config.AI_MODEL_SMART),
                  "openai": (config.OPENAI_MODEL_FAST, config.OPENAI_MODEL_SMART)}


def models_for(p: str) -> tuple[str, str]:
    """(rápido, inteligente) escolhidos para o provedor (Configurações), ou o padrão."""
    fast, smart = DEFAULT_MODELS[p]
    return (db.get_setting(f"{p}_model_fast") or fast, db.get_setting(f"{p}_model_smart") or smart)


def openai_models() -> tuple[str, str]:
    return models_for("openai")


def resolve_model(model: str) -> str:
    """Os chamadores pedem o nível (config.AI_MODEL_FAST/SMART); aqui vira o modelo escolhido no provedor em uso."""
    fast, smart = models_for(provider())
    return fast if model == config.AI_MODEL_FAST else smart


def list_models(p: str) -> list[dict]:
    """Modelos de texto da conta, com preço (quando conhecido). Para escolher em Configurações."""
    ids = check_key(p, key_for(p))
    if p == "openai":
        skip = ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding", "moderation", "dall",
                "whisper", "codex", "instruct", "live", "chat-latest", "sora", "babbage", "davinci", "-pro")
        ids = [m for m in ids if m.startswith(("gpt-", "o3", "o4")) and not any(x in m for x in skip)
               and not m.startswith(("gpt-3", "gpt-4-"))]
    else:
        ids = [m for m in ids if m.startswith("claude-")]
    out = []
    for m in ids:
        pr = price_of(m)
        out.append({"id": m, "input": pr[0] if pr else None, "output": pr[2] if pr else None})
    # Os de preço conhecido primeiro, do mais barato ao mais caro.
    return sorted(out, key=lambda x: (x["input"] is None, (x["input"] or 0) + (x["output"] or 0) / 4, x["id"]))


def estimate(fast: str, smart: str) -> list[dict]:
    """Custo estimado de cada tarefa com esse par de modelos (tokens medidos de verdade no darkbot)."""
    out = []
    for key, (label, tiers) in config.TASK_TOKENS.items():
        cost, known = 0.0, True
        for tier, (tin, tout) in tiers.items():
            pr = price_of(fast if tier == "fast" else smart)
            if not pr:
                known = False
                continue
            cost += (tin * pr[0] + tout * pr[2]) / 1_000_000
        out.append({"task": key, "label": label, "cost": round(cost, 4) if known else None})
    return out


def test_model(p: str, model: str) -> None:
    """Chamada mínima para confirmar que o modelo funciona na conta (ex.: modelo que exige verificação)."""
    if p == "openai":
        _call_openai(model, "Responda com 1 busca curta.", "tema: oceano", Queries, 200, None, 60, True)
    else:
        _call_anthropic(model, "Responda com 1 busca curta.", "tema: oceano", Queries, 200, None, 60)


def _client(p: str):
    key = key_for(p)
    if not key:
        raise AIError(f"Sem chave da {'OpenAI' if p == 'openai' else 'Anthropic'}. Coloque em Configurações.")
    c = _clients.get(p)
    if c is None or getattr(c, "api_key", None) != key:
        c = (openai.OpenAI if p == "openai" else anthropic.Anthropic)(api_key=key, max_retries=2, timeout=60)
        _clients[p] = c
    return c


def check_key(p: str, key: str) -> list[str]:
    """Valida a chave (lista os modelos, sem gastar nada). Devolve os modelos disponíveis."""
    try:
        if p == "openai":
            return sorted(m.id for m in openai.OpenAI(api_key=key, timeout=20).models.list())
        return sorted(m.id for m in anthropic.Anthropic(api_key=key, timeout=20).models.list())
    except (openai.AuthenticationError, anthropic.AuthenticationError):
        raise AIError("Essa chave não funcionou. Confira se copiou inteira.")
    except (openai.APIConnectionError, anthropic.APIConnectionError):
        raise AIError("Sem conexão para testar a chave.")
    except (openai.APIStatusError, anthropic.APIStatusError) as e:
        raise AIError(f"A chave não foi aceita ({e.status_code}).")


def price_of(model: str) -> tuple[float, float, float] | None:
    """(entrada, entrada em cache, saída) em US$ por milhão. Aceita o nome com data (ex.: ...-2026-03-17)."""
    if model in config.AI_PRICES:
        return config.AI_PRICES[model]
    base = max((k for k in config.AI_PRICES if model.startswith(k + "-")), key=len, default=None)
    return config.AI_PRICES[base] if base else None


def _cost(model: str, inp: int, cache_write: int, cache_read: int, out: int) -> float:
    pin, pcache, pout = price_of(model) or (0.0, 0.0, 0.0)
    return (inp * pin + cache_write * pin * 1.25 + cache_read * pcache + out * pout) / 1_000_000


def cached(kind: str, target: str) -> dict | None:
    r = db.row("SELECT result FROM ai_results WHERE kind=? AND target=?", (kind, target))
    return json.loads(r["result"]) if r else None


# ---------------------------------------------------------------------------
# Chamada (Anthropic ou OpenAI), sempre com resposta estruturada
# ---------------------------------------------------------------------------

def _call_anthropic(model, system, user, schema, max_tokens, effort, timeout):
    extra = {"output_config": {"effort": effort}} if effort else {}
    try:
        resp = _client("anthropic").with_options(timeout=timeout).messages.parse(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}], output_format=schema, **extra,
        )
    except anthropic.AuthenticationError:
        raise AIError("Chave da Anthropic inválida. Confira em Configurações.")
    except anthropic.PermissionDeniedError:
        raise AIError("A chave da Anthropic não tem permissão para esse modelo.")
    except anthropic.RateLimitError:
        raise AIError("Limite da API da Anthropic atingido. Tente de novo em instantes.")
    except anthropic.APIStatusError as e:
        if "credit" in (e.message or "").lower():
            raise AIError("Sem créditos na conta da Anthropic.")
        raise AIError(f"Erro na API da Anthropic ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise AIError("Sem conexão com a API da Anthropic.")
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise AIError("A IA não conseguiu responder essa análise.")
    u = resp.usage
    cost = _cost(model, u.input_tokens or 0, u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0,
                 u.output_tokens or 0)
    return resp.parsed_output, u.input_tokens, u.output_tokens, cost


def _openai_content(user: str | list):
    """Converte o conteúdo (texto ou blocos no formato da Anthropic) para o formato da OpenAI."""
    if isinstance(user, str):
        return user
    out = []
    for b in user:
        if b.get("type") == "image":
            out.append({"type": "input_image", "image_url": b["source"]["url"], "detail": "low"})
        elif b.get("type") == "text":
            out.append({"type": "input_text", "text": b["text"]})
    return out


_effort_ok: dict[str, str | None] = {}   # modelo -> modo de raciocínio que ele aceita (descoberto na prática)


def _openai_parse(model, system, user, schema, max_tokens, effort, timeout, fast):
    """Chama com o raciocínio pedido; se o modelo não aceitar esse modo, tenta o próximo e lembra qual serviu."""
    wanted = effort or "low"   # tarefas rápidas também em "low": no teste foi o que deu o melhor resultado
    chain = [_effort_ok[model]] if model in _effort_ok else [wanted, "medium", "minimal", None]
    last = None
    for eff in chain:
        try:
            kw = {"reasoning": {"effort": eff}} if eff else {}
            resp = _client("openai").with_options(timeout=timeout).responses.parse(
                model=model, instructions=system, input=[{"role": "user", "content": _openai_content(user)}],
                text_format=schema, max_output_tokens=max(max_tokens, 1500) + (1000 if fast else 4000), **kw,
            )
            _effort_ok[model] = eff
            return resp
        except openai.BadRequestError as e:
            if "reasoning" in str(e) and ("Unsupported" in str(e) or "not supported" in str(e)):
                last = e
                continue
            raise
    raise last


def _call_openai(model, system, user, schema, max_tokens, effort, timeout, fast):
    try:
        resp = _openai_parse(model, system, user, schema, max_tokens, effort, timeout, fast)
    except openai.AuthenticationError:
        raise AIError("Chave da OpenAI inválida. Confira em Configurações.")
    except openai.PermissionDeniedError:
        raise AIError("A chave da OpenAI não tem permissão para esse modelo.")
    except openai.RateLimitError as e:
        if "insufficient_quota" in str(e) or "quota" in str(e).lower():
            raise AIError("Sem créditos na conta da OpenAI.")
        raise AIError("Limite da API da OpenAI atingido. Tente de novo em instantes.")
    except openai.NotFoundError as e:
        if "verified" in str(e).lower():
            raise AIError(f"A OpenAI só libera o {model} para organizações verificadas "
                          "(platform.openai.com → Settings → Organization → Verify). Ou escolha outro modelo em Configurações.")
        raise AIError(f"O modelo {model} não está disponível na sua conta da OpenAI. Escolha outro em Configurações.")
    except openai.BadRequestError as e:
        raise AIError(f"A OpenAI recusou o pedido: {getattr(e, 'message', e)}")
    except openai.APIStatusError as e:
        raise AIError(f"Erro na API da OpenAI ({e.status_code}).")
    except openai.APIConnectionError:
        raise AIError("Sem conexão com a API da OpenAI.")
    if resp.output_parsed is None:
        raise AIError("A IA não conseguiu responder essa análise.")
    u = resp.usage
    cached_in = (getattr(u, "input_tokens_details", None) and u.input_tokens_details.cached_tokens) or 0
    cost = _cost(model, (u.input_tokens or 0) - cached_in, 0, cached_in, u.output_tokens or 0)
    return resp.output_parsed, u.input_tokens, u.output_tokens, cost


def _run(kind: str, target: str, model: str, system: str, user: str | list, schema: type[BaseModel],
         max_tokens: int = 400, refresh: bool = False, effort: str | None = None, timeout: float = 60) -> dict:
    """Devolve o resultado guardado; só chama a IA se ainda não existir (ou se refresh=True)."""
    if not refresh:
        hit = cached(kind, target)
        if hit is not None:
            return hit | {"cached": True}
    fast = model == config.AI_MODEL_FAST
    real = resolve_model(model)
    if provider() == "openai":
        parsed, tin, tout, cost = _call_openai(real, system, user, schema, max_tokens, effort, timeout, fast)
    else:
        parsed, tin, tout, cost = _call_anthropic(real, system, user, schema, max_tokens, effort, timeout)

    result = parsed.model_dump()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.tx() as con:
        con.execute(
            "INSERT INTO ai_usage(kind, model, input_tokens, output_tokens, cost_usd, created_at) VALUES(?,?,?,?,?,?)",
            (kind, real, tin, tout, cost, now),
        )
        con.execute(
            """INSERT INTO ai_results(kind, target, model, result, input_tokens, output_tokens, cost_usd, created_at)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(kind, target) DO UPDATE SET model=excluded.model,
               result=excluded.result, input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
               cost_usd=excluded.cost_usd, created_at=excluded.created_at""",
            (kind, target, real, json.dumps(result, ensure_ascii=False), tin, tout, cost, now),
        )
    return result | {"cached": False}


def usage() -> dict:
    r = db.row("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS cost FROM ai_usage")
    return {"analyses": r["n"], "cost_usd": round(r["cost"], 4)}


# ---------------------------------------------------------------------------
# Detecção de nicho
# ---------------------------------------------------------------------------

NICHE_KIND = "niche:v1"

_NICHE_SYSTEM = """Você ajuda um produtor de canais dark do YouTube (canais sem rosto, com narração e imagens) \
a organizar os perfis de navegador que ele treina para o algoritmo.

Você recebe títulos de vídeos que o YouTube entrega (ou entregou) para um perfil. Diga qual é o nicho desse perfil.

- niche: nome curto do nicho em português, 2 a 5 palavras, específico o bastante para diferenciar \
(ex.: "mistérios não resolvidos", "true crime brasileiro", "histórias de terror reais", "curiosidades históricas"). \
Se os títulos não forem de conteúdo dark, diga o nicho real mesmo assim (ex.: "maquiagem", "programação").
- kind: "nicho" se a maioria dos títulos gira em torno de um mesmo tema; "coringa" se mistura vários temas dark diferentes.
- confidence: "alta", "media" ou "baixa", conforme o quanto os títulos concordam entre si.
- reason: uma frase de no máximo 15 palavras sobre o que você viu nos títulos."""


class NicheGuess(BaseModel):
    niche: str
    kind: Literal["nicho", "coringa"]
    confidence: Literal["alta", "media", "baixa"]
    reason: str


def detect_niche(target: str, titles: list[str], refresh: bool = False) -> dict:
    titles = [t.strip() for t in titles if t and t.strip()][: config.AI_NICHE_TITLES]
    if len(titles) < config.AI_NICHE_MIN_TITLES and not cached(NICHE_KIND, target):
        raise AIError(f"Poucos títulos para detectar o nicho ({len(titles)}).")
    user = "Títulos:\n" + "\n".join(f"- {t}" for t in titles)
    return _run(NICHE_KIND, target, config.AI_MODEL_FAST, _NICHE_SYSTEM, user, NicheGuess,
                max_tokens=300, refresh=refresh)


# ---------------------------------------------------------------------------
# Palavras-chave de pesquisa a partir de um vídeo de referência
# ---------------------------------------------------------------------------

KEYWORDS_KIND = "keywords:v1"

_KEYWORDS_SYSTEM = """Você é pesquisador de mercado para canais dark do YouTube (sem rosto, narração, imagens ou IA).
A partir de um vídeo de referência, escreva as buscas que um pesquisador digitaria no YouTube para achar
vídeos do MESMO nicho e do MESMO formato (concorrentes diretos que dá para modelar).

- queries: 4 buscas curtas (2 a 5 palavras), no idioma do título, variando o ângulo (tema central,
  subtema, formato do vídeo, termo que o público usa). Nada de nomes de canal."""


class Queries(BaseModel):
    queries: list[str]


def history_keywords(target: str, titles: list[str]) -> list[str]:
    """Buscas a partir dos vídeos que o perfil assistiu (o centro de interesse do editor)."""
    user = "Vídeos assistidos recentemente (os do topo são os mais recentes):\n" + "\n".join(
        f"- {t}" for t in titles[:40])
    res = _run(KEYWORDS_KIND, target, config.AI_MODEL_FAST, _KEYWORDS_SYSTEM.replace(
        "A partir de um vídeo de referência", "A partir dos vídeos que o editor assistiu (ache o centro do nicho)"),
        user, Queries, max_tokens=200)
    return [q.strip() for q in res["queries"] if q.strip()][:4]


def search_keywords(video_id: str, title: str, channel: str) -> list[str]:
    user = f"Título: {title}\nCanal: {channel}"
    res = _run(KEYWORDS_KIND, f"video:{video_id}", config.AI_MODEL_FAST, _KEYWORDS_SYSTEM, user, Queries,
               max_tokens=200)
    return [q.strip() for q in res["queries"] if q.strip()][:4]


# ---------------------------------------------------------------------------
# Classificação de canais: dark ou não, e o formato (uma vez por canal)
# ---------------------------------------------------------------------------

FORMAT_LABELS = {
    "narracao": "Narração", "musica": "Música", "compilacao": "Compilação", "reupload": "Reupload",
    "animacao": "Animação", "comentario": "Youtuber", "cortes": "Cortes", "com_rosto": "Com rosto",
    "oficial": "Oficial", "outro": "Outro",
}
CHANNELS_VERSION = 2

_CHANNELS_SYSTEM = """Você classifica canais do YouTube para um produtor de CANAIS DARK.

Canal dark = canal ANÔNIMO, produzido em escala, onde nenhuma pessoa real é a marca do canal. Típico:
narração com voz de IA ou locutor genérico sobre imagens geradas por IA, banco de imagens/vídeos ou animação simples;
histórias, relatos, curiosidades, mistério, true crime, listas, "explicado"; compilações anônimas narradas.
Muitos usam o selo "conteúdo gerado por IA" do YouTube.

NÃO é dark, mesmo sem rosto na tela:
- qualquer canal de MÚSICA: playlists, coletâneas, música ambiente, lofi, sons para dormir/estudar, ruído branco,
  louvores, sertanejo, remixes (mesmo anônimo e feito com IA) -> format "musica", dark=false
- youtuber/criador com nome próprio, apelido ou personalidade (análise, comentário, react, gameplay, review,
  "explicando" com a própria voz e estilo) -> format "comentario"
- cortes de podcast, humorista, streamer, celebridade -> format "cortes"
- criador que aparece (chef, vlog, tutorial, entrevista) -> format "com_rosto"
- artista, gravadora, TV, jornal, marca, igreja, governo, VEVO -> format "oficial"
Na dúvida entre youtuber pessoal e dark, marque dark=false com confiança baixa.

Sinais de dark: nome genérico/temático ("Mistérios do Mundo", "Relatos da Escuridão", "Curiosidades TV"), descrição
genérica sem pessoa, selo de IA, títulos em série ou fórmula, muitos vídeos longos com estrutura repetida.
Sinais de NÃO dark: nome de pessoa ou apelido, "cortes do/da", descrição em 1ª pessoa, redes sociais pessoais,
contato comercial de influenciador, colaborações, "meu canal", "inscreva-se para mais vídeos meus".

Os canais vêm numerados. Para cada um responda em formato curto:
n = o número do canal; d = dark (true/false); c = confiança (a = alta, m = média, b = baixa);
f = formato (narracao, musica, compilacao, reupload, animacao, comentario, cortes, com_rosto, oficial, outro)."""


class ChannelClass(BaseModel):
    n: int
    d: bool
    c: Literal["a", "m", "b"]
    f: Literal["narracao", "musica", "compilacao", "reupload", "animacao", "comentario", "cortes",
               "com_rosto", "oficial", "outro"]


class ChannelList(BaseModel):
    items: list[ChannelClass]


_CONF = {"a": "alta", "m": "media", "b": "baixa"}


def _corrections() -> str:
    """As correções do editor viram exemplos: a IA aprende o critério dele."""
    rows = db.rows("""SELECT title, dark_manual, format, substr(COALESCE(description, ''), 1, 120) AS d
                      FROM channels WHERE dark_manual IS NOT NULL ORDER BY rowid DESC LIMIT 25""")
    if not rows:
        return ""
    lines = [f"- {r['title']} -> {'DARK' if r['dark_manual'] else 'NÃO é dark'}" + (f" ({r['d']})" if r['d'] else "")
             for r in rows]
    return "\n\nCorreções feitas pelo editor (siga este critério):\n" + "\n".join(lines)


def _fmt_subs(n) -> str:
    return "?" if n is None else f"{n:,}".replace(",", ".")


def classify_channels(channels: list[dict], batch: int = 30) -> int:
    """channels: [{channel_id, title, description, subs, ai, titles: [...]}]. Grava dark/conf/formato/tema."""
    system = _CHANNELS_SYSTEM + _corrections()

    def one(part: list[dict]) -> int:
        user = "\n".join(
            f"{i} | {c['title']} | selo IA: {'sim' if c.get('ai') else 'não'} | "
            f"inscritos: {_fmt_subs(c.get('subs'))} | descrição: {' '.join((c.get('description') or '-').split())[:200]} | "
            "títulos: " + " / ".join(t[:70] for t in c["titles"][:3])
            for i, c in enumerate(part, 1)
        )
        target = f"v{CHANNELS_VERSION}:" + hashlib.sha1((system + user).encode()).hexdigest()[:16]
        res = _run("channels:v3", target, config.AI_MODEL_FAST, system, user, ChannelList,
                   max_tokens=30 * len(part) + 150)
        rows = [(int(x["d"]), _CONF[x["c"]], x["f"], CHANNELS_VERSION, part[x["n"] - 1]["channel_id"])
                for x in res["items"] if 1 <= x["n"] <= len(part)]
        with db.tx() as con:
            con.executemany("UPDATE channels SET dark=?, dark_conf=?, format=?, class_v=? WHERE channel_id=?", rows)
        return len(rows)

    parts = [channels[i:i + batch] for i in range(0, len(channels), batch)]
    with ThreadPoolExecutor(AI_WORKERS) as pool:  # lotes em paralelo: mesmo custo, bem mais rápido
        return sum(pool.map(one, parts))


# ---------------------------------------------------------------------------
# Tradução de títulos (Haiku, uma vez por vídeo)
# ---------------------------------------------------------------------------

_TRANSLATE_SYSTEM = """Traduza títulos de vídeos do YouTube para português do Brasil, de forma natural (como um
brasileiro escreveria o título), mantendo números, nomes próprios e o tom. Se o título já estiver em português,
devolva igual. Os títulos vêm numerados: devolva a lista de traduções NA MESMA ORDEM e com a MESMA QUANTIDADE,
só o texto traduzido (sem o número)."""


class TranslationList(BaseModel):
    items: list[str]


def translate_titles(videos: list[dict], batch: int = 30) -> int:
    """videos: [{video_id, title}]. Grava videos.title_pt."""
    def one(part):
        user = "\n".join(f"{i}. {' '.join(v['title'].split())}" for i, v in enumerate(part, 1))
        target = "batch:" + hashlib.sha1(user.encode()).hexdigest()[:16]
        res = _run("translate:v2", target, config.AI_MODEL_FAST, _TRANSLATE_SYSTEM, user, TranslationList,
                   max_tokens=35 * len(part) + 150)
        if len(res["items"]) != len(part):   # veio desalinhado: não arrisca gravar tradução no vídeo errado
            return 0
        rows = [(t, v["video_id"]) for t, v in zip(res["items"], part)]
        with db.tx() as con:
            con.executemany("UPDATE videos SET title_pt=? WHERE video_id=?", rows)
        return len(rows)

    parts = [videos[i:i + batch] for i in range(0, len(videos), batch)]
    with ThreadPoolExecutor(AI_WORKERS) as pool:
        return sum(pool.map(one, parts))


# ---------------------------------------------------------------------------
# Buscas em outros idiomas
# ---------------------------------------------------------------------------

LANGUAGES = {  # código: (hl, gl, nome)
    "pt": ("pt-BR", "BR", "Português"), "en": ("en", "US", "Inglês"), "es": ("es", "MX", "Espanhol"),
    "hi": ("hi", "IN", "Hindi"), "id": ("id", "ID", "Indonésio"), "fr": ("fr", "FR", "Francês"),
    "de": ("de", "DE", "Alemão"), "ja": ("ja", "JP", "Japonês"), "ko": ("ko", "KR", "Coreano"),
    "ru": ("ru", "RU", "Russo"), "ar": ("ar", "SA", "Árabe"), "tr": ("tr", "TR", "Turco"),
    "it": ("it", "IT", "Italiano"),
}

_QTRANS_SYSTEM = """Você adapta buscas do YouTube para outros idiomas. Para cada idioma pedido, escreva como um
nativo PESQUISARIA esse mesmo assunto no YouTube (não é tradução literal: use o termo que o público daquele país usa).
Buscas curtas, de 2 a 5 palavras."""


class LangQueries(BaseModel):
    lang: str
    queries: list[str]


class LangQueryList(BaseModel):
    items: list[LangQueries]


def localize_queries(queries: list[str], langs: list[str]) -> dict[str, list[str]]:
    langs = [l for l in langs if l in LANGUAGES]
    if not langs:
        return {}
    user = "Buscas:\n" + "\n".join(f"- {q}" for q in queries) + "\n\nIdiomas: " + ", ".join(
        f"{l} ({LANGUAGES[l][2]})" for l in langs)
    target = hashlib.sha1(user.encode()).hexdigest()[:16]
    res = _run("qtrans:v1", target, config.AI_MODEL_FAST, _QTRANS_SYSTEM, user, LangQueryList,
               max_tokens=80 * len(langs) * max(len(queries), 1) + 200)
    return {i["lang"]: [q for q in i["queries"] if q.strip()] for i in res["items"] if i["lang"] in langs}


# ---------------------------------------------------------------------------
# Perfil do vídeo-semente: tema, ângulo e variações do título (Haiku)
# ---------------------------------------------------------------------------

SEED_KIND = "seed:v1"

_SEED_SYSTEM = """Você é um pesquisador de mercado de canais dark do YouTube. Recebe um vídeo de referência que o editor
quer MODELAR e prepara a pesquisa de concorrentes diretos.

Responda:
- theme: o tema central em poucas palavras (em português).
- format: o tipo de vídeo/formato (ex.: "documentário narrado de desmontagem", "lista de curiosidades", "história narrada").
- angle: o ângulo/gancho que faz o vídeo funcionar (ex.: "rivalidade entre países + revelação técnica").
- topic: 1 a 2 frases em português descrevendo exatamente que tipo de vídeo conta como concorrente direto
  (tema + formato + ângulo). Isso vai ser usado para julgar se outros vídeos são relevantes.
- queries: 6 buscas curtas (2 a 6 palavras) NO IDIOMA DO VÍDEO, como um pesquisador digitaria para achar
  concorrentes diretos (tema central, subtemas, termos do público). Sem nome de canal.
- variants: 8 títulos-variação NO IDIOMA DO VÍDEO que mantêm a estrutura e o ângulo do título original mas trocam
  os detalhes (países, marcas, objetos, pessoas, números), como outros canais do mesmo nicho fariam.
  Ex.: "American Engineers Tore Down a Chinese Tractor - What They Found Inside" ->
  "Japanese Engineers Tore Down an American Tractor", "German Engineers Took Apart a Chinese Excavator",
  "Engineers Tore Down a Chinese Electric Car - What They Found Inside"."""


class SeedProfile(BaseModel):
    theme: str
    format: str
    angle: str
    topic: str
    queries: list[str]
    variants: list[str]


def seed_profile(video_id: str, title: str, channel: str, description: str, tags: list[str], lang: str) -> dict:
    user = "\n".join([
        f"Título: {title}", f"Canal: {channel}", f"Idioma do vídeo: {lang}",
        f"Tags: {', '.join(tags[:25]) or '-'}",
        f"Descrição: {' '.join((description or '-').split())[:700]}",
    ])
    return _run(SEED_KIND, f"video:{video_id}", config.AI_MODEL_FAST, _SEED_SYSTEM, user, SeedProfile, max_tokens=900)


# ---------------------------------------------------------------------------
# Juiz de relevância: separa o que tem a ver do que é ruído (Haiku, em lotes)
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """Você filtra resultados de uma pesquisa de mercado no YouTube. Recebe a descrição do que o editor
procura e uma lista numerada de vídeos (número | título, em qualquer idioma). Dê uma nota de relevância:
3 = concorrente direto: mesmo tema central E mesmo formato/ângulo (dá para modelar)
2 = mesmo tema central, formato ou ângulo diferente
1 = mesma área ampla, mas outro tema
0 = nada a ver (não liste)
O idioma do título não importa. Seja rigoroso: na dúvida entre duas notas, use a menor.
Liste SOMENTE os vídeos com nota 1, 2 ou 3: n = número do vídeo, r = nota."""


class Relevance(BaseModel):
    n: int
    r: int


class RelevanceList(BaseModel):
    items: list[Relevance]


# ---------------------------------------------------------------------------
# Método Malandro: o mesmo vídeo em outras línguas (Haiku)
# ---------------------------------------------------------------------------

_MALANDRO_TITLES_SYSTEM = """Você ajuda um produtor de canais dark a achar em que línguas um vídeo ainda não foi feito.
Para cada idioma pedido, escreva:
- title: como um criador NATIVO daquele país intitularia ESTE MESMO vídeo no YouTube (título completo e chamativo,
  adaptado à cultura, não tradução literal);
- query: a busca curta (2 a 6 palavras) que um nativo digitaria para achar esse tipo de vídeo.
Use o código do idioma exatamente como recebido."""


class LangTitle(BaseModel):
    lang: str
    title: str
    query: str


class LangTitleList(BaseModel):
    items: list[LangTitle]


def malandro_titles(video_id: str, title: str, topic: str, langs: list[str]) -> dict[str, dict]:
    user = (f"Vídeo: {title}\nDo que se trata: {topic}\n\nIdiomas: "
            + ", ".join(f"{l} ({LANGUAGES[l][2]})" for l in langs))
    res = _run("malandro-titles:v1", f"video:{video_id}", config.AI_MODEL_FAST, _MALANDRO_TITLES_SYSTEM, user,
               LangTitleList, max_tokens=60 * len(langs) + 200)
    return {i["lang"]: {"title": i["title"], "query": i["query"]} for i in res["items"] if i["lang"] in LANGUAGES}


_SAME_VIDEO_SYSTEM = """Você verifica se um vídeo já foi "modelado" (refeito por outros canais) em outras línguas.
Recebe o vídeo de referência e uma lista numerada de títulos de vídeos (de vários países). Para cada título dê:
r = 3 se é o MESMO vídeo modelado (mesma premissa e ângulo, só mudando detalhes ou idioma);
r = 2 se é o mesmo tema com outra premissa;
l = código de 2 letras do idioma DO TÍTULO (pt, en, es, hi, id, fr, de, ja, ko, ru, ar, tr, it ou xx se outro).
Liste SOMENTE os de nota 2 ou 3: n = número do título, r = nota, l = idioma."""


class SameVideo(BaseModel):
    n: int
    r: int
    l: str


class SameVideoList(BaseModel):
    items: list[SameVideo]


def judge_same_video(reference: str, items: list[tuple[str, str]], batch: int = 100) -> dict[str, tuple[int, str]]:
    """items: [(video_id, título)] -> {video_id: (nota, idioma do título)}; quem não aparece é irrelevante."""
    system = _SAME_VIDEO_SYSTEM + "\n\nVídeo de referência: " + reference

    def one(part):
        user = "\n".join(f"{i} | {' '.join((t or '').split())[:120]}" for i, (_vid, t) in enumerate(part, 1))
        target = hashlib.sha1((system + user).encode()).hexdigest()[:20]
        res = _run("same:v1", target, config.AI_MODEL_FAST, system, user, SameVideoList,
                   max_tokens=26 * len(part) + 200)  # teto para todos passarem; só se paga o que a IA escreve
        return {part[x["n"] - 1][0]: (max(0, min(3, x["r"])), x["l"].lower()[:2])
                for x in res["items"] if 1 <= x["n"] <= len(part)}

    out: dict[str, tuple[int, str]] = {}
    with ThreadPoolExecutor(AI_WORKERS) as pool:
        for d in pool.map(one, [items[i:i + batch] for i in range(0, len(items), batch)]):
            out.update(d)
    return out


def judge_relevance(topic: str, items: list[tuple[str, str]], batch: int = 100) -> dict[str, int]:
    """items: [(video_id, título)]. Devolve {video_id: nota}; quem não aparece tem nota 0."""
    system = _JUDGE_SYSTEM + "\n\nO editor procura: " + topic

    def one(part):
        user = "\n".join(f"{i} | {' '.join((t or '').split())[:120]}" for i, (_vid, t) in enumerate(part, 1))
        target = hashlib.sha1((system + user).encode()).hexdigest()[:20]
        res = _run("rel:v2", target, config.AI_MODEL_FAST, system, user, RelevanceList,
                   max_tokens=20 * len(part) + 200)  # teto para todos passarem; só se paga o que a IA escreve
        return {part[x["n"] - 1][0]: max(0, min(3, x["r"])) for x in res["items"] if 1 <= x["n"] <= len(part)}

    parts = [items[i:i + batch] for i in range(0, len(items), batch)]
    out: dict[str, int] = {}
    with ThreadPoolExecutor(AI_WORKERS) as pool:
        for d in pool.map(one, parts):
            out.update(d)
    return out


# ---------------------------------------------------------------------------
# Análise de um vídeo (Sonnet, com a thumbnail)
# ---------------------------------------------------------------------------

VIDEO_KIND = "analysis:v1"

_VIDEO_SYSTEM = """Você é um estrategista de canais dark do YouTube. Analise um vídeo que um editor está considerando
modelar: o que fez ele funcionar e como replicar. Use só os dados recebidos (números, título, descrição, thumbnail e
comentários). Seja concreto, profissional e direto. Explicações em português do Brasil."""

_VIDEO_TASK = """Responda:
- verdict: uma frase: vale modelar? por quê?
- why_it_worked: 3 a 5 motivos concretos (tema, ângulo, título, thumbnail, timing, formato, duração).
- title_breakdown: como o título funciona (gatilhos, estrutura, palavras-chave).
- thumbnail: o que a thumbnail faz (composição, texto, cores, emoção) e como replicar.
- audience: o que os comentários mostram sobre o público (o que gostou, o que pediu, dúvidas).
- how_to_model: 4 a 6 passos práticos para fazer um vídeo modelado nesse (o que manter, o que mudar, como se diferenciar).
- titles: 5 títulos modelados prontos, no idioma {lang}.
- risks: 1 a 3 riscos (saturação, direitos, tema datado)."""


class VideoAnalysis(BaseModel):
    verdict: str
    why_it_worked: list[str]
    title_breakdown: str
    thumbnail: str
    audience: str
    how_to_model: list[str]
    titles: list[str]
    risks: list[str]


def analyze_video(video_id: str, text: str, lang: str, refresh: bool = False) -> dict:
    content = [
        {"type": "image", "source": {"type": "url", "url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        {"type": "text", "text": text + "\n\n" + _VIDEO_TASK.format(lang=lang)},
    ]
    return _run(VIDEO_KIND, f"video:{video_id}", config.AI_MODEL_SMART, _VIDEO_SYSTEM, content, VideoAnalysis,
                max_tokens=8000, refresh=refresh, effort="low", timeout=180)


# ---------------------------------------------------------------------------
# Ideias de variações do título, com chance de viralizar (Sonnet)
# ---------------------------------------------------------------------------

VARIATIONS_KIND = "variations:v1"

_VARIATIONS_SYSTEM = """Você é estrategista de canais dark do YouTube. O editor quer fazer VARIAÇÕES de um vídeo que
viralizou: o mesmo formato, trocando os detalhes (quem faz, o objeto, o país, a marca, o número...).
Ex.: "Engenheiros Japoneses Desmontaram um Carro Chinês" -> "Engenheiros Alemães Desmontaram um Carro Japonês",
"Engenheiros Americanos Desmontaram um Trator Chinês".

Use os DADOS recebidos (vídeos parecidos com números reais, idiomas onde já foi feito, comentários do público) para
estimar a chance de cada variação viralizar para o público desse nicho:
- sobe a chance: combinação parecida com outras que viralizaram recentemente; rivalidade ou comparação que o público
  ama (países, marcas famosas, "barato x caro"); algo que o público pediu nos comentários; poucos canais fizeram.
- desce a chance: combinação que muitos canais já fizeram (saturada); troca sem graça ou sem lógica; tema que não é do
  interesse desse público.
- seja honesto: sem dados que sustentem, não passe de 60%.
Explicações curtas em português do Brasil, simples (o editor não é técnico)."""

_VARIATIONS_TASK = """Responda:
- fits: true se o título dá para variar trocando detalhes; false se não dá (ex.: é sobre um fato único).
- template: o "molde" do título, com as partes trocáveis entre [colchetes], no idioma {lang}.
- note: uma frase: como usar essas variações (ou, se não dá para variar, que outros ângulos funcionam).
- variations: 10 títulos prontos no idioma {lang}, do mais provável para o menos provável de viralizar. Para cada um:
  title (o título completo), changes (o que foi trocado, curto), chance (0 a 100: chance de viralizar),
  why (uma frase simples com o motivo, citando o dado que sustenta quando houver)."""


class Variation(BaseModel):
    title: str
    changes: str
    chance: int
    why: str


class Variations(BaseModel):
    fits: bool
    template: str
    note: str
    variations: list[Variation]


def title_variations(video_id: str, payload: str, lang: str, refresh: bool = False) -> dict:
    res = _run(VARIATIONS_KIND, f"video:{video_id}", config.AI_MODEL_SMART, _VARIATIONS_SYSTEM,
               payload + "\n\n" + _VARIATIONS_TASK.format(lang=lang), Variations,
               max_tokens=6000, refresh=refresh, effort="low", timeout=180)
    res["variations"] = sorted(res["variations"], key=lambda v: -v["chance"])
    return res


# ---------------------------------------------------------------------------
# Relatório da pesquisa de mercado (Sonnet)
# ---------------------------------------------------------------------------

REPORT_KIND = "report:v1"

_REPORT_SYSTEM = """Você é um analista sênior de mercado para canais dark do YouTube (sem rosto: narração com IA ou
locutor sobre imagens, IA, banco de vídeos, animação ou compilação). Um editor vai usar seu relatório para decidir o
PRÓXIMO VÍDEO A MODELAR, então ele precisa ser concreto, acionável e fiel aos dados.

Você recebe: os vídeos encontrados na pesquisa (com números reais), os padrões de título dos que mais furaram a bolha
e comentários reais do público nos vídeos principais.

Regras:
- Baseie tudo nos dados. Cite os vídeos pelo ID entre colchetes, ex.: [dQw4w9WgXcQ]. Não invente números.
- Multiplicador = views / inscritos do canal. Alto = furou a bolha (o algoritmo empurrou para fora da base do canal).
- Recência importa muito: vídeo recente que furou a bolha indica demanda ATUAL. Priorize o que tem até 30 a 90 dias.
- Canais pequenos ou novos com vídeos explodindo = espaço para entrar no nicho.
- Nos comentários, procure pedidos explícitos ("faz um sobre...", "parte 2"), perguntas, dúvidas e o que emocionou.
- As ideias devem ser modeláveis por um canal dark (mesmo formato dos que funcionaram), no idioma dos vídeos do nicho.
- Vídeos de outros idiomas são referência para ADAPTAR (não traduzir ao pé da letra) para o público do canal.
- Explicações em português do Brasil. Direto, sem enrolação."""

_REPORT_TASK = """Monte o relatório:
- summary: diagnóstico do nicho em 3 a 5 frases (o que o público quer agora, quem está crescendo, onde está a brecha).
- saturation e opportunity: sua leitura do nicho.
- what_works: 4 a 7 padrões concretos (tema, formato, duração, ângulo, estrutura de título), cada um com IDs de exemplo.
- title_formulas: 4 a 6 fórmulas de título com lacunas, ex.: "[NÚMERO] [COISA] que [AUTORIDADE] não consegue explicar".
- audience_requests: 3 a 8 pedidos do público, com a evidência (trecho do comentário) e a força do sinal.
- to_model: os 5 melhores vídeos para modelar agora (IDs), priorizando recentes que furaram a bolha.
- ideas: 5 vídeos prontos para produzir: title (principal), alt_titles (2), hook (primeiros 15 a 30 segundos de
  narração), structure (4 a 7 blocos do roteiro), description (descrição pronta para o YouTube, 2 a 4 frases e uma
  chamada), tags (6 a 10), based_on (IDs de referência), why_now (por que esse vídeo agora).
- keywords: 8 a 15 palavras-chave e buscas do nicho, para as próximas pesquisas e para SEO.
- avoid: 2 a 5 coisas que não estão funcionando ou que saturaram."""


class VideoRef(BaseModel):
    video_id: str
    why: str


class AudienceRequest(BaseModel):
    request: str
    evidence: str
    strength: Literal["forte", "media", "fraca"]


class Idea(BaseModel):
    title: str
    alt_titles: list[str]
    hook: str
    structure: list[str]
    description: str
    tags: list[str]
    based_on: list[str]
    why_now: str


class Report(BaseModel):
    summary: str
    saturation: Literal["baixa", "media", "alta"]
    opportunity: Literal["baixa", "media", "alta"]
    what_works: list[str]
    title_formulas: list[str]
    audience_requests: list[AudienceRequest]
    to_model: list[VideoRef]
    ideas: list[Idea]
    keywords: list[str]
    avoid: list[str]


def research_report(research_id: int, payload: str, lang: str, refresh: bool = False) -> dict:
    task = _REPORT_TASK + f"\n\nIdioma do canal do editor: {lang}. Escreva title_formulas, ideas (título, " \
        f"alternativos, gancho, estrutura, descrição, tags) e keywords em {lang}."
    return _run(REPORT_KIND, f"research:{research_id}", config.AI_MODEL_SMART, _REPORT_SYSTEM,
                payload + "\n\n" + task, Report, max_tokens=16000, refresh=refresh, effort="medium",
                timeout=300)
