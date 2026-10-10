# -*- coding: utf-8 -*-
"""
Motor de texto a voz. Es el mismo Edge TTS de TTS-FMPEG, con velocidad
variable para que dos directos no suenen calcados.
"""

import os
import re
import time
import asyncio
import logging
import edge_tts
from config import TEMP_AUDIO_DIR, VOICES

logger = logging.getLogger(__name__)


def sanitize_text_for_tts(text):
    if not text:
        return "Sin texto disponible."
    text = re.sub(r"http[s]?://\S+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace('"', "").replace("*", "").replace("_", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or "Sin texto disponible."


async def _async_generate_audio(text, voice_code, output_path, rate):
    communicate = edge_tts.Communicate(text, voice_code, rate=rate)
    await communicate.save(output_path)
    return True


def generate_audio_clip(text, voice_key, filename, rate="+0%"):
    logger.info("  [TTS] Locución %s (%s, rate %s)", filename, voice_key, rate)
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
