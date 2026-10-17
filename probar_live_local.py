# -*- coding: utf-8 -*-
"""
Muestra el directo en esta computadora, como si estuvieras mirándolo.

    python probar_live_local.py --cuenta 1
    python probar_live_local.py --json payload.json
    python probar_live_local.py --desde-api --job ID_DEL_DIRECTO

No abre YouTube. No le avisa a lfaftechapi. Solo escucha en 127.0.0.1.
"""

import argparse
import json
import os
import random
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.chdir(RAIZ)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import script_director
from live_local import aplicar_cuenta, bajar_payload, ficha_publica, plan_local, render_programa, servir
from live_orchestrator import prepare_show
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
    parser.add_argument("--segundos-nota", type=float, default=6)
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

    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    try:
        show = prepare_show(payload, rng, with_script=True)
    except PayloadError as exc:
        print(f"El JSON no sirve para un directo: {exc}")
        return 2

    if not show.get("package"):
        print("No pude armar el título del vivo.")
        return 2

    segundos = min(20, max(3, args.segundos_nota))
    segmentos = plan_local(show, segundos_nota=segundos)
    ficha = ficha_publica(show, segmentos)
    carpeta = os.path.join(RAIZ, "temp_video", f"ensayo_{ficha['live_id']}")
    print(f"Armando el ensayo de {ficha['pais']} en {ficha['canal']}...")
    try:
        video = render_programa(segmentos, carpeta)
    except RuntimeError as exc:
        print(exc)
        return 2

    servir(ficha, video, puerto=args.puerto, abrir=not args.sin_navegador)
    return 0


if __name__ == "__main__":
    sys.exit(main())
