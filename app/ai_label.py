"""Selo "conteúdo alterado ou gerado por IA" que o próprio criador declara no YouTube.

A API oficial não devolve isso para vídeos de terceiros, mas a página do vídeo mostra a seção
"Como este conteúdo foi criado". Cada tipo de aviso aponta para um artigo de ajuda diferente,
o que funciona em qualquer idioma:
- answer/15447836 -> sons ou imagens alterados ou gerados por IA (o que nos interessa)
- answer/15569972 -> dublagem automática (ignorado: aparece até em canal com rosto)
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import httpx

from .youtube_web import client

_AI_MARK = "answer/15447836"
WORKERS = 16  # páginas abertas ao mesmo tempo (medido: ~18 vídeos/s sem o YouTube reclamar)


def _check(c: httpx.Client, video_id: str) -> int | None:
    """1 = tem o selo de IA, 0 = não tem, None = não deu para saber (tenta de novo na próxima coleta)."""
    try:
        html = c.get(f"https://www.youtube.com/watch?v={video_id}").text
    except httpx.HTTPError:
        return None
    if "ytInitialData" not in html:  # página de consentimento, bloqueio etc.
        return None
    return 1 if _AI_MARK in html else 0


def check_videos(video_ids: list[str], on_progress: Callable[[int, int], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> dict[str, int]:
    """Fila contínua em paralelo; se cancelar, os que ainda não começaram são pulados (o já feito fica)."""
    out: dict[str, int] = {}
    if not video_ids:
        return out

    def task(vid):
        if should_stop and should_stop():
            return vid, None
        return vid, _check(c, vid)

    with client() as c, ThreadPoolExecutor(WORKERS) as pool:
        for done, fut in enumerate(as_completed([pool.submit(task, v) for v in video_ids]), 1):
            vid, label = fut.result()
            if label is not None:
                out[vid] = label
            if on_progress:
                on_progress(done, len(video_ids))
    return out
