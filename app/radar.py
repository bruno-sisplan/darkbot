"""Radar do zero: achar NICHOS com oportunidade fresca, para quem ainda está decidindo o nicho (ou usa perfil coringa).

Em vez de partir de um nicho, parte do que está viralizando AGORA entre canais dark de QUALQUER tema:
1. varredura ampla: o mais visto de hoje e da semana em ~25 gêneros que costumam ter canal dark, em PT, EN e ES
   (páginas públicas do YouTube, sem cota);
2. a régua do editor: números pela API (1 unidade a cada 50), sem short e sem infantil, parâmetros de viral;
3. só dark: os canais dos que mais ganham views por hora são classificados (o resto nem gasta IA); no máximo 2 por canal;
4. a IA agrupa em nichos e diz o que é oportunidade; os números de cada nicho (vídeos, views por hora, canais, canais
   novos) são calculados em código a partir dos vídeos que a IA citou.
Cada nicho vira um perfil com um clique (nicho preenchido + buscas para treinar/garimpar). O resultado fica guardado.
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import median
from typing import Literal

from pydantic import BaseModel

from . import ai, analytics, config, db, jobs, viral, youtube_api, youtube_web

LANGS = ("pt", "en", "es")
# Gêneros que costumam ter canal dark (narração sobre imagens, IA, banco de vídeos, animação), com a busca larga em
# cada idioma. Larga de propósito: quem filtra é a régua (views por hora) + a classificação dark + a IA.
GENRES = {
    "mistério":        ("mistérios não resolvidos", "unsolved mysteries", "misterios sin resolver"),
    "true crime":      ("caso criminal real", "true crime story", "caso criminal real"),
    "terror real":     ("histórias de terror reais", "true scary stories", "historias de terror reales"),
    "história":        ("história que ninguém te contou", "history documentary", "historia que nadie te contó"),
    "guerra":          ("segunda guerra mundial história", "ww2 history", "segunda guerra mundial historia"),
    "curiosidades":    ("curiosidades que você não sabia", "facts you didn't know", "curiosidades que no sabías"),
    "ciência":         ("descoberta científica", "scientists discovered", "científicos descubrieron"),
    "espaço":          ("universo espaço documentário", "space documentary", "universo documental"),
    "engenharia":      ("engenharia impressionante", "engineering marvel", "ingeniería impresionante"),
    "natureza":        ("natureza animais documentário", "wildlife documentary", "documental animales"),
    "oceano":          ("fundo do oceano", "deep ocean", "fondo del océano"),
    "arqueologia":     ("arqueólogos encontraram", "archaeologists found", "arqueólogos encontraron"),
    "religião":        ("bíblia revelação", "bible prophecy", "biblia revelación"),
    "comunidades":     ("comunidade isolada", "isolated community", "comunidad aislada"),
    "países e povos":  ("como vivem as pessoas em", "life in the most", "así se vive en"),
    "biografias":      ("a história de vida de", "the untold story of", "la historia de vida de"),
    "celebridades":    ("o que aconteceu com o ator", "what happened to the actor", "qué pasó con el actor"),
    "dinheiro":        ("como ficou bilionário", "how he became a billionaire", "cómo se hizo millonario"),
    "empresas":        ("a queda da empresa", "the downfall of the company", "la caída de la empresa"),
    "tecnologia":      ("tecnologia proibida", "new technology china", "tecnología prohibida"),
    "geopolítica":     ("por que o país está", "why the country is", "por qué el país está"),
    "sobrevivência":   ("sobreviveu sozinho", "survived alone", "sobrevivió solo"),
    "lugares":         ("lugares abandonados", "abandoned places", "lugares abandonados"),
    "histórias de vida": ("história emocionante de", "heartwarming story", "historia conmovedora de"),
    "conspiração":     ("o que esconderam de nós", "what they hid from us", "lo que nos ocultaron"),
}
SEARCH_PAGES = 2
TOP_FOR_CLASSIFY = 300   # só os que mais ganham views por hora têm o canal classificado (o resto nem gasta IA)
PER_CHANNEL = 2
POOL = 150               # vídeos dark que a IA agrupa
NEW_CHANNEL_DAYS = 180


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_RADAR_SYSTEM = """Você é analista de mercado de canais dark do YouTube (sem rosto: narração sobre imagens, IA, banco de
vídeos, animação). O editor está DECIDINDO o nicho de um canal novo. Você recebe uma tabela numerada de vídeos de
CANAIS DARK que estão viralizando agora (de qualquer tema, em português, inglês e espanhol), com números reais.

Agrupe em 6 a 12 NICHOS (um nicho = um assunto + o tipo de vídeo que um canal novo faria dele, ex.: "casos de
desaparecimento narrados", "comunidades religiosas isoladas", "engenharia chinesa vs ocidental"). Específico o bastante
para virar um canal, amplo o bastante para render muitos vídeos. Não force: vídeo solto que não forma nicho fica de fora.

Para cada nicho:
- name: nome curto (2 a 5 palavras), em português.
- what: 1 frase: do que o nicho fala e qual é o vídeo típico.
- refs: os números da tabela que são desse nicho (todos os que forem).
- why_now: 1 frase: por que é oportunidade AGORA, com os números (views por hora, canais pequenos ou novos indo bem).
- competition: "baixa", "media" ou "alta" (muitos canais grandes fazendo = alta).
- entry: "facil", "medio" ou "dificil" para um canal dark novo (pesquisa, roteiro e imagens que exige).
- profile_niche: o texto do nicho para o perfil (curto, é o critério do filtro: o ASSUNTO, ex.: "amish e menonitas").
- searches: 4 buscas curtas (2 a 5 palavras) que o público digita, para treinar o perfil nesse nicho (no idioma em que
  o nicho mais aparece na tabela).
- langs: os idiomas (pt, en, es) em que o nicho aparece na tabela.
Português do Brasil, simples (o editor não é técnico). O editor NÃO vê a tabela: não cite "o vídeo 12" no texto."""


class Niche(BaseModel):
    name: str
    what: str
    refs: list[int]
    why_now: str
    competition: Literal["baixa", "media", "alta"]
    entry: Literal["facil", "medio", "dificil"]
    profile_niche: str
    searches: list[str]
    langs: list[str]


class Niches(BaseModel):
    niches: list[Niche]


def _in_langs(m: dict) -> bool:
    """O vídeo é de um dos idiomas da varredura? Pelo idioma que o canal informa; sem ele, pelo título: quase só letras
    latinas (as buscas em PT/EN/ES devolvem muito vídeo em hindi, tâmil, bengali, russo...)."""
    lang = (m.get("lang") or "").split("-")[0].lower()
    if lang:
        return lang in LANGS
    letters = [ch for ch in (m.get("title") or "") if ch.isalpha()]
    latin = sum(1 for ch in letters if ch < "ɐ")
    return not letters or latin / len(letters) >= 0.85


def _fmt_n(x) -> str:
    return "?" if x is None else f"{x:,}".replace(",", ".")


def run(job: jobs.Job) -> dict:
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("O Radar do zero precisa da chave do YouTube (Configurações).")
    if not ai.enabled():
        raise RuntimeError("O Radar do zero precisa da IA (Configurações).")
    spent0 = ai.usage()["cost_usd"]
    p = viral.get()
    up = viral.upload_filter(p["max_days"]) or "semana"
    sorts = [("views", up)] + ([("views", "hoje")] if p["max_days"] <= 7 and up != "hoje" else [])

    # 1. Varredura ampla (sem cota).
    tasks = [(q, lang, s, u) for qs in GENRES.values() for lang, q in zip(LANGS, qs) for s, u in sorts]
    job.update(0.03, f"Varrendo o que viraliza agora em {len(GENRES)} gêneros, PT/EN/ES ({len(tasks)} buscas)...")
    found: dict[str, str] = {}
    with youtube_web.client() as c, ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        def one(t):
            hl, gl, _n = ai.LANGUAGES[t[1]]
            return youtube_web.search(c, t[0], t[2], t[3], hl, gl, pages=SEARCH_PAGES)
        for i, res in enumerate(pool.map(one, tasks), 1):
            for vid, title in res:
                found.setdefault(vid, title)
            if i % 10 == 0:
                job.update(0.03 + 0.3 * i / len(tasks), f"Varrendo... {i}/{len(tasks)} buscas · {len(found)} vídeos")
            if job.stopped():
                raise RuntimeError("Cancelado.")
    if not found:
        raise RuntimeError("O YouTube não devolveu resultados agora. Tente de novo em instantes.")

    # 2. Números (barato) e a régua do editor, ainda sem saber quem é dark.
    job.update(0.36, f"Buscando os números de {len(found)} vídeos...")
    meta = {m["video_id"]: m for m in youtube_api.fetch_videos(list(found), key)}
    cands = []
    for vid, m in meta.items():
        if (m.get("duration_s") or 0) <= config.SHORT_MAX_SECONDS or m.get("kids") or not _in_langs(m):
            continue
        v = {"video_id": vid, "views": m.get("views"), "published_at": m.get("published_at")}
        viral.add_metrics(v)
        v["age_days"] = (v.get("age_hours") or 0) / 24
        if viral.passes(v, p | {"only_dark": False, "min_mult": 0, "max_subs": 0}):
            cands.append(v)
    cands.sort(key=lambda v: -(v.get("views_hour") or 0))
    top = [v["video_id"] for v in cands[:TOP_FOR_CLASSIFY]]
    if not top:
        raise RuntimeError(f"Nada bate os seus parâmetros nessa varredura ({viral.describe()}).")

    # 3. Só dark: grava os melhores, busca canal (inscritos, descrição) e classifica os canais.
    job.update(0.45, f"Conferindo quais dos {len(top)} vídeos que mais crescem são de canais dark...")
    with db.tx() as con:
        con.executemany("INSERT OR IGNORE INTO videos(video_id, first_seen_at) VALUES(?, ?)", [(v, now_iso()) for v in top])
    jobs.enrich(None, top, key)
    if job.stopped():
        raise RuntimeError("Cancelado.")
    jobs.classify_new_channels(video_ids=top)
    det = []
    for vid in top:
        v = analytics.video_detail(vid)
        if not v or not v.get("title") or v.get("is_short"):
            continue
        if v.get("views_hour") is None:
            viral.add_metrics(v)
        if viral.passes(v, p) and _in_langs(v):   # régua completa (só dark, inscritos, viralizou...) e idioma
            det.append(v)
    det = viral.rank(det, p)
    pool_v, per = [], {}
    for v in det:
        ch = v.get("channel_id") or v["video_id"]
        if per.get(ch, 0) < PER_CHANNEL:
            per[ch] = per.get(ch, 0) + 1
            pool_v.append(v)
    pool_v = pool_v[:POOL]
    if len(pool_v) < 5:
        raise RuntimeError(f"Poucos vídeos dark viralizando agora ({len(pool_v)}). Afrouxe os parâmetros em Configurações.")

    # 4. A IA agrupa em nichos; os números de cada nicho saem dos vídeos citados.
    job.update(0.8, f"IA agrupando {len(pool_v)} vídeos dark em nichos...")
    table = ["(n | título | idioma | views por hora | views | viralizou | dias | canal | inscritos | idade do canal em dias)"]
    table += [f"{i} | {v['title']} | {(v.get('lang') or '?')[:2]} | {_fmt_n(round(v.get('views_hour') or 0))} | "
              f"{_fmt_n(v.get('views'))} | {v.get('multiplier')}x | {round(v.get('age_days') or 0)} | {v.get('channel_title')} | "
              f"{_fmt_n(v.get('subs'))} | {v.get('channel_age_days') or '?'}" for i, v in enumerate(pool_v, 1)]
    res = ai._run("radar:v1", f"run:{now_iso()}", config.AI_MODEL_SMART, _RADAR_SYSTEM, "\n".join(table), Niches,
                  max_tokens=8000, effort="low", timeout=240)

    def card(v):
        return {"video_id": v["video_id"], "title": v["title"], "channel_title": v.get("channel_title"),
                "channel_id": v.get("channel_id"), "lang": (v.get("lang") or "").split("-")[0] or None,
                "views": v.get("views"), "views_hour": round(v.get("views_hour") or 0), "multiplier": v.get("multiplier"),
                "subs": v.get("subs"), "age_days": round(v.get("age_days") or 0, 1),
                "channel_age_days": v.get("channel_age_days")}

    niches = []
    for n in res["niches"]:
        vids = [pool_v[i - 1] for i in dict.fromkeys(n["refs"]) if 1 <= i <= len(pool_v)]
        if len(vids) < 2 or len({v.get("channel_id") for v in vids}) < 2:
            continue   # um canal sozinho não é nicho
        vph = [v.get("views_hour") or 0 for v in vids]
        chans = {v.get("channel_id") for v in vids}
        new = {v.get("channel_id") for v in vids if (v.get("channel_age_days") or 9999) <= NEW_CHANNEL_DAYS}
        comp = {"baixa": 1.0, "media": 0.7, "alta": 0.4}[n["competition"]]
        # nota de oportunidade: ritmo típico × quantidade (log) × espaço (canais novos indo bem, concorrência)
        score = median(vph) * math.log2(1 + len(vids)) * (1 + len(new) / max(len(chans), 1)) * comp
        niches.append(n | {
            "videos": [card(v) for v in sorted(vids, key=lambda v: -(v.get("views_hour") or 0))],
            "count": len(vids), "channels": len(chans), "new_channels": len(new),
            "vph_median": round(median(vph)), "vph_top": round(max(vph)), "score": round(score, 1),
        })
    niches.sort(key=lambda n: -n["score"])
    result = {"niches": niches, "params": viral.describe(), "langs": list(LANGS),
              "funnel": {"found": len(found), "in_rule": len(cands), "checked": len(top), "dark": len(det),
                         "pool": len(pool_v)},
              "created_at": now_iso(), "cost_usd": round(ai.usage()["cost_usd"] - spent0, 4)}
    with db.tx() as con:
        rid = con.execute("INSERT INTO radar_runs(result, created_at) VALUES(?, ?)",
                          (json.dumps(result, ensure_ascii=False), result["created_at"])).lastrowid
    job.update(1.0, f"{len(niches)} nichos com oportunidade")
    return {"radar_id": rid, "note": f"Radar do zero: {len(niches)} nichos com vídeos dark viralizando agora."}


def runs() -> list[dict]:
    out = []
    for r in db.rows("SELECT id, result, created_at FROM radar_runs ORDER BY id DESC LIMIT 20"):
        res = json.loads(r["result"])
        out.append({"id": r["id"], "created_at": r["created_at"], "niches": len(res.get("niches") or [])})
    return out


def get(radar_id: int) -> dict | None:
    r = db.row("SELECT id, result FROM radar_runs WHERE id=?", (radar_id,))
    return json.loads(r["result"]) | {"id": r["id"]} if r else None
