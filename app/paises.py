"""Método Malandro + países: onde o público PROCURA esse conteúdo e ainda não tem quem faça.

O Malandro diz a OFERTA por língua (quantos canais já fizeram este vídeo). Aqui entra a PROCURA, país por país, com
dados (sem achismo):
- buscas (por PAÍS): o que o YouTube daquele país completa quando alguém começa a digitar os termos do tema
  (autocompletar da busca, o mesmo do site; muita sugestão = muita gente buscando; termo sem sugestão é encurtado);
- vídeos do tema no último mês (por IDIOMA: a busca do YouTube dá o mesmo resultado em países da mesma língua):
  quantos ganharam tração (30+ views por hora) e as views por hora típicas dos 10 melhores.
O resultado é por MERCADO (idioma, com os países dele e as buscas de cada país). Só contam os vídeos que são mesmo
daquele idioma (a busca em hindi, por exemplo, devolve muito vídeo em inglês).
Procura em número ABSOLUTO (não relativa: um mercado fraco não vira "alta" só por ser o menos fraco): vídeos do nicho
com tração no último mês e views por hora típicas. O autocompletar não entra na nota (qualquer palavra comum enche as
10 sugestões); ele só mostra O QUE se busca em cada país. O idioma do vídeo original não é oportunidade (já existe lá).
Nota de oportunidade = procura × oferta (livre 1, pouco explorada 0,6, saturada 0,25). A IA (modelo rápido) só escreve,
para os mercados com procura, o porquê e o que adaptar.
O resultado fica junto do Malandro do vídeo (refazer o Malandro apaga, porque a oferta mudou).
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import median

from . import ai, config, db, jobs, malandro, research, viral, youtube_api, youtube_web

# (país, idioma do radar, nome). Um idioma pode valer para vários países: a procura muda de país para país.
COUNTRIES = [
    ("BR", "pt", "Brasil"), ("PT", "pt", "Portugal"),
    ("US", "en", "Estados Unidos"), ("GB", "en", "Reino Unido"), ("CA", "en", "Canadá"), ("AU", "en", "Austrália"),
    ("IN", "en", "Índia (inglês)"), ("PH", "en", "Filipinas"), ("NG", "en", "Nigéria"),
    ("MX", "es", "México"), ("ES", "es", "Espanha"), ("AR", "es", "Argentina"), ("CO", "es", "Colômbia"),
    ("FR", "fr", "França"), ("DE", "de", "Alemanha"), ("IT", "it", "Itália"),
    ("IN", "hi", "Índia (hindi)"), ("ID", "id", "Indonésia"), ("JP", "ja", "Japão"), ("KR", "ko", "Coreia do Sul"),
    ("RU", "ru", "Rússia"), ("SA", "ar", "Arábia Saudita"), ("EG", "ar", "Egito"), ("TR", "tr", "Turquia"),
]
SUPPLY_FACTOR = {"livre": 1.0, "pouca": 0.6, "saturada": 0.25}
TRACTION_VPH = 30      # vídeo do tema "ganhando views" no país
AI_COUNTRIES = 8       # países que recebem o porquê e o que adaptar


def _in_lang(v: dict, lang: str) -> bool:
    """O vídeo é mesmo desse idioma? Pela língua que o canal informa; sem ela, pelo alfabeto do título."""
    api = (v.get("lang") or "").split("-")[0].lower()
    if api:
        return api == lang
    title = v.get("title") or ""
    if lang in malandro._SCRIPTS:
        return bool(malandro._SCRIPTS[lang].search(title))
    return not any(rx.search(title) for rx in malandro._SCRIPTS.values())   # idioma latino: sem outro alfabeto


def _countries_txt(market: dict) -> str:
    return ", ".join(x["name"] + ("" if x["auto"] else " (o YouTube não completa nada)") for x in market["countries"])


def _vph(m: dict) -> float:
    h = viral.hours_since(m.get("published_at")) or 0
    return (m.get("views") or 0) / max(h, 1)


def run(job: jobs.Job, video_id: str) -> dict:
    m = malandro.get(video_id)
    if not m:
        raise RuntimeError("Rode o Método Malandro neste vídeo antes (ele mede quem já fez em cada língua).")
    key = jobs.youtube_api_key()
    if not key or not ai.enabled():
        raise RuntimeError("Precisa da chave do YouTube e da IA (Configurações).")
    spent0 = ai.usage()["cost_usd"]
    by_lang = {l["code"]: l for l in m["langs"]}
    langs = sorted({lang for _c, lang, _n in COUNTRIES})

    job.update(0.05, "IA escrevendo os termos de busca do tema em cada idioma...")
    terms = ai.country_terms(video_id, m["title"], m.get("topic") or "", langs)

    # Por país: o autocompletar de cada termo. Por idioma: os vídeos do tema no último mês (os mais vistos).
    auto_tasks = [(i, t) for i, (_c, lang, _n) in enumerate(COUNTRIES) for t in terms.get(lang, [])]
    theme_tasks = [(lang, t) for lang in langs for t in terms.get(lang, [])[:2]]

    job.update(0.15, f"Medindo a procura em {len(COUNTRIES)} países (buscas e vídeos do último mês)...")
    with youtube_web.client() as c, ThreadPoolExecutor(youtube_web.WORKERS) as pool:
        def suggest(task):
            """Autocompletar; sem sugestão, tenta de novo com o termo mais curto (o começo do que se digita)."""
            i, term = task
            country, lang, _n = COUNTRIES[i]
            words = term.split()
            for n in range(len(words), 0, -1):
                part = " ".join(words[:n])
                if n < len(words) and len(part) < 4:
                    break
                res = youtube_web.suggest(c, part, ai.LANGUAGES[lang][0], country)
                if res:
                    return res
            return []

        def theme(task):
            lang, term = task
            hl, gl, _n = ai.LANGUAGES[lang]
            return lang, youtube_web.search(c, term, "views", "mes", hl, gl, pages=2)

        auto_res = list(pool.map(suggest, auto_tasks))
        if job.stopped():
            raise RuntimeError("Cancelado.")
        theme_res = list(pool.map(theme, theme_tasks))
    if job.stopped():
        raise RuntimeError("Cancelado.")

    suggestions: dict[int, list[str]] = {}
    for (i, _t), res in zip(auto_tasks, auto_res):
        suggestions.setdefault(i, [])
        suggestions[i] += [s for s in res if s not in suggestions[i]]
    by_lang_ids: dict[str, list[str]] = {}
    for lang, res in theme_res:
        by_lang_ids.setdefault(lang, [])
        by_lang_ids[lang] += [v for v, _t in res if v not in by_lang_ids[lang]]

    job.update(0.55, "Buscando os números dos vídeos do tema...")
    ids = list(dict.fromkeys(v for lst in by_lang_ids.values() for v in lst))
    meta = {v["video_id"]: v for v in youtube_api.fetch_videos(ids, key)}

    # Só conta o que é do NICHO: tira o infantil (marcado pelo YouTube) e passa o resto pelo juiz de relevância
    # (termos amplos como "tratores" puxam desenho, música e gameplay, que inflariam a procura).
    cand = [v for lst in by_lang_ids.values() for v in lst if v != video_id   # o próprio vídeo não é "procura"
            and v in meta and not meta[v].get("kids") and (meta[v].get("duration_s") or 0) > config.SHORT_MAX_SECONDS]
    cand = list(dict.fromkeys(cand))
    job.update(0.62, f"IA separando os vídeos do tema que são do nicho ({len(cand)})...")
    notes_rel = ai.judge_relevance(
        f"vídeos que o MESMO público deste vídeo assistiria: {m.get('topic') or m['title']}. Nota 2 = mesmo nicho "
        f"(outro assunto vale); desenho, infantil, música, gameplay e brinquedo = 0.",
        [(v, meta[v]["title"], f"{(meta[v].get('channel_title') or '?')[:40]} | {round((meta[v].get('duration_s') or 0) / 60)} min")
         for v in cand]) if cand else {}
    niche = {v for v in cand if notes_rel.get(v, 0) >= 2}

    markets = []
    for lang in langs:
        vids = [meta[v] for v in by_lang_ids.get(lang, []) if v in niche and _in_lang(meta[v], lang)]
        speeds = sorted((_vph(v) for v in vids), reverse=True)
        best = max(vids, key=_vph) if vids else None
        sup = by_lang.get(lang) or {}
        # Ordem fixa por tamanho do mercado (a da lista COUNTRIES): quem tem buscas primeiro, mas sem reordenar pelo
        # número de sugestões (isso punha a Nigéria na frente dos EUA).
        countries = sorted([{"country": cc, "name": nm, "auto": len(suggestions.get(i, [])),
                             "suggestions": suggestions.get(i, [])[:8], "_i": i}
                            for i, (cc, lg, nm) in enumerate(COUNTRIES) if lg == lang],
                           key=lambda x: (x["auto"] == 0, x["_i"]))
        for x in countries:
            x.pop("_i")
        markets.append({
            "lang": lang, "lang_name": ai.LANGUAGES[lang][2], "countries": countries,
            "auto": max((x["auto"] for x in countries), default=0),
            "traction": sum(1 for x in speeds if x >= TRACTION_VPH), "videos": len(vids),
            # poucos vídeos não viram "procura alta": a mediana é ponderada pela quantidade (até 5)
            "vph_typical": round(median(speeds[:10]) * min(len(speeds), 5) / 5) if speeds else 0,
            "best": {"video_id": best["video_id"], "title": best["title"], "vph": round(_vph(best)),
                     "views": best.get("views")} if best else None,
            "status": sup.get("status", "livre"), "channels": sup.get("channels", 0),
            "title": sup.get("suggested_title"), "original": bool(sup.get("original")), "terms": terms.get(lang, []),
            "original_dub": bool(sup.get("original_dub")),
        })

    # Procura ABSOLUTA (0 a 1): views por hora típicas (1.000/h = teto) e vídeos do nicho com tração (15 = teto).
    for r in markets:
        d = 0.55 * min(1.0, math.log1p(r["vph_typical"]) / math.log1p(1000)) + 0.45 * min(1.0, r["traction"] / 15)
        r["demand"] = round(d, 2)
        r["level"] = "alta" if d >= 0.6 else "media" if d >= 0.35 else "baixa"
        # Não é oportunidade: o idioma do original e o idioma saturado (3+ canais já fizeram NATIVO).
        # A dublagem do original não conta (regra do editor: só vale quem fez o vídeo nativo na língua).
        r["covered"] = r["original"]
        r["score"] = 0.0 if r["covered"] or r["status"] == "saturada" else round(d * SUPPLY_FACTOR.get(r["status"], 0.6), 3)
    markets.sort(key=lambda r: (r["covered"], -r["score"]))

    job.update(0.75, "IA lendo os números e escrevendo onde vale a pena...")
    top = [r for r in markets if r["score"] > 0 and r["level"] != "baixa"][:AI_COUNTRIES]
    table = ["Mercado (código do idioma | idioma | procura 0-1 (absoluta) | países | vídeos do nicho NESSE IDIOMA com "
             "tração no último mês | views/h típicas | oferta: quem já fez este vídeo nesse idioma | nota de oportunidade | "
             "o que buscam no país líder)"]
    table += [f"{r['lang']} | {r['lang_name']} | {r['demand']} | "
              f"{_countries_txt(r)} | {r['traction']} de {r['videos']} | "
              f"{r['vph_typical']} | {r['status']} ({r['channels']} canais)"
              f"{' (IDIOMA DO ORIGINAL: não é oportunidade)' if r['original'] else ''}"
              f"{' (o original tem dublagem automática nesse idioma; não conta como oferta)' if r['original_dub'] else ''} | "
              f"{r['score']} | {'; '.join(r['countries'][0]['suggestions'][:5]) if r['countries'] else '-'}"
              for r in markets]
    cms = research.top_comments(video_id, 30)
    text = "\n".join([f"Vídeo: {m['title']}", f"Tema: {m.get('topic') or '-'}", "", *table, "",
                      "Analise estes: " + ", ".join(r["lang"] for r in top), "",
                      "Comentários do vídeo original (mais curtidos):",
                      *[f"- {' '.join(c['text'].split())[:160]}" for c in cms]])
    rep = ai.countries_report(video_id, text) if top else {
        "summary": "Nenhum idioma tem procura por esse tema E está livre ao mesmo tempo: onde há procura, o vídeo já "
                   "existe (no original ou feito por 3+ canais); onde está livre, quase ninguém assiste esse tema "
                   "no último mês. Vale mais modelar onde ele já provou que viraliza.",
        "notes": [], "comment_signals": ""}
    notes = {n["c"]: n for n in rep["notes"]}
    for r in markets:
        if r["lang"] in notes:
            r["why"], r["adapt"] = notes[r["lang"]]["why"], notes[r["lang"]]["adapt"]

    m["paises"] = {"markets": markets, "summary": rep["summary"], "comment_signals": rep["comment_signals"],
                   "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "cost_usd": round(ai.usage()["cost_usd"] - spent0, 4)}
    with db.tx() as con:
        con.execute("UPDATE malandro SET result=? WHERE video_id=?", (json.dumps(m, ensure_ascii=False), video_id))
    best = [r["countries"][0]["name"] if len(r["countries"]) == 1 else r["lang_name"] for r in top[:3]]
    job.update(1.0, "Países prontos" + (f": {', '.join(best)}" if best else ""))
    return {"video_id": video_id, "note": "Onde há procura e ninguém faz: " + (", ".join(best) or "nenhum outro idioma com procura medível")}
