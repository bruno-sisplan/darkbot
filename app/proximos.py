"""Próximos vídeos: "modelei esse, e agora?". Sempre vídeos REAIS para modelar (nada de título inventado).

- Vídeos que modelei: a VERDADE sobre o canal do editor (por link, ou "Já modelei" em Descobrir e na prévia).
  Não precisa logar na conta do canal (o editor usa proxy nos canais): tudo sai do perfil e dessa lista.
- DNA do canal: a IA lê os modelados e escreve do que o canal fala (temas, formatos, ângulos, público, estilo dos
  títulos). O editor pode corrigir; a correção vale como verdade. Fica guardado e só é refeito quando a lista muda.
- Rodada (v4): parte dos vídeos que o editor modelou e junta o que é PRÓXIMO de verdade: o que o canal de origem
  postou, o que o YouTube recomenda depois do vídeo modelado, o que quem fez o mesmo vídeo postou e buscas amplas do
  assunto. Tira o mesmo vídeo de novo, o que foge do nicho e canal não dark; no máximo 2 por canal; régua do editor
  (amplia o período se vier pouca coisa). A IA ordena os vídeos reais e diz por que cada um é o próximo.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from . import ai, analytics, config, db, jobs, research, viral, youtube_api, youtube_web

DNA_MODELED = 40        # modelados que entram no DNA (os mais recentes)

KINDS = {"continuacao": "Continuação", "vizinho": "Tema vizinho", "pedido": "Pedido do público",
         "tendencia": "Tendência agora", "angulo": "Ângulo novo"}
BOLDNESS = {
    "perto": ("Perto", "6 buscas que continuam o território do canal (o que ele já faz e funciona) e 4 de temas vizinhos",
              "A maioria deve ser continuação ou tema vizinho bem próximo do que o canal já faz. Pouco risco."),
    "equilibrado": ("Equilibrado", "3 buscas do território do canal, 5 de temas vizinhos e 2 de ângulos novos no mesmo assunto",
                    "Misture continuação, tema vizinho, pedido e tendência, com 1 ou 2 ângulos novos."),
    "ousado": ("Ousado", "1 busca do território do canal, 4 de temas vizinhos e 5 de ângulos e temas que o canal nunca explorou "
                         "dentro do mesmo assunto",
               "Priorize a FRONTEIRA: ângulos novos e temas vizinhos que o canal nunca fez, mas que estão em alta no "
               "nicho. Continue no mesmo assunto e para o mesmo público; diferente não é aleatório."),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lang_code() -> str:
    name = research.channel_lang().lower()
    for code, (_hl, _gl, label) in ai.LANGUAGES.items():
        if label.lower()[:5] in name:
            return code
    return "pt"


def _fmt_n(x) -> str:
    return "?" if x is None else f"{x:,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Vídeos que modelei (a verdade sobre o canal)
# ---------------------------------------------------------------------------

def modeled(profile_id: int) -> list[dict]:
    return db.rows("SELECT * FROM modeled WHERE profile_id=? ORDER BY id DESC", (profile_id,))


def _video_info(video_id: str) -> dict:
    """Dados do vídeo original: do banco se o app já conhece, senão pela API (2 unidades de cota)."""
    v = analytics.video_detail(video_id)
    if v and v.get("title"):
        return {"title": v["title"], "channel_title": v["channel_title"], "views": v["views"], "subs": v["subs"],
                "multiplier": v["multiplier"], "lang": v["lang"], "published_at": v["published_at"],
                "description": (v.get("description") or "")[:600], "tags": v.get("tags") or "[]"}
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("Para adicionar por link, coloque a chave do YouTube em Configurações.")
    found = youtube_api.fetch_videos([video_id], key)
    if not found:
        raise RuntimeError("Não achei esse vídeo no YouTube. Confira o link.")
    f = found[0]
    ch = (youtube_api.fetch_channels([f["channel_id"]], key) or [{}])[0] if f.get("channel_id") else {}
    subs = ch.get("subs")
    return {"title": f["title"], "channel_title": f["channel_title"], "views": f["views"], "subs": subs,
            "multiplier": round(f["views"] / max(subs, 100), 2) if f["views"] is not None and subs is not None else None,
            "lang": f["lang"], "published_at": f["published_at"], "description": (f["description"] or "")[:600],
            "tags": json.dumps(f["tags"] or [], ensure_ascii=False)}


def modeled_add(profile_id: int, video_id: str | None, my_title: str | None = None) -> int:
    my_title = " ".join((my_title or "").split()) or None
    if not video_id and not my_title:
        raise ValueError("Cole o link do vídeo que você modelou (ou escreva o título que você usou).")
    if video_id:
        dup = db.row("SELECT id FROM modeled WHERE profile_id=? AND video_id=?", (profile_id, video_id))
        if dup:
            if my_title:
                with db.tx() as con:
                    con.execute("UPDATE modeled SET my_title=? WHERE id=?", (my_title, dup["id"]))
            return dup["id"]
        info = _video_info(video_id)
    else:
        info = {"title": None, "channel_title": None, "views": None, "subs": None, "multiplier": None, "lang": None,
                "published_at": None, "description": None, "tags": None}
    with db.tx() as con:
        return con.execute(
            """INSERT INTO modeled(profile_id, video_id, title, my_title, channel_title, views, subs, multiplier, lang,
               published_at, description, tags, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (profile_id, video_id, info["title"], my_title, info["channel_title"], info["views"], info["subs"],
             info["multiplier"], info["lang"], info["published_at"], info["description"], info["tags"], now_iso()),
        ).lastrowid


# ---------------------------------------------------------------------------
# Fila "vou fazer" (feito = vira modelado)
# ---------------------------------------------------------------------------

def queue(profile_id: int) -> list[dict]:
    return db.rows("SELECT * FROM queue WHERE profile_id=? AND status='planned' ORDER BY id DESC", (profile_id,))


def queue_add(profile_id: int, title: str, video_id: str | None = None, kind: str | None = None,
              note: str | None = None) -> int:
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("Escreva o título.")
    with db.tx() as con:
        dup = con.execute("SELECT id FROM queue WHERE profile_id=? AND status='planned' AND lower(title)=lower(?)",
                          (profile_id, title)).fetchone()
        if dup:
            return dup[0]
        return con.execute(
            "INSERT INTO queue(profile_id, title, status, video_id, kind, note, created_at, updated_at) "
            "VALUES(?,?, 'planned', ?,?,?,?,?)", (profile_id, title, video_id, kind, note, now_iso(), now_iso()),
        ).lastrowid


def queue_done(item_id: int) -> int:
    """Fiz o vídeo da fila: sai da fila e entra nos modelados (com o título que eu usei)."""
    q = db.row("SELECT * FROM queue WHERE id=?", (item_id,))
    if not q:
        raise ValueError("Item da fila não encontrado.")
    mid = modeled_add(q["profile_id"], q["video_id"], q["title"])
    with db.tx() as con:
        con.execute("DELETE FROM queue WHERE id=?", (item_id,))
    return mid


# ---------------------------------------------------------------------------
# DNA do canal
# ---------------------------------------------------------------------------

DNA_KIND = "dna:v1"

_DNA_SYSTEM = """Você é estrategista de canais dark do YouTube (sem rosto: narração sobre imagens, IA, animação).
Recebe a lista de vídeos que o editor JÁ MODELOU no canal dele (o vídeo original que ele usou de referência e, quando
houver, o título que ele usou). Isso é a VERDADE sobre o canal. Escreva o DNA do canal, curto e específico:
- summary: 1 a 2 frases: do que o canal fala e qual a pegada.
- themes: 3 a 8 temas que o canal cobre (curtos).
- formats: 1 a 4 formatos de vídeo (ex.: "lista de lições narrada", "história narrada de um caso").
- angles: 2 a 5 ângulos/ganchos que se repetem (ex.: "o que ninguém te conta", "filósofo antigo resolve problema moderno").
- audience: 1 frase: quem assiste e o que busca.
- title_style: 1 frase: como são os títulos (estrutura, tamanho, números, CAPS, emoção).
Tudo em português do Brasil, simples. Não invente o que os dados não mostram."""


class DNA(BaseModel):
    summary: str
    themes: list[str]
    formats: list[str]
    angles: list[str]
    audience: str
    title_style: str


def _modeled_sig(rows: list[dict]) -> str:
    return hashlib.sha1("|".join(sorted(f"{r['video_id']}:{r['my_title']}" for r in rows)).encode()).hexdigest()[:16]


def dna_get(profile_id: int) -> dict:
    rows = modeled(profile_id)
    d = db.row("SELECT * FROM channel_dna WHERE profile_id=?", (profile_id,))
    return {
        "dna": json.loads(d["result"]) if d and d["result"] else None,
        "notes": (d or {}).get("notes") or "",
        "updated_at": (d or {}).get("updated_at"),
        "stale": bool(rows) and (not d or not d["result"] or d["modeled_sig"] != _modeled_sig(rows)),
        "modeled": len(rows),
    }


def dna_build(profile_id: int) -> dict:
    rows = modeled(profile_id)[:DNA_MODELED]
    if not rows:
        raise RuntimeError("Adicione pelo menos um vídeo que você modelou.")
    p = db.row("SELECT niche FROM profiles WHERE id=?", (profile_id,)) or {}
    lines = [f"Nicho informado no perfil: {p.get('niche') or '-'}", "", "## Vídeos que o editor modelou"]
    for r in rows:
        lines.append(f"- Original: {r['title'] or '-'}" + (f" | título que o editor usou: {r['my_title']}" if r["my_title"] else "")
                     + (f" | canal: {r['channel_title']} | viralizou {r['multiplier']}x | idioma {r['lang'] or '?'}"
                        if r["title"] else ""))
        if r["description"]:
            lines.append(f"  Descrição: {' '.join(r['description'].split())[:200]}")
    notes = dna_get(profile_id)["notes"]
    if notes:
        lines += ["", f"## Correções do editor (valem como verdade): {notes}"]
    sig = _modeled_sig(modeled(profile_id))
    res = ai._run(DNA_KIND, f"profile:{profile_id}:{sig}:{hashlib.sha1(notes.encode()).hexdigest()[:8]}",
                  config.AI_MODEL_SMART, _DNA_SYSTEM, "\n".join(lines), DNA, max_tokens=1500, effort="low")
    res.pop("cached", None)
    with db.tx() as con:
        con.execute("""INSERT INTO channel_dna(profile_id, result, modeled_sig, notes, updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(profile_id) DO UPDATE SET result=excluded.result, modeled_sig=excluded.modeled_sig,
                       updated_at=excluded.updated_at""",
                    (profile_id, json.dumps(res, ensure_ascii=False), sig, notes, now_iso()))
    return dna_get(profile_id)


def dna_set_notes(profile_id: int, notes: str) -> dict:
    with db.tx() as con:
        con.execute("""INSERT INTO channel_dna(profile_id, notes, updated_at) VALUES(?,?,?)
                       ON CONFLICT(profile_id) DO UPDATE SET notes=excluded.notes, modeled_sig=NULL""",
                    (profile_id, (notes or "").strip(), now_iso()))
    return dna_get(profile_id)


def _dna_lines(profile_id: int) -> list[str]:
    d = dna_get(profile_id)
    out = []
    if d["dna"]:
        x = d["dna"]
        out += ["## DNA do canal (o que o canal é)", f"{x['summary']}", f"Temas: {', '.join(x['themes'])}",
                f"Formatos: {', '.join(x['formats'])}", f"Ângulos: {', '.join(x['angles'])}",
                f"Público: {x['audience']}", f"Estilo dos títulos: {x['title_style']}"]
    if d["notes"]:
        out.append(f"Correções do editor (VERDADE, vale mais que o resto): {d['notes']}")
    return out


# ---------------------------------------------------------------------------
# Contexto do canal para a rodada
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rodada v4: o PRÓXIMO a partir do que o editor modelou (vídeos reais, do nicho, viralizando)
# ---------------------------------------------------------------------------
# De onde vêm os candidatos (o que é "próximo" de verdade, não só "em alta no nicho"):
#   origem   - o que o canal de origem do vídeo modelado postou (a sequência dele; mostra se a fórmula rende)
#   a_seguir - o que o YouTube recomenda depois do vídeo modelado (o que o MESMO público assiste em seguida)
#   mesmo    - o que os canais que fizeram o MESMO vídeo (Método Malandro) postaram
#   assunto  - buscas amplas do assunto do vídeo modelado (no idioma dele e no do canal do editor)
# Filtros: só o nicho (juiz), nunca o MESMO vídeo de novo (juiz de "mesmo vídeo"), só canal dark (classificação),
# no máximo 2 por canal, e a régua do editor (período, views...). Se o período der pouca coisa, amplia (30, 90 dias)
# e marca. Ordem: views por hora (recente + muita view = melhor).

ANCHORS = 3              # vídeos modelados usados como ponto de partida (os mais recentes)
ORIGIN_UPLOADS = 30      # uploads do canal de origem (1 unidade de cota)
OTHER_CHANNELS = 6       # canais que fizeram o mesmo vídeo (Malandro) que têm os uploads lidos
OTHER_UPLOADS = 15
RELATED_PAGES = 2        # páginas de sugeridos do vídeo modelado (sem cota)
SEARCH_PAGES = 2
WIDEN_DAYS = (30, 90)    # ampliação do período quando a régua do editor traz pouca coisa
MIN_POOL = 12            # abaixo disso, amplia o período
PER_CHANNEL = 2          # no máximo N vídeos do mesmo canal (sem "vídeos idênticos do mesmo canal")
POOL = 30                # candidatos que a IA recebe para ordenar
VIA_LABEL = {"origem": "o canal de origem postou", "a_seguir": "o YouTube recomenda depois do seu vídeo",
             "mesmo": "quem fez o mesmo vídeo postou", "assunto": "busca do assunto"}

_NEXT_SYSTEM = """Você é o estrategista de conteúdo de um canal dark do YouTube (sem rosto: narração sobre imagens,
IA, animação). O editor MODELOU um vídeo e pergunta: "e agora, qual é o PRÓXIMO?". Você recebe o vídeo modelado
(a verdade) e uma tabela numerada de vídeos REAIS do mesmo nicho que estão viralizando, com números e DE ONDE vieram:
- "o canal de origem postou": a sequência do canal que o editor copiou (prova se a fórmula rende em outro tema);
- "o YouTube recomenda depois do seu vídeo": o que o mesmo público assiste em seguida;
- "quem fez o mesmo vídeo postou": o que os concorrentes fizeram depois;
- "busca do assunto": o que viraliza no assunto.

picks: escolha até {n} vídeos DA TABELA para o editor modelar em seguida, na ordem em que deve modelar.
- Prioridade: views por hora alto (recente + muita view), depois o que um canal dark replica fácil (premissa clara,
  canal pequeno), depois o encaixe com o vídeo modelado. Vídeo marcado "fora do período" só se valer muito a pena.
- {boldness}
- Varie: não escolha dois vídeos com a mesma premissa (salvo continuação clara).
- Para cada um: n (número na tabela), kind (continuacao = a mesma fórmula em outro tema/povo/caso; vizinho = outro
  assunto que o mesmo público assiste; tendencia = explodindo agora; angulo = ângulo novo no mesmo assunto; pedido =
  o público pede) e why (UMA frase simples: por que esse é o próximo, citando de onde veio e o número dele).
strategy: 2 frases: a lógica da sequência agora.
Português do Brasil, simples (o editor não é técnico). O editor NÃO vê a tabela: nunca cite "o vídeo 3" no texto."""


class NextPick(BaseModel):
    n: int
    kind: Literal["continuacao", "vizinho", "pedido", "tendencia", "angulo"]
    why: str


class NextList(BaseModel):
    picks: list[NextPick]
    strategy: str


_DUP_SYSTEM = """Você confere se vídeos são DUPLICATAS de vídeos que o editor já modelou. Recebe os vídeos modelados e uma
lista numerada de candidatos (n | título, em qualquer idioma).
Duplicata (d = 1) = conta a MESMA HISTÓRIA de um modelado: o mesmo grupo/pessoa/lugar E o mesmo acontecimento
(ex.: "Thousands of Amish are leaving their homes" e "Miles de amish están abandonando sus hogares" = duplicata).
NÃO é duplicata (d = 0): a mesma fórmula com OUTRO assunto (outro povo, país, grupo, objeto ou acontecimento: "rarámuris
abandonam a serra" não duplica "menonitas abandonam o México") e o mesmo grupo com outro acontecimento ("amish chegando
a uma cidade" não duplica "amish saindo de casa").
Liste SOMENTE as duplicatas: n = número."""


class Dup(BaseModel):
    n: int


class DupList(BaseModel):
    items: list[Dup]


def _duplicates(anchors: list[dict], items: list[tuple[str, str]], batch: int = 100) -> set[str]:
    """IDs que contam a mesma história de algum vídeo modelado (Haiku, resposta compacta, em lotes)."""
    if not items:
        return set()
    system = _DUP_SYSTEM + "\n\nVídeos modelados:\n" + "\n".join(f"- {a['title']}" for a in anchors)

    def one(part):
        user = "\n".join(f"{i} | {' '.join((t or '').split())[:120]}" for i, (_v, t) in enumerate(part, 1))
        res = ai._run("dup:v1", hashlib.sha1((system + user).encode()).hexdigest()[:20], config.AI_MODEL_FAST,
                      system, user, DupList, max_tokens=8 * len(part) + 150)
        return {part[x["n"] - 1][0] for x in res["items"] if 1 <= x["n"] <= len(part)}

    out: set[str] = set()
    with ThreadPoolExecutor(ai.AI_WORKERS) as tp:
        for d in tp.map(one, [items[i:i + batch] for i in range(0, len(items), batch)]):
            out |= d
    return out


def _ensure(ids: list[str], key: str) -> None:
    """Grava os vídeos que o app ainda não conhece e busca os números (1 unidade de cota a cada 50)."""
    if not ids:
        return
    with db.tx() as con:
        con.executemany("INSERT OR IGNORE INTO videos(video_id, first_seen_at) VALUES(?, ?)",
                        [(v, now_iso()) for v in ids])
    jobs.enrich(None, ids, key)


def _detail(ids: list[str]) -> dict[str, dict]:
    out = {}
    for vid in ids:
        v = analytics.video_detail(vid)
        if v and v.get("title") and not v.get("is_short") and not v.get("hidden"):
            if v.get("views_hour") is None:
                viral.add_metrics(v)
            out[vid] = v
    return out


def _niche_subject(profile_id: int, anchors: list[dict]) -> str:
    """O assunto do nicho: o do perfil; sem ele, os temas do DNA (tirados dos modelados); sem DNA, os temas dos modelados."""
    p = db.row("SELECT niche FROM profiles WHERE id=?", (profile_id,)) or {}
    if (p.get("niche") or "").strip():
        return p["niche"].strip()
    dna = dna_get(profile_id)["dna"]
    if dna and dna.get("themes"):
        return ", ".join(dna["themes"][:6])
    return ", ".join(dict.fromkeys(a["profile"]["theme"] for a in anchors))


def _anchors(profile_id: int, key: str) -> list[dict]:
    mods = [m for m in modeled(profile_id) if m["video_id"]][:ANCHORS]
    if not mods:
        raise RuntimeError("Adicione o link de um vídeo que você modelou (em \"Vídeos que modelei\"): "
                           "o próximo é achado a partir dele.")
    _ensure([m["video_id"] for m in mods], key)
    out = []
    for m in mods:
        v = analytics.video_detail(m["video_id"])
        if not v or not v.get("title"):
            continue
        tags = json.loads(v["tags"]) if isinstance(v.get("tags"), str) and v["tags"] else []
        lang = (v.get("lang") or "").split("-")[0].lower() or None
        prof = ai.seed_profile(v["video_id"], v["title"], v.get("channel_title") or "", v.get("description") or "",
                               tags, lang or "?")
        out.append({"video_id": v["video_id"], "title": v["title"], "my_title": m["my_title"],
                    "channel_id": v.get("channel_id"), "lang": lang, "profile": prof})
    if not out:
        raise RuntimeError("Não consegui ler os vídeos que você modelou (removidos ou privados?).")
    return out


def run(job: jobs.Job, profile_id: int, boldness: str) -> dict:
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("Precisa da chave do YouTube (Configurações).")
    if not ai.enabled():
        raise RuntimeError("Precisa da IA (Configurações).")
    from . import malandro
    boldness = boldness if boldness in BOLDNESS else "equilibrado"
    b_label, _mix, b_rule = BOLDNESS[boldness]
    spent0 = ai.usage()["cost_usd"]
    p = viral.get()
    my_lang = _lang_code()

    job.update(0.03, "Lendo os vídeos que você modelou...")
    if dna_get(profile_id)["stale"]:
        job.update(0.05, "Atualizando o DNA do canal com os vídeos que você modelou...")
        dna_build(profile_id)
    anchors = _anchors(profile_id, key)
    seen = {m["video_id"] for m in modeled(profile_id) if m["video_id"]} | \
        {x["video_id"] for x in queue(profile_id) if x["video_id"]}

    cand: dict[str, dict] = {}   # video_id -> {"title", "via": set, "anchor": video_id}

    def add(vid, title, via, anchor):
        if vid in seen:
            return
        c = cand.setdefault(vid, {"title": title, "via": set(), "anchor": anchor})
        c["via"].add(via)

    # Canais: origem (de cada vídeo modelado) e quem fez o mesmo vídeo (Malandro, se já rodou).
    job.update(0.1, "Lendo o que o canal de origem e os concorrentes postaram...")
    ch_tasks = [(a["channel_id"], ORIGIN_UPLOADS, "origem", a["video_id"]) for a in anchors if a.get("channel_id")]
    for a in anchors:
        mal = malandro.get(a["video_id"]) or {}
        others = []
        for l in mal.get("langs", []):
            others += [v.get("channel_id") for v in l.get("videos", []) if v.get("relevance", 0) >= 3]
        for chid in list(dict.fromkeys(c for c in others if c and c != a.get("channel_id")))[:OTHER_CHANNELS]:
            ch_tasks.append((chid, OTHER_UPLOADS, "mesmo", a["video_id"]))
    with ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        for (chid, n, via, anc), ups in zip(ch_tasks, pool.map(lambda t: youtube_api.fetch_uploads(t[0], key, t[1]), ch_tasks)):
            for vid, title in ups:
                add(vid, title, via, anc)

    # Sugeridos do vídeo modelado (como o público dele) + buscas amplas do assunto (idioma do vídeo e do editor).
    job.update(0.2, "Vendo o que o YouTube recomenda depois e buscando o assunto...")
    up = viral.upload_filter(max(WIDEN_DAYS))
    searches = []
    for a in anchors:
        hl, gl, _n = ai.LANGUAGES.get(a["lang"] or my_lang, ai.LANGUAGES[my_lang])
        for q in a["profile"]["queries"][:6]:
            searches.append((q, hl, gl, a["video_id"]))
        if a["lang"] != my_lang:
            mhl, mgl, _ = ai.LANGUAGES[my_lang]
            for q in ai.localize_queries(a["profile"]["queries"][:4], [my_lang]).get(my_lang, []):
                searches.append((q, mhl, mgl, a["video_id"]))
    with youtube_web.client() as c, ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        rel = list(pool.map(lambda a: youtube_web.related(c, a["video_id"], *ai.LANGUAGES.get(a["lang"] or my_lang, ai.LANGUAGES[my_lang])[:2],
                                                          pages=RELATED_PAGES), anchors))
        found = list(pool.map(lambda s: youtube_web.search(c, s[0], "views", up, s[1], s[2], pages=SEARCH_PAGES), searches))
    for a, (_info, items) in zip(anchors, rel):
        for vid, title in items:
            add(vid, title, "a_seguir", a["video_id"])
    for s, items in zip(searches, found):
        for vid, title in items:
            add(vid, title, "assunto", s[3])
    for a in anchors:
        cand.pop(a["video_id"], None)
    if job.stopped():
        raise RuntimeError("Cancelado.")
    if not cand:
        raise RuntimeError("O YouTube não devolveu nada agora. Tente de novo em instantes.")

    # Números primeiro (barato): o que nem chega perto da régua sai antes de gastar IA.
    job.update(0.35, f"Buscando os números de {len(cand)} vídeos...")
    _ensure(list(cand), key)
    det = _detail(list(cand))
    wide = p | {"max_days": max(WIDEN_DAYS), "only_dark": False}
    alive = [vid for vid, v in det.items() if viral.passes(v, wide)]
    if job.stopped():
        raise RuntimeError("Cancelado.")

    # Juízes: nunca o MESMO vídeo de novo; só o nicho (o mesmo público, outro assunto vale).
    job.update(0.5, f"IA tirando o que é o mesmo vídeo e o que foge do nicho ({len(alive)})...")
    # Sai só a DUPLICATA (a mesma história de um vídeo já modelado). A mesma fórmula com outro assunto fica: é o próximo.
    same = _duplicates(anchors, [(vid, det[vid]["title"]) for vid in alive])
    # O nicho é o ASSUNTO (mesmo critério do Descobrir): qualquer vídeo cujo assunto principal é o nicho vale nota 2.
    crit = research.niche_topic(_niche_subject(profile_id, anchors), [a["title"] for a in anchors])
    notes = ai.judge_relevance(crit, [(vid, det[vid]["title"], f"{(det[vid].get('channel_title') or '?')[:40]} | "
                                       f"{round((det[vid].get('duration_s') or 0) / 60)} min")
                                      for vid in alive if vid not in same])
    keep = [vid for vid in alive if vid not in same and notes.get(vid, 0) >= 2]

    # Só dark de verdade: classifica os canais que ainda não foram olhados e aplica a régua completa.
    job.update(0.65, "Conferindo quais canais são dark...")
    if keep:
        jobs.classify_new_channels(video_ids=keep)
    det = _detail(keep)

    def pick(max_days):
        rule = p | {"max_days": max_days}
        ok = viral.rank([v for v in det.values() if viral.passes(v, rule)], rule)
        out, per = [], {}
        for v in ok:
            ch = v.get("channel_id") or v["video_id"]
            if per.get(ch, 0) < PER_CHANNEL:
                per[ch] = per.get(ch, 0) + 1
                out.append(v)
        return out

    days = p["max_days"]
    pool_v = pick(days)
    for wd in WIDEN_DAYS:
        if len(pool_v) >= MIN_POOL or wd <= days:
            continue
        days = wd
        pool_v = pick(wd)
    pool_v = pool_v[:POOL]
    if not pool_v:
        raise RuntimeError(f"Nada do nicho viralizando nem em {max(WIDEN_DAYS)} dias ({viral.describe()}). "
                           "Afrouxe os parâmetros em Configurações.")

    def card(v):
        c = cand[v["video_id"]]
        age = v.get("age_days") if v.get("age_days") is not None else (v.get("age_hours") or 0) / 24
        return {"video_id": v["video_id"], "title": v["title"], "channel_id": v.get("channel_id"),
                "channel_title": v.get("channel_title"), "lang": (v.get("lang") or "").split("-")[0] or None,
                "views": v.get("views"), "subs": v.get("subs"), "multiplier": v.get("multiplier"),
                "views_hour": v.get("views_hour"), "age_days": round(age, 1), "age_hours": v.get("age_hours"),
                "via": sorted(c["via"]), "anchor": c["anchor"], "widened": age > p["max_days"]}

    cards = [card(v) for v in pool_v]
    job.update(0.8, "IA escolhendo a ordem dos próximos vídeos...")
    anchor_txt = "\n".join(f"- \"{a['title']}\"" + (f" (o editor publicou como \"{a['my_title']}\")" if a["my_title"] else "")
                           + f" — {a['profile']['topic']}" for a in anchors)
    table = ["(n | título | idioma | views por hora | views | viralizou | dias | canal | de onde veio)"]
    table += [f"{i} | {c['title']} | {c['lang'] or '?'} | {_fmt_n(c['views_hour'])} | {_fmt_n(c['views'])} | "
              f"{c['multiplier']}x | {c['age_days']}{' (fora do período)' if c['widened'] else ''} | {c['channel_title']} | "
              f"{', '.join(VIA_LABEL[x] for x in c['via'])}" for i, c in enumerate(cards, 1)]
    res = ai._run("next:v4", f"run:{now_iso()}:{profile_id}", config.AI_MODEL_SMART,
                  _NEXT_SYSTEM.format(n=min(10, len(cards)), boldness=f"Ousadia pedida: {b_label}. {b_rule}"),
                  "## Vídeos que o editor modelou\n" + anchor_txt + "\n\n## Candidatos\n" + "\n".join(table),
                  NextList, max_tokens=4000, effort="low", timeout=180)

    items, used = [], set()
    for pk in res["picks"]:
        if 1 <= pk["n"] <= len(cards) and pk["n"] not in used:
            used.add(pk["n"])
            items.append(cards[pk["n"] - 1] | {"kind": pk["kind"], "why": pk["why"]})
    # Ordem do editor: o mais recente e mais visto primeiro (views por hora); os de dentro do período antes.
    items.sort(key=lambda it: (it["widened"], -(it.get("views_hour") or 0)))
    result = {
        "version": 4, "profile_id": profile_id, "boldness": boldness,
        "niche": " / ".join(a["profile"]["topic"] for a in anchors),
        "anchors": [{"video_id": a["video_id"], "title": a["title"]} for a in anchors],
        "params": viral.describe(), "days_used": days, "widened": days > p["max_days"],
        "funnel": {"candidates": len(cand), "in_range": len(alive), "same_video": len(same), "niche": len(keep),
                   "final": len(cards)},
        "strategy": res["strategy"], "territories": [], "items": items, "pool": cards,
        "created_at": now_iso(), "cost_usd": round(ai.usage()["cost_usd"] - spent0, 4),
    }
    with db.tx() as con:
        run_id = con.execute("INSERT INTO next_runs(profile_id, anchor_video_id, result, created_at) VALUES(?,?,?,?)",
                             (profile_id, anchors[0]["video_id"], json.dumps(result, ensure_ascii=False),
                              result["created_at"])).lastrowid
    job.update(1.0, f"{len(items)} vídeos para modelar em seguida")
    return {"next_id": run_id, "note": f"{len(items)} vídeos reais para modelar em seguida"
                                       + (f" (ampliei para {days} dias: nos seus {p['max_days']} dias veio pouca coisa)."
                                          if result["widened"] else ".")}


def runs(profile_id: int) -> list[dict]:
    out = []
    for r in db.rows("SELECT id, result, created_at FROM next_runs WHERE profile_id=? ORDER BY id DESC LIMIT 30",
                     (profile_id,)):
        res = json.loads(r["result"])
        out.append({"id": r["id"], "created_at": r["created_at"], "boldness": res.get("boldness"),
                    "items": len(res.get("items") or [])})
    return out


def get(run_id: int) -> dict | None:
    r = db.row("SELECT id, result FROM next_runs WHERE id=?", (run_id,))
    if not r:
        return None
    res = json.loads(r["result"]) | {"id": r["id"]}
    res.setdefault("territories", [])   # rodadas antigas (antes do mapa)
    return res
