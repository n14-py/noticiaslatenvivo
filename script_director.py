# -*- coding: utf-8 -*-
"""
Crea título, descripción y las únicas frases que se locutan en el directo:
bienvenida (fecha, canal, país), puentes entre bloques y despedida.

La noticia en sí ya viene locutada dentro de cada video.
Gemini escribe los textos cuando hay clave. Si no responde, entran plantillas
distintas en cada emisión para que el vivo no se repita.
"""

import json
import logging
import os
import re
import requests

from config import (
    APP_STORE_LINK,
    CANAL_DEFAULT,
    CATEGORY_LABELS,
    GEMINI_MODEL,
    SITE_URL,
)

logger = logging.getLogger(__name__)

TONOS = [
    "sobrio de noticiero de medianoche",
    "enérgico de apertura de mediodía",
    "cercano, claro y sin gritar",
    "urgente pero respetuoso",
    "calendario, con la fecha bien marcada",
    "de resumen, como quien ordena el día",
]

INTROS = [
    "Bienvenidos a {canal}. Hoy es {fecha}. Les habla {nombre} con el resumen en vivo de {pais}. Arrancamos con {inicio}.",
    "Muy buenas. Soy {nombre} y esto es {canal}, en directo. {fecha}. Vamos con lo más importante de {pais}, empezando por {inicio}.",
    "Hola, qué tal. Están en el vivo de {canal}. Hoy, {fecha}, repasamos las noticias de los últimos días en {pais}. Comenzamos con {inicio}.",
    "Buenas. {nombre} al aire en {canal}. Estamos a {fecha} y este es el repaso en vivo de {pais}. La primera parte es {inicio}.",
    "Gracias por acompañarnos. {canal} en vivo, {fecha}. Soy {nombre}. En los próximos minutos, las notas que marcaron {pais}. Abrimos con {inicio}.",
    "Esto es {canal}. {fecha}. Les saluda {nombre} desde el resumen de {pais}. Sin más trámite, entramos en {inicio}.",
]

PUENTES = [
    "Hasta aquí {actual}. Ahora pasamos a {siguiente}.",
    "Cerramos {actual}. Enseguida, {siguiente}.",
    "Y cambiamos de tema. Dejamos {actual} y entramos en {siguiente}.",
    "Eso fue {actual}. Vamos ahora con {siguiente}.",
    "Ponemos pausa en {actual}. Lo que sigue es {siguiente}.",
    "De {actual} saltamos a {siguiente}. Seguimos en vivo.",
]

PUENTES_CONTINUACION = [
    "Seguimos con más notas de {siguiente}.",
    "Hay más en {siguiente}. Vamos con la que sigue.",
    "No cerramos todavía {siguiente}. Acá va otra.",
    "Volvemos un momento a {siguiente}.",
]

OUTROS = [
    "Eso fue todo en este vivo de {canal}. Gracias por acompañarnos en el resumen de {pais}. {fecha}. Nos vemos en el próximo directo.",
    "Cerramos la edición en vivo. Soy {nombre}, esto fue {canal}, con las noticias de {pais}. Gracias y hasta la próxima.",
    "Hasta aquí el repaso de {pais}. Gracias por estar del otro lado. {canal} vuelve con otro directo pronto.",
    "Terminamos por hoy. {fecha}, {pais}, {canal}. Les habló {nombre}. Que estén muy bien.",
]

TITLE_TEMPLATES = [
    "EN VIVO: {n} noticias de {pais} | {fecha_corta}",
    "Noticias de {pais} en directo | {resumen_bloques} | {fecha_corta}",
    "{canal}: resumen en vivo de {pais} ({n} notas)",
    "DIRECTO | {pais}: {titular}",
    "Lo último en {pais} en vivo | {n} noticias | {canal}",
]

BGM_MOODS = ["analisis", "tension", "urgencia"]
SFX_TYPES = ["transiciones", "impactos", "alertas"]
RATES = ["-5%", "+0%", "+5%", "+8%", "+10%", "+12%"]


def _clean_spoken(text, limit=420):
    if not text:
        return ""
    text = re.sub(r"http[s]?://\S+", "", str(text))
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("\n", " ").replace("*", "").replace("_", "").replace("#", "")
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "."
    return text


def _gemini_keys():
    keys = []
    primary = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if primary:
        keys.append(primary)
    for i in range(2, 8):
        value = os.getenv(f"GEMINI_API_KEY_{i}")
        if value:
            keys.append(value)
    return keys


def _headlines_by_block(blocks):
    lines = []
    for block in blocks:
        titles = [v["titulo"] for v in block["videos"]]
        lines.append(f"{block['label']}: " + " | ".join(titles))
    return "\n".join(lines)


def _local_package(meta, blocks, anchor, rng):
    inicio = blocks[0]["label"] if blocks else "la actualidad"
    ctx = {
        "canal": meta["canal"],
        "fecha": meta["fecha_larga"],
        "fecha_corta": meta["fecha_corta"],
        "nombre": anchor["name"],
        "pais": meta["pais_nombre"],
        "inicio": inicio,
        "n": meta["video_count"],
        "titular": blocks[0]["videos"][0]["titulo"] if blocks and blocks[0]["videos"] else meta["pais_nombre"],
        "resumen_bloques": ", ".join(dict.fromkeys(b["label"] for b in blocks)) or "actualidad",
    }
    bridges = []
    previous = None
    for block in blocks:
        if previous is None:
            previous = block
            continue
        actual = previous["label"]
        siguiente = block["label"]
        if block.get("continuacion") and block["categoria"] == previous["categoria"]:
            template = rng.choice(PUENTES_CONTINUACION)
            spoken = template.format(actual=actual, siguiente=siguiente)
        else:
            template = rng.choice(PUENTES)
            spoken = template.format(actual=actual, siguiente=siguiente)
        bridges.append(_clean_spoken(spoken))
        previous = block

    title = rng.choice(TITLE_TEMPLATES).format(**ctx)
    description = _description(meta, blocks, title)
    return {
        "youtube_title": title[:100],
        "youtube_description": description[:4900],
        "youtube_tags": _tags(meta, blocks),
        "intro_text": _clean_spoken(rng.choice(INTROS).format(**ctx)),
        "outro_text": _clean_spoken(rng.choice(OUTROS).format(**ctx)),
        "bridges": bridges,
        "source": "plantillas",
    }


def _description(meta, blocks, title):
    partes = [
        f"🔴 EN VIVO | {meta['canal']}",
        meta["fecha_larga"],
        "",
        f"Resumen en directo de las noticias de los últimos días en {meta['pais_nombre']}.",
        title,
        "",
    ]
    for block in blocks:
        partes.append(f"▸ {block['label'].capitalize()}")
        for video in block["videos"]:
            partes.append(f"• {video['titulo']}")
        partes.append("")
    partes.extend([
        "📱 Noticias LAT en el celular",
        APP_STORE_LINK,
        "",
        SITE_URL,
    ])
    return "\n".join(partes).strip()


def _tags(meta, blocks):
    tags = [
        "noticias",
        "en vivo",
        "noticias lat",
        meta["pais_nombre"].lower(),
        "directo",
        "última hora",
    ]
    for block in blocks:
        label = CATEGORY_LABELS.get(block["categoria"], block["label"])
        tags.append(label)
    seen = []
    for tag in tags:
        clean = tag.strip().lower()
        if clean and clean not in seen:
            seen.append(clean)
    return seen[:12]


def _ask_gemini(meta, blocks, anchor, rng):
    keys = _gemini_keys()
    if not keys:
        return None

    n_bridges = max(0, len(blocks) - 1)
    tono = rng.choice(TONOS)
    variante = rng.randint(1000, 9999)
    transiciones = []
    previous = None
    for block in blocks:
        if previous is not None:
            transiciones.append({
                "desde": previous["label"],
                "hacia": block["label"],
                "continuacion": bool(block.get("continuacion") and block["categoria"] == previous["categoria"]),
            })
        previous = block

    prompt = f"""Eres el editor de un noticiero de televisión en español de {meta['pais_nombre']}.
Vas a escribir SOLO los textos hablados de un directo de YouTube y los metadatos del video.
Las notas ya están grabadas. NO resumas cada noticia. NO inventes datos que no estén en los títulos.
La locución es únicamente: saludo de entrada, puentes entre bloques y despedida.

Variante creativa #{variante}. Tono: {tono}.
Canal: {meta['canal']}
Presentador: {anchor['name']} ({anchor['gender']})
Fecha que debe decir en voz alta: {meta['fecha_larga']}
País: {meta['pais_nombre']}

TÍTULOS REALES, EN ORDEN DE EMISIÓN:
{_headlines_by_block(blocks)}

TRANSICIONES NECESARIAS ({n_bridges}):
{json.dumps(transiciones, ensure_ascii=False)}

REGLAS:
- "intro_text": 25 a 45 palabras. Saluda, dice el canal, la fecha completa, el nombre del presentador, el país, y con qué bloque arranca. Es texto para leer en voz alta. Nada de acotaciones.
- "bridges": exactamente {n_bridges} frases. Cada una 10 a 24 palabras. Si continuacion es true, la frase sigue en el mismo tema ("seguimos con más de..."). Si es false, anuncia el cambio ("ahora pasamos a...").
- "outro_text": 20 a 35 palabras. Agradece, repite canal y país, se despide.
- "youtube_title": máximo 90 caracteres, en español, deja claro que es EN VIVO y el país. No uses comillas.
- "youtube_description": 2 párrafos cortos con el espíritu de la edición, sin inventar cifras.
- "youtube_tags": 6 a 10 tags en minúscula.
- Devuelve ÚNICAMENTE JSON válido, sin markdown.

{{
  "youtube_title": "",
  "youtube_description": "",
  "youtube_tags": ["noticias"],
  "intro_text": "",
  "bridges": ["frase 1"],
  "outro_text": ""
}}"""

    models = [GEMINI_MODEL, "gemini-2.0-flash", "gemini-2.5-flash"]
    seen_models = []
    for model in models:
        if model in seen_models:
            continue
        seen_models.append(model)
        for key in keys:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                response = requests.post(
                    url,
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1200},
                    },
                    timeout=40,
                )
                if response.status_code in (400, 403, 404, 429):
                    logger.warning("  [Guion] Gemini %s respondió %s", model, response.status_code)
                    continue
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return _parse_gemini_json(text)
            except Exception as exc:
                logger.warning("  [Guion] Gemini no respondió (%s): %s", model, exc)
    return None


def _parse_gemini_json(text):
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Gemini no devolvió JSON.")
    return json.loads(cleaned[start:end + 1])


def _merge_ai(ai, local, n_bridges):
    if not isinstance(ai, dict):
        return local
    title = _clean_spoken(ai.get("youtube_title"), limit=100)
    intro = _clean_spoken(ai.get("intro_text"))
    outro = _clean_spoken(ai.get("outro_text"))
    bridges_raw = ai.get("bridges") if isinstance(ai.get("bridges"), list) else []
    bridges = [_clean_spoken(item, limit=280) for item in bridges_raw]
    bridges = [item for item in bridges if item]
    while len(bridges) < n_bridges:
        bridges.append(local["bridges"][len(bridges)])
    bridges = bridges[:n_bridges]

    description = str(ai.get("youtube_description") or "").strip()
    if len(description) < 40:
        description = local["youtube_description"]
    else:
        description = (description + "\n\n" + local["youtube_description"])[:4900]

    tags = ai.get("youtube_tags") if isinstance(ai.get("youtube_tags"), list) else []
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
    for tag in local["youtube_tags"]:
        if tag not in tags:
            tags.append(tag)

    if not title or not intro or not outro:
        return local

    merged = dict(local)
    merged.update({
        "youtube_title": title[:100],
        "youtube_description": description[:4900],
        "youtube_tags": tags[:12],
        "intro_text": intro,
        "outro_text": outro,
        "bridges": bridges,
        "source": "gemini",
    })
    return merged


def choose_anchor(rng, voice_key=None):
    from config import PRESENTER_NAMES, VOICE_GENDER, VOICES

    if voice_key not in VOICES:
        voice_key = rng.choice(list(VOICES.keys()))
    return {
        "voice_key": voice_key,
        "gender": VOICE_GENDER[voice_key],
        "name": rng.choice(PRESENTER_NAMES[voice_key]),
        "rate": rng.choice(RATES),
        "bgm_mood": rng.choice(BGM_MOODS),
        "sfx_type": rng.choice(SFX_TYPES),
    }


def compose(meta, blocks, anchor, rng):
    local = _local_package(meta, blocks, anchor, rng)
    ai = _ask_gemini(meta, blocks, anchor, rng)
    package = _merge_ai(ai, local, len(local["bridges"])) if ai else local
    package["anchor"] = anchor
    logger.info(
        "  [Guion] Fuente=%s voz=%s presentador=%s",
        package["source"], anchor["voice_key"], anchor["name"],
    )
    return package
