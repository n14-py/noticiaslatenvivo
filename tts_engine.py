# -*- coding: utf-8 -*-
"""
Motor de texto a voz. Es el mismo Edge TTS de TTS-FMPEG, con velocidad
variable para que dos directos no suenen calcados.

Microsoft dejó de aceptar el token viejo el 10 de octubre de 2026.
edge-tts anterior a 7.3.1 manda Sec-MS-GEC-Version=1-... y el servicio
responde 403. Desde 7.3.1 el token es el v2 y la voz vuelve a salir.
"""

import importlib
import logging
import os
import re
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, version

from config import TEMP_AUDIO_DIR, VOICES

logger = logging.getLogger(__name__)

# 7.3.1 (13 de octubre de 2026) es la primera que manda el token v2.
_EDGE_MIN = (7, 3, 1)

# Si la voz elegida ya no existe, el directo sigue con otra en español.
# El 403 no entra acá: eso es el token viejo y hay que actualizar edge-tts.
_VOCES_DE_RESPALDO = (
    "es-MX-DaliaNeural",
    "es-AR-TomasNeural",
    "es-ES-ElviraNeural",
    "es-CO-GonzaloNeural",
)


def _version_de(paquete):
    try:
        texto = version(paquete)
    except PackageNotFoundError:
        return (0, 0, 0)
    numeros = []
    for parte in str(texto).split("."):
        digitos = ""
        for caracter in parte:
            if caracter.isdigit():
                digitos += caracter
            else:
                break
        if not digitos:
            break
        numeros.append(int(digitos))
    return tuple(numeros[:3]) or (0, 0, 0)


def _texto_version(numeros):
    if not numeros or numeros == (0, 0, 0):
        return "no instalado"
    return ".".join(str(numero) for numero in numeros)


def asegurar_edge_tts():
    """Deja instalada una edge-tts que Microsoft todavía acepta."""
    actual = _version_de("edge-tts")
    if actual >= _EDGE_MIN:
        return actual

    logger.warning(
        "  [TTS] edge-tts %s está vieja. Microsoft responde 403. La actualizo.",
        _texto_version(actual),
    )
    comando = [sys.executable, "-m", "pip", "install", "-U", "edge-tts>=7.3.1"]
    try:
        subprocess.run(comando, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError(
            "La voz no sale: edge-tts está vieja y Microsoft la rechaza con 403. "
            'Actualizala con: pip install -U "edge-tts>=7.3.1"'
        ) from exc

    importlib.invalidate_caches()
    nuevo = _version_de("edge-tts")
    if nuevo < _EDGE_MIN:
        raise RuntimeError(
            "Seguí con edge-tts vieja después de actualizar. "
            'Ejecutá: pip install -U "edge-tts>=7.3.1"'
        )
    for nombre in list(sys.modules):
        if nombre == "edge_tts" or nombre.startswith("edge_tts."):
            del sys.modules[nombre]
    logger.info("  [TTS] edge-tts quedó en %s.", _texto_version(nuevo))
    return nuevo


def sanitize_text_for_tts(text):
    if not text:
        return "Sin texto disponible."
    text = re.sub(r"http[s]?://\S+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace('"', "").replace("*", "").replace("_", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or "Sin texto disponible."


def _orden_de_voces(voice_code):
    orden = [voice_code]
    for otra in _VOCES_DE_RESPALDO:
        if otra not in orden:
            orden.append(otra)
    return orden


async def _async_generate_audio(text, voice_code, output_path, rate):
    import edge_tts
    from edge_tts.exceptions import NoAudioReceived

    ultimo = None
    for voz in _orden_de_voces(voice_code):
        try:
            communicate = edge_tts.Communicate(text, voz, rate=rate)
            await communicate.save(output_path)
        except NoAudioReceived as exc:
            ultimo = exc
            logger.warning("  [TTS] %s no devolvió audio.", voz)
            continue
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            if voz != voice_code:
                logger.warning("  [TTS] %s ya no responde. Usé %s.", voice_code, voz)
            return True
        ultimo = NoAudioReceived("archivo vacío")
    if ultimo:
        raise ultimo
    return False


def generate_audio_clip(text, voice_key, filename, rate="+0%"):
    import asyncio

    logger.info("  [TTS] Locución %s (%s, rate %s)", filename, voice_key, rate)
    asegurar_edge_tts()
    clean_text = sanitize_text_for_tts(text)
    voice_code = VOICES.get(voice_key, VOICES["hombre_1"])
    output_path = os.path.join(TEMP_AUDIO_DIR, filename)

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            logger.warning("  [TTS] No se pudo sobrescribir %s", output_path)

    for attempt in range(3):
        try:
            asyncio.run(_async_generate_audio(clean_text, voice_code, output_path, rate))
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                logger.info("  [TTS] Listo: %s", filename)
                return output_path
            logger.warning("  [TTS] Archivo vacío. Intento %s/3", attempt + 1)
        except Exception as exc:
            logger.warning("  [TTS] Error en intento %s: %s", attempt + 1, exc)
        time.sleep(1.5)

    logger.error("  [TTS] No se pudo generar %s", filename)
    return None
