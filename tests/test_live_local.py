# -*- coding: utf-8 -*-
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import script_director
import tts_engine
from config import TEMP_AUDIO_DIR
from live_local import _Emision, _handler, aplicar_cuenta, ficha_publica, pagina_html
from live_orchestrator import armar_emision, prepare_show
from ffmpeg_tools import probe_duration


def _nota_mp4(path, segundos=2):
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={segundos}",
            "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000",
            "-t", str(segundos), "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _voz_falsa(text, voice_key, filename, rate="+0%"):
    dest = os.path.join(TEMP_AUDIO_DIR, filename)
    os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "1.2", "-q:a", "6", "-acodec", "libmp3lame", dest,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dest


def _show(video_url, cuenta=1):
    payload = aplicar_cuenta({
        "pais": "py",
        "live_id": "py-ensayo-video",
        "videos": [
            {
                "article_id": "a",
                "titulo": "El Congreso retoma el presupuesto",
                "categoria": "politica",
                "video_url": video_url,
                "descripcion": "La cámara vuelve a tratar el proyecto.",
            },
            {
                "article_id": "b",
                "titulo": "El dólar abre estable",
                "categoria": "economia",
                "video_url": video_url,
            },
        ],
    }, cuenta=cuenta)
    return prepare_show(payload, random.Random(3), with_script=False)


class EnsayoLocalTests(unittest.TestCase):
    def setUp(self):
        self._gemini = script_director._ask_gemini
        self._voz = tts_engine.generate_audio_clip
        script_director._ask_gemini = lambda *args, **kwargs: None
        tts_engine.generate_audio_clip = _voz_falsa

    def tearDown(self):
        script_director._ask_gemini = self._gemini
        tts_engine.generate_audio_clip = self._voz

    def test_la_ficha_nombra_las_notas(self):
        show = _show("https://cdn.ejemplo/a.mp4", cuenta=1)
        show["package"] = script_director.compose(
            show["meta"], show["rundown"]["blocks"], show["anchor"], random.Random(3)
        )
        segmentos = [
            {"kind": "intro", "titulo": "Apertura", "categoria": "apertura", "starts_at": 0, "duration": 2},
            {"kind": "news", "titulo": "El Congreso retoma el presupuesto", "categoria": "política", "starts_at": 2, "duration": 8},
            {"kind": "outro", "titulo": "Cierre", "categoria": "cierre", "starts_at": 10, "duration": 2},
        ]
        ficha = ficha_publica(show, segmentos)
        self.assertEqual(ficha["canal"], "Noticias Lat Última Hora")
        self.assertEqual(ficha["cuenta"], 1)
        self.assertEqual([item["kind"] for item in ficha["segmentos"]], ["intro", "nota", "outro"])
        html = pagina_html(ficha)
        self.assertIn("El Congreso retoma el presupuesto", html)
        self.assertIn("videos de las notas", html)
        datos = json.loads(html.split('id="ficha" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(datos["cuenta"], 1)

    def test_reproduce_el_mp4_y_borra_la_descarga(self):
        with tempfile.TemporaryDirectory() as tmp:
            nota = os.path.join(tmp, "nota.mp4")
            _nota_mp4(nota, segundos=2)
            show = _show(nota, cuenta=0)
            carpeta = os.path.join(tmp, "emision")
            segmentos, programa = armar_emision(show, random.Random(3), carpeta)
            noticias = [item for item in segmentos if item["kind"] == "news"]
            self.assertEqual(len(noticias), 2)
            self.assertGreater(noticias[0]["duration"], 1.5)
            self.assertGreater(probe_duration(programa), noticias[0]["duration"] + 1)
            self.assertEqual(os.listdir(carpeta), ["programa.mp4"])
            self.assertFalse(any(name.startswith("nota_") for name in os.listdir(carpeta)))

    def test_el_navegador_recibe_el_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "programa.mp4")
            _nota_mp4(video, segundos=1)
            tamano = os.path.getsize(video)
            ficha = {
                "duracion": 1,
                "titulo": "Noticias Lat: resumen en vivo",
                "canal": "Noticias Lat",
                "cuenta": 0,
                "descripcion": "",
                "tags": [],
                "presentador": "Mateo",
                "fecha": "hoy",
                "segmentos": [],
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(_Emision(ficha, video, 0)))
            puerto = server.server_address[1]
            hilo = threading.Thread(target=server.serve_forever, daemon=True)
            hilo.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/") as pagina:
                    self.assertEqual(pagina.status, 200)
                    self.assertIn(b"/programa.mp4", pagina.read())
                pedido = urllib.request.Request(
                    f"http://127.0.0.1:{puerto}/programa.mp4",
                    headers={"Range": "bytes=0-"},
                )
                with urllib.request.urlopen(pedido) as respuesta:
                    cuerpo = respuesta.read()
                    self.assertEqual(respuesta.status, 206)
                    self.assertEqual(len(cuerpo), tamano)
                    self.assertIn(b"ftyp", cuerpo[:32])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
