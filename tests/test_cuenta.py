# -*- coding: utf-8 -*-
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import script_director
from config import requested_account
from live_orchestrator import prepare_show
from rundown_builder import PayloadError


def _nota():
    return {
        "article_id": "1",
        "titulo": "El Congreso retoma el presupuesto",
        "categoria": "politica",
        "video_url": "https://cdn.ejemplo/1.mp4",
    }


class CuentaTests(unittest.TestCase):
    def test_sin_cuenta_rota(self):
        self.assertIsNone(requested_account({}))
        self.assertIsNone(requested_account({"cuenta": None, "canal": "Noticias Lat"}))

    def test_elige_la_cuenta_del_admin(self):
        self.assertEqual(requested_account({"cuenta": 0}), 0)
        self.assertEqual(requested_account({"cuenta": "3"}), 3)
        self.assertEqual(requested_account({"canal_id": 2}), 2)

    def test_ignora_vacio_y_usa_el_siguiente(self):
        self.assertEqual(requested_account({"cuenta": "", "canal_id": 1}), 1)

    def test_fuera_de_rango(self):
        with self.assertRaises(ValueError):
            requested_account({"cuenta": 9})


class PrepareCuentaTests(unittest.TestCase):
    def setUp(self):
        self._original = script_director._ask_gemini
        script_director._ask_gemini = lambda *args, **kwargs: None

    def tearDown(self):
        script_director._ask_gemini = self._original

    def test_sin_nombre_usa_el_canal_de_la_cuenta(self):
        show = prepare_show({"pais": "py", "cuenta": 2, "videos": [_nota()]}, random.Random(1))
        self.assertEqual(show["cuenta"], 2)
        self.assertEqual(show["meta"]["canal"], "Noticias Lat Ahora")

    def test_respeta_el_json_de_lfaftechapi(self):
        show = prepare_show({
            "pais": "py",
            "canal": "Noticias Lat",
            "cuenta": 0,
            "canal_id": 0,
            "live_id": "py-c0-ensayo",
            "videos": [_nota()],
        }, random.Random(1))
        self.assertEqual(show["cuenta"], 0)
        self.assertEqual(show["live_id"], "py-c0-ensayo")
        self.assertEqual(show["meta"]["canal"], "Noticias Lat")
        self.assertIn("Noticias Lat", show["package"]["intro_text"])

    def test_cuenta_inexistente(self):
        with self.assertRaises(PayloadError):
            prepare_show({"pais": "py", "cuenta": 40, "videos": [_nota()]}, random.Random(1))


if __name__ == "__main__":
    unittest.main()
