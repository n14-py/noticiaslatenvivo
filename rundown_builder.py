# -*- coding: utf-8 -*-
"""
Arma el orden del directo.

Si lfaftechapi manda bloques ya agrupados, se respetan.
Si manda una lista plana, se agrupa por país y categoría:
los primeros 3 de política, después economía, y así.
"""

import unicodedata
from config import BLOCK_SIZE, CATEGORY_ALIASES, CATEGORY_LABELS, CATEGORY_PRIORITY


class PayloadError(ValueError):
    pass


def _strip_accents(text):
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_category(raw):
    if not raw:
        return "general"
    key = _strip_accents(str(raw).strip().lower())
    key = key.replace("categoría:", "").replace("categoria:", "").strip()
    return CATEGORY_ALIASES.get(key, "general")


def category_label(code):
    return CATEGORY_LABELS.get(code, code)


def _first(data, *keys, default=""):
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def normalize_video(raw, index):
    if not isinstance(raw, dict):
        raise PayloadError(f"El video #{index} no es un objeto.")
    url = _first(raw, "video_url", "videoUrl", "url", "r2_url", "r2Url")
    if not url:
        raise PayloadError(f"El video #{index} no trae video_url.")
    titulo = str(_first(raw, "titulo", "title", "youtube_title", default=f"Noticia {index + 1}")).strip()
    return {
        "article_id": str(_first(raw, "article_id", "articleId", "id", default=f"nota-{index + 1}")),
        "titulo": titulo,
        "descripcion": str(_first(raw, "descripcion", "description", default="")).strip(),
        "categoria": normalize_category(_first(raw, "categoria", "category", "categoriaNoticia")),
        "video_url": str(url).strip(),
        "fecha": str(_first(raw, "fecha", "publishedAt", "date", default="")),
    }


def extract_videos(payload):
    """Devuelve (videos_planos, bloques_explicitos|None)."""
    if not isinstance(payload, dict):
        raise PayloadError("El cuerpo tiene que ser un JSON objeto.")

    explicit = payload.get("bloques") or payload.get("blocks")
    if explicit:
        if not isinstance(explicit, list) or not explicit:
            raise PayloadError("bloques tiene que ser una lista con al menos un grupo.")
        videos = []
        blocks = []
        for block in explicit:
            if not isinstance(block, dict):
                raise PayloadError("Cada bloque tiene que ser un objeto.")
            raw_videos = block.get("videos") or block.get("items") or []
            categoria = normalize_category(
                block.get("categoria") or block.get("category") or block.get("nombre")
            )
            normalized = []
            for raw in raw_videos:
                item = normalize_video(raw, len(videos))
                if not (block.get("categoria") or block.get("category")):
                    categoria = item["categoria"]
                else:
                    item["categoria"] = categoria
                normalized.append(item)
                videos.append(item)
            if normalized:
                blocks.append({
                    "categoria": categoria,
                    "label": category_label(categoria),
                    "videos": normalized,
                    "continuacion": False,
                })
        if not videos:
            raise PayloadError("Los bloques no traen videos.")
        return videos, blocks

    raw_videos = payload.get("videos") or payload.get("items") or payload.get("noticias")
    if not isinstance(raw_videos, list) or not raw_videos:
        raise PayloadError("Falta la lista videos (o bloques) con las notas del país.")
    videos = [normalize_video(raw, i) for i, raw in enumerate(raw_videos)]
    return videos, None


def _chunk(videos, size):
    size = max(1, size)
    return [videos[i:i + size] for i in range(0, len(videos), size)]


def build_rundown(videos, explicit_blocks=None, block_size=BLOCK_SIZE):
    """
    Orden editorial fijo de noticiero.
    La variación del directo está en la voz, el presentador y los textos,
    no en mezclar política con deportes al azar.
    """
    if explicit_blocks is not None:
        blocks = []
        for block in explicit_blocks:
            chunks = _chunk(block["videos"], block_size)
            for index, chunk in enumerate(chunks):
                blocks.append({
                    "categoria": block["categoria"],
                    "label": block["label"],
                    "videos": chunk,
                    "continuacion": bool(block.get("continuacion")) or index > 0,
                })
        return {"blocks": blocks, "video_count": sum(len(b["videos"]) for b in blocks)}

    grouped = {code: [] for code in CATEGORY_PRIORITY}
    for video in videos:
        grouped.setdefault(video["categoria"], []).append(video)

    present = [code for code in CATEGORY_PRIORITY if grouped.get(code)]
    for code in grouped:
        if code not in present and grouped[code]:
            present.append(code)

    # Primera pasada: un bloque de cada rubro (política, economía, ...).
    # Segunda pasada: lo que haya sobrado, para no perder notas.
    blocks = []
    leftovers = {code: list(grouped[code]) for code in present}
    for code in present:
        take = leftovers[code][:block_size]
        leftovers[code] = leftovers[code][block_size:]
        if take:
            blocks.append({
                "categoria": code,
                "label": category_label(code),
                "videos": take,
                "continuacion": False,
            })
    for code in present:
        for chunk in _chunk(leftovers[code], block_size):
            blocks.append({
                "categoria": code,
                "label": category_label(code),
                "videos": chunk,
                "continuacion": True,
            })

    return {"blocks": blocks, "video_count": sum(len(b["videos"]) for b in blocks)}
