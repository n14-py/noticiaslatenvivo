# -*- coding: utf-8 -*-
"""Elige al azar intros, presentadores, música y efectos. Igual que TTS-FMPEG."""

import os
import logging
import requests
from config import BGM_DIR, SFX_DIR, TEMPLATES_DIR

logger = logging.getLogger(__name__)


def list_media_files(directory):
    if not directory or not os.path.isdir(directory):
        return []
    files = []
    for name in os.listdir(directory):
        if name.startswith("."):
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            files.append(path)
    return files


def get_random_file_from_dir(directory, rng):
    files = list_media_files(directory)
    if not files:
        logger.warning("  [Media] Carpeta vacía o inexistente: %s", directory)
        return None
    return rng.choice(files)


def get_random_bgm(mood, rng):
    mood_dir = os.path.join(BGM_DIR, mood or "analisis")
    bgm_path = get_random_file_from_dir(mood_dir, rng)
    if bgm_path:
        return bgm_path
    if not os.path.isdir(BGM_DIR):
        return None
    for name in os.listdir(BGM_DIR):
        fallback = os.path.join(BGM_DIR, name)
        if os.path.isdir(fallback):
            bgm_path = get_random_file_from_dir(fallback, rng)
            if bgm_path:
                return bgm_path
    return None


def get_random_sfx(sfx_type, rng):
    return get_random_file_from_dir(os.path.join(SFX_DIR, sfx_type or "transiciones"), rng)


def get_random_template(template_type, rng):
    return get_random_file_from_dir(os.path.join(TEMPLATES_DIR, template_type), rng)


def download_media(url, save_path, retries=3):
    if not url:
        return None
    logger.info("  [Media] Descargando %s", url[:80])
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NoticiasLAT-EnVivo/1.0)"}
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=90)
            if response.status_code != 200:
                logger.warning("  [Media] HTTP %s en intento %s", response.status_code, attempt + 1)
                continue
            with open(save_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
            if os.path.getsize(save_path) > 1024:
                return save_path
        except Exception as exc:
            logger.warning("  [Media] Fallo intento %s: %s", attempt + 1, exc)
    logger.error("  [Media] No se pudo descargar %s", url[:80])
    return None
