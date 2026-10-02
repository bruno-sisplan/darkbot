"""Meus parâmetros de viral: a régua única do app inteiro (Descobrir, pesquisas, relatório, Próximos vídeos).

O editor define em Configurações o que conta como "viral agora" (padrão: postado nesta semana, 3 mil views ou mais,
do mais forte para o mais fraco). O "mais forte" é por VIEWS POR HORA: um vídeo de 1 dia com 50 mil views ganha
de um de 7 dias com 80 mil, porque é o que está explodindo AGORA.
"""
import json
from datetime import datetime, timezone

from . import db

DEFAULTS = {
    "max_days": 7,          # postado há até N dias
    "min_views": 3000,      # pelo menos N views
    "min_vph": 0,           # pelo menos N views por hora (0 = sem mínimo)
    "min_mult": 0.0,        # viralizou pelo menos N× (views ÷ inscritos; 0 = sem mínimo)
    "max_subs": 0,          # canal com até N inscritos (0 = qualquer tamanho)
    "only_dark": True,      # só canais dark
    "sort": "vph",          # vph (views por hora), views ou mult
}
SORTS = {"vph": "Views por hora (o que está explodindo agora)", "views": "Total de views",
         "mult": "Quanto viralizou (views ÷ inscritos)"}


def get() -> dict:
    try:
        saved = json.loads(db.get_setting("viral_params") or "{}")
    except ValueError:
        saved = {}
    return DEFAULTS | {k: v for k, v in saved.items() if k in DEFAULTS}


def save(new: dict) -> dict:
    cur = get()
    for k, default in DEFAULTS.items():
        if k not in new or new[k] is None:
            continue
        v = new[k]
        if isinstance(default, bool):
            cur[k] = bool(v)
        elif k == "sort":
            cur[k] = v if v in SORTS else "vph"
        elif isinstance(default, float):
            cur[k] = max(0.0, float(v))
        else:
            cur[k] = max(0, int(float(v)))
    cur["max_days"] = max(1, cur["max_days"])
    db.set_setting("viral_params", json.dumps(cur))
    return cur


def hours_since(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - t).total_seconds() / 3600, 0.0)


def add_metrics(v: dict) -> dict:
    """age_hours e views_hour (views por hora desde que foi postado)."""
    h = hours_since(v.get("published_at"))
    v["age_hours"] = round(h, 1) if h is not None else None
    v["views_hour"] = round(v["views"] / max(h, 1)) if v.get("views") is not None and h is not None else None
    return v


def passes(v: dict, p: dict | None = None) -> bool:
    """O vídeo bate os parâmetros de viral do editor?"""
    p = p or get()
    age = v.get("age_days")
    if age is None and v.get("age_hours") is not None:
        age = v["age_hours"] / 24
    if age is None or age > p["max_days"]:
        return False
    if (v.get("views") or 0) < p["min_views"]:
        return False
    if p["min_vph"] and (v.get("views_hour") or 0) < p["min_vph"]:
        return False
    if p["min_mult"] and (v.get("multiplier") or 0) < p["min_mult"]:
        return False
    if p["max_subs"] and (v.get("subs") is None or v["subs"] > p["max_subs"]):
        return False
    if p["only_dark"] and v.get("is_dark") is False:
        return False
    return True


def rank_value(v: dict, p: dict | None = None) -> float:
    p = p or get()
    key = {"vph": "views_hour", "views": "views", "mult": "multiplier"}[p["sort"]]
    return float(v.get(key) or 0)


def rank(videos: list[dict], p: dict | None = None) -> list[dict]:
    p = p or get()
    return sorted(videos, key=lambda v: -rank_value(v, p))


def upload_filter(max_days: int | None) -> str | None:
    """Filtro de data da busca do YouTube que cobre o período."""
    if not max_days:
        return None
    if max_days <= 1:
        return "hoje"
    if max_days <= 7:
        return "semana"
    if max_days <= 31:
        return "mes"
    if max_days <= 366:
        return "ano"
    return None


def describe(p: dict | None = None) -> str:
    """Resumo em linguagem simples (vai para a tela e para a IA)."""
    p = p or get()
    parts = [f"postado há até {p['max_days']} dia{'s' if p['max_days'] > 1 else ''}",
             f"{p['min_views']:,} views ou mais".replace(",", ".")]
    if p["min_vph"]:
        parts.append(f"{p['min_vph']:,} views por hora ou mais".replace(",", "."))
    if p["min_mult"]:
        parts.append(f"viralizou {p['min_mult']:g}× ou mais".replace(".", ","))
    if p["max_subs"]:
        parts.append(f"canal com até {p['max_subs']:,} inscritos".replace(",", "."))
    if p["only_dark"]:
        parts.append("só canais dark")
    return " · ".join(parts)
