"""Meu canal: "modelei esse, e agora?". O lado do APÓS (Descobertas é o lado certo, de onde partir).

- Vídeos que modelei: a VERDADE sobre o canal do editor (por link, ou "Já modelei" em Descobertas e na prévia).
  Não precisa logar na conta do canal (o editor usa proxy nos canais): tudo sai do perfil e dessa lista.
- DNA do canal: a IA lê os modelados e escreve do que o canal fala (temas, formatos, ângulos, público, estilo dos
  títulos). O editor pode corrigir; a correção vale como verdade. Fica guardado e só é refeito quando a lista muda.
- Rodada de sugestões: busca o que está em alta AGORA no nicho, a IA filtra o que o público do canal assistiria,
  agrupa em territórios (seu território / fronteira / saturado) e sugere os próximos vídeos com uma "ousadia"
  (perto, equilibrado, ousado). Evita o que já está em Descobertas (lá é o seguro; aqui é o "e depois").
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from . import ai, analytics, config, db, jobs, research, youtube_api, youtube_web

QUERIES = 10            # buscas que a IA monta
SEARCHES = [("data", "semana"), ("views", "mes")]   # cada busca: os mais novos da semana + os mais vistos do mês
MAX_JUDGE = 400         # títulos que o juiz avalia
MAX_NUMBERS = 200       # vídeos que têm os números buscados (4 unidades de cota)
MAX_AGE_DAYS = 90       # "em alta agora": só o que foi postado nos últimos 3 meses
POOL = 40               # vídeos em alta que o Sonnet recebe (para o mapa e as sugestões)
SUGGESTIONS = 8
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

def _context(profile_id: int) -> tuple[list[str], set[str], set[str]]:
    """Linhas de contexto + IDs que não podem voltar (modelados e fila) + IDs de Descobertas (o lado seguro)."""
    p = db.row("SELECT * FROM profiles WHERE id=?", (profile_id,))
    if not p:
        raise RuntimeError("Perfil não encontrado.")
    lines = [f"# Canal do editor (perfil \"{p['name']}\")", f"Nicho: {p['niche'] or '(não definido)'}",
             f"Idioma do canal: {research.channel_lang()}", ""]
    lines += _dna_lines(profile_id)

    mods = modeled(profile_id)
    seen = {m["video_id"] for m in mods if m["video_id"]}
    if mods:
        lines += ["", "## Vídeos que o editor JÁ MODELOU (verdade; não repetir, dá para continuar a sequência)"]
        lines += [f"- {m['my_title'] or m['title']}" + (f" (original: {m['title']})" if m["my_title"] and m["title"] else "")
                  for m in mods[:30]]
    q = queue(profile_id)
    if q:
        lines += ["", "## Vídeos que o editor JÁ VAI FAZER (não repetir)"] + [f"- {x['title']}" for x in q[:25]]
    seen |= {x["video_id"] for x in q if x["video_id"]}

    disc = [v for v in analytics.videos(profile_id) if v["is_dark"] and v["multiplier"] is not None]
    disc_ids = {v["video_id"] for v in disc}
    best = sorted(disc, key=lambda v: -(analytics.opportunity(v) or 0))[:15]
    if best:
        lines += ["", "## Já está em DESCOBERTAS (o lado seguro, já provado; NÃO sugira esses de novo, use como prova)"]
        lines += [f"- {v['title']} ({v['multiplier']}x, há {round(v['age_days'] or 0)} dias)" for v in best]

    rs = db.rows("SELECT id, label, topic FROM research WHERE profile_id=? AND status<>'error' ORDER BY id DESC LIMIT 8",
                 (profile_id,))
    if rs:
        lines += ["", "## O que o editor pesquisou"]
        for r in rs:
            t = json.loads(r["topic"]) if r.get("topic") else None
            lines.append(f"- {r['label']}" + (f" (tema: {t['theme']})" if t else ""))

    cms = db.rows("""SELECT cm.text, cm.likes FROM comments cm
                     JOIN research_videos rv ON rv.video_id = cm.video_id
                     JOIN research r ON r.id = rv.research_id
                     WHERE r.profile_id = ? GROUP BY cm.comment_id ORDER BY cm.likes DESC LIMIT 15""", (profile_id,))
    if cms:
        lines += ["", "## Comentários mais curtidos do público do nicho"]
        lines += [f"- ({c['likes']}) {' '.join(c['text'].split())[:180]}" for c in cms]

    if not (p["niche"] or mods or q or best or rs):
        raise RuntimeError("Ainda não sei do que o seu canal fala. Adicione os vídeos que você já modelou "
                           "(ou defina o nicho do perfil).")
    return lines, seen, disc_ids


# ---------------------------------------------------------------------------
# IA: plano de buscas (Haiku) e mapa + sugestões (Sonnet)
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """Você é estrategista de canais dark do YouTube (sem rosto: narração sobre imagens, IA, animação).
Recebe o que se sabe do canal do editor (o DNA e os vídeos que ele já modelou são a verdade). Responda:
- niche: 1 a 2 frases descrevendo o NICHO e o PÚBLICO do canal. Vai servir de critério para julgar se um vídeo serve
  para esse canal. Seja específico, mas inclua os temas vizinhos que o mesmo público assiste.
- queries: {n} buscas curtas (2 a 6 palavras) no idioma {lang}, como o público pesquisaria, para achar o que está em
  alta AGORA. Distribuição: {mix}. Não repita temas que o editor já fez."""


class NextPlan(BaseModel):
    niche: str
    queries: list[str]


_NEXT_SYSTEM = """Você é o estrategista de conteúdo de um canal dark do YouTube. O editor pergunta: "modelei esses
vídeos, e agora?". Você recebe a verdade sobre o canal (DNA, vídeos que ele já modelou, fila) e uma tabela numerada de
vídeos EM ALTA AGORA no nicho, com números reais. O que já está em Descobertas é o lado seguro e já conhecido: aqui o
valor é mostrar o PRÓXIMO PASSO e o que é DIFERENTE, sempre no mesmo assunto e para o mesmo público.

1) territories: agrupe os vídeos em alta em 5 a 8 territórios (assuntos/ângulos). Para cada um:
   name (curto), status ("seu" = o canal já faz isso; "fronteira" = vizinho do que o canal faz, em alta, e o canal
   NUNCA fez; "saturado" = muitos canais fazendo, difícil entrar), heat ("alta", "media" ou "baixa", pelo quanto os
   vídeos viralizaram e são recentes), why (uma frase simples) e refs (números da tabela, 1 a 4).
2) items: {n} próximos vídeos. {boldness} Para cada um: title (no idioma {lang}, modelando a estrutura dos que
   viralizaram, sem copiar), kind (continuacao, vizinho, pedido, tendencia ou angulo = ângulo novo no mesmo assunto),
   territory (o name do território), why (uma frase com o motivo e o dado), refs (números da tabela que comprovam),
   chance (0 a 100, honesta: sem evidência forte, no máximo 60) e hook (o gancho da primeira frase, no idioma {lang}).
   Ordem = o que fazer primeiro. Não repita nada que o editor já modelou ou vai fazer, nem o que já está em Descobertas.
3) strategy: 2 a 3 frases: a lógica da sequência agora.
why, strategy e nomes de território em português do Brasil, curtos e simples (o editor não é técnico).
IMPORTANTE: o editor NÃO vê a tabela. Nunca cite os números da tabela no texto (nada de "o vídeo 2", "o 5" ou
"(21, 25)"): fale do vídeo pelo assunto e pelos números dele (ex.: "um vídeo sobre calma fez 25x em 3 dias").
Os números da tabela vão SÓ no campo refs."""


class Territory(BaseModel):
    name: str
    status: Literal["seu", "fronteira", "saturado"]
    heat: Literal["alta", "media", "baixa"]
    why: str
    refs: list[int]


class NextItem(BaseModel):
    title: str
    kind: Literal["continuacao", "vizinho", "pedido", "tendencia", "angulo"]
    territory: str
    why: str
    refs: list[int]
    chance: int
    hook: str


class NextList(BaseModel):
    territories: list[Territory]
    items: list[NextItem]
    strategy: str


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------

def _cards(ids: list[str], key: str) -> list[dict]:
    vids = youtube_api.fetch_videos(ids, key)
    chans = {c["channel_id"]: c for c in youtube_api.fetch_channels(
        list({v["channel_id"] for v in vids if v.get("channel_id")}), key)}
    out = []
    for v in vids:
        if (v.get("duration_s") or 0) <= config.SHORT_MAX_SECONDS:
            continue  # shorts ficam de fora de tudo
        ch = chans.get(v.get("channel_id")) or {}
        age = analytics._age_days(v.get("published_at"))
        c = {"video_id": v["video_id"], "title": v["title"], "channel_id": v.get("channel_id"),
             "channel_title": v.get("channel_title"), "views": v.get("views"), "subs": ch.get("subs"),
             "lang": (v.get("lang") or "").split("-")[0] or None, "age_days": round(age, 1) if age else None}
        c["views_day"] = round(c["views"] / max(age, 1)) if c["views"] is not None and age else None
        c["multiplier"] = round(c["views"] / max(c["subs"], 100), 2) if c["views"] is not None and c["subs"] is not None else None
        c["score"] = analytics.opportunity(c)
        if c["age_days"] is not None and c["age_days"] <= MAX_AGE_DAYS and analytics.has_potential(c):
            out.append(c)
    return sorted(out, key=lambda c: -(c["score"] or 0))


def run(job: jobs.Job, profile_id: int, boldness: str) -> dict:
    key = jobs.youtube_api_key()
    if not key:
        raise RuntimeError("Precisa da chave do YouTube (Configurações).")
    if not ai.enabled():
        raise RuntimeError("Precisa da IA (Configurações).")
    boldness = boldness if boldness in BOLDNESS else "equilibrado"
    b_label, b_mix, b_rule = BOLDNESS[boldness]
    spent0 = ai.usage()["cost_usd"]
    lang = _lang_code()
    hl, gl, lang_name = ai.LANGUAGES[lang]

    job.update(0.03, "Entendendo o seu canal...")
    if dna_get(profile_id)["stale"]:
        job.update(0.05, "Atualizando o DNA do canal com os vídeos que você modelou...")
        dna_build(profile_id)
    ctx, seen, disc_ids = _context(profile_id)
    plan = ai._run("next-plan:v2", f"run:{now_iso()}:{profile_id}", config.AI_MODEL_FAST,
                   _PLAN_SYSTEM.format(n=QUERIES, lang=lang_name, mix=b_mix), "\n".join(ctx), NextPlan, max_tokens=800)

    job.update(0.15, f"Procurando o que está em alta agora ({len(plan['queries'])} buscas)...")
    tasks = [(q, s, u) for q in plan["queries"][:QUERIES] for s, u in SEARCHES]
    found: dict[str, str] = {}
    with youtube_web.client() as c, ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        for res in pool.map(lambda t: youtube_web.search(c, t[0], t[1], t[2], hl, gl), tasks):
            for vid, title in res:
                if vid not in seen and vid not in disc_ids:
                    found.setdefault(vid, title)
    if job.stopped():
        raise RuntimeError("Cancelado.")
    if not found:
        raise RuntimeError("O YouTube não devolveu resultados agora. Tente de novo em instantes.")

    job.update(0.4, f"IA separando o que o seu público assistiria ({len(found)} vídeos)...")
    items = list(found.items())[:MAX_JUDGE]
    notes = ai.judge_relevance(f"vídeos que o público deste canal assistiria. {plan['niche']}", items)
    keep = [vid for vid, _ in items if notes.get(vid, 0) >= 2]
    if job.stopped():
        raise RuntimeError("Cancelado.")

    job.update(0.6, f"Buscando os números de {min(len(keep), MAX_NUMBERS)} vídeos...")
    pool_cards = _cards(keep[:MAX_NUMBERS], key)[:POOL]
    if not pool_cards:
        raise RuntimeError("Não achei vídeos recentes viralizando nesse nicho agora. Tente outra ousadia ou adicione "
                           "mais vídeos modelados.")

    job.update(0.75, "IA montando o mapa e os próximos vídeos (uns 40 segundos)...")
    table = ["", "## Vídeos em alta agora no nicho (n | título | idioma | viralizou | views | dias desde que postou | canal)"]
    table += [f"{i} | {c['title']} | {c['lang'] or '?'} | {c['multiplier']}x | {_fmt_n(c['views'])} | "
              f"{round(c['age_days'] or 0)} | {c['channel_title']}" for i, c in enumerate(pool_cards, 1)]
    res = ai._run("next:v2", f"run:{now_iso()}:{profile_id}", config.AI_MODEL_SMART,
                  _NEXT_SYSTEM.format(n=SUGGESTIONS, lang=lang_name, boldness=f"Ousadia pedida: {b_label}. {b_rule}"),
                  "\n".join(ctx + table), NextList, max_tokens=8000, effort="low", timeout=240)

    def refs(ns):
        return [pool_cards[n - 1] for n in ns if 1 <= n <= len(pool_cards)]

    for t in res["territories"]:
        t["refs"] = refs(t["refs"])
    for it in res["items"]:
        it["refs"] = refs(it["refs"])
        it["chance"] = max(0, min(100, it["chance"]))
    result = {
        "profile_id": profile_id, "boldness": boldness, "niche": plan["niche"], "queries": plan["queries"],
        "strategy": res["strategy"], "territories": res["territories"], "items": res["items"], "pool": pool_cards,
        "created_at": now_iso(), "cost_usd": round(ai.usage()["cost_usd"] - spent0, 4),
    }
    with db.tx() as con:
        run_id = con.execute("INSERT INTO next_runs(profile_id, anchor_video_id, result, created_at) VALUES(?,?,?,?)",
                             (profile_id, None, json.dumps(result, ensure_ascii=False), result["created_at"])).lastrowid
    job.update(1.0, f"{len(res['items'])} próximos vídeos sugeridos")
    return {"next_id": run_id, "note": f"{len(res['items'])} próximos vídeos e {len(res['territories'])} territórios."}


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
