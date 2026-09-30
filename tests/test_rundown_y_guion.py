# -*- coding: utf-8 -*-
"""Escaleta, textos y el JSON que después manda lfaftechapi."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import script_director
from rundown_builder import PayloadError, build_rundown, extract_videos, normalize_category
from script_director import choose_anchor, compose
from youtube_live import _broadcast_body


def _video(i, categoria, titulo=None):
    return {
        "article_id": f"id-{i}",
        "titulo": titulo or f"Titular {categoria} {i}",
        "categoria": categoria,
        "video_url": f"https://cdn.ejemplo/{i}.mp4",
    }


class RundownTests(unittest.TestCase):
    def test_politica_primero_y_despues_economia(self):
        videos = []
        n = 1
        for _ in range(4):
            videos.append(_video(n, "politica"))
            n += 1
        for _ in range(3):
            videos.append(_video(n, "economia"))
            n += 1
        for _ in range(2):
            videos.append(_video(n, "deportes"))
            n += 1
        videos.append(_video(n, "salud"))

        _, explicit = extract_videos({"pais": "py", "videos": videos})
        self.assertIsNone(explicit)
        rundown = build_rundown(videos)
        labels = [(b["categoria"], len(b["videos"]), b["continuacion"]) for b in rundown["blocks"]]
        self.assertEqual(labels[0], ("politica", 3, False))
        self.assertEqual(labels[1][0], "economia")
        self.assertEqual(labels[1][1], 3)
        self.assertEqual(sum(len(b["videos"]) for b in rundown["blocks"]), 10)
        politica_tail = [b for b in rundown["blocks"] if b["categoria"] == "politica"]
        self.assertEqual(len(politica_tail), 2)
        self.assertTrue(politica_tail[1]["continuacion"])

    def test_respeta_bloques_que_manda_lfaf(self):
        payload = {
            "pais": "chile",
            "bloques": [
                {"categoria": "economia", "videos": [_video(1, "otra", "Dolar"), _video(2, "otra", "Salario")]},
                {"categoria": "política", "videos": [_video(3, "otra", "Congreso")]},
            ],
        }
        videos, blocks = extract_videos(payload)
        self.assertEqual(len(videos), 3)
        rundown = build_rundown(videos, explicit_blocks=blocks)
        self.assertEqual([b["categoria"] for b in rundown["blocks"]], ["economia", "politica"])
        self.assertEqual(rundown["blocks"][0]["videos"][0]["titulo"], "Dolar")

    def test_categoria_con_acentos(self):
        self.assertEqual(normalize_category("Economía"), "economia")
        self.assertEqual(normalize_category("Fútbol"), "deportes")
        self.assertEqual(normalize_category(""), "general")

    def test_rechaza_json_sin_videos(self):
        with self.assertRaises(PayloadError):
            extract_videos({"pais": "py"})
        with self.assertRaises(PayloadError):
            extract_videos({"videos": [{"titulo": "sin url"}]})


class GuionTests(unittest.TestCase):
    def setUp(self):
        self._original = script_director._ask_gemini
        script_director._ask_gemini = lambda *args, **kwargs: None

    def tearDown(self):
        script_director._ask_gemini = self._original

    def _show(self, seed):
        videos = [
            _video(1, "politica", "El congreso trata el presupuesto"),
            _video(2, "politica", "Nuevo ministro del interior"),
            _video(3, "politica", "Marcha en el centro"),
            _video(4, "economia", "El dolar abre estable"),
            _video(5, "economia", "Sube el salario minimo"),
            _video(6, "deportes", "La albirroja concentra"),
        ]
        rundown = build_rundown(videos)
        rng = random.Random(seed)
        anchor = choose_anchor(rng, voice_key="mujer_1" if seed % 2 == 0 else "hombre_2")
        meta = {
            "canal": "Noticias LAT",
            "pais_codigo": "py",
            "pais_nombre": "Paraguay",
            "fecha_larga": "miércoles 30 de septiembre de 2026",
            "fecha_corta": "30 de septiembre",
            "video_count": rundown["video_count"],
        }
        return compose(meta, rundown["blocks"], anchor, rng), rundown

    def test_textos_hablan_fecha_canal_y_cambio_de_bloque(self):
        package, rundown = self._show(3)
        self.assertIn("Noticias LAT", package["intro_text"])
        self.assertIn("septiembre", package["intro_text"])
        self.assertIn("Paraguay", package["intro_text"])
        self.assertEqual(len(package["bridges"]), len(rundown["blocks"]) - 1)
        self.assertIn("economía", package["bridges"][0])
        self.assertTrue(package["youtube_title"])
        self.assertIn("Paraguay", package["youtube_description"])
        self.assertLessEqual(len(package["youtube_title"]), 100)

    def test_dos_emisiones_no_dicen_lo_mismo(self):
        intros = set()
        titles = set()
        bridges = set()
        for seed in range(12):
            package, _ = self._show(seed)
            intros.add(package["intro_text"])
            titles.add(package["youtube_title"])
            bridges.add(tuple(package["bridges"]))
        self.assertGreater(len(intros), 1)
        self.assertGreater(len(titles), 1)
        self.assertGreater(len(bridges), 1)

    def test_si_gemini_responde_se_usa_su_texto(self):
        def fake_gemini(*_args, **_kwargs):
            return {
                "youtube_title": "EN VIVO Paraguay: el resumen de este miércoles",
                "youtube_description": "Edición en vivo con política y economía de los últimos días en Paraguay, contada al aire.",
                "youtube_tags": ["paraguay", "en vivo"],
                "intro_text": "Bienvenidos a Noticias LAT. Hoy es miércoles 30 de septiembre de 2026. Soy Camila y arrancamos el vivo de Paraguay con política.",
                "bridges": [
                    "Cerramos política. Ahora pasamos a economía.",
                    "Dejamos economía y entramos en deportes.",
                ],
                "outro_text": "Gracias por estar en Noticias LAT. Cerramos el vivo de Paraguay. Hasta el próximo directo.",
            }

        script_director._ask_gemini = fake_gemini
        package, _ = self._show(1)
        self.assertEqual(package["source"], "gemini")
        self.assertIn("Camila", package["intro_text"])
        self.assertEqual(len(package["bridges"]), 2)


class MonetizacionTests(unittest.TestCase):
    def test_el_vivo_pide_pauta_y_latencia_normal(self):
        body = _broadcast_body("EN VIVO Paraguay", "descripcion", "public", True)
        self.assertTrue(body["monetizationDetails"]["cuepointSchedule"]["enabled"])
        self.assertEqual(body["contentDetails"]["latencyPreference"], "normal")
        self.assertTrue(body["contentDetails"]["enableAutoStart"])
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])

    def test_sin_pauta_no_manda_el_bloque(self):
        body = _broadcast_body("titulo", "descripcion", "unlisted", False)
        self.assertNotIn("monetizationDetails", body)
        self.assertEqual(body["status"]["privacyStatus"], "unlisted")


if __name__ == "__main__":
    unittest.main()
