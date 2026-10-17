# -*- coding: utf-8 -*-
"""
Ensayo del directo en la computadora local.

Usa el mismo JSON que lfaftechapi manda a POST /live/start, arma título,
canal y escaleta con el motor real, y lo muestra en 127.0.0.1.
No abre YouTube, no descarga las notas y no avisa a la API.
"""

import html
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from config import ADMIN_API_KEY, FONT_PATH, MAIN_API_URL
from ffmpeg_tools import probe_duration, write_concat_playlist

_FUENTES = [
    FONT_PATH,
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/macos/Inter-Bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def fuente_disponible():
    for path in _FUENTES:
        if path and os.path.exists(path):
            return path
    return None


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


def _plano(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def _lineas(texto, ancho, maximo):
    palabras = _plano(texto).split()
    if not palabras:
        return ""
    filas = []
    actual = ""
    for palabra in palabras:
        propuesta = palabra if not actual else actual + " " + palabra
        if len(propuesta) > ancho and actual:
            filas.append(actual)
            actual = palabra
        else:
            actual = propuesta
        if len(filas) >= maximo:
            break
    if len(filas) < maximo and actual:
        filas.append(actual)
    return "\n".join(filas[:maximo])


def _duracion(base, texto, piso, techo):
    estimado = base + max(0, len(_plano(texto)) - 80) / 28
    return round(min(techo, max(piso, estimado)), 2)


def plan_local(show, segundos_nota=6, segundos_puente=5, segundos_intro=9, segundos_outro=8):
    """Placas del ensayo, en el mismo orden en que saldría el directo."""
    package = show["package"]
    blocks = show["rundown"]["blocks"]
    pais = show["meta"]["pais_nombre"]
    canal = show["meta"]["canal"]
    segmentos = []
    clock = 0.0

    def agregar(kind, titulo, texto, categoria, base, piso, techo):
        nonlocal clock
        duration = _duracion(base, texto, piso, techo)
        segmentos.append({
            "kind": kind,
            "titulo": titulo,
            "texto": texto,
            "categoria": categoria,
            "pais": pais,
            "canal": canal,
            "starts_at": round(clock, 2),
            "duration": duration,
        })
        clock += duration

    agregar("intro", pais, package["intro_text"], "apertura", segundos_intro, 6, 16)
    bridge_i = 0
    for index, block in enumerate(blocks):
        if index > 0:
            bridges = package["bridges"]
            if bridge_i < len(bridges):
                texto = bridges[bridge_i]
            else:
                texto = f"Ahora pasamos a {block['label']}."
            bridge_i += 1
            agregar("puente", block["label"].capitalize(), texto, block["label"], segundos_puente, 4, 10)
        for video in block["videos"]:
            texto = video.get("descripcion") or video["titulo"]
            agregar("nota", video["titulo"], texto, block["label"], segundos_nota, 3, 20)
    agregar("outro", canal, package["outro_text"], "cierre", segundos_outro, 6, 14)
    return segmentos


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
                "kind": item["kind"],
                "titulo": item["titulo"],
                "categoria": item["categoria"],
                "starts_at": item["starts_at"],
                "duration": item["duration"],
            }
            for item in segmentos
        ],
    }


def _ff_ruta(path):
    texto = os.path.abspath(path).replace("\\", "/")
    return texto.replace(":", "\\:").replace("'", r"\'")


def _escribir(path, texto):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(texto if texto else " ")


def _clip(segmento, destino, fuente, indice, carpeta):
    colores = {
        "intro": "0x0B1F3A",
        "puente": "0x1C1408",
        "nota": "0x121212",
        "outro": "0x0B1F3A",
    }
    kicker = {
        "intro": "APERTURA",
        "puente": "AHORA",
        "nota": segmento["categoria"].upper(),
        "outro": "CIERRE",
    }.get(segmento["kind"], "EN VIVO")
    if segmento["kind"] == "nota":
        kicker = f"{segmento['pais'].upper()} · {kicker}"

    kicker_path = os.path.join(carpeta, f"kicker_{indice}.txt")
    titulo_path = os.path.join(carpeta, f"titulo_{indice}.txt")
    cuerpo_path = os.path.join(carpeta, f"cuerpo_{indice}.txt")
    pie_path = os.path.join(carpeta, f"pie_{indice}.txt")
    _escribir(kicker_path, kicker)
    _escribir(titulo_path, _lineas(segmento["titulo"], 32, 3))
    _escribir(cuerpo_path, _lineas(segmento["texto"], 52, 4))
    _escribir(pie_path, segmento["canal"])

    font = _ff_ruta(fuente)
    vf = ",".join([
        "drawbox=x=0:y=0:w=14:h=ih:color=0xE10600:t=fill",
        "drawbox=x=36:y=28:w=132:h=40:color=0xE10600:t=fill",
        f"drawtext=expansion=none:fontfile='{font}':text='EN VIVO':fontcolor=white:fontsize=22:x=52:y=36",
        f"drawtext=expansion=none:fontfile='{font}':textfile='{_ff_ruta(kicker_path)}':fontcolor=0xF5C518:fontsize=26:x=72:y=150",
        f"drawtext=expansion=none:fontfile='{font}':textfile='{_ff_ruta(titulo_path)}':fontcolor=white:fontsize=42:line_spacing=8:x=72:y=200",
        f"drawtext=expansion=none:fontfile='{font}':textfile='{_ff_ruta(cuerpo_path)}':fontcolor=0xD0D0D0:fontsize=26:line_spacing=8:x=72:y=430",
        f"drawtext=expansion=none:fontfile='{font}':textfile='{_ff_ruta(pie_path)}':fontcolor=0x9AA0A6:fontsize=22:x=72:y=660",
    ])
    segundos = f"{segmento['duration']:.2f}"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={colores.get(segmento['kind'], '0x121212')}:s=1280x720:r=30:d={segundos}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", vf,
        "-t", segundos,
        "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-g", "60", "-keyint_min", "60",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
        destino,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    except subprocess.CalledProcessError as exc:
        detalle = (exc.stderr or b"").decode("utf-8", errors="ignore")[-500:]
        raise RuntimeError(f"FFmpeg no armó la placa {indice}: {detalle}") from exc
    if not os.path.exists(destino) or os.path.getsize(destino) < 1000:
        raise RuntimeError(f"La placa {indice} quedó vacía.")
    return destino


def render_programa(segmentos, carpeta):
    fuente = fuente_disponible()
    if not fuente:
        raise RuntimeError("No encontré una fuente para las placas. Hace falta assets_video/fonts/ARIALBD.TTF.")
    if not shutil_which("ffmpeg"):
        raise RuntimeError("No está ffmpeg en el PATH. Sin eso no puedo armar el ensayo.")
    os.makedirs(carpeta, exist_ok=True)
    partes = []
    for indice, segmento in enumerate(segmentos):
        destino = os.path.join(carpeta, f"placa_{indice:02d}.mp4")
        _clip(segmento, destino, fuente, indice, carpeta)
        partes.append(destino)
    programa = os.path.join(carpeta, "programa.mp4")
    lista = write_concat_playlist(partes, os.path.join(carpeta, "lista.txt"))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", lista,
        "-c", "copy", "-movflags", "+faststart",
        programa,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
    except subprocess.CalledProcessError as exc:
        detalle = (exc.stderr or b"").decode("utf-8", errors="ignore")[-500:]
        raise RuntimeError(f"No pude unir el ensayo: {detalle}") from exc
    if probe_duration(programa) < 1:
        raise RuntimeError("El ensayo quedó sin duración.")
    return programa


def shutil_which(nombre):
    import shutil
    return shutil.which(nombre)


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
      <p class="aviso">Así queda la ficha que iría a YouTube: título, canal y orden. Las placas reemplazan a las notas para poder verlo sin descargar los videos ni abrir el canal. El directo real sigue siendo el que dispara lfaftechapi.</p>
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


def servir(ficha, video_path, puerto=8765, abrir=True):
    """Publica el ensayo solo en 127.0.0.1. El reloj del vivo arranca acá."""
    emision = _Emision(ficha, video_path, time.monotonic())
    try:
        server = ThreadingHTTPServer(("127.0.0.1", puerto), _handler(emision))
    except OSError as exc:
        raise RuntimeError(
            f"El puerto {puerto} está ocupado. Probá con --puerto {puerto + 1}."
        ) from exc
    url = f"http://127.0.0.1:{puerto}/"
    print("")
    print("Ensayo al aire, solo en esta computadora.")
    print(f"  Canal:  {ficha['canal']} (cuenta {ficha['cuenta']})")
    print(f"  Título: {ficha['titulo']}")
    print(f"  Mirá:   {url}")
    print("  No se abrió YouTube y no se avisó a lfaftechapi.")
    print("  Ctrl+C corta el ensayo.")
    print("")
    if abrir:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEnsayo cortado.")
    finally:
        server.server_close()
    return url
