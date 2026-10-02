"""Métricas de decisão. Tudo calculado em código (custo zero); a IA entra depois só nos outliers.

- multiplicador: views / inscritos do canal. Quanto maior, mais o vídeo furou a bolha do canal.
- views_dia: views / dias desde a publicação.
- crescimento_dia: views ganhas por dia entre as duas últimas coletas.
- canal_dias: idade do canal (canais novos explodindo = nicho com espaço).
- vezes_visto: em quantas coletas o algoritmo empurrou esse vídeo.
"""
from datetime import datetime, timezone

from . import config, db, viral


def _age_days(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - t).total_seconds() / 86400, 0.25)


def _growth() -> dict[str, float]:
    """Ritmo AGORA: views por hora entre as duas últimas medições de cada vídeo (comparar com a média desde a
    postagem diz se o vídeo está acelerando). Usa as horas reais entre as medições: _age_days arredonda o que tem
    menos de 6 horas e inflava a conta."""
    out = {}
    last: dict[str, tuple] = {}
    for r in db.rows("SELECT video_id, captured_at, views FROM video_stats ORDER BY video_id, captured_at"):
        prev = last.get(r["video_id"])
        if prev and r["views"] is not None and prev[1] is not None:
            h1, h2 = viral.hours_since(prev[0]), viral.hours_since(r["captured_at"])
            if h1 is not None and h2 is not None and h1 - h2 >= 1:   # pelo menos 1 hora entre as medições
                out[r["video_id"]] = max(r["views"] - prev[1], 0) / (h1 - h2)
        last[r["video_id"]] = (r["captured_at"], r["views"])
    return out


_BASE_COLS = """v.video_id, v.title, v.title_pt, v.channel_id, v.channel_title, v.published_at, v.duration_s,
                   v.views, v.likes, v.comments, v.is_short, v.lang, v.ai_label, v.hidden,
                   (SELECT MAX(v2.ai_label) FROM videos v2 WHERE v2.channel_id = v.channel_id) AS channel_ai,
                   c.subs, c.published_at AS channel_published_at, c.video_count AS channel_videos,
                   c.thumbnail AS channel_thumb, c.handle, c.dark AS channel_dark, c.format AS channel_format,
                   c.theme AS channel_theme, c.dark_conf AS channel_dark_conf, c.dark_manual AS channel_dark_manual"""

# Formatos que nunca são dark, mesmo sem rosto na tela (têm uma pessoa real como marca).
NOT_DARK_FORMATS = {"com_rosto", "oficial", "cortes", "comentario", "musica"}  # música nunca é dark (decisão do editor)


def is_dark(v: dict) -> bool:
    """Canal dark = anônimo e produzido em escala. Ordem de prioridade:
    1. correção do editor; 2. formato com pessoa real -> não; 3. IA com confiança alta/média;
    4. selo "gerado por IA" do YouTube enquanto a IA ainda não classificou o canal."""
    if v.get("channel_dark_manual") is not None:
        return bool(v["channel_dark_manual"])
    if v.get("channel_format") in NOT_DARK_FORMATS:
        return False
    if v.get("channel_dark") is not None:
        return bool(v["channel_dark"]) and v.get("channel_dark_conf") != "baixa"
    return bool(v.get("channel_ai"))


def _decorate(data: list[dict]) -> list[dict]:
    growth = _growth()
    for v in data:
        age = _age_days(v["published_at"])
        v["age_days"] = round(age, 1) if age is not None else None
        v["channel_age_days"] = round(_age_days(v["channel_published_at"]) or 0) or None
        v["views_day"] = round(v["views"] / max(age, 1)) if v["views"] is not None and age else None
        v["multiplier"] = (
            round(v["views"] / max(v["subs"], 100), 2) if v["views"] is not None and v["subs"] is not None else None
        )
        v["growth_hour"] = round(growth[v["video_id"]]) if v["video_id"] in growth else None
        v["engagement"] = (
            round(100 * ((v["likes"] or 0) + (v["comments"] or 0)) / v["views"], 2) if v["views"] else None
        )
        v["is_dark"] = is_dark(v)
        viral.add_metrics(v)   # age_hours e views_hour (views por hora: o "agora")
    return data


def videos(profile_id: int | None = None, run_id: int | None = None, source: str | None = None,
           include_hidden: bool = False) -> list[dict]:
    where, params = "WHERE v.is_short = 0", []
    if not include_hidden:
        where += " AND COALESCE(v.hidden, 0) = 0"
    if profile_id:
        where, params = where + " AND r.profile_id = ?", params + [profile_id]
    if run_id:
        where, params = where + " AND r.id = ?", params + [run_id]
    if source:
        where, params = where + " AND COALESCE(r.source, 'home') = ?", params + [source]
    data = db.rows(
        f"""SELECT {_BASE_COLS},
                   COUNT(DISTINCT s.run_id) AS times_seen, MIN(s.position) AS best_position,
                   MIN(r.started_at) AS first_seen, MAX(r.started_at) AS last_seen,
                   GROUP_CONCAT(DISTINCT r.profile_id) AS profile_ids,
                   GROUP_CONCAT(DISTINCT COALESCE(r.source, 'home')) AS sources
            FROM sightings s
            JOIN runs r ON r.id = s.run_id
            JOIN videos v ON v.video_id = s.video_id
            LEFT JOIN channels c ON c.channel_id = v.channel_id
            {where}
            GROUP BY v.video_id""",
        params,
    )
    for v in _decorate(data):
        v["profile_ids"] = [int(x) for x in (v["profile_ids"] or "").split(",") if x]
        v["sources"] = (v["sources"] or "home").split(",")
    return data


def video_detail(video_id: str) -> dict | None:
    """Tudo sobre um vídeo, para o painel de prévia."""
    rows = _decorate(db.rows(
        f"""SELECT {_BASE_COLS}, v.description, v.tags, v.first_seen_at, v.comments_fetched_at,
                   c.description AS channel_description, c.total_views AS channel_total_views, c.country,
                   (SELECT COUNT(DISTINCT s.run_id) FROM sightings s WHERE s.video_id = v.video_id) AS times_seen,
                   (SELECT COUNT(DISTINCT rv.research_id) FROM research_videos rv WHERE rv.video_id = v.video_id) AS in_research
            FROM videos v LEFT JOIN channels c ON c.channel_id = v.channel_id WHERE v.video_id = ?""",
        (video_id,),
    ))
    if not rows:
        return None
    v = rows[0]
    v["score"] = opportunity(v)
    return v


def research_videos(research_id: int) -> list[dict]:
    """Vídeos de uma pesquisa, com as mesmas métricas + como foram achados e uma nota de oportunidade."""
    data = _decorate(db.rows(
        f"""SELECT {_BASE_COLS}, rv.via, rv.depth, rv.keyword, rv.position, rv.relevance,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.video_id = v.video_id) AS comments_saved
            FROM research_videos rv
            JOIN videos v ON v.video_id = rv.video_id
            LEFT JOIN channels c ON c.channel_id = v.channel_id
            WHERE rv.research_id = ? AND v.is_short = 0 AND COALESCE(v.hidden, 0) = 0""",
        (research_id,),
    ))
    for v in data:
        v["score"] = opportunity(v)
        v["potential"] = has_potential(v)
    return data


def has_potential(v: dict) -> bool:
    """Furou a própria base (multiplicador) ou está ganhando tração (views/dia). Sem números: sem potencial."""
    return (v.get("multiplier") or 0) >= config.POTENTIAL_MIN_MULT or \
        (v.get("views_day") or 0) >= config.POTENTIAL_MIN_VIEWS_DAY


def saturation(videos: list[dict], min_relevance: int = 3) -> list[dict]:
    """Onde o formato já foi modelado: por idioma, quantos vídeos e canais (total e nos últimos 30 dias)."""
    by: dict[str, dict] = {}
    for v in videos:
        if (v.get("relevance") or 0) < min_relevance:
            continue
        lang = (v.get("lang") or "?").split("-")[0].lower()
        b = by.setdefault(lang, {"lang": lang, "videos": 0, "channels": set(), "recent_videos": 0,
                                 "recent_channels": set(), "mults": [], "best": None})
        b["videos"] += 1
        b["channels"].add(v["channel_id"])
        if (v.get("age_days") or 9999) <= 30:
            b["recent_videos"] += 1
            b["recent_channels"].add(v["channel_id"])
        if v.get("multiplier") is not None:
            b["mults"].append(v["multiplier"])
            if not b["best"] or v["multiplier"] > b["best"]["multiplier"]:
                b["best"] = {"video_id": v["video_id"], "title": v["title"], "multiplier": v["multiplier"]}
    out = []
    for b in by.values():
        m = sorted(b.pop("mults"))
        out.append({**b, "channels": len(b["channels"]), "recent_channels": len(b["recent_channels"]),
                    "median_mult": round(m[len(m) // 2], 1) if m else None})
    return sorted(out, key=lambda x: -x["videos"])


def opportunity(v: dict) -> float | None:
    """Força agora, pela régua do editor (Configurações → Meus parâmetros): por padrão views por hora."""
    if v.get("views") is None:
        return None
    if v.get("views_hour") is None and v.get("published_at"):
        viral.add_metrics(v)
    return round(viral.rank_value(v), 2)


def channels(profile_id: int | None = None) -> list[dict]:
    by_channel: dict[str, dict] = {}
    for v in videos(profile_id):
        cid = v["channel_id"]
        if not cid:
            continue
        c = by_channel.setdefault(cid, {
            "channel_id": cid, "title": v["channel_title"], "handle": v["handle"], "thumb": v["channel_thumb"],
            "subs": v["subs"], "channel_age_days": v["channel_age_days"], "channel_videos": v["channel_videos"],
            "videos_seen": 0, "times_seen": 0, "best_multiplier": None, "sum_views_day": 0,
            "top_video": None, "ai": v["channel_ai"], "dark": v["is_dark"], "format": v["channel_format"],
            "dark_manual": v["channel_dark_manual"],
        })
        c["videos_seen"] += 1
        c["times_seen"] += v["times_seen"]
        c["sum_views_day"] += v["views_day"] or 0
        if v["multiplier"] is not None and (c["best_multiplier"] is None or v["multiplier"] > c["best_multiplier"]):
            c["best_multiplier"] = v["multiplier"]
            c["top_video"] = {"video_id": v["video_id"], "title": v["title"], "views": v["views"]}
    out = list(by_channel.values())
    for c in out:
        c["avg_views_day"] = round(c.pop("sum_views_day") / c["videos_seen"]) if c["videos_seen"] else None
    return out


def overview() -> dict:
    r = db.row(
        """SELECT (SELECT COUNT(*) FROM profiles) AS profiles,
                  (SELECT COUNT(*) FROM videos WHERE is_short = 0) AS videos,
                  (SELECT COUNT(*) FROM channels) AS channels,
                  (SELECT COUNT(*) FROM runs WHERE status='done') AS runs,
                  (SELECT MAX(finished_at) FROM runs WHERE status='done') AS last_run"""
    )
    return r or {}
