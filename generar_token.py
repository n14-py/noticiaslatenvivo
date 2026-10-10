# -*- coding: utf-8 -*-
"""
Genera el token de YouTube con permiso de DIRECTO y de monetización.

Los tokens viejos de TTS-FMPEG solo sirven para subir videos.
Hay que volver a autorizar cada canal con este script antes del primer vivo.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import SCOPES

ACCOUNTS = [
    {"id": 0, "name": "Principal", "secret": "client_secret_0.json", "token": "token_0.json"},
    {"id": 1, "name": "NoticiasLat1", "secret": "client_secret_1.json", "token": "token_1.json"},
    {"id": 2, "name": "NoticiasLat2", "secret": "client_secret_2.json", "token": "token_2.json"},
    {"id": 3, "name": "NoticiasLat3", "secret": "client_secret_3.json", "token": "token_3.json"},
    {"id": 4, "name": "NoticiasLat4", "secret": "client_secret_4.json", "token": "token_4.json"},
    {"id": 5, "name": "NoticiasLat5", "secret": "client_secret_5.json", "token": "token_5.json"},
]


def generar_token():
    print("--- TOKENS DE YOUTUBE LIVE (Noticias.lat en vivo) ---")
    print("Scopes: directo, forzar SSL y subida (hace falta para la miniatura y la pauta).")
    for acc in ACCOUNTS:
        estado = "LISTO" if os.path.exists(acc["token"]) else "FALTA TOKEN"
        print(f"[{acc['id']}] {acc['name']} ({acc['secret']}) -> {estado}")

    try:
        seleccion = int(input("\nNúmero de cuenta (0-5): "))
    except ValueError:
        print("Tenés que ingresar un número.")
        return

    cuenta = next((acc for acc in ACCOUNTS if acc["id"] == seleccion), None)
    if not cuenta:
        print("Elegí un número del 0 al 5.")
        return
    if not os.path.exists(cuenta["secret"]):
        print(f"No encuentro {cuenta['secret']}. Descargalo de Google Cloud Console.")
        return

    creds = None
    if os.path.exists(cuenta["token"]):
        try:
            creds = Credentials.from_authorized_user_file(cuenta["token"], SCOPES)
        except Exception:
            print("El token viejo no sirve para estos permisos. Hay que autorizar de nuevo.")
            creds = None

    if not creds or not creds.valid or set(SCOPES) - set(creds.scopes or []):
        if creds and creds.expired and creds.refresh_token and not (set(SCOPES) - set(creds.scopes or [])):
            creds.refresh(Request())
        else:
            print("Se abre el navegador. Entrá con el canal que va a emitir el vivo.")
            flow = InstalledAppFlow.from_client_secrets_file(cuenta["secret"], SCOPES)
            creds = flow.run_local_server(port=0)

    with open(cuenta["token"], "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    print(f"Token guardado en {cuenta['token']}.")


if __name__ == "__main__":
    generar_token()
