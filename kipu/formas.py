"""Formas de un nombre propio y su mapeo al seudónimo (solo librería estándar)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PARTICULAS = {"de", "del", "la", "las", "los", "y"}


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def plano(s: str) -> str:
    """minúsculas sin tildes."""
    return sin_tildes(s).lower()


@dataclass(frozen=True)
class Persona:
    nombres: tuple
    apellidos: tuple
    genero: str = ""

    @classmethod
    def desde_texto(cls, texto: str, n_apellidos: int | None = None, genero: str = "") -> "Persona":
        """Parte "Manuela Castaño Ruiz" en nombres y apellidos (2 apellidos con 3+ palabras)."""
        toks = texto.split()
        palabras, buf = [], []
        for i, t in enumerate(toks):
            if t.lower() in PARTICULAS and i < len(toks) - 1:
                buf.append(t)  # "de la Cruz" es un solo apellido
            else:
                palabras.append(" ".join(buf + [t]))
                buf = []
        n = len(palabras)
        if n_apellidos is None:
            n_apellidos = 0 if n <= 1 else 1 if n <= 2 else 2
        n_apellidos = min(n_apellidos, max(n - 1, 0))
        cut = n - n_apellidos
        return cls(tuple(palabras[:cut]), tuple(palabras[cut:]), genero)

    @property
    def completo(self) -> str:
        return " ".join(self.nombres + self.apellidos)

    @property
    def pila(self) -> str:
        return self.nombres[0] if self.nombres else ""

    @property
    def apellido1(self) -> str:
        return self.apellidos[0] if self.apellidos else ""

    def __str__(self) -> str:
        return self.completo


def como_persona(p) -> Persona:
    return p if isinstance(p, Persona) else Persona.desde_texto(str(p))


def _plantillas(p: Persona, todas: bool = False) -> dict:
    """tipo -> palabras. Con todas=True emite todos los tipos (lado del seudónimo)."""
    n, a = list(p.nombres), list(p.apellidos)
    pt: dict = {}
    if n and a:
        if todas or len(n) > 1 or len(a) > 1:
            pt["completo"] = n + a
        if todas or len(n) > 1:
            pt["nombres_ap1"] = n + a[:1]
        pt["pila1_ap1"] = n[:1] + a[:1]
        if todas or (len(a) > 1 and len(n) > 1):
            pt["pila1_ap1_ap2"] = n[:1] + a
        pt["ap1"] = a[:1]
        if todas or len(a) > 1:
            pt["apellidos"] = a
        pt["inicial_ap1"] = [n[0][0]] + a[:1]
    elif a:
        pt["ap1"] = a[:1]
    if n:
        pt["pila1"] = n[:1]
        if todas or len(n) > 1:
            pt["nombres"] = n
    return pt


ORDEN = ["completo", "pila1_ap1_ap2", "nombres_ap1", "pila1_ap1", "apellidos", "nombres", "ap1", "pila1", "inicial_ap1"]
SEPS = [" ", "_", "-", ".", ""]


def _unir(palabras: list, sep: str) -> str:
    """Une palabras planas; una palabra con espacios ("de la cruz") usa el mismo separador."""
    return sep.join(plano(x).replace(" ", sep) for x in palabras)


def locales_correo(p) -> list:
    """Locales de correo habituales (minúsculas sin tildes)."""
    p = como_persona(p)
    if not p.nombres or not p.apellidos:
        return []
    n = plano(p.nombres[0]).replace(" ", "")
    a = plano(p.apellidos[0]).replace(" ", "")
    out = [f"{n[0]}{a}", f"{n}.{a}", f"{n}{a}", f"{n}_{a}", f"{n}-{a}", f"{a}.{n}"]
    if len(p.nombres) > 1:
        out.append("".join(plano(x) for x in p.nombres) + a)
    if len(p.apellidos) > 1:
        a2 = plano(p.apellidos[1]).replace(" ", "")
        out += [f"{n}.{a}.{a2}", f"{n}{a}{a2}", f"{n[0]}{a}{a2[0]}"]
    return out


def formas_reales(persona_real) -> list:
    """Todas las formas con las que puede aparecer una persona en el texto."""
    p = como_persona(persona_real)
    out: list = []
    for tipo, pal in _plantillas(p, todas=True).items():
        if tipo == "inicial_ap1":
            out += [f"{pal[0]}. {pal[1]}", f"{pal[0]} {pal[1]}"]
            continue
        base = " ".join(pal)
        out += [base, sin_tildes(base), base.upper(), sin_tildes(base).upper(), base.lower()]
        for sep in "_-.":
            out.append(_unir(pal, sep))
        out.append(_unir(pal, ""))
    out += locales_correo(p)
    vistos, res = set(), []
    for f in out:
        if f and f not in vistos:
            vistos.add(f)
            res.append(f)
    return res


def _estilo(orig: str, real_txt: str, texto: str) -> str:
    """Aplica a `texto` (con tildes y capitalización del catálogo) el estilo de `orig`."""
    letras = [c for c in orig if c.isalpha()]
    if letras and all(c.isupper() for c in letras):
        t = texto.upper()
    elif letras and all(c.islower() for c in letras):
        t = texto.lower()
    else:
        t = texto
    if not any(ord(c) > 127 for c in orig) and any(ord(c) > 127 for c in real_txt):
        t = sin_tildes(t)  # el original venía sin tildes aunque el nombre las lleva
    return t


def mapear_forma(forma_original: str, persona_real, seudonimo):
    """Forma equivalente del seudónimo, o None si no es una forma de esa persona."""
    real, seu = como_persona(persona_real), como_persona(seudonimo)
    objetivo = plano(forma_original).strip()
    if not objetivo:
        return None
    pr, ps = _plantillas(real), _plantillas(seu, todas=True)
    for tipo in ORDEN:
        if tipo not in pr or tipo not in ps:
            continue
        pal_r, pal_s = pr[tipo], ps[tipo]
        if tipo == "inicial_ap1":
            if objetivo in (f"{plano(pal_r[0])}. {plano(pal_r[1])}", f"{plano(pal_r[0])} {plano(pal_r[1])}"):
                punto = "." if "." in objetivo else ""
                return _estilo(forma_original, "", f"{pal_s[0]}{punto} {pal_s[1]}")
            if objetivo == _unir(pal_r, ""):
                return _unir(pal_s, "")
            continue
        for sep in SEPS:
            if _unir(pal_r, sep) == objetivo:
                if sep == " ":
                    return _estilo(forma_original, " ".join(pal_r), " ".join(pal_s))
                return _unir(pal_s, sep)
    return None


# ---------------------------------------------------------------- correos deletreados
_A_PALABRA = {".": "punto", "_": "guion bajo", "-": "guion", "+": "mas", "@": "arroba"}
_DE_PALABRA = {"punto": ".", "guion bajo": "_", "guion": "-", "mas": "+", "arroba": "@"}


def deletrear(correo: str) -> str:
    """'martin.torres@icloud.com' -> 'martin punto torres arroba icloud punto com'."""
    partes = re.split(r"([.@_+\-])", correo)
    return " ".join(_A_PALABRA.get(p, p) for p in partes if p)


_PAL = r"[a-z0-9áéíóúñü]+"
_SEP_RX = r"(?:gui[oó]n\s+bajo|gui[oó]n|punto|m[aá]s)"
_RX_DELETREADO = re.compile(
    rf"(?<![\w@.])({_PAL}(?:\s+{_SEP_RX}\s+{_PAL})*)\s+arroba\s+({_PAL}(?:\s+punto\s+{_PAL})+)(?![\w@])",
    re.IGNORECASE,
)


def _unir_palabras(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower()).replace("guión", "guion").replace("más", "mas")
    s = re.sub(r"\s*\b(guion bajo|guion|punto|mas)\b\s*", lambda m: _DE_PALABRA[m.group(1)], s)
    return s.replace(" ", "")


def _correo_de(m) -> str:
    return _unir_palabras(m.group(1)) + "@" + _unir_palabras(m.group(2))


def buscar_deletreados(texto: str) -> list:
    """[(inicio, fin, correo)] de cada correo deletreado del texto."""
    return [(m.start(), m.end(), _correo_de(m)) for m in _RX_DELETREADO.finditer(texto)]


def desdeletrear(texto: str) -> str:
    """Reemplaza cada correo deletreado del texto por su forma normal."""
    return _RX_DELETREADO.sub(_correo_de, texto)


# ---------------------------------------------------------------- números
def formatear_como(original: str, digitos_nuevos: str) -> str:
    """Copia puntos, espacios, guiones y el prefijo 57 del original sobre `digitos_nuevos`."""
    nuevos = re.sub(r"\D", "", digitos_nuevos)
    d_orig = re.sub(r"\D", "", original)
    prefijo = ""
    if len(d_orig) == len(nuevos) + 2 and d_orig.startswith("57"):
        prefijo = "57"
    todos = prefijo + nuevos
    out, k = [], 0
    for c in original:
        if c.isdigit():
            if k < len(todos):
                out.append(todos[k])
                k += 1
        else:
            out.append(c)
    out.append(todos[k:])  # sobrantes si el original era más corto
    return "".join(out)
