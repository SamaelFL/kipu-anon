"""Compara evals/texto.py contra la logica real del validador (via node).
Uso: python3 evals/test_texto.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import texto
from ref_texto import correr_node

ZW = "\u200b"
CASOS = [
    # (haystack, needle, digitos_o_None)
    ("Hola, soy MANUELA CASTAÑO y pago", "Manuela Castaño", None),
    ("MANUELA CASTANO", "Manuela Castaño", None),
    ("Manuela    Castaño", "manuela castaño", None),
    ("M" + ZW + "anuela Cast" + ZW + "año", "Manuela Castaño", None),
    ("Мanuela Castaño", "Manuela Castaño", None),          # M cirilica
    ("Manuela Castano Ruiz", "Manuela Castaño Ruiz", None),
    ("manuela_castano", "manuela_castano", None),
    ("manuela castano", "manuela_castano", None),
    ("Manuelita Castaño", "Manuela Castaño", None),
    ("Nequi y Bancolombia", "Nequi", None),
    ("nequixyz", "Nequi", None),
    ("mcastano@gmail.com", "mcastano@gmail.com", None),
    ("MCASTANO@GMAIL.COM", "mcastano@gmail.com", None),
    ("escribe a mcastano arroba gmail punto com", "mcastano@gmail.com", None),
    ("cédula 1.107.360.039 gracias", "1107360039", "1107360039"),
    ("cédula 1 107 360 039 gracias", "1.107.360.039", "1107360039"),
    ("cc 1-107-360-039", "1107360039", "1107360039"),
    ("cc 1107360040", "1107360039", "1107360039"),
    ("cc 11073600391", "1107360039", "1107360039"),
    ("celular +57 314 872 9552", "3148729552", "3148729552"),
    ("celular 573148729552", "3148729552", "3148729552"),
    ("celular 57-314-872-9552", "314 872 9552", "3148729552"),
    ("tel 314\u00a0872\u00a09552", "3148729552", "3148729552"),
    ("tel 3\u200b148729552", "3148729552", "3148729552"),
    ("tel ３１４８７２９５５２", "3148729552", "3148729552"),   # ancho completo
    ("placa JXA-971 del carro", "JXA-971", None),
    ("placa jxa 971", "JXA-971", None),
    ("placa JXA971", "JXA-971", None),
    ("pasaporte AR752831", "AR752831", None),
    ("pasaporte AR 752 831", "AR752831", None),
    ("Diagonal 3A # 78-6 apto 1501", "Diagonal 3A # 78-6 apto 1501", None),
    ("diagonal 3a # 78-6 apto 1501", "Diagonal 3A # 78-6 apto 1501", None),
    ("nació el 1997-07-23", "1997-07-23", None),
    ("nació el 23/07/1997", "1997-07-23", None),
    ("Straße STRASSE", "strasse", None),
    ("ΟΡΤΑ", "orta", None),
    ("Santander", "Luis Santander", None),
    ("señor Santander llamó", "Santander", None),
    ("ﬁnanciera", "financiera", None),                      # ligadura NFKC
    ("Ca\u0301mila Arango", "Camila Arango", None),         # tilde combinante
]


def main():
    esperado = correr_node([{"h": h, "n": n, "d": d} for h, n, d in CASOS])
    fallos = 0
    for (h, n, d), e in zip(CASOS, esperado):
        mio = {
            "clean": texto.clean(h), "norm": texto.norm(h),
            "compactos": texto.digitos_compactos(h),
            "contiene": texto.contiene(h, n),
            "digitosEn": texto.digitos_en(h, d) if d else None,
        }
        for k in mio:
            if mio[k] != e[k]:
                fallos += 1
                print(f"DIFIERE {k}: h={h!r} n={n!r} py={mio[k]!r} node={e[k]!r}")
    print(f"{len(CASOS)} casos x 5 funciones, {fallos} diferencias")
    return 1 if fallos else 0


class TestTextoContraNode(unittest.TestCase):
    def test_igual_que_validar_mjs(self):
        self.assertEqual(main(), 0)


if __name__ == "__main__":
    sys.exit(main())
