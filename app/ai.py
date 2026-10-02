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
# Briefing da pesquisa por assunto ou pelo histórico (o equivalente ao perfil da semente)
# ---------------------------------------------------------------------------

class Queries(BaseModel):   # resposta mínima (usada no teste dos modelos)
    queries: list[str]


BRIEF_KIND = "brief:v1"

_BRIEF_SYSTEM = """Você é um pesquisador de mercado sênior de canais dark do YouTube (sem rosto: narração com voz de IA
ou locutor sobre imagens de IA, banco de vídeos ou animação). O editor quer achar o que está VIRALIZANDO AGORA {source}.
Monte o briefing da pesquisa:
- theme: o tema central em poucas palavras, em português.
- format: o formato que mais funciona para canais dark nesse tema (ex.: "história real narrada com imagens de IA",
  "documentário de engenharia narrado", "lista de curiosidades com banco de vídeos").
- angle: o gancho que mais puxa views nesse tema (ex.: "rivalidade entre países + revelação técnica").
- topic: 1 a 2 frases em português dizendo exatamente que vídeo conta como concorrente (tema + formato + premissa).
  É o critério do filtro de relevância: específico o bastante para cortar ruído, amplo o bastante para pegar os
  subtemas que o mesmo público assiste.
- queries: 6 buscas curtas (2 a 6 palavras) em {lang}, como o PÚBLICO digita no YouTube: 2 do tema central, 2 com o
  vocabulário do público (termos populares, não técnicos) e 2 de subtemas em alta nesse nicho. Sem nome de canal,
  sem aspas, sem hashtags.
- variants: 6 títulos no estilo exato dos vídeos que viralizam nesse tema, em {lang}. São SÓ sondas de busca (achar
  concorrentes pelo jeito de titular): variem a premissa e os detalhes (país, objeto, pessoa, número, época)."""


def research_brief(target: str, source: str, text: str, lang: str) -> dict:
    """Briefing de uma pesquisa por assunto (source = o que o editor escreveu) ou pelo histórico (títulos assistidos)."""
    system = _BRIEF_SYSTEM.format(
        source="sobre o assunto que ele escreveu" if source == "keyword" else
        "no nicho dos vídeos que o perfil dele assistiu (ache o CENTRO do nicho, ignore os vídeos fora da curva)",
        lang=lang)
    return _run(BRIEF_KIND, target, config.AI_MODEL_FAST, system, text, SeedProfile, max_tokens=900)


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

_QTRANS_SYSTEM = """Você adapta buscas e títulos do YouTube para outros mercados. Para cada idioma pedido, reescreva
cada item como um NATIVO daquele país digitaria para achar o MESMO tipo de vídeo: mesma intenção, termos e ordem de
palavras naturais do público local (não é tradução literal). Mantenha em inglês só o que o público local já usa em
inglês (marcas, nomes próprios). Itens curtos, de 2 a 6 palavras, sem aspas. Use o código do idioma como recebido."""


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
    res = _run("qtrans:v2", target, config.AI_MODEL_FAST, _QTRANS_SYSTEM, user, LangQueryList,
               max_tokens=80 * len(langs) * max(len(queries), 1) + 200)
    return {i["lang"]: [q for q in i["queries"] if q.strip()] for i in res["items"] if i["lang"] in langs}


# ---------------------------------------------------------------------------
# Buscas aprendidas: o que está viralizando ensina o que buscar a seguir (bola de neve)
# ---------------------------------------------------------------------------

_LEARN_SYSTEM = """Você é um pesquisador de mercado sênior de canais dark do YouTube. Recebe o que o editor procura, as
buscas que já foram feitas e títulos de vídeos do nicho que estão VIRALIZANDO AGORA (com idioma e views por hora).
Faça o que um bom pesquisador faz ao ver o que está funcionando: pesquise MAIS DISSO, dentro do MESMO ASSUNTO.

- items: até {n} buscas NOVAS, de 2 a 6 palavras, cada uma no idioma do público que ela deve achar (lang = um destes
  códigos: {langs}). TODA busca cita o assunto específico do editor (o grupo, o objeto, o lugar: ex. "amish",
  "menonitas", "trator chinês"). Tire dos títulos que mais ganham views por hora os termos, premissas, lugares e
  formatos que se repetem e AINDA NÃO foram buscados. NUNCA generalize para categorias amplas ou assuntos parecidos
  (ex.: de "amish" para "comunidades religiosas", "povos indígenas", "migração"): isso traz vídeo fora do nicho.
  Não repita nem reformule as buscas já feitas. Sem nome de canal, sem aspas, sem hashtag."""


class LangQ(BaseModel):
    lang: str
    q: str


class LangQList(BaseModel):
    items: list[LangQ]


def learn_queries(topic: str, done: list[str], titles: list[tuple[str, str, int]], langs: list[str],
                  n: int = 8) -> list[tuple[str, str]]:
    """titles: [(idioma, título, views por hora)] dos relevantes que viralizam -> [(idioma, busca)] novas."""
    langs = [l for l in langs if l in LANGUAGES] or ["pt"]
    system = _LEARN_SYSTEM.format(n=n, langs=", ".join(langs))
    user = "\n".join([f"O editor procura: {topic}", "", "Buscas já feitas: " + "; ".join(done[:40]), "",
                      "Viralizando agora (idioma | views por hora | título):"]
                     + [f"- {l} | {vph} | {' '.join(t.split())[:110]}" for l, t, vph in titles[:30]])
    target = hashlib.sha1((system + user).encode()).hexdigest()[:20]
    res = _run("learn:v2", target, config.AI_MODEL_FAST, system, user, LangQList, max_tokens=40 * n + 200)
    seen = {d.lower() for d in done}
    out = []
    for it in res["items"]:
        q = " ".join(it["q"].split()).strip("\"'")
        if it["lang"] in langs and q and q.lower() not in seen:
            seen.add(q.lower())
            out.append((it["lang"], q))
    return out[:n]


# ---------------------------------------------------------------------------
# Perfil do vídeo-semente: tema, ângulo e variações do título (Haiku)
# ---------------------------------------------------------------------------

SEED_KIND = "seed:v3"

_SEED_SYSTEM = """Você é um pesquisador de mercado sênior de canais dark do YouTube. Recebe um vídeo de referência que o
editor quer MODELAR e prepara a caça aos concorrentes diretos (outros canais que fizeram o mesmo vídeo trocando detalhes).

Responda:
- theme: o tema central em poucas palavras (em português).
- format: o formato do vídeo (ex.: "documentário narrado de desmontagem", "lista de curiosidades", "história narrada").
- angle: a PREMISSA que faz o vídeo funcionar, o que se repete nos modelados (ex.: "engenheiros de um país desmontam
  um produto do país rival e revelam o que há dentro").
- topic: 1 a 2 frases em português dizendo exatamente que vídeo conta como concorrente direto (tema + formato +
  premissa). É o critério do filtro de relevância: inclua as variações da premissa, exclua o que só divide o tema.
- queries: 6 buscas curtas (2 a 6 palavras) NO IDIOMA DO VÍDEO, como o público digita: 2 da premissa, 2 do tema
  central e 2 com termos populares do nicho. TODA busca cita o assunto específico (ex.: "amish", "trator chinês");
  nada de categoria ampla ("comunidades tradicionais", "pressão econômica"). Sem nome de canal, sem aspas.
- variants: 8 títulos-variação NO IDIOMA DO VÍDEO que mantêm a estrutura e a premissa do original mas trocam os
  detalhes, variando os eixos (quem faz, o objeto, o país/marca rival, o número, a época), como os canais que
  modelam esse vídeo fariam. Pelo menos 2 devem inverter os papéis (quem desmonta vira quem é desmontado). O assunto
  central continua o mesmo (trocar "amish" por "menonitas" vale; por "comunidades agrícolas" ou "indígenas", não).
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

_JUDGE_SYSTEM = """Você é o filtro de qualidade de uma pesquisa de mercado de canais dark do YouTube. Recebe o que o
editor procura e uma lista numerada de vídeos (n | título | canal | duração em minutos), em qualquer idioma.

Nota de relevância:
3 = concorrente direto: mesmo tema E mesma premissa/formato. Um canal dark refaria este vídeo trocando só os detalhes
    (país, marca, objeto, personagem, número).
2 = mesmo tema, outra premissa ou formato (serve de referência para o mesmo público).
1 = mesma área ampla, outro tema (o público até assiste, mas não é o que se procura).
0 = nada a ver: não liste.

Regras:
- Julgue o assunto e a premissa, nunca o idioma: o mesmo vídeo em japonês ou hindi vale igual.
- Canal de pessoa do mesmo tema (react, vlog, podcast, cortes, gameplay, opinião, telejornal): no máximo 2.
- Música, playlist, clipe, trailer, teaser, live, vídeo de 1 minuto ou menos: 0.
- Título isca sem relação clara com o tema: 0.
- Na dúvida entre duas notas, use a menor.
Liste SOMENTE os vídeos com nota 1, 2 ou 3: n = número, r = nota."""


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


# Malandro + países: onde há PROCURA por esse conteúdo e ninguém faz (termos curtos por idioma + leitura final)

_TERMS_SYSTEM = """Você ajuda a medir em que países existe PROCURA por um tipo de vídeo no YouTube. Para cada idioma
pedido, escreva 3 termos MUITO CURTOS (1 ou 2 palavras), como o COMEÇO de uma busca que muita gente digita no YouTube
daquele país (o autocompletar só funciona com termos populares). TODO termo começa pelo NOME ESPECÍFICO do assunto
(o grupo, o objeto, o lugar, a marca: "menonitas", "amish", "trator chinês"), nunca por verbo ou palavra genérica
("abandono", "análise", "comparação", "história"), que puxam qualquer coisa: 1) o assunto principal (ex.: "menonitas"),
2) o assunto + o detalhe que mais importa no vídeo (ex.: "menonitas méxico"), 3) o assunto vizinho que o mesmo público
busca (ex.: "amish"). Evite palavras ambíguas (banda, time, novela). Use o código do idioma exatamente como recebido."""


class LangTerms(BaseModel):
    lang: str
    terms: list[str]


class LangTermsList(BaseModel):
    items: list[LangTerms]


def country_terms(video_id: str, title: str, topic: str, langs: list[str]) -> dict[str, list[str]]:
    user = (f"Vídeo: {title}\nTema: {topic}\n\nIdiomas: " + ", ".join(f"{l} ({LANGUAGES[l][2]})" for l in langs))
    res = _run("paises-termos:v3", f"video:{video_id}", config.AI_MODEL_FAST, _TERMS_SYSTEM, user, LangTermsList,
               max_tokens=40 * len(langs) + 200)
    return {i["lang"]: [t.strip() for t in i["terms"] if t.strip()][:3] for i in res["items"] if i["lang"] in LANGUAGES}


_COUNTRIES_SYSTEM = """Você é analista de mercado internacional de canais dark do YouTube. O editor rodou o Método
Malandro neste vídeo (em que línguas ninguém fez) e agora quer saber EM QUE PAÍSES o público PROCURA esse conteúdo e
ainda não tem quem faça.

Você recebe uma tabela por MERCADO (um idioma com os seus países) com dados reais: procura (quantas buscas o YouTube
de cada país completa para os termos do tema, quantos vídeos do tema NAQUELE IDIOMA postados no último mês ganharam
tração, views por hora típicas) e oferta (quantos canais já fizeram ESTE vídeo nesse idioma), com a nota de oportunidade
já calculada; e comentários do vídeo original. O autocompletar mostra no máximo 10 sugestões por termo (30 = teto).

Regras: use só os dados e cite os números em linguagem simples (vídeos do nicho ganhando views, views por hora,
quantos canais já fizeram, o que se busca); NUNCA cite a nota 0-1 nem "procura de 0,xx"; nada genérico; procura alta com oferta zero é o melhor sinal; procura baixa
é procura baixa (não invente interesse; não chame de oportunidade). O idioma do original não é oportunidade, nem idioma
saturado. Dublagem automática do original NÃO conta como oferta (só vale vídeo nativo na língua). Fale SÓ dos mercados de "Analise estes": não cite,
não compare e não recomende nenhum outro idioma (nem como "aberto", "vale atenção" ou "a observar"). Oferta: "livre" = ninguém fez, "pouca" = 1 ou 2 canais fizeram, "saturada" = 3
ou mais; use exatamente esses termos (não chame "pouca" de saturada). Português do Brasil, frases curtas, o editor não é técnico.
- summary: 2 a 3 frases: onde está a melhor oportunidade e por quê, com números.
- notes: para cada mercado em "Analise estes": c = o código do idioma exatamente como veio; why = uma frase com o
  motivo (procura x oferta, com números) e o país que puxa a procura; adapt = uma frase do que adaptar para o vídeo
  soar nativo no país principal (moeda, unidades, marcas, rival local, referências culturais).
- comment_signals: uma frase sobre países ou idiomas que APARECEM ESCRITOS nos comentários do original ("saludos desde",
  pedidos de tradução, comentários em outra língua). Só o que está lá, sem deduzir interesse. Sem sinais, diga isso."""


class CountryNote(BaseModel):
    c: str
    why: str
    adapt: str


class CountryReport(BaseModel):
    summary: str
    notes: list[CountryNote]
    comment_signals: str


def countries_report(video_id: str, text: str, refresh: bool = True) -> dict:
    target = f"video:{video_id}:" + hashlib.sha1(text.encode()).hexdigest()[:12]
    return _run("paises:v5", target, config.AI_MODEL_FAST, _COUNTRIES_SYSTEM, text, CountryReport,
                max_tokens=2500, refresh=refresh)


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


def judge_relevance(topic: str, items: list[tuple], batch: int = 100) -> dict[str, int]:
    """items: [(video_id, título)] ou [(video_id, título, "canal | duração")]. Devolve {video_id: nota};
    quem não aparece tem nota 0."""
    system = _JUDGE_SYSTEM + "\n\nO editor procura: " + topic

    def line(i, it):
        extra = f" | {it[2]}" if len(it) > 2 and it[2] else ""
        return f"{i} | {' '.join((it[1] or '').split())[:90]}{extra}"

    def one(part):
        user = "\n".join(line(i, it) for i, it in enumerate(part, 1))
        target = hashlib.sha1((system + user).encode()).hexdigest()[:20]
        res = _run("rel:v3", target, config.AI_MODEL_FAST, system, user, RelevanceList,
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

VIDEO_KIND = "analysis:v2"   # v2: sem títulos inventados

_VIDEO_SYSTEM = """Você é um estrategista sênior de canais dark do YouTube (sem rosto: narração com voz de IA ou locutor
sobre imagens de IA, banco de vídeos ou animação). Um editor está decidindo se MODELA este vídeo: refazer a mesma
premissa e estrutura, trocando os detalhes, num canal dark. Analise o que fez ele funcionar e como replicar.

Regras:
- Use só os dados recebidos (números, título, descrição, thumbnail e comentários). Não invente números nem fatos.
- Toda afirmação forte vem com o dado que a sustenta (ex.: "1,4 mil views por hora com 4 dias de vida").
- Views por hora = o que está explodindo agora; viralizou (views ÷ inscritos) alto = o algoritmo levou o vídeo para
  fora da base do canal. Canal pequeno ou novo com vídeo explodindo = premissa forte, não fama do canal.
- Nada de conselho genérico ("faça uma thumbnail chamativa", "capriche no roteiro"): diga O QUE exatamente.
- Nunca invente títulos: o editor modela o vídeo real.
- Português do Brasil, direto, frases curtas."""

_VIDEO_TASK = """Responda:
- verdict: uma frase: vale modelar agora? Sim/não e o motivo com o número que decide.
- why_it_worked: 3 a 5 motivos concretos (premissa, ângulo, título, thumbnail, timing, formato, duração), cada um com
  a evidência.
- title_breakdown: a estrutura do título (gatilho, promessa, curiosidade aberta, palavras que puxam) e o que manter.
- thumbnail: composição, texto, cores, emoção e o elemento que prende o olho; o que copiar e o que trocar.
- audience: o que os comentários mostram (o que emocionou, o que pediram, dúvidas, críticas). Sem comentários, diga isso.
- how_to_model: 4 a 6 passos práticos para um editor que publica em {lang}: o que MANTER (premissa, estrutura, ritmo,
  duração), o que TROCAR (detalhes, país, objeto) e como se diferenciar sem perder o que funcionou.
- risks: 1 a 3 riscos concretos (saturação, direitos de imagem/marca, tema que perde a validade rápido)."""


class VideoAnalysis(BaseModel):
    verdict: str
    why_it_worked: list[str]
    title_breakdown: str
    thumbnail: str
    audience: str
    how_to_model: list[str]
    risks: list[str]


def analyze_video(video_id: str, text: str, lang: str, refresh: bool = False) -> dict:
    content = [
        {"type": "image", "source": {"type": "url", "url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        {"type": "text", "text": text + "\n\n" + _VIDEO_TASK.format(lang=lang)},
    ]
    return _run(VIDEO_KIND, f"video:{video_id}", config.AI_MODEL_SMART, _VIDEO_SYSTEM, content, VideoAnalysis,
                max_tokens=8000, refresh=refresh, effort="low", timeout=180)




# ---------------------------------------------------------------------------
# Relatório da pesquisa de mercado (Sonnet)
# ---------------------------------------------------------------------------

REPORT_KIND = "report:v3"   # v3: régua dos parâmetros de viral, brechas e evidência obrigatória
_OLD_REPORT_KINDS = ("report:v2",)   # relatórios antigos continuam aparecendo (sem as brechas)

_REPORT_SYSTEM = """Você é um analista sênior de mercado de canais dark do YouTube (sem rosto: narração com voz de IA ou
locutor sobre imagens de IA, banco de vídeos, animação ou compilação). O editor usa o seu relatório como VERDADE para
decidir o próximo vídeo a modelar: ele precisa ser fiel aos dados, específico e acionável, no nível de uma consultoria.

Você recebe: a régua de viral do editor, os vídeos da pesquisa que batem essa régua (números reais), os padrões de
título dos que mais viralizaram e comentários reais do público.

Como ler os números:
- Views por hora (desde a postagem) = o que está explodindo AGORA. É o critério principal do editor.
- Viralizou = views ÷ inscritos do canal. Alto = o algoritmo levou o vídeo para fora da base do canal (premissa forte,
  não fama do canal). Canal pequeno ou novo explodindo = espaço para entrar.
- Relevância 3 = concorrente direto (mesma premissa), 2 = mesmo tema.
- Vários canais diferentes acertando a mesma premissa na mesma semana = demanda comprovada; um único vídeo isolado =
  sinal fraco (diga isso).

Regras:
- Toda afirmação vem com evidência: o ID entre colchetes (ex.: [dQw4w9WgXcQ]) e o número que sustenta. Não invente
  números, vídeos nem comentários.
- Nada de conselho genérico ("capriche na thumbnail", "poste com frequência"): só o que ESTES dados mostram.
- Nos comentários, procure pedidos explícitos ("faz um sobre...", "parte 2"), perguntas sem resposta, o que emocionou
  e críticas (o que o público sente falta).
- NUNCA invente títulos: o editor só modela vídeos que EXISTEM e já provaram.
- Vídeos de outros idiomas são para ADAPTAR ao público do canal (premissa e estrutura), não traduzir ao pé da letra.
- Português do Brasil, frases curtas, sem enrolação. O editor não é técnico."""

_REPORT_TASK = """Monte o relatório:
- summary: diagnóstico em 3 a 5 frases: o que o público quer AGORA, quem está crescendo (canais pequenos/novos?), qual
  premissa está quente e onde está a brecha. Com IDs e números.
- saturation e opportunity: sua leitura (baixa, media, alta), coerente com o summary.
- what_works: 4 a 7 padrões concretos (premissa, formato, duração, estrutura de título, thumbnail se der para inferir),
  cada um com 2 ou mais IDs de exemplo e o número que prova.
- gaps: 2 a 5 brechas: o que o público pede ou que está crescendo e quase ninguém entregou ainda (subtema, idioma,
  ângulo). Cada uma com a evidência (ID, comentário ou contagem).
- audience_requests: 3 a 8 pedidos do público, com a evidência (trecho real do comentário) e a força do sinal
  (forte = vários comentários/muitas curtidas; fraca = um comentário isolado).
- to_model: os 8 melhores vídeos para modelar AGORA (IDs da tabela), do mais forte para o mais fraco. Priorize views
  por hora, depois concorrente direto (relevância 3), canal dark e canal pequeno (mais fácil de replicar). Em why,
  uma frase com o número (views por hora, idade) e o que modelar nele.
- keywords: 8 a 15 buscas e palavras-chave do nicho, como o público digita (para as próximas pesquisas e SEO).
- avoid: 2 a 5 coisas que não funcionam ou saturaram, com evidência."""


class VideoRef(BaseModel):
    video_id: str
    why: str


class AudienceRequest(BaseModel):
    request: str
    evidence: str
    strength: Literal["forte", "media", "fraca"]


class Report(BaseModel):
    summary: str
    saturation: Literal["baixa", "media", "alta"]
    opportunity: Literal["baixa", "media", "alta"]
    what_works: list[str]
    gaps: list[str]
    audience_requests: list[AudienceRequest]
    to_model: list[VideoRef]
    keywords: list[str]
    avoid: list[str]


def report_cached(research_id: int) -> tuple[dict | None, str]:
    """(relatório, kind em que está guardado): o atual ou, se não houver, o da versão anterior."""
    for kind in (REPORT_KIND, *_OLD_REPORT_KINDS):
        rep = cached(kind, f"research:{research_id}")
        if rep:
            return rep, kind
    return None, REPORT_KIND


def research_report(research_id: int, payload: str, lang: str, refresh: bool = False) -> dict:
    task = _REPORT_TASK + f"\n\nIdioma do canal do editor: {lang}. Escreva as keywords em {lang}."
    return _run(REPORT_KIND, f"research:{research_id}", config.AI_MODEL_SMART, _REPORT_SYSTEM,
                payload + "\n\n" + task, Report, max_tokens=16000, refresh=refresh, effort="medium",
                timeout=300)
