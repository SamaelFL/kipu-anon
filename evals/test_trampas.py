"""Cada trampa generada existe en fuentes/ (record y payload). Se salta sin fuentes/."""
import os
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import gen_trampas  # noqa: E402

FUENTES = os.path.join(AQUI, "..", "fuentes")


@unittest.skipUnless(os.path.isdir(FUENTES), "sin fuentes/")
class TestTrampas(unittest.TestCase):
    def test_trampas_verificadas(self):
        with tempfile.TemporaryDirectory() as d:
            salida = os.path.join(d, "t.jsonl")
            old = sys.argv
            sys.argv = ["gen", "--input", FUENTES, "--out", salida]
            try:
                self.assertEqual(gen_trampas.main(), 0)
                casos = gen_trampas.cargar(salida)
            finally:
                sys.argv = old
            self.assertGreaterEqual(len(casos), 60)


if __name__ == "__main__":
    unittest.main()
