# -*- coding: utf-8 -*-
"""Preview HTTP y mezcla real de voz sobre el video del presentador."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import script_director
from app import app
from config import ADMIN_API_KEY, TEMPLATES_DIR
from ffmpeg_tools import make_thumbnail, probe_duration, render_voice_bed, write_concat_playlist


def _payload():
    videos = []
    categorias = ["politica"] * 3 + ["economia"] * 3 + ["deportes"] * 2 + ["salud", "tecnologia"]
    for i, categoria in enumerate(categorias, start=1):
        videos.append({
            "article_id": f"n{i}",
            "titulo": f"Nota {i} de {categoria}",
            "categoria": categoria,
            "video_url": f"https://cdn.ejemplo/{i}.mp4",
        })
    return {"pais": "py", "canal": "Noticias LAT", "videos": videos}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self._original = script_director._ask_gemini
        script_director._ask_gemini = lambda *args, **kwargs: None
        self.client = app.test_client()

    def tearDown(self):
        script_director._ask_gemini = self._original

    def test_preview_arma_el_vivo_sin_abrir_youtube(self):
        response = self.client.post(
            "/live/preview",
            json=_payload(),
            headers={"x-api-key": ADMIN_API_KEY},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["pais"], "Paraguay")
        self.assertIn("septiembre", data["fecha"])
        self.assertEqual(data["bloques"][0]["categoria"], "politica")
        self.assertEqual(len(data["bloques"][0]["videos"]), 3)
        self.assertEqual(data["bloques"][1]["categoria"], "economia")
        self.assertIn("economía", data["bridges"][0])
        self.assertTrue(data["intro_text"])
        self.assertTrue(data["youtube_title"])

    def test_sin_clave_no_entra(self):
        response = self.client.post("/live/preview", json=_payload())
        self.assertEqual(response.status_code, 403)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ffmpeg"])


class FfmpegVoiceTests(unittest.TestCase):
    def test_la_voz_entra_sobre_el_video_del_presentador(self):
        folder = os.path.join(TEMPLATES_DIR, "hombre")
        videos = [os.path.join(folder, name) for name in os.listdir(folder)] if os.path.isdir(folder) else []
        videos = [path for path in videos if path.endswith(".mp4")]
        if not videos:
            self.skipTest("No hay video de presentador en assets.")

        with tempfile.TemporaryDirectory() as tmp:
            voice = os.path.join(tmp, "voz.mp3")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "2", "-q:a", "6", "-acodec", "libmp3lame", voice,
                ],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            out_a = os.path.join(tmp, "puente_a.ts")
            out_b = os.path.join(tmp, "puente_b.ts")
            self.assertTrue(render_voice_bed(videos[0], voice, None, None, out_a, still_image=False))
            self.assertTrue(render_voice_bed(videos[-1], voice, None, None, out_b, still_image=False))
            duration = probe_duration(out_a)
            self.assertGreater(duration, 1.2)
            self.assertLess(duration, 4.0)

            playlist = write_concat_playlist([out_a, out_b], os.path.join(tmp, "lista.txt"))
            merged = os.path.join(tmp, "bloque.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", playlist, "-c", "copy", merged],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.assertGreater(probe_duration(merged), duration + 1.0)

            thumb = os.path.join(tmp, "thumb.jpg")
            self.assertTrue(make_thumbnail("Paraguay", "30 de septiembre", thumb, ""))
            self.assertGreater(os.path.getsize(thumb), 1000)


if __name__ == "__main__":
    unittest.main()
