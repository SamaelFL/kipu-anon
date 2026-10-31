import json
import re
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kipu.formas import (Persona, deletrear, desdeletrear, formas_reales, formatear_como,  # noqa: E402
                         mapear_forma)
from kipu.pseudo import Pseudonimizador  # noqa: E402

# ---- copia en Python de norm/contiene de material/frontier-reto-1/validar.mjs
ESPACIO = r"\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"


def _clean(s):
    s = unicodedata.normalize("NFKC", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Cf")
    s = re.sub(r"[\s\u00a0]", " ", s)
    return re.sub(r" {2,}", " ", s)


def norm(s):
    s = _clean(s)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.lower().replace("ß", "ss")


def contiene(haystack, needle):
    if not needle:
        return False
    dig = re.sub(r"\D", "", needle)
    if dig and len(dig) >= 6 and len(dig) >= 0.6 * len(needle) and not re.search("[a-zA-Z]", needle):
        h = re.sub(r"(?<=\d)[ \t.,'`´·/\-–—_](?=\d)", "", _clean(haystack))
        cands = {dig} | ({dig[2:]} if len(dig) == 12 and dig.startswith("57") else set())
        return any(re.search(rf"(?<!\d)(?:57)?{re.escape(d)}(?!\d)", h) for d in cands)
    h, n = norm(haystack), norm(needle)
    if re.fullmatch(r"[\w .'_-]+", n) and re.search("[a-z]", n):
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h):
            return True
        pal = n.split()
        if len(pal) >= 2 and all(len(w) >= 3 for w in pal):
            return bool(re.search(r"(?<![a-z0-9])" + r"[ ]*".join(map(re.escape, pal)) + r"(?![a-z0-9])", h))
        return False
    return n in h


REALES = ["Manuela Castaño Ruiz", "Pamela Castaño Hoyos", "David Mejía Hoyos", "Ricardo Martínez Gil"]
NUMEROS_REALES = ["1.107.360.039", "1107252808", "3148729552", "+57 318 642 3850", "AR752831", "4471-0211"]


def nuevo(secreto="s3", ruta=None, formas=None):
    ruta = ruta or Path(tempfile.mkdtemp()) / "store.json"
    f = list(formas if formas is not None else [])
    for r in REALES:
        f += formas_reales(r)
    return Pseudonimizador(secreto, ruta, f + NUMEROS_REALES), ruta


class Determinismo(unittest.TestCase):
    def test_entre_instancias(self):
        a, _ = nuevo()
        b, _ = nuevo()
        for k in ("p1", "p2", "p3"):
            self.assertEqual(a.persona(k, "f", 2, 2), b.persona(k, "f", 2, 2))
        self.assertEqual(a.cedula("1.107.360.039"), b.cedula("1.107.360.039"))
        self.assertEqual(a.celular("3148729552"), b.celular("3148729552"))
        self.assertEqual(a.direccion("Cl 98 # 91-10"), b.direccion("Cl 98 # 91-10"))
        self.assertEqual(a.nacimiento("1997-07-23"), b.nacimiento("1997-07-23"))

    def test_secreto_distinto(self):
        a, _ = nuevo("a")
        b, _ = nuevo("b")
        self.assertNotEqual(a.persona("p1", "f", 1, 2), b.persona("p1", "f", 1, 2))

    def test_recarga_del_store(self):
        a, ruta = nuevo()
        p = a.persona("p1", "m", 2, 2)
        a.guardar()
        self.assertTrue(json.loads(Path(ruta).read_text(encoding="utf-8"))["personas"])
        b, _ = nuevo(ruta=ruta)
        self.assertEqual(b.persona("p1", "f", 1, 2), p)  # la llave guardada gana, aunque cambie el género pedido
        self.assertEqual(b.persona("p1", "m", 2, 2), p)
        self.assertEqual(list(Path(ruta).parent.glob("*.tmp")), [])

    def test_unicidad_5000(self):
        a, _ = nuevo()
        vistos = set()
        for i in range(5000):
            p = a.persona(f"k{i}", "f" if i % 2 else "m", 1 + i % 2, 2)
            vistos.add(p.completo.lower())
        self.assertEqual(len(vistos), 5000)

    def test_homonimos_distintos(self):
        a, _ = nuevo()
        self.assertNotEqual(a.persona("ana-1", "f", 1, 2), a.persona("ana-2", "f", 1, 2))


class Genero(unittest.TestCase):
    def test_genero(self):
        a, _ = nuevo()
        self.assertEqual(a.genero("Manuela", []), "f")
        self.assertEqual(a.genero("Santiago", []), "m")
        self.assertEqual(a.genero("Zorbak", ["Contadora Pública"]), "f")
        self.assertEqual(a.genero("Zorbak", ["señor"]), "m")
        self.assertEqual(a.genero("Zorbak", []), a.genero("Zorbak", []))
        self.assertEqual(a.genero("Alexis", ["clienta"]), "f")

    def test_catalogo_del_genero(self):
        a, _ = nuevo()
        m = {x.split()[0] for x in a.mujeres}
        for i in range(200):
            self.assertIn(a.persona(f"g{i}", "f", 1, 2).nombres[0], m | {y for x in a.mujeres for y in x.split()})


class Formatos(unittest.TestCase):
    def setUp(self):
        self.p, _ = nuevo()

    def test_cedula(self):
        for o in ("1.107.360.039", "1107360039", "43062949", "43.062.949"):
            n = self.p.cedula(o)
            self.assertEqual(re.sub(r"\d", "9", n), re.sub(r"\d", "9", o))
            self.assertNotEqual(n, o)

    def test_celular(self):
        for o in ("3148729552", "+57 318 642 3850", "57-3186423850", "318-642-3850"):
            n = self.p.celular(o)
            self.assertEqual(re.sub(r"\d", "9", n), re.sub(r"\d", "9", o))
            core = re.sub(r"\D", "", n)[-10:]
            self.assertRegex(core, r"^3\d{9}$")
            self.assertNotEqual(n, o)

    def test_placa(self):
        for o in ("KFY046", "JXA-971", "jxa971"):
            n = self.p.placa(o)
            self.assertEqual(re.sub(r"[A-Za-z]", "L", re.sub(r"\d", "9", n)), re.sub(r"[A-Za-z]", "L", re.sub(r"\d", "9", o)))
            self.assertNotEqual(n.upper(), o.upper())

    def test_pasaporte(self):
        self.assertRegex(self.p.pasaporte("AR752831"), r"^[A-Z]{2}\d{6}$")

    def test_credito(self):
        n = self.p.credito("4471-0211")
        self.assertRegex(n, r"^4471-\d{4}$")
        self.assertNotEqual(n, "4471-0211")
        self.assertRegex(self.p.credito("4471 0211 8844 1234"), r"^4471 \d{4} \d{4} \d{4}$")

    def test_direccion(self):
        for o in ("Diagonal 3A # 78-6 apto 1501", "Cl 108 # 66-81 casa 52", "Calle 98 Bis # 91-10 of 406",
                  "Tv 105 Sur # 6-45 apto 704", "Cra 113 Sur # 74-2"):
            n = self.p.direccion(o)
            esqueleto = lambda s: re.sub(r"\d+", "N", re.sub(r"(?<=\d)[A-Ea-e]\b", "", s))
            self.assertEqual(esqueleto(n), esqueleto(o))
            self.assertNotEqual(n, o)

    def test_nacimiento(self):
        import datetime as dt
        for o, rx in (("1997-07-23", r"^\d{4}-\d\d-\d\d$"), ("23/07/1997", r"^\d\d/\d\d/\d{4}$"),
                      ("23 de julio de 1997", r"^\d{1,2} de [a-z]+ de \d{4}$")):
            n = self.p.nacimiento(o)
            self.assertRegex(n, rx)
        base = dt.date(1997, 7, 23)
        for k in range(30):
            o = (base + dt.timedelta(days=k * 40)).isoformat()
            n = dt.date.fromisoformat(self.p.nacimiento(o))
            dias = abs((n - dt.date.fromisoformat(o)).days)
            self.assertTrue(365 <= dias <= 365 * 5 + 1, dias)

    def test_barrio(self):
        m = {"Cali": ["Santa Mónica", "Granada", "Ciudad Jardín"], "Bogotá": ["Chapinero", "Usaquén"]}
        for ciudad in ("Cali", "cali"):
            b = self.p.barrio("Granada", ciudad, m)
            self.assertIn(b, m["Cali"])
            self.assertNotEqual(b, "Granada")

    def test_sector(self):
        self.assertEqual(self.p.sector("community manager"), "profesional de medios")
        self.assertEqual(self.p.sector("fotógrafa"), "profesional de las industrias creativas")
        self.assertEqual(self.p.sector("mecánico"), "profesional del transporte")
        self.assertEqual(self.p.sector("astronauta"), self.p.sector_defecto)

    def test_correo(self):
        q = Persona(("Sofía", "Elena"), ("Zambrano", "Naranjo"), "f")
        self.assertEqual(self.p.correo("mcastano@gmail.com", q), "szambrano@gmail.com")
        self.assertEqual(self.p.correo("kelly.castano@kipupay.co", q), "sofia.zambrano@kipupay.co")
        self.assertEqual(self.p.correo("MCastano@Gmail.com", q), "szambrano@gmail.com")
        self.assertEqual(self.p.correo("manuela.castano@yahoo.com", q), "sofia.zambrano@yahoo.com")
        self.assertEqual(self.p.correo("manuelacastano@outlook.com", q), "sofiazambrano@outlook.com")
        c = self.p.correo("mcastano85@gmail.com", q)
        self.assertRegex(c, r"^szambrano\d\d@gmail\.com$")
        self.assertNotEqual(c, "szambrano85@gmail.com")
        self.assertEqual(self.p.correo("x.y@kipupay.co", q).split("@")[1], "kipupay.co")


class SinCoincidencias(unittest.TestCase):
    def test_numeros_lejos_de_los_reales(self):
        p, _ = nuevo()
        salidas = []
        for i in range(300):
            salidas.append(p.cedula("1.107.360.039"))
            salidas.append(p.celular("+57 318 642 3850"))
            salidas.append(p.credito("4471-0211"))
            salidas.append(p.cedula(f"{1000000000 + i * 7919}"))
            salidas.append(p.celular(f"31{i:08d}"))
        for s in salidas:
            for real in NUMEROS_REALES:
                self.assertFalse(contiene(s, real), (s, real))
        for r in ("1107360039", "3148729552", "3186423850"):
            self.assertFalse(any(contiene(s, r) for s in salidas))

    def test_numeros_sin_6_digitos_en_comun(self):
        p, _ = nuevo()
        reales = {re.sub(r"\D", "", x) for x in NUMEROS_REALES}
        gr = {r[j:j + 6] for r in reales for j in range(len(r) - 5)}
        for i in range(500):
            for s in (p.cedula(f"11073600{i:02d}"), p.celular("3186423850")):
                d = re.sub(r"\D", "", s)
                self.assertFalse(any(d[j:j + 6] in gr for j in range(len(d) - 5)), s)

    def test_nombres_no_son_formas_reales(self):
        p, _ = nuevo()
        reales = [f for r in REALES for f in formas_reales(r)]
        for i in range(2000):
            q = p.persona(f"n{i}", "f" if i % 2 else "m", 1 + i % 2, 2)
            texto = f"{q.completo} {q.nombres[0]} {q.nombres[0]} {q.apellidos[0]} " + " ".join(formas_reales(q))
            for f in reales:
                self.assertFalse(contiene(texto, f), (q, f))

    def test_catalogo_excluye_fuentes(self):
        base = Path(__file__).resolve().parent.parent / "fuentes"
        if not base.exists():
            self.skipTest("sin fuentes/")
        reales = set()
        for u in json.loads((base / "users.json").read_text(encoding="utf-8")):
            reales |= set(norm(u.get("real_name", "")).split())
        p, _ = nuevo()
        cat = {norm(w) for x in p.mujeres + p.hombres + p.apellidos for w in x.split()}
        self.assertEqual(cat & reales, set())
        self.assertGreaterEqual(len({x for x in p.mujeres if " " not in x}), 250)
        self.assertGreaterEqual(len({x for x in p.hombres if " " not in x}), 250)
        self.assertGreaterEqual(len(p.apellidos), 300)


class Formas(unittest.TestCase):
    real = Persona(("Manuela",), ("Castaño", "Ruiz"), "f")
    seu = Persona(("Sofía", "Elena"), ("Zambrano", "Naranjo"), "f")

    def test_mapeo_muestra(self):
        casos = {
            "Manuela": "Sofía",
            "Manuela Castaño": "Sofía Zambrano",
            "Manuela Castaño Ruiz": "Sofía Elena Zambrano Naranjo",
            "MANUELA CASTANO": "SOFIA ZAMBRANO",
            "Manuela Castano": "Sofia Zambrano",
            "manuela_castano": "sofia_zambrano",
            "manuela-castano": "sofia-zambrano",
            "manuela.castano": "sofia.zambrano",
            "mcastano": "szambrano",
            "manuelacastano": "sofiazambrano",
            "Castaño": "Zambrano",
        }
        for o, esperado in casos.items():
            self.assertEqual(mapear_forma(o, self.real, self.seu), esperado, o)

    def test_no_es_forma(self):
        self.assertIsNone(mapear_forma("Bancolombia", self.real, self.seu))

    def test_mapeo_con_nombre_compuesto_real(self):
        r = Persona(("Juan", "Pablo"), ("Pérez", "Gil"))
        s = Persona(("Hugo", "Armando"), ("Rueda", "Soto"))
        self.assertEqual(mapear_forma("Juan Pablo", r, s), "Hugo Armando")
        self.assertEqual(mapear_forma("Juan", r, s), "Hugo")
        self.assertEqual(mapear_forma("Juan Pérez", r, s), "Hugo Rueda")

    def test_formas_reales(self):
        f = set(formas_reales("Manuela Castaño Ruiz"))
        for x in ("Manuela Castaño Ruiz", "Manuela", "Manuela Castaño", "Manuela Castano", "MANUELA CASTAÑO",
                  "MANUELA CASTANO", "manuela_castano", "manuela-castano", "manuela.castano", "mcastano",
                  "manuelacastano"):
            self.assertIn(x, f)

    def test_deletreado(self):
        self.assertEqual(deletrear("martin.torres@icloud.com"), "martin punto torres arroba icloud punto com")
        self.assertEqual(deletrear("a_b-c@x.co"), "a guion bajo b guion c arroba x punto co")
        t = "mi correo es martin punto torres arroba icloud punto com gracias"
        self.assertEqual(desdeletrear(t), "mi correo es martin.torres@icloud.com gracias")
        for c in ("martin.torres@icloud.com", "a_b-c@x.co", "ana85@gmail.com"):
            self.assertEqual(desdeletrear(deletrear(c)), c)
        self.assertEqual(desdeletrear("nada que ver aquí"), "nada que ver aquí")

    def test_formatear_como(self):
        self.assertEqual(formatear_como("1.107.360.039", "2233445566"), "2.233.445.566")
        self.assertEqual(formatear_como("+57 318 642 3850", "3001112233"), "+57 300 111 2233")
        self.assertEqual(formatear_como("573186423850", "3001112233"), "573001112233")
        self.assertEqual(formatear_como("318-642-3850", "3001112233"), "300-111-2233")


if __name__ == "__main__":
    unittest.main()
