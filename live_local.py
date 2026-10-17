# -*- coding: utf-8 -*-
"""
Directo real, solo en esta computadora.

Usa el mismo JSON que lfaftechapi manda a POST /live/start: baja cada mp4,
pone la voz del presentador y reproduce las notas. No abre YouTube y no
avisa a la API. Al cortar, borra lo que descargó.
"""

import html
import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from config import ADMIN_API_KEY, MAIN_API_URL
from live_orchestrator import _cleanup_dir


def aplicar_cuenta(payload, cuenta=None, canal=None):
    """Pisa el canal del JSON cuando el ensayo se pide en una cuenta concreta."""
    from config import canal_nombre

    data = dict(payload or {})
    if cuenta is not None:
        data["cuenta"] = int(cuenta)
        data["canal_id"] = int(cuenta)
        if canal is None:
            data["canal"] = canal_nombre(cuenta)
    if canal:
        data["canal"] = canal
    return data


def bajar_payload(job_id):
    """Trae el JSON que lfaftechapi ya guardó para ese directo."""
    url = f"{MAIN_API_URL}/api/lives/admin/jobs/{job_id}"
    try:
        response = requests.get(
            url,
            headers={"x-api-key": ADMIN_API_KEY},
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"No pude hablar con lfaftechapi: {exc}") from exc
    if response.status_code == 403:
        raise RuntimeError("lfaftechapi rechazó la clave. Revisá ADMIN_API_KEY en el .env.")
    if response.status_code == 404:
        raise RuntimeError("lfaftechapi no tiene ese directo.")
    if response.status_code >= 300:
        raise RuntimeError(f"lfaftechapi respondió {response.status_code}.")
    payload = (response.json() or {}).get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Ese directo no tiene el JSON de las notas.")
    return payload


_KIND_PAGINA = {
    "intro": "intro",
    "bridge": "puente",
    "puente": "puente",
    "news": "nota",
    "nota": "nota",
    "outro": "outro",
}


def ficha_publica(show, segmentos):
    package = show["package"]
    anchor = package["anchor"]
    return {
        "live_id": show["live_id"],
        "titulo": package["youtube_title"],
        "descripcion": package["youtube_description"],
        "tags": package["youtube_tags"],
        "canal": show["meta"]["canal"],
        "cuenta": show["cuenta"],
        "pais": show["meta"]["pais_nombre"],
        "fecha": show["meta"]["fecha_larga"],
        "presentador": anchor["name"],
        "voz": anchor["voice_key"],
        "guion": package["source"],
        "intro": package["intro_text"],
        "outro": package["outro_text"],
        "duracion": round(sum(item["duration"] for item in segmentos), 2),
        "segmentos": [
            {
                "kind": _KIND_PAGINA.get(item["kind"], item["kind"]),
                "titulo": item.get("titulo") or "Bloque",
                "categoria": item.get("categoria") or "",
                "starts_at": item["starts_at"],
                "duration": item["duration"],
            }
            for item in segmentos
        ],
    }


def pagina_html(ficha):
    datos = json.dumps(ficha, ensure_ascii=False).replace("<", "\\u003c")
    cuenta = ficha["cuenta"]
    colores = {0: "#e10600", 1: "#e07a2f", 2: "#3ea6ff", 3: "#2ebd85"}
    color = colores.get(cuenta, "#3ea6ff")
    inicial = html.escape((ficha["canal"] or "N")[:1].upper())
    filas = []
    for item in ficha["segmentos"]:
        etiqueta = {"intro": "Apertura", "puente": "Pase", "nota": "Nota", "outro": "Cierre"}.get(item["kind"], "Bloque")
        filas.append(
            "<li class=\"item\" data-inicio=\"{inicio}\">"
            "<div class=\"kicker\">{etiqueta}</div>"
            "<div>{titulo}</div></li>".format(
                inicio=item["starts_at"],
                etiqueta=html.escape(etiqueta),
                titulo=html.escape(item["titulo"]),
            )
        )
    tags = "".join(f"<span class=\"tag\">{html.escape(tag)}</span>" for tag in ficha["tags"])
    cuenta_txt = "sin cuenta fija" if cuenta is None else f"cuenta {cuenta}"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EN VIVO · {html.escape(ficha["titulo"])}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #0f0f0f; color: #f1f1f1; font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
.sala {{ max-width: 1180px; margin: 0 auto; padding: 18px 16px 56px; }}
.marca {{ color: #aaaaaa; font-size: 12px; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 14px; }}
.layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 22px; align-items: start; }}
@media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} }}
.player {{ position: relative; background: #000; border-radius: 12px; overflow: hidden; }}
video {{ width: 100%; aspect-ratio: 16/9; background: #000; display: block; }}
.badge {{ position: absolute; top: 12px; left: 12px; background: #ff2a2a; color: white; font-weight: 700; font-size: 13px; letter-spacing: .06em; padding: 5px 9px; border-radius: 4px; }}
.badge.fin {{ background: #444; }}
.reloj {{ position: absolute; top: 12px; right: 12px; background: rgba(0,0,0,.72); padding: 5px 9px; border-radius: 4px; font-variant-numeric: tabular-nums; font-size: 14px; }}
.entrar {{ position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); border: 0; border-radius: 24px; background: #fff; color: #111; font-weight: 700; font-size: 16px; padding: 12px 18px; cursor: pointer; }}
h1 {{ font-size: 20px; line-height: 1.35; font-weight: 650; margin: 14px 0 12px; }}
.canal {{ display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }}
.avatar {{ width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; color: white; background: {color}; flex: 0 0 auto; }}
.nombre {{ font-weight: 650; }}
.sub {{ color: #aaaaaa; font-size: 13px; margin-top: 2px; }}
.descripcion {{ white-space: pre-wrap; background: #1a1a1a; border-radius: 12px; padding: 14px 16px; color: #dedede; font-size: 14px; line-height: 1.45; }}
.tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
.tag {{ background: #272727; color: #3ea6ff; border-radius: 12px; padding: 4px 10px; font-size: 13px; }}
.lado h2 {{ font-size: 15px; margin: 0 0 8px; }}
.lista {{ list-style: none; margin: 0; padding: 8px; background: #1a1a1a; border-radius: 12px; max-height: 520px; overflow: auto; }}
.item {{ padding: 10px 12px; border-radius: 8px; }}
.item.ahora {{ background: #2a2a2a; }}
.kicker {{ color: #aaaaaa; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 3px; }}
.aviso {{ margin-top: 18px; color: #9a9a9a; font-size: 13px; line-height: 1.45; }}
</style>
</head>
<body>
<div class="sala">
  <div class="marca">Ensayo local · no sale de esta computadora</div>
  <div class="layout">
    <section>
      <div class="player">
        <video id="vivo" src="/programa.mp4" playsinline preload="auto"></video>
        <div class="badge" id="badge">EN VIVO</div>
        <div class="reloj" id="reloj">00:00</div>
        <button class="entrar" id="entrar" type="button" hidden>Sumarme al vivo</button>
      </div>
      <h1>{html.escape(ficha["titulo"])}</h1>
      <div class="canal">
        <div class="avatar">{inicial}</div>
        <div>
          <div class="nombre">{html.escape(ficha["canal"])}</div>
          <div class="sub">{html.escape(cuenta_txt)} · presenta {html.escape(ficha["presentador"])} · {html.escape(ficha["fecha"])}</div>
        </div>
      </div>
      <div class="descripcion">{html.escape(ficha["descripcion"])}</div>
      <div class="tags">{tags}</div>
      <p class="aviso">Esto es el directo con los videos de las notas y la voz del presentador. Solo se ve en esta computadora: no se abrió YouTube. Al cortar con Ctrl+C se borran los archivos que se descargaron.</p>
    </section>
    <aside class="lado">
      <h2>En este vivo</h2>
      <ul class="lista">{''.join(filas)}</ul>
    </aside>
  </div>
</div>
<script id="ficha" type="application/json">{datos}</script>
<script>
const ficha = JSON.parse(document.getElementById("ficha").textContent);
const video = document.getElementById("vivo");
const badge = document.getElementById("badge");
const reloj = document.getElementById("reloj");
const boton = document.getElementById("entrar");
const items = Array.from(document.querySelectorAll("[data-inicio]"));
let ancla = null;
let base = 0;
let traba = false;
let ultimo = null;

function formato(segundos) {{
  const s = Math.max(0, Math.floor(segundos));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}}
function tope() {{
  return Math.max(0, (video.duration || ficha.duracion) - 0.25);
}}
function esperado() {{
  if (ancla === null) return base;
  return base + (performance.now() - ancla) / 1000;
}}
function marcar(tiempo) {{
  let activo = items[0];
  items.forEach((item) => {{
    if (Number(item.dataset.inicio) <= tiempo + 0.05) activo = item;
  }});
  items.forEach((item) => item.classList.toggle("ahora", item === activo));
  if (activo && activo !== ultimo) {{
    ultimo = activo;
    activo.scrollIntoView({{ block: "nearest" }});
  }}
}}
function cerrar() {{
  badge.textContent = "FINALIZÓ";
  badge.classList.add("fin");
  boton.hidden = true;
}}
function tick() {{
  const t = video.currentTime || 0;
  reloj.textContent = formato(t);
  marcar(t);
  if (video.ended || t >= ficha.duracion - 0.2) cerrar();
  requestAnimationFrame(tick);
}}
async function enganchar(desdeClick) {{
  const estado = await fetch("/estado").then((r) => r.json());
  const limite = tope();
  base = Math.min(Math.max(0, estado.elapsed), limite);
  if (estado.status === "complete" || base >= limite) {{
    video.currentTime = limite;
    cerrar();
    return;
  }}
  video.currentTime = base;
  try {{
    await video.play();
    ancla = performance.now();
    boton.hidden = true;
  }} catch (error) {{
    if (!desdeClick) boton.hidden = false;
  }}
}}
boton.addEventListener("click", () => enganchar(true));
video.addEventListener("playing", () => {{
  ancla = performance.now();
  base = video.currentTime;
  boton.hidden = true;
}});
video.addEventListener("seeking", () => {{
  if (traba || ancla === null) return;
  const debe = esperado();
  if (Math.abs(video.currentTime - debe) > 1.4) {{
    traba = true;
    video.currentTime = Math.min(Math.max(0, debe), tope());
    traba = false;
  }}
}});
video.addEventListener("loadedmetadata", () => {{
  enganchar(false);
  requestAnimationFrame(tick);
}});
</script>
</body>
</html>
"""


class _Emision:
    def __init__(self, ficha, video_path, iniciado):
        self.ficha = ficha
        self.video_path = video_path
        self.iniciado = iniciado


def _handler(emision):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if args and str(args[0]).startswith("GET / "):
                print("  Alguien abrió el ensayo en esta computadora.")

        def do_GET(self):
            ruta = self.path.split("?", 1)[0]
            try:
                if ruta == "/":
                    cuerpo = pagina_html(emision.ficha).encode("utf-8")
                    self._bytes(200, "text/html; charset=utf-8", cuerpo)
                elif ruta == "/ficha.json":
                    cuerpo = json.dumps(emision.ficha, ensure_ascii=False).encode("utf-8")
                    self._bytes(200, "application/json; charset=utf-8", cuerpo)
                elif ruta == "/estado":
                    elapsed = time.monotonic() - emision.iniciado
                    duracion = emision.ficha["duracion"]
                    cuerpo = json.dumps({
                        "status": "complete" if elapsed >= duracion else "live",
                        "elapsed": round(max(0, elapsed), 3),
                        "duracion": duracion,
                        "titulo": emision.ficha["titulo"],
                        "canal": emision.ficha["canal"],
                        "cuenta": emision.ficha["cuenta"],
                    }).encode("utf-8")
                    self._bytes(200, "application/json; charset=utf-8", cuerpo)
                elif ruta == "/programa.mp4":
                    self._video(emision.video_path)
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _bytes(self, status, content_type, cuerpo):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _video(self, path):
            size = os.path.getsize(path)
            start, end = 0, size - 1
            status = 200
            rango = self.headers.get("Range")
            if rango and rango.startswith("bytes="):
                spec = rango.split("=", 1)[1].split(",")[0].strip()
                left, _, right = spec.partition("-")
                if left == "":
                    start = max(0, size - int(right or "0"))
                else:
                    start = int(left)
                    end = int(right) if right else size - 1
                if start >= size or start < 0:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(path, "rb") as handle:
                handle.seek(start)
                restante = length
                while restante > 0:
                    chunk = handle.read(min(65536, restante))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    restante -= len(chunk)

    return Handler


def servir(ficha, video_path, puerto=8765, abrir=True, carpeta=None):
    """Publica el directo solo en 127.0.0.1. Al cortar, borra la carpeta de trabajo."""
    emision = _Emision(ficha, video_path, time.monotonic())
    try:
        server = ThreadingHTTPServer(("127.0.0.1", puerto), _handler(emision))
    except OSError as exc:
        raise RuntimeError(
            f"El puerto {puerto} está ocupado. Probá con --puerto {puerto + 1}."
        ) from exc
    url = f"http://127.0.0.1:{puerto}/"
    print("")
    print("Directo al aire, solo en esta computadora.")
    print(f"  Canal:  {ficha['canal']} (cuenta {ficha['cuenta']})")
    print(f"  Título: {ficha['titulo']}")
    print(f"  Mirá:   {url}")
    print("  Se reproducen los videos de las notas. No se abrió YouTube.")
    print("  Ctrl+C corta y borra lo descargado.")
    print("")
    if abrir:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDirecto cortado. Borrando los videos descargados.")
    finally:
        server.server_close()
        if carpeta:
            _cleanup_dir(carpeta)
    return url
