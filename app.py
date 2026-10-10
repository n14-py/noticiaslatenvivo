# -*- coding: utf-8 -*-
"""
Servidor del directo. lfaftechapi le manda el JSON del país y esto abre el vivo.
Solo hay un directo a la vez, igual que el worker de videos de TTS-FMPEG.
"""

import logging
import os
import random
import shutil
import threading

from flask import Flask, jsonify, request

import live_orchestrator
from config import ADMIN_API_KEY, PORT, TEMPLATES_DIR
from rundown_builder import PayloadError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
processing_lock = threading.Lock()


def _authorized():
    return request.headers.get("x-api-key") == ADMIN_API_KEY


def _asset_counts():
    counts = {}
    base = TEMPLATES_DIR
    if not os.path.isdir(base):
        return counts
    for name in os.listdir(base):
        folder = os.path.join(base, name)
        if os.path.isdir(folder):
            counts[name] = len([f for f in os.listdir(folder) if not f.startswith(".")])
    return counts


@app.route("/", methods=["GET"])
def index():
    return "<h1>Noticias.lat — Motor de directos activo</h1>", 200


@app.route("/health", methods=["GET"])
def health():
    state = live_orchestrator.snapshot()
    return jsonify({
        "status": "healthy",
        "server": "Noticias.lat En Vivo",
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "templates": _asset_counts(),
        "live": state,
    }), 200


@app.route("/live/preview", methods=["POST"])
def preview():
    """Arma título, descripción y escaleta. No abre YouTube ni descarga videos."""
    if not _authorized():
        return jsonify({"error": "No autorizado. API Key inválida."}), 403
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "No se envió un JSON válido."}), 400
    try:
        rng = random.Random()
        show = live_orchestrator.prepare_show(payload, rng)
    except PayloadError as exc:
        return jsonify({"error": str(exc)}), 400

    blocks = []
    for block in show["rundown"]["blocks"]:
        blocks.append({
            "categoria": block["categoria"],
            "label": block["label"],
            "continuacion": block["continuacion"],
            "videos": [video["titulo"] for video in block["videos"]],
        })
    package = show["package"]
    return jsonify({
        "live_id": show["live_id"],
        "pais": show["meta"]["pais_nombre"],
        "fecha": show["meta"]["fecha_larga"],
        "presentador": package["anchor"]["name"],
        "voz": package["anchor"]["voice_key"],
        "guion": package["source"],
        "youtube_title": package["youtube_title"],
        "youtube_description": package["youtube_description"],
        "youtube_tags": package["youtube_tags"],
        "intro_text": package["intro_text"],
        "bridges": package["bridges"],
        "outro_text": package["outro_text"],
        "bloques": blocks,
    }), 200


@app.route("/live/start", methods=["POST"])
def start():
    if not _authorized():
        return jsonify({"error": "No autorizado. API Key inválida."}), 403
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "No se envió un JSON válido."}), 400

    try:
        # Validación rápida. El título lo escribe la IA dentro del hilo, una sola vez.
        live_orchestrator.prepare_show(payload, random.Random(), with_script=False)
    except PayloadError as exc:
        return jsonify({"error": str(exc)}), 400

    if not processing_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay un directo en curso. Esperá a que termine."}), 503

    def _job():
        try:
            live_orchestrator.run_live(payload, random.Random())
        finally:
            processing_lock.release()
            logger.info("  [API] Directo liberado. El servidor puede tomar otro país.")

    threading.Thread(target=_job, daemon=False).start()
    return jsonify({
        "message": "Directo aceptado. Estoy armando la voz y abriendo YouTube.",
        "status": "processing",
        "pais": payload.get("pais") or payload.get("country"),
    }), 202


@app.route("/live/status", methods=["GET"])
def status():
    if not _authorized():
        return jsonify({"error": "No autorizado. API Key inválida."}), 403
    return jsonify(live_orchestrator.snapshot()), 200


@app.route("/live/stop", methods=["POST"])
def stop():
    if not _authorized():
        return jsonify({"error": "No autorizado. API Key inválida."}), 403
    return jsonify(live_orchestrator.request_stop()), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
