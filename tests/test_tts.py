# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tts_engine
from config import TEMP_AUDIO_DIR, VOICES
from edge_tts.exceptions import NoAudioReceived
from tts_engine import _async_generate_audio, _version_de, asegurar_edge_tts, generate_audio_clip


class VersionEdgeTests(unittest.TestCase):
    def test_lee_la_version_instalada(self):
        self.assertGreaterEqual(_version_de("edge-tts"), (7, 3, 1))

    def test_no_reinstala_si_ya_es_nueva(self):
        with patch("tts_engine.subprocess.run") as correr:
            asegurar_edge_tts()
            correr.assert_not_called()

    def test_la_vieja_se_actualiza_antes_de_hablar(self):
        versiones = iter([(7, 2, 8), (7, 3, 1)])

        def falsa(_paquete):
            return next(versiones)

        with patch("tts_engine._version_de", side_effect=falsa), patch(
            "tts_engine.subprocess.run"
        ) as correr, patch("tts_engine.importlib.invalidate_caches"):
            self.assertEqual(asegurar_edge_tts(), (7, 3, 1))
        correr.assert_called_once()
        comando = correr.call_args.args[0]
        self.assertIn("edge-tts>=7.3.1", comando)


class RespaldoTests(unittest.TestCase):
    def test_hombre_2_es_gonzalo(self):
        self.assertEqual(VOICES["hombre_2"], "es-CO-GonzaloNeural")

    def test_si_la_voz_no_existe_usa_otra(self):
        ruta = os.path.join(TEMP_AUDIO_DIR, "respaldo_tts.mp3")
        usadas = []

        class Falsa:
            def __init__(self, text, voice, rate="+0%"):
                self.voice = voice
                usadas.append(voice)

            async def save(self, path):
                if self.voice == "es-CO-TomasNeural":
                    raise NoAudioReceived("No audio was received.")
                with open(path, "wb") as handle:
                    handle.write(b"a" * 200)

        with patch("edge_tts.Communicate", Falsa):
            ok = asyncio.run(
                _async_generate_audio("hola", "es-CO-TomasNeural", ruta, "+12%")
            )
        self.assertTrue(ok)
        self.assertEqual(usadas[:2], ["es-CO-TomasNeural", "es-MX-DaliaNeural"])
        self.assertGreater(os.path.getsize(ruta), 100)
        os.remove(ruta)

    def test_el_403_no_cambia_de_voz(self):
        class Falsa:
            def __init__(self, text, voice, rate="+0%"):
                self.voice = voice

            async def save(self, path):
                raise RuntimeError("403, message='Invalid response status'")

        with patch("edge_tts.Communicate", Falsa):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    _async_generate_audio("hola", "es-CO-GonzaloNeural", "no.mp3", "+0%")
                )


class VozRealTests(unittest.TestCase):
    def test_edge_responde_la_locucion(self):
        ruta = generate_audio_clip(
            "Hola, esto es una prueba corta.", "hombre_2", "prueba_tts.mp3", rate="+12%"
        )
        self.assertTrue(ruta and os.path.exists(ruta))
        self.assertGreater(os.path.getsize(ruta), 1000)
        os.remove(ruta)


if __name__ == "__main__":
    unittest.main()
