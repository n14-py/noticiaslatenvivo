# -*- coding: utf-8 -*-
"""
Configuración del directo de Noticias.lat.
Misma base que TTS-FMPEG (voces, assets, resolución) adaptada a YouTube Live.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.getcwd()

TEMP_AUDIO_DIR = os.path.join(BASE_DIR, "temp_audio")
TEMP_VIDEO_DIR = os.path.join(BASE_DIR, "temp_video")
TEMP_IMG_DIR = os.path.join(BASE_DIR, "temp_processing")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOCKS_DIR = os.path.join(BASE_DIR, "locks_history")

ASSETS_DIR = os.path.join(BASE_DIR, "assets_video")
TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
BGM_DIR = os.path.join(ASSETS_DIR, "bgm")
SFX_DIR = os.path.join(ASSETS_DIR, "sfx")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "ARIALBD.TTF")
OUTRO_IMAGE = os.path.join(ASSETS_DIR, "outro_final.png")

# Mismo lienzo que los videos que ya renderiza TTS-FMPEG.
RESOLUTION_W = 1280
RESOLUTION_H = 720
FPS = 30
VIDEO_BITRATE = os.getenv("LIVE_VIDEO_BITRATE", "2500k")
AUDIO_BITRATE = "160k"
AUDIO_RATE = 48000

# Voces Edge TTS. La clave la elige el directo al azar (hombre o mujer).
VOICES = {
    "mujer_1": "es-MX-DaliaNeural",
    "mujer_2": "es-ES-ElviraNeural",
    "hombre_1": "es-AR-TomasNeural",
    "hombre_2": "es-CO-TomasNeural",
}

VOICE_GENDER = {
    "mujer_1": "mujer",
    "mujer_2": "mujer",
    "hombre_1": "hombre",
    "hombre_2": "hombre",
}

PRESENTER_NAMES = {
    "mujer_1": ["Valentina", "Camila", "Lucía", "Sofía", "Martina"],
    "mujer_2": ["Ana", "Paula", "Elena", "Renata", "Carla"],
    "hombre_1": ["Martín", "Andrés", "Lucas", "Diego", "Joaquín"],
    "hombre_2": ["Carlos", "Mateo", "Nicolás", "Santiago", "Fernando"],
}

# Orden de un noticiero: política primero, después economía, después el resto.
CATEGORY_PRIORITY = [
    "politica",
    "economia",
    "deportes",
    "internacional",
    "seguridad",
    "sociedad",
    "tecnologia",
    "salud",
    "entretenimiento",
    "cultura",
    "general",
]

CATEGORY_LABELS = {
    "politica": "política",
    "economia": "economía",
    "deportes": "deportes",
    "internacional": "internacional",
    "seguridad": "seguridad",
    "sociedad": "sociedad",
    "tecnologia": "tecnología",
    "salud": "salud",
    "entretenimiento": "entretenimiento",
    "cultura": "cultura",
    "general": "actualidad",
}

CATEGORY_ALIASES = {
    "politica": "politica",
    "política": "politica",
    "politics": "politica",
    "economia": "economia",
    "economía": "economia",
    "economy": "economia",
    "negocios": "economia",
    "finanzas": "economia",
    "deportes": "deportes",
    "deporte": "deportes",
    "sports": "deportes",
    "futbol": "deportes",
    "fútbol": "deportes",
    "internacional": "internacional",
    "mundo": "internacional",
    "world": "internacional",
    "seguridad": "seguridad",
    "policial": "seguridad",
    "policiales": "seguridad",
    "sociedad": "sociedad",
    "social": "sociedad",
    "tecnologia": "tecnologia",
    "tecnología": "tecnologia",
    "tech": "tecnologia",
    "ciencia": "tecnologia",
    "salud": "salud",
    "health": "salud",
    "entretenimiento": "entretenimiento",
    "espectaculos": "entretenimiento",
    "espectáculos": "entretenimiento",
    "farandula": "entretenimiento",
    "farándula": "entretenimiento",
    "cultura": "cultura",
    "general": "general",
    "actualidad": "general",
    "nacional": "general",
    "noticias": "general",
}

# Cuántas notas seguidas antes de cortar con el presentador.
BLOCK_SIZE = 3

COUNTRIES = {
    "ar": {"nombre": "Argentina", "tz": "America/Argentina/Buenos_Aires"},
    "bo": {"nombre": "Bolivia", "tz": "America/La_Paz"},
    "br": {"nombre": "Brasil", "tz": "America/Sao_Paulo"},
    "cl": {"nombre": "Chile", "tz": "America/Santiago"},
    "co": {"nombre": "Colombia", "tz": "America/Bogota"},
    "cr": {"nombre": "Costa Rica", "tz": "America/Costa_Rica"},
    "cu": {"nombre": "Cuba", "tz": "America/Havana"},
    "ec": {"nombre": "Ecuador", "tz": "America/Guayaquil"},
    "sv": {"nombre": "El Salvador", "tz": "America/El_Salvador"},
    "gt": {"nombre": "Guatemala", "tz": "America/Guatemala"},
    "hn": {"nombre": "Honduras", "tz": "America/Tegucigalpa"},
    "mx": {"nombre": "México", "tz": "America/Mexico_City"},
    "ni": {"nombre": "Nicaragua", "tz": "America/Managua"},
    "pa": {"nombre": "Panamá", "tz": "America/Panama"},
    "py": {"nombre": "Paraguay", "tz": "America/Asuncion"},
    "pe": {"nombre": "Perú", "tz": "America/Lima"},
    "do": {"nombre": "República Dominicana", "tz": "America/Santo_Domingo"},
    "uy": {"nombre": "Uruguay", "tz": "America/Montevideo"},
    "ve": {"nombre": "Venezuela", "tz": "America/Caracas"},
}

COUNTRY_NAME_TO_CODE = {}
for _code, _info in COUNTRIES.items():
    COUNTRY_NAME_TO_CODE[_info["nombre"].lower()] = _code
    COUNTRY_NAME_TO_CODE[_code] = _code
COUNTRY_NAME_TO_CODE.update({
    "mexico": "mx",
    "méxico": "mx",
    "peru": "pe",
    "perú": "pe",
    "panama": "pa",
    "panamá": "pa",
    "republica dominicana": "do",
    "república dominicana": "do",
    "brasil": "br",
    "brazil": "br",
})

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "secreto123456")
MAIN_API_URL = os.getenv("MAIN_API_URL", "https://lfaftechapi.onrender.com").rstrip("/")
PORT = int(os.getenv("PORT", "3002"))
CANAL_DEFAULT = os.getenv("CANAL_NOMBRE", "Noticias LAT")
LIVE_PRIVACY = os.getenv("LIVE_PRIVACY", "public")
MAX_ACCOUNTS = int(os.getenv("YOUTUBE_MAX_ACCOUNTS", "6"))
AD_CUEPOINT_SECONDS = int(os.getenv("AD_CUEPOINT_SECONDS", "30"))
AD_MIN_GAP_SECONDS = int(os.getenv("AD_MIN_GAP_SECONDS", "120"))
AD_REPEAT_SECONDS = int(os.getenv("AD_REPEAT_SECONDS", "600"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
APP_STORE_LINK = "https://play.google.com/store/apps/details?id=com.noticiaslat.app"
SITE_URL = "https://noticias.lat"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
]


def init_directories():
    folders = [
        TEMP_AUDIO_DIR, TEMP_VIDEO_DIR, TEMP_IMG_DIR, OUTPUT_DIR, LOCKS_DIR,
        ASSETS_DIR,
        os.path.join(ASSETS_DIR, "fonts"),
        TEMPLATES_DIR, BGM_DIR, SFX_DIR,
        os.path.join(TEMPLATES_DIR, "intros"),
        os.path.join(TEMPLATES_DIR, "hombre"),
        os.path.join(TEMPLATES_DIR, "mujer"),
        os.path.join(TEMPLATES_DIR, "outros"),
        os.path.join(TEMPLATES_DIR, "sin_presentador"),
        os.path.join(BGM_DIR, "urgencia"),
        os.path.join(BGM_DIR, "analisis"),
        os.path.join(BGM_DIR, "tension"),
        os.path.join(SFX_DIR, "transiciones"),
        os.path.join(SFX_DIR, "impactos"),
        os.path.join(SFX_DIR, "alertas"),
        os.path.join(SFX_DIR, "tecnologia"),
    ]
    for directory in folders:
        os.makedirs(directory, exist_ok=True)


init_directories()
