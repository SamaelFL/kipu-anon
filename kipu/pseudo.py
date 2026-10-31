"""Seudónimos deterministas: todo sale de HMAC-SHA256(secreto, f"{llave}:{campo}:{i}")."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from .formas import (Persona, como_persona, formas_reales as formas_de, formatear_como,
                     locales_correo, plano, sin_tildes)

DATA = Path(__file__).parent / "data"
AUTOGUARDAR = 200

FEMENINAS = {"senora", "sra", "dona", "clienta", "ella", "hija", "esposa", "madre", "mama", "hermana",
             "cunada", "tia", "jefa", "abuela", "novia", "sobrina", "ms", "srta", "senorita",
             "administradora", "abogada", "arquitecta", "contadora", "enfermera", "fotografa",
             "ingeniera", "odontologa", "psicologa", "veterinaria", "disenadora", "docente_f",
             "periodista_f", "gerenta", "directora", "coordinadora", "analista_f", "asesora",
             "vendedora", "secretaria", "doctora", "dra", "profesora", "licenciada", "estudiante_f",
             "panadera", "mecanica", "conductora", "piloto_f", "estilista_f", "chef_f", "gerente_f"}
MASCULINAS = {"senor", "sr", "don", "cliente_m", "el", "hijo", "esposo", "padre", "papa", "hermano",
              "cunado", "tio", "jefe", "abuelo", "novio", "sobrino", "mr", "administrador", "abogado",
              "arquitecto", "contador", "fotografo", "ingeniero", "veterinario", "disenador",
              "director", "coordinador", "asesor", "vendedor", "secretario", "doctor", "dr",
              "profesor", "licenciado", "panadero", "mecanico", "conductor", "gerente_m", "electricista_m"}

LETRAS = "ABCDEFGHJKLMNPRSTUVWXYZ"
_ABREV_VIA = {"calle": "cl", "cl": "cl", "cll": "cl", "carrera": "cra", "cra": "cra", "cr": "cra", "kr": "cra",
              "transversal": "tv", "tv": "tv", "trans": "tv", "diagonal": "dg", "dg": "dg", "diag": "dg",
              "avenida": "av", "av": "av"}
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre"]


def _leer(nombre: str) -> list:
    with open(DATA / nombre, encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]


class _Flujo:
    """Números pseudoaleatorios deterministas a partir de HMAC."""

    def __init__(self, secreto: bytes, llave: str, campo: str, i: int):
        self.s, self.base, self.k, self.buf = secreto, f"{llave}:{campo}:{i}", 0, 0
        self.n = 0
        self._recargar()

    def _recargar(self):
        msg = self.base if self.k == 0 else f"{self.base}:{self.k}"
        self.buf = int.from_bytes(hmac.new(self.s, msg.encode(), hashlib.sha256).digest(), "big")
        self.n = 256
        self.k += 1

    def rango(self, n: int) -> int:
        """Entero en [0, n)."""
        if self.n < 40:
            self._recargar()
        self.buf, r = divmod(self.buf, n)
        self.n -= max(n.bit_length(), 1)
        return r

    def digitos(self, largo: int, primero_no_cero: bool = False) -> str:
        out = [str(self.rango(10)) for _ in range(largo)]
        if primero_no_cero and out and out[0] == "0":
            out[0] = str(1 + self.rango(9))
        return "".join(out)

    def elegir(self, seq):
        return seq[self.rango(len(seq))]


class Pseudonimizador:
    def __init__(self, secreto, ruta_store, formas_reales=()):
        self.secreto = secreto.encode() if isinstance(secreto, str) else bytes(secreto)
        if not self.secreto:
            raise ValueError("secreto vacío")
        self.ruta = Path(ruta_store)
        self._lock = threading.RLock()
        self._pendientes = 0

        self.mujeres = _leer("nombres_mujer.txt")
        self.hombres = _leer("nombres_hombre.txt")
        self.apellidos = _leer("apellidos.txt")
        self._simples = {"f": [x for x in self.mujeres if " " not in x], "m": [x for x in self.hombres if " " not in x]}
        self._compuestos = {"f": [x for x in self.mujeres if " " in x], "m": [x for x in self.hombres if " " in x]}
        self._genero_cat: dict = {}
        for g, lista in (("f", self.mujeres), ("m", self.hombres)):
            for x in lista:
                for tok in x.split():
                    k = plano(tok)
                    self._genero_cat[k] = g if self._genero_cat.get(k, g) == g else "a"
        with open(DATA / "genero_reales.json", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                self._genero_cat.setdefault(k, v)
        with open(DATA / "sectores.json", encoding="utf-8") as f:
            sec = json.load(f)
        self.sectores = {plano(k): v for k, v in sec["oficios"].items()}
        self.sector_defecto = sec["defecto"]

        # números y nombres reales a evitar
        self._grams: set = set()
        self._reales_norm: set = set()
        self.agregar_formas_reales(formas_reales)

        self._personas: dict = {}
        self._usados: set = set()
        self._cargar()

    # ------------------------------------------------------------------ store
    def agregar_formas_reales(self, formas):
        with self._lock:
            for f in formas:
                f = str(f)
                self._reales_norm.add(plano(f).strip())
                for run in re.findall(r"\d[\d .\-]*\d|\d", f):
                    d = re.sub(r"\D", "", run)
                    for j in range(len(d) - 5):
                        self._grams.add(d[j:j + 6])
                d = re.sub(r"\D", "", f)
                for j in range(len(d) - 5):
                    self._grams.add(d[j:j + 6])
                alnum = re.sub(r"[^A-Za-z0-9]", "", f).upper()
                if re.fullmatch(r"[A-Z]{3}\d{2}[\dA-Z]|[A-Z]{2}\d{6}", alnum):
                    self._reales_norm.add(alnum.lower())

    def _cargar(self):
        if self.ruta.exists():
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
            self._personas = datos.get("personas", {})
            self._usados = {self._clave(Persona(tuple(v["nombres"]), tuple(v["apellidos"]))) for v in self._personas.values()}

    def guardar(self):
        with self._lock:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.ruta.parent, prefix=self.ruta.name + ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "personas": self._personas}, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.ruta)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            self._pendientes = 0

    # ------------------------------------------------------------------ HMAC
    def _flujo(self, llave: str, campo: str, i: int = 0) -> _Flujo:
        return _Flujo(self.secreto, llave, campo, i)

    @staticmethod
    def _clave(p: Persona) -> str:
        return plano(p.completo)

    # ------------------------------------------------------------------ género
    def genero(self, primer_nombre: str, pistas=()) -> str:
        """'f' o 'm'."""
        pal = plano(primer_nombre).split()
        g = self._genero_cat.get(pal[0]) if pal else None
        if g in ("f", "m"):
            return g
        textos = [pistas] if isinstance(pistas, str) else list(pistas or [])
        f = m = 0
        for t in textos:
            for w in re.findall(r"[a-zñ]+", plano(str(t))):
                f += w in FEMENINAS
                m += w in MASCULINAS
        if f != m:
            return "f" if f > m else "m"
        if g is None and pal:  # nombre desconocido: terminación
            if pal[0].endswith("a"):
                return "f"
            if pal[0].endswith("o"):
                return "m"
        return "f" if self._flujo(plano(primer_nombre), "genero").rango(2) == 0 else "m"

    # ------------------------------------------------------------------ persona
    def _armar(self, llave: str, g: str, n_nombres: int, n_apellidos: int, i: int) -> Persona:
        fl = self._flujo(llave, "persona", i)
        nombres: list = []
        simples = self._simples[g]
        if n_nombres == 2 and self._compuestos[g] and fl.rango(4) == 0:
            nombres = fl.elegir(self._compuestos[g]).split()
        else:
            while len(nombres) < n_nombres:
                x = fl.elegir(simples)
                if x not in nombres:
                    nombres.append(x)
        apes: list = []
        while len(apes) < n_apellidos:
            x = fl.elegir(self.apellidos)
            if x not in apes and plano(x) not in {plano(n) for n in nombres}:
                apes.append(x)
        return Persona(tuple(nombres), tuple(apes), g)

    def persona(self, llave: str, genero: str, n_nombres: int = 1, n_apellidos: int = 2) -> Persona:
        """Seudónimo único para `llave`; la llave ya guardada gana."""
        g = "f" if genero in ("f", "F", "mujer", "femenino") else "m"
        with self._lock:
            v = self._personas.get(llave)
            if v:
                return Persona(tuple(v["nombres"]), tuple(v["apellidos"]), v.get("genero", g))
            i = 0
            while True:
                p = self._armar(llave, g, max(n_nombres, 1), n_apellidos, i)
                if self._clave(p) not in self._usados and not self._choca_real(p):
                    break
                i += 1
            self._usados.add(self._clave(p))
            self._personas[llave] = {"genero": g, "nombres": list(p.nombres), "apellidos": list(p.apellidos), "i": i}
            self._pendientes += 1
            if self._pendientes >= AUTOGUARDAR:
                self.guardar()
            return p

    def _choca_real(self, p: Persona) -> bool:
        if not self._reales_norm:
            return False
        piezas = [t for x in p.nombres + p.apellidos for t in (x, *x.split())]
        return any(plano(f).strip() in self._reales_norm for f in list(formas_de(p)) + piezas)

    # ------------------------------------------------------------------ números
    def _lejos(self, nuevo_digitos: str, original_digitos: str = "") -> bool:
        """Sin subcadena de 6+ dígitos en común con números reales ni 5+ con el original."""
        for j in range(len(nuevo_digitos) - 5):
            if nuevo_digitos[j:j + 6] in self._grams:
                return False
        if len(original_digitos) >= 5 and len(nuevo_digitos) >= 5:
            g = {original_digitos[j:j + 5] for j in range(len(original_digitos) - 4)}
            if any(nuevo_digitos[j:j + 5] in g for j in range(len(nuevo_digitos) - 4)):
                return False
        return True

    def _intentar(self, llave: str, campo: str, gen, original_digitos: str, max_i: int = 400):
        ultimo = None
        for i in range(max_i):
            ultimo = gen(self._flujo(llave, campo, i))
            if self._lejos(re.sub(r"\D", "", ultimo), original_digitos):
                return ultimo
        return ultimo

    def cedula(self, original: str) -> str:
        d = re.sub(r"\D", "", original)
        if not d:
            return original
        n = len(d)

        def gen(fl):
            return "1" + fl.digitos(n - 1) if n >= 10 else fl.digitos(n, True)

        return formatear_como(original, self._intentar(d, "cedula", gen, d))

    def celular(self, original: str) -> str:
        d = re.sub(r"\D", "", original)
        core = d[2:] if len(d) == 12 and d.startswith("57") else d
        if len(core) != 10:
            core = core[-10:] if len(core) > 10 else core

        prefijos = ["300", "301", "302", "304", "305", "310", "311", "312", "313", "314", "315", "316",
                    "317", "318", "319", "320", "321", "322", "323", "324", "350", "351"]

        def gen(fl):
            return fl.elegir(prefijos) + fl.digitos(max(len(core) - 3, 0))

        return formatear_como(original, self._intentar(core, "celular", gen, core))

    def placa(self, original: str) -> str:
        alnum = re.sub(r"[^A-Za-z0-9]", "", original).upper()
        patron = "".join("L" if c.isalpha() else "D" for c in alnum)
        reales = self._reales_norm

        def gen(fl):
            s = "".join(fl.elegir(LETRAS) if t == "L" else str(fl.rango(10)) for t in patron)
            return s

        for i in range(400):
            s = gen(self._flujo(alnum, "placa", i))
            if s != alnum and s.lower() not in reales and self._lejos(re.sub(r"\D", "", s), re.sub(r"\D", "", alnum)):
                break
        out, k = [], 0
        for c in original:
            if c.isalnum():
                x = s[k]
                k += 1
                out.append(x.lower() if c.islower() else x)
            else:
                out.append(c)
        return "".join(out)

    def pasaporte(self, original: str) -> str:
        alnum = re.sub(r"[^A-Za-z0-9]", "", original).upper()
        d = re.sub(r"\D", "", alnum)
        nd = len(d) or 6

        def gen(fl):
            return fl.elegir(LETRAS) + fl.elegir(LETRAS) + fl.digitos(nd, True)

        s = self._intentar(alnum, "pasaporte", gen, d)
        return s.lower() if original.islower() else s

    def credito(self, original: str) -> str:
        grupos = re.findall(r"\d+|\D+", original)
        nums = [g for g in grupos if g.isdigit()]
        if len(nums) >= 2:
            fijo = nums[0]
            largos = [len(x) for x in nums[1:]]
        else:
            d = nums[0] if nums else ""
            fijo, largos = d[:4], [max(len(d) - 4, 4)]
        orig_resto = "".join(nums[1:]) if len(nums) >= 2 else (nums[0][4:] if nums else "")

        def gen(fl):
            resto = [fl.digitos(n) for n in largos]
            return "".join(resto)

        def armar(resto):
            if len(nums) >= 2:
                k, out = 0, []
                primero = True
                for g in grupos:
                    if g.isdigit():
                        if primero:
                            out.append(g)
                            primero = False
                        else:
                            n = len(g)
                            out.append(resto[k:k + n])
                            k += n
                    else:
                        out.append(g)
                return "".join(out)
            return fijo + resto

        for i in range(400):
            resto = gen(self._flujo(original, "credito", i))
            if resto != orig_resto and self._lejos(re.sub(r"\D", "", fijo + resto), re.sub(r"\D", "", orig_resto)):
                break
        return armar(resto)

    def direccion(self, original: str) -> str:
        """Cambia cada número conservando abreviatura (Cl/Cra/Tv/Dg), Bis, Sur, '#', apto/casa/of."""
        llave = self._canon_dir(original)
        orig_d = re.sub(r"\D", "", original)
        r = original
        for i in range(200):
            fl = self._flujo(llave, "direccion", i)

            visto = [False]

            def num(m):
                s = m.group(0)
                primero, visto[0] = not visto[0], True
                for _ in range(10):
                    if len(s) >= 3 and primero:
                        nuevo = str(100 + fl.rango(80))[:len(s)].ljust(len(s), "0")  # calles 100-179
                    elif len(s) >= 3:
                        nuevo = str(1 + fl.rango(20 if len(s) == 4 else 9)) + f"{1 + fl.rango(12):02d}"  # piso + unidad
                    else:
                        nuevo = fl.digitos(len(s), True)
                    if nuevo != s:
                        return nuevo
                return str(int(s) % 9 + 1) * len(s)

            def letra(m):
                alfabeto = "ABCDE" if m.group(0).isupper() else "abcde"
                return fl.elegir(alfabeto)

            r = re.sub(r"\d+", num, original)
            r = re.sub(r"(?<=\d)[A-Ea-e](?![A-Za-z])", letra, r)
            if r != original and self._lejos(re.sub(r"\D", "", r), orig_d):
                break
        return r

    @staticmethod
    def _canon_dir(s: str) -> str:
        toks = re.findall(r"[a-z]+|\d+", plano(s))
        return " ".join(_ABREV_VIA.get(t, t) for t in toks)

    def nacimiento(self, original: str) -> str:
        """Fecha válida entre 1 y 5 años distinta, con el mismo formato (ISO, d/m/a o "d de mes de a")."""
        m = re.fullmatch(r"(\s*)(\d{4})([-/.])(\d{1,2})\3(\d{1,2})(.*)", original, re.S)
        if m:
            ini, y, sep, mo, d, resto = m[1], int(m[2]), m[3], int(m[4]), int(m[5]), m[6]
            orden, ancho = "ymd", len(m[4]) == 2 or len(m[5]) == 2
        else:
            m = re.fullmatch(r"(\s*)(\d{1,2})([-/.])(\d{1,2})\3(\d{4})(.*)", original, re.S)
            if m:
                ini, d, sep, mo, y, resto = m[1], int(m[2]), m[3], int(m[4]), int(m[5]), m[6]
                orden, ancho = "dmy", len(m[2]) == 2 or len(m[4]) == 2
            else:
                m = re.fullmatch(r"(\s*)(\d{1,2}) de ([A-Za-záéíóúÁÉÍÓÚ]+) de (\d{4})(.*)", original, re.S)
                if not m or plano(m[3]) not in _MESES:
                    return original
                ini, d, mo, y, resto = m[1], int(m[2]), _MESES.index(plano(m[3])) + 1, int(m[4]), m[5]
                orden, ancho, sep = "texto", False, " "
        try:
            base = dt.date(y, mo, d)
        except ValueError:
            return original
        fl = self._flujo(base.isoformat(), "nacimiento")
        dias = 365 + fl.rango(1461)
        nueva = base + dt.timedelta(days=dias if fl.rango(2) else -dias)

        def f(v):
            return str(v).zfill(2) if ancho else str(v)

        if orden == "ymd":
            t = f"{nueva.year}{sep}{f(nueva.month)}{sep}{f(nueva.day)}"
        elif orden == "dmy":
            t = f"{f(nueva.day)}{sep}{f(nueva.month)}{sep}{nueva.year}"
        else:
            mes = _MESES[nueva.month - 1]
            mes = mes.capitalize() if m[3][:1].isupper() else mes
            t = f"{nueva.day} de {mes} de {nueva.year}"
        return ini + t + resto

    def barrio(self, original: str, ciudad: str, barrios_por_ciudad: dict) -> str:
        ref = None
        for c, lista in barrios_por_ciudad.items():
            if plano(c) == plano(ciudad or ""):
                ref = list(lista)
                break
        if not ref:
            ref = sorted({b for l in barrios_por_ciudad.values() for b in l})
        cand = [b for b in ref if plano(b) != plano(original)]
        if not cand:
            return original
        cand = sorted(set(cand))
        return self._flujo(f"{plano(ciudad or '')}|{plano(original)}", "barrio").elegir(cand)

    def sector(self, oficio: str) -> str:
        return self.sectores.get(plano(oficio).strip(), self.sector_defecto)

    # ------------------------------------------------------------------ correo
    def correo(self, original: str, persona, persona_real=None) -> str:
        p = como_persona(persona)
        if "@" not in original:
            return original
        local, dom = original.rsplit("@", 1)
        dom_l = dom.lower()
        nom = plano(p.nombres[0]).replace(" ", "")
        ap = plano(p.apellidos[0]).replace(" ", "") if p.apellidos else ""
        ap2 = plano(p.apellidos[1]).replace(" ", "") if len(p.apellidos) > 1 else ""
        if dom_l == "kipupay.co":
            return f"{nom}.{ap}@{dom_l}"
        estilo, dig = self._estilo_local(local, persona_real)
        cola = ""
        if dig:
            fl = self._flujo(original, "correo")
            cola = fl.digitos(len(dig))
            if cola == dig:
                cola = str((int(dig) + 1) % (10 ** len(dig))).zfill(len(dig))
        nuevo = {
            "inicial": nom[:1] + ap,
            "nombre.ap": f"{nom}.{ap}", "nombre_ap": f"{nom}_{ap}", "nombre-ap": f"{nom}-{ap}",
            "nombreap": nom + ap,
            "ap.nombre": f"{ap}.{nom}", "apinicial": ap + nom[:1],
            "nombre": nom, "ap": ap,
            "nombre.ap.ap2": f"{nom}.{ap}.{ap2}" if ap2 else f"{nom}.{ap}",
            "nombreapap2": nom + ap + ap2,
        }[estilo]
        return f"{nuevo}{cola}@{dom_l}"

    def _estilo_local(self, local: str, real) -> tuple:
        """Devuelve (estilo, dígitos finales)."""
        l = plano(local)
        m = re.fullmatch(r"(.*?)(\d*)", l)
        base, dig = m[1], m[2]
        if real is not None:
            r = como_persona(real)
            if r.nombres and r.apellidos:
                n = plano(r.nombres[0]).replace(" ", "")
                a = plano(r.apellidos[0]).replace(" ", "")
                a2 = plano(r.apellidos[1]).replace(" ", "") if len(r.apellidos) > 1 else None
                tabla = [("inicial", n[0] + a), ("nombre.ap", f"{n}.{a}"), ("nombre_ap", f"{n}_{a}"),
                         ("nombre-ap", f"{n}-{a}"), ("nombreap", n + a), ("ap.nombre", f"{a}.{n}"),
                         ("apinicial", a + n[0]), ("nombre", n), ("ap", a)]
                if a2:
                    tabla += [("nombre.ap.ap2", f"{n}.{a}.{a2}"), ("nombreapap2", n + a + a2)]
                for est, v in tabla:
                    if base == v:
                        return est, dig
        if "." in base:
            return ("nombre.ap.ap2" if base.count(".") >= 2 else "nombre.ap"), dig
        if "_" in base:
            return "nombre_ap", dig
        if "-" in base:
            return "nombre-ap", dig
        return ("inicial" if len(base) <= 9 else "nombreap"), dig
