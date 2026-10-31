"""Port exacto de juez/texto.ts (embebido en material/frontier-reto-1/validar.mjs).

clean, norm, digitos_compactos, digitos_en y contiene se comportan como el
validador oficial: confusables, NFKC, invisibles (Cf), tildes, separadores de
digitos y prefijo 57. Solo libreria estandar.
"""
import re
import unicodedata

ESPACIO = "\t\n\x0b\x0c\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"

CONFUSABLES = {
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
    "\u0445": "x", "\u0443": "y", "\u0456": "i", "\u0458": "j", "\u0455": "s",
    "\u0410": "A", "\u0415": "E", "\u041e": "O", "\u0420": "P", "\u0421": "C",
    "\u0425": "X", "\u0423": "Y", "\u0406": "I", "\u0408": "J", "\u0405": "S",
    "\u0412": "B", "\u041d": "H", "\u041a": "K", "\u041c": "M", "\u0422": "T",
    "\u03bf": "o", "\u03b1": "a", "\u03c1": "p", "\u03bd": "v", "\u03b9": "i",
    "\u2113": "l", "\u0131": "i", "\u0251": "a",
}
_RX_CONFUSABLE = re.compile("[" + "".join(CONFUSABLES) + "]")
_SEP_DIGITOS = set(" \t\n\x0b\x0c\r\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000"
                   + "".join(chr(c) for c in range(0x2000, 0x200b))
                   + ".,'\u2019`\xb4\xb7/-\u2013\u2014_")
_RX_ESPACIOS = re.compile(r" {2,}")
_RX_BLANCOS = re.compile("[" + ESPACIO + "]+")
_CLASE_ESPACIO = "[" + ESPACIO + "]*"
_CACHE_MAX = 200_000
_cache_norm: dict = {}
_cache_compacto: dict = {}


def _es_espacio_raro(c: str) -> bool:  # [\p{Zs}\t\r\n\v\f]
    return unicodedata.category(c) == "Zs" or c in "\t\r\n\x0b\x0c"


def _es_texto(n: str) -> bool:  # ^[\p{L}\p{N}_ .'_-]+$
    if not n:
        return False
    for c in n:
        if c in " .'_-":
            continue
        if unicodedata.category(c)[0] in "LN":
            continue
        return False
    return True


def largo(s: str) -> int:
    return len(s)  # python cuenta puntos de codigo, igual que el for..of de JS


def plegar(s: str) -> str:
    return s.lower().replace("ß", "ss").replace("ς", "σ").replace("ſ", "s")


def quitar_tildes(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def clean(s: str) -> str:
    base = unicodedata.normalize("NFKC", s)
    base = _RX_CONFUSABLE.sub(lambda m: CONFUSABLES.get(m.group(0), m.group(0)), base)
    out = []
    for c in base:
        if unicodedata.category(c) == "Cf":
            continue
        out.append(" " if _es_espacio_raro(c) else c)
    return _RX_ESPACIOS.sub(" ", "".join(out))


def norm(s: str) -> str:
    r = _cache_norm.get(s)
    if r is None:
        r = plegar(quitar_tildes(clean(s)))
        if len(_cache_norm) > _CACHE_MAX:
            _cache_norm.clear()
        _cache_norm[s] = r
    return r


def digitos_compactos(s: str) -> str:
    r = _cache_compacto.get(s)
    if r is None:
        c = clean(s)
        out = []
        n = len(c)
        for i, ch in enumerate(c):
            if (ch in _SEP_DIGITOS and 0 < i < n - 1
                    and unicodedata.category(c[i - 1]) == "Nd"
                    and unicodedata.category(c[i + 1]) == "Nd"):
                continue
            out.append(ch)
        r = "".join(out)
        if len(_cache_compacto) > _CACHE_MAX:
            _cache_compacto.clear()
        _cache_compacto[s] = r
    return r


def solo_digitos(s: str) -> str:
    return "".join(c for c in s if unicodedata.category(c) == "Nd")


_cache_rx: dict = {}


def _rx(fuente: str) -> "re.Pattern":
    r = _cache_rx.get(fuente)
    if r is None:
        r = re.compile(fuente)
        if len(_cache_rx) > 50_000:
            _cache_rx.clear()
        _cache_rx[fuente] = r
    return r


def digitos_en(haystack: str, digitos: str) -> bool:
    compacto = digitos_compactos(haystack)
    candidatos = [digitos]
    if len(digitos) == 12 and digitos.startswith("57"):
        candidatos.append(digitos[2:])
    for d in candidatos:
        if _rx(r"(?<!\d)(?:57)?" + re.escape(d) + r"(?!\d)").search(compacto):
            return True
    return False


def contiene(haystack: str, needle: str, exacto: bool = False) -> bool:
    if not needle:
        return False
    if exacto:
        return needle in haystack
    digitos = solo_digitos(needle)
    if (digitos and largo(digitos) >= 6 and largo(digitos) >= 0.6 * largo(needle)
            and not re.search(r"[a-zA-Z]", needle)):
        return digitos_en(haystack, digitos)
    h = norm(haystack)
    n = norm(needle)
    if _es_texto(n) and re.search(r"[a-z]", n):
        if _rx(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])").search(h):
            return True
        palabras = [p for p in _RX_BLANCOS.split(n) if p != ""]
        if len(palabras) >= 2 and all(largo(w) >= 3 for w in palabras):
            patron = r"(?<![a-z0-9])" + _CLASE_ESPACIO.join(re.escape(w) for w in palabras) + r"(?![a-z0-9])"
            return bool(_rx(patron).search(h))
        return False
    return n in h
