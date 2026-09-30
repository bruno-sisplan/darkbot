"""Métricas de decisão. Tudo calculado em código (custo zero); a IA entra depois só nos outliers.

- multiplicador: views / inscritos do canal. Quanto maior, mais o vídeo furou a bolha do canal.
- views_dia: views / dias desde a publicação.
- crescimento_dia: views ganhas por dia entre as duas últimas coletas.
- canal_dias: idade do canal (canais novos explodindo = nicho com espaço).
- vezes_visto: em quantas coletas o algoritmo empurrou esse vídeo.
"""
from datetime import datetime, timezone

from . import db


def _age_days(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - t).total_seconds() / 86400, 0.25)


def _growth() -> dict[str, float]:
    """Views/dia entre as duas últimas medições de cada vídeo."""
    out = {}
    last: dict[str, tuple] = {}
    for r in db.rows("SELECT video_id, captured_at, views FROM video_stats ORDER BY video_id, captured_at"):
        prev = last.get(r["video_id"])
        if prev:
            d1, d2 = _age_days(prev[0]), _age_days(r["captured_at"])
            if d1 is not None and d2 is not None and d1 - d2 >= 0.04:  # ~1h entre medições
                out[r["video_id"]] = (r["views"] - prev[1]) / (d1 - d2)
        last[r["video_id"]] = (r["captured_at"], r["views"])
    return out


def videos(profile_id: int | None = None) -> list[dict]:
    where, params = "", []
    if profile_id:
        where, params = "WHERE r.profile_id = ?", [profile_id]
    data = db.rows(
        f"""SELECT v.video_id, v.title, v.channel_id, v.channel_title, v.published_at, v.duration_s,
                   v.views, v.likes, v.comments, v.is_short, v.lang,
                   c.subs, c.published_at AS channel_published_at, c.video_count AS channel_videos,
                   c.thumbnail AS channel_thumb, c.handle,
                   COUNT(DISTINCT s.run_id) AS times_seen, MIN(s.position) AS best_position,
                   MIN(r.started_at) AS first_seen, MAX(r.started_at) AS last_seen,
                   GROUP_CONCAT(DISTINCT r.profile_id) AS profile_ids
            FROM sightings s
            JOIN runs r ON r.id = s.run_id
            JOIN videos v ON v.video_id = s.video_id
            LEFT JOIN channels c ON c.channel_id = v.channel_id
            {where}
            GROUP BY v.video_id""",
        params,
    )
    growth = _growth()
    for v in data:
        age = _age_days(v["published_at"])
        v["age_days"] = round(age, 1) if age is not None else None
        v["channel_age_days"] = round(_age_days(v["channel_published_at"]) or 0) or None
        v["views_day"] = round(v["views"] / age) if v["views"] is not None and age else None
        v["multiplier"] = (
            round(v["views"] / max(v["subs"], 100), 2) if v["views"] is not None and v["subs"] is not None else None
        )
        v["growth_day"] = round(growth[v["video_id"]]) if v["video_id"] in growth else None
        v["engagement"] = (
            round(100 * ((v["likes"] or 0) + (v["comments"] or 0)) / v["views"], 2) if v["views"] else None
        )
        v["profile_ids"] = [int(x) for x in (v["profile_ids"] or "").split(",") if x]
    return data


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
            "top_video": None, "shorts": 0,
        })
        c["videos_seen"] += 1
        c["times_seen"] += v["times_seen"]
        c["shorts"] += 1 if v["is_short"] else 0
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
                  (SELECT COUNT(*) FROM videos) AS videos,
                  (SELECT COUNT(*) FROM channels) AS channels,
                  (SELECT COUNT(*) FROM runs WHERE status='done') AS runs,
                  (SELECT MAX(finished_at) FROM runs WHERE status='done') AS last_run"""
    )
    return r or {}
