"""Padrões de título: o que os outliers têm que o resto do nicho não tem. Custo zero (sem IA).

Compara dois grupos de vídeos:
- outliers: os que mais furaram a bolha (top 20% por multiplicador, ou multiplicador mínimo)
- demais: o resto do mesmo recorte
e mede palavras, pares de palavras, aberturas e formatos (número, pergunta, CAPS...).
Esse resumo também é o que a IA vai receber, em vez de centenas de títulos crus.
"""
import re
from collections import Counter
from statistics import median

from . import analytics

_STOP = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra pro com sem
e ou mas que se como quando onde porque por que qual quais quem ao aos à às é são foi era ser ter tem têm
eu tu ele ela nós vós eles elas me te se lhe nos vos lhes meu minha seu sua seus suas isso isto esse essa
este esta aquele aquela aqui ali lá já não sim mais muito muita muitos muitas também só até sobre entre
the a an of to in on at for with and or but is are was were be been this that these those it its you your
from by as how what why who when where which do does did not no yes all any
el la los las un una unos unas de del en y o que por para con sin es son fue se su sus lo le les al
""".split())

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_WORD = re.compile(r"[a-zà-öø-ÿ0-9']+")


def _tokens(title: str) -> list[str]:
    text = re.sub(r"#\w+", " ", title.lower())
    return ["#" if t.isdigit() else t for t in _WORD.findall(text)]


def _content(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _STOP and t != "#" and len(t) > 2]


# Formatos medidos em cada título: (chave, rótulo, teste)
_FEATURES = [
    ("number", "Tem número", lambda t: bool(re.search(r"\d", t))),
    ("starts_number", "Começa com número", lambda t: bool(re.match(r"\s*\d", t))),
    ("question", "Faz uma pergunta (?)", lambda t: "?" in t),
    ("exclaim", "Tem exclamação (!)", lambda t: "!" in t),
    ("caps", "Palavra em MAIÚSCULAS", lambda t: bool(re.search(r"\b[A-ZÀ-Ý]{3,}\b", t))),
    ("emoji", "Tem emoji", lambda t: bool(_EMOJI.search(t))),
    ("separator", "Tem separador ( : | - )", lambda t: bool(re.search(r"[:|]| - | – ", t))),
    ("brackets", "Tem parênteses ou colchetes", lambda t: bool(re.search(r"[\(\[]", t))),
    ("hashtag", "Tem hashtag (#)", lambda t: "#" in t),
    ("you", "Fala com quem assiste (você)", lambda t: bool(re.search(r"\b(você|voce|vc|you|tu)\b", t, re.I))),
    ("superlative", "Exagera (mais, maior, pior)", lambda t: bool(re.search(r"\b(mais|maior|maiores|pior|piores|melhor|melhores|most|biggest|worst)\b", t, re.I))),
    ("negative", "Proibido / nunca / ninguém", lambda t: bool(re.search(r"\b(nunca|ninguém|ninguem|jamais|proibid\w*|never|nobody)\b", t, re.I))),
]


def _pick(videos: list[dict], max_age: float) -> list[dict]:
    out = []
    for v in videos:
        if v["multiplier"] is None or not v["title"]:
            continue
        if max_age and (v["age_days"] is None or v["age_days"] > max_age):
            continue
        out.append(v)
    return out


def _split(videos: list[dict], outlier: str) -> tuple[list[dict], list[dict]]:
    ranked = sorted(videos, key=lambda v: v["multiplier"], reverse=True)
    if outlier.startswith("min:"):
        cut = float(outlier[4:])
        top = [v for v in ranked if v["multiplier"] >= cut]
    else:  # topN (percentual)
        pct = int(outlier[3:] or 20) if outlier.startswith("top") else 20
        top = ranked[: max(1, round(len(ranked) * pct / 100))]
    ids = {v["video_id"] for v in top}
    return top, [v for v in ranked if v["video_id"] not in ids]


def _share(counter: Counter, n: int, key) -> float:
    return counter[key] / n if n else 0.0


def _terms(top_docs, rest_docs, n_top, n_rest, min_count, limit):
    c_top, c_rest = Counter(), Counter()
    for d in top_docs:
        c_top.update(set(d))
    for d in rest_docs:
        c_rest.update(set(d))
    rows = []
    for term, cnt in c_top.items():
        if cnt < min_count:
            continue
        s_top, s_rest = _share(c_top, n_top, term), _share(c_rest, n_rest, term)
        rows.append({
            "term": term, "count": cnt,
            "pct_top": round(100 * s_top, 1), "pct_rest": round(100 * s_rest, 1),
            "lift": round((s_top + 0.01) / (s_rest + 0.01), 1),
        })
    rows.sort(key=lambda r: (r["pct_top"] - r["pct_rest"], r["count"]), reverse=True)
    return rows[:limit]


def _med(values) -> float | None:
    vals = [x for x in values if x is not None]
    return round(median(vals), 1) if vals else None


def patterns(profile_id: int | None = None, max_age: float = 0, outlier: str = "top20") -> dict:
    return analyze(_pick(analytics.videos(profile_id), max_age), outlier)


def analyze(videos: list[dict], outlier: str = "top20") -> dict:
    """Padrões de título dos outliers vs. o resto, para qualquer conjunto de vídeos (coleta ou pesquisa)."""
    videos = [v for v in videos if v["multiplier"] is not None and v["title"]]
    if len(videos) < 6:
        return {"ok": False, "total": len(videos),
                "reason": "Poucos vídeos com números para comparar. Colete mais (com a chave da API configurada)."}

    top, rest = _split(videos, outlier)
    if not rest:
        return {"ok": False, "total": len(videos), "reason": "Todos os vídeos caíram como outlier. Suba o corte."}
    n_top, n_rest = len(top), len(rest)

    tok_top = [_tokens(v["title"]) for v in top]
    tok_rest = [_tokens(v["title"]) for v in rest]
    words_top = [_content(t) for t in tok_top]
    words_rest = [_content(t) for t in tok_rest]

    def bigrams(tokens):
        return [f"{a} {b}" for a, b in zip(tokens, tokens[1:]) if not (a in _STOP and b in _STOP)]

    def opening(tokens):
        return " ".join(tokens[:2]) if len(tokens) >= 2 else None

    min_count = 2 if n_top >= 8 else 1
    features = []
    for key, label, test in _FEATURES:
        with_f = [v for v in videos if test(v["title"])]
        without = [v for v in videos if not test(v["title"])]
        features.append({
            "key": key, "label": label,
            "pct_top": round(100 * sum(test(v["title"]) for v in top) / n_top, 1),
            "pct_rest": round(100 * sum(test(v["title"]) for v in rest) / n_rest, 1),
            "mult_with": _med(v["multiplier"] for v in with_f),
            "mult_without": _med(v["multiplier"] for v in without),
            "n_with": len(with_f),
        })
    features.sort(key=lambda f: f["pct_top"] - f["pct_rest"], reverse=True)

    openings = Counter(o for o in (opening(t) for t in tok_top) if o)
    open_mult: dict[str, list] = {}
    for v, t in zip(top, tok_top):
        o = opening(t)
        if o:
            open_mult.setdefault(o, []).append(v["multiplier"])

    return {
        "ok": True,
        "total": len(videos), "n_top": n_top, "n_rest": n_rest,
        "cut": round(top[-1]["multiplier"], 1),
        "length": {
            "chars_top": _med(len(v["title"]) for v in top),
            "chars_rest": _med(len(v["title"]) for v in rest),
            "words_top": _med(len(t) for t in tok_top),
            "words_rest": _med(len(t) for t in tok_rest),
        },
        "median_mult_top": _med(v["multiplier"] for v in top),
        "median_mult_rest": _med(v["multiplier"] for v in rest),
        "features": features,
        "words": _terms(words_top, words_rest, n_top, n_rest, min_count, 24),
        "bigrams": _terms([bigrams(t) for t in tok_top], [bigrams(t) for t in tok_rest], n_top, n_rest, min_count, 16),
        "openings": [
            {"term": o, "count": c, "mult": _med(open_mult[o])}
            for o, c in openings.most_common(12) if c >= min_count
        ],
        "examples": [
            {"video_id": v["video_id"], "title": v["title"], "multiplier": v["multiplier"],
             "views": v["views"], "channel_title": v["channel_title"]}
            for v in top[:30]
        ],
    }
