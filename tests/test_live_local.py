# -*- coding: utf-8 -*-
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import script_director
from live_local import aplicar_cuenta, ficha_publica, pagina_html, plan_local, render_programa
from live_orchestrator import prepare_show


def _show(cuenta=1):
    payload = aplicar_cuenta({
        "pais": "py",
        "live_id": "py-ensayo",
        "videos": [
            {
                "article_id": "a",
                "titulo": "El Congreso retoma el presupuesto",
                "categoria": "politica",
                "video_url": "https://cdn.ejemplo/a.mp4",
                "descripcion": "La cámara vuelve a tratar el proyecto.",
            },
            {
                "article_id": "b",
                "titulo": "El dólar abre estable",
                "categoria": "economia",
                "video_url": "https://cdn.ejemplo/b.mp4",
            },
        ],
    }, cuenta=cuenta)
    return prepare_show(payload, random.Random(3))


class EnsayoLocalTests(unittest.TestCase):
    def setUp(self):
        self._original = script_director._ask_gemini
        script_director._ask_gemini = lambda *args, **kwargs: None

    def tearDown(self):
        script_director._ask_gemini = self._original

    def test_la_ficha_tiene_titulo_y_canal(self):
        show = _show(cuenta=1)
        segmentos = plan_local(show, segundos_nota=4, segundos_puente=4, segundos_intro=6, segundos_outro=6)
        ficha = ficha_publica(show, segmentos)
        self.assertEqual(ficha["canal"], "Noticias Lat Última Hora")
        self.assertEqual(ficha["cuenta"], 1)
        self.assertEqual(ficha["pais"], "Paraguay")
        self.assertTrue(ficha["titulo"])
        self.assertIn("Paraguay", ficha["titulo"] + ficha["descripcion"])
        kinds = [item["kind"] for item in segmentos]
        self.assertEqual(kinds, ["intro", "nota", "puente", "nota", "outro"])
        self.assertGreater(segmentos[-1]["starts_at"], segmentos[0]["duration"])
        html = pagina_html(ficha)
        self.assertIn(ficha["titulo"], html)
        self.assertIn("Noticias Lat Última Hora", html)
        self.assertIn("esta computadora", html)
        datos = json.loads(html.split('id="ficha" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(datos["cuenta"], 1)

    def test_arma_un_programa_corto(self):
        show = _show(cuenta=0)
        segmentos = plan_local(show, segundos_nota=2, segundos_puente=2, segundos_intro=2, segundos_outro=2)
        with tempfile.TemporaryDirectory() as tmp:
            programa = render_programa(segmentos, tmp)
            self.assertGreater(os.path.getsize(programa), 5000)


if __name__ == "__main__":
    unittest.main()
