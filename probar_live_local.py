# -*- coding: utf-8 -*-
"""
Reproduce el directo en esta computadora, con los videos del JSON.

    python probar_live_local.py --json payload.json --cuenta 1
    python probar_live_local.py --desde-api --job ID_DEL_DIRECTO

Baja cada mp4, arma la voz del presentador y los pasa en orden.
No abre YouTube. Al cortar con Ctrl+C borra lo descargado.
"""

import argparse
import json
import logging
import os
import random
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.chdir(RAIZ)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import script_director
from live_local import aplicar_cuenta, bajar_payload, ficha_publica, servir
from live_orchestrator import armar_emision, prepare_show
from rundown_builder import PayloadError


def _leer_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError("El JSON tiene que ser un objeto, el mismo que manda lfaftechapi.")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ensayo local del directo de Noticias.lat. No publica en YouTube."
    )
    parser.add_argument("--json", dest="json_path", help="JSON de POST /live/start, el que arma lfaftechapi.")
    parser.add_argument("--desde-api", action="store_true", help="Baja el JSON ya guardado de un directo.")
    parser.add_argument("--job", help="Id del directo en lfaftechapi (con --desde-api).")
    parser.add_argument("--cuenta", type=int, choices=(0, 1, 2, 3), help="Canal a simular.")
    parser.add_argument("--canal", help="Nombre del canal, si querés pisar el del JSON.")
    parser.add_argument("--puerto", type=int, default=8765)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--sin-navegador", action="store_true", help="No abre el navegador; imprime la URL.")
    parser.add_argument("--sin-gemini", action="store_true", help="Usa las plantillas, sin llamar a Gemini.")
    args = parser.parse_args(argv)

    if args.desde_api and args.json_path:
        parser.error("Usá --json o --desde-api, no los dos.")
    if args.desde_api and not args.job:
        parser.error("--desde-api necesita --job con el id del directo.")

    if args.desde_api:
        print(f"Bajando el JSON del directo {args.job} desde lfaftechapi...")
        payload = bajar_payload(args.job)
    elif args.json_path:
        payload = _leer_json(args.json_path)
    else:
        ejemplo = os.path.join(RAIZ, "examples", "payload_paraguay.json")
        print(f"Sin JSON propio: uso el ejemplo {os.path.basename(ejemplo)}.")
        payload = _leer_json(ejemplo)

    payload = aplicar_cuenta(payload, cuenta=args.cuenta, canal=args.canal)
    if args.sin_gemini:
        script_director._ask_gemini = lambda *a, **k: None

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    try:
        show = prepare_show(payload, rng, with_script=False)
    except PayloadError as exc:
        print(f"El JSON no sirve para un directo: {exc}")
        return 2

    carpeta = os.path.join(RAIZ, "temp_video", f"ensayo_{show['live_id']}")
    print(
        f"Bajando {show['rundown']['video_count']} notas de {show['meta']['pais_nombre']} "
        f"para {show['meta']['canal']}..."
    )
    try:
        segmentos, video = armar_emision(show, rng, carpeta)
    except RuntimeError as exc:
        print(exc)
        return 2

    ficha = ficha_publica(show, segmentos)
    print(f"Programa listo: {ficha['duracion']:.0f} segundos, {show['meta']['video_count']} videos.")
    servir(ficha, video, puerto=args.puerto, abrir=not args.sin_navegador, carpeta=carpeta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
