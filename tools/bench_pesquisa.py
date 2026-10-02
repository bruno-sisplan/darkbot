"""Mede o motor de pesquisa: roda pesquisas reais num servidor de teste e conta as oportunidades.

Oportunidade = vídeo do nicho (relevância >= 1), canal dark e dentro dos parâmetros de viral (7 dias, 3 mil views).

Uso (NUNCA no app em uso: servidor separado, com uma CÓPIA do banco):
  set DARKBOT_HOME=<pasta com a cópia do banco> && python -m uvicorn app.server:app --port 8766
  python tools/bench_pesquisa.py <rótulo>      -> grava bench_<rótulo>.json na pasta atual
Para comparar antes/depois, restaure a mesma cópia do banco antes de cada medição (o cache da IA muda o custo).
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8766"
OUT = Path(".")
CASES = [
    {"kind": "video", "seed": "https://www.youtube.com/watch?v=BwSNvnhu0J0", "langs": ["pt", "en", "es"]},
    {"kind": "keyword", "seed": "histórias de terror reais", "langs": ["pt", "en", "es"]},
]


def passes(v):
    return (v.get("age_days") is not None and v["age_days"] <= 7 and (v.get("views") or 0) >= 3000
            and v.get("is_dark"))


def spent(c):
    return c.get(f"{BASE}/api/settings").json()["ai_usage"]["cost_usd"]


def run_case(c, case):
    cost0, t0 = spent(c), time.time()
    r = c.post(f"{BASE}/api/research", json={**case, "report": False, "profile_id": 1}).json()
    jid, rid = r["job"]["id"], r["id"]
    while True:
        j = c.get(f"{BASE}/api/jobs/{jid}").json()
        if j["status"] != "running":
            break
        time.sleep(3)
    d = c.get(f"{BASE}/api/research/{rid}").json()
    vids = d["videos"]
    opps = [v for v in vids if (v.get("relevance") or 0) >= 1 and passes(v)]
    opps.sort(key=lambda v: -(v.get("views_hour") or 0))
    return {
        "case": case["seed"], "status": j["status"], "error": j.get("error"),
        "segundos": round(time.time() - t0), "custo": round(spent(c) - cost0, 4),
        "videos": len(vids), "rel2": sum(1 for v in vids if (v.get("relevance") or 0) >= 2),
        "oportunidades": len(opps), "op_rel2": sum(1 for v in opps if (v.get("relevance") or 0) >= 2),
        "canais": len({v["channel_id"] for v in opps}), "idiomas": sorted({(v.get("lang") or "?")[:2] for v in opps}),
        "views_hora_soma": sum(v.get("views_hour") or 0 for v in opps),
        "top": [f"{v.get('views_hour')}/h r{v.get('relevance')} {v['title'][:70]}" for v in opps[:8]],
        "research_id": rid,
    }


if __name__ == "__main__":
    label = sys.argv[1]
    out = []
    with httpx.Client(timeout=120) as c:
        for case in CASES:
            res = run_case(c, case)
            print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
            out.append(res)
    (OUT / f"bench_{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
