"""Cuasi-identificadores: oficio, barrio y año de vinculación (solo librería estándar).

aplicar(records, entidades, pseudo) corre DESPUÉS de reemplaza.aplicar y muta los registros
en el lugar. Debe correrse una sola vez por corrida (el barrio ya cambiado no se puede
distinguir del original).

  clientes (siempre):  ocupacion -> sector; barrio -> otro barrio de la misma ciudad.
  texto de P.records:  oficio de P -> sector; barrio de P -> su ciudad;
                       año de vinculación de P -> "hace unos años".
  tuplas sin nombre:   (oficio + ciudad/barrio + año) u (oficio + barrio) que apuntan a
                       menos de K clientes del maestro -> se generalizan igual.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

K = 5
HACE = "hace unos años"

# claves que nunca se tocan al buscar en el texto
CLAVES_PROTEGIDAS = {"id", "thread_id", "ts", "table", "format", "ocupacion", "barrio", "ciudad",
                     "cliente_id", "fecha_vinculacion", "fecha_nacimiento", "direccion"}

# contexto de "me vinculé en/desde ..." mirando hacia atrás en la misma frase
_CTX = re.compile(
    r"entré|ingresé|ingresó|ingreso\b|me vinculé|vinculad[oa]s?\b|vinculación|vinculó"
    r"|(?:cliente|clienta|usuari[oa]|afiliad[oa]|socio|socia)\s+(?:\w+\s+){0,2}?desde|nuestr[oa]\s+(?:cliente|clienta)"
    r"|(?:cliente|clienta)\s+(?:nuestr[oa]\s+)?(?:hace|desde)|trabaja\s+con\s+nosotros|(?:está|estamos)\s+con\s+nosotros"
    r"|me uní|me registré|me inscribí|abrí (?:mi|la|una) cuenta|con ustedes|con kipu"
    r"|desde que (?:soy|estoy)|antigüedad|con nosotros|lleva\b|llevo\b|llevamos\b"
)
_ANIO = re.compile(r"(?<![\d\-/.,])(?:19[5-9]\d|20[0-4]\d)(?![\d\-/]|[.,]\d)")
_FRASE = re.compile(r"[.!?\n]+")


# ------------------------------------------------------------------ utilidades de texto
def _p(s: str) -> str:
    """Minúsculas sin tildes, con la MISMA longitud (los índices valen sobre el original)."""
    out = []
    for c in s:
        d = unicodedata.normalize("NFD", c)
        out.append(((d[0] if d else c).lower()[:1]) or c)
    return "".join(out)


def plano(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower().strip()


def _swap(w: str) -> str | None:
    if len(w) <= 3:
        return None
    if w.endswith("ora"):
        return w[:-1]
    if w.endswith("or"):
        return w + "a"
    if w.endswith("a"):
        return w[:-1] + "o"
    if w.endswith("o"):
        return w[:-1] + "a"
    return None


@lru_cache(maxsize=None)
def variantes(oficio: str) -> tuple:
    """Formas con y sin género de un oficio, en texto plano."""
    opciones = []
    for w in plano(oficio).split():
        s = _swap(w)
        opciones.append([w] + ([s] if s else []))
    out = [""]
    for op in opciones:
        out = [f"{a} {b}".strip() for a in out for b in op]
    return tuple(dict.fromkeys(out))


@lru_cache(maxsize=None)
def canon(oficio: str) -> str:
    """Clave que no distingue género: 'fotógrafa' == 'fotógrafo'."""
    ws = []
    for w in plano(oficio).split():
        if len(w) > 3 and w[-1] in "ao":
            w = w[:-1]
        ws.append(w)
    return " ".join(ws)


def _alt(items):
    items = sorted({i for i in items if i}, key=len, reverse=True)
    if not items:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(i) for i in items) + r")(?![a-z0-9])")


def _anio_con_contexto(s: str, ini: int) -> bool:
    ventana = s[max(0, ini - 90):ini]
    cortes = list(_FRASE.finditer(ventana))
    if cortes:
        ventana = ventana[cortes[-1].end():]
    return bool(_CTX.search(ventana.lower()))


_ANTES_ANIO = (
    # "hace dos años, en 2024" / "hace 2 años, desde el 2024": se reemplaza todo el giro
    (re.compile(r"hace\s+\S+\s+años?,?\s+(?:en|desde)(?:\s+el)?\s+$", re.I), 0),
    # "desde el 2021" -> "desde hace unos años" (solo "el 2021")
    (re.compile(r"(?<=desde\s)el\s+$", re.I), 0),
    # "en el 2024" -> "hace unos años"
    (re.compile(r"\ben\s+el\s+$", re.I), 0),
)


def anios_vinculacion(s: str) -> list:
    """[(ini, fin, año)] de los años que hablan de la vinculación. El tramo incluye giros como
    "en el 2024" o "hace dos años, en 2024" para que quede "hace unos años" completo."""
    out = []
    for m in _ANIO.finditer(s):
        if not _anio_con_contexto(s, m.start()):
            continue
        ini = m.start()
        previo = s[max(0, ini - 60):ini]
        for rx, _ in _ANTES_ANIO:
            x = rx.search(previo)
            if x:
                ini = ini - len(previo) + x.start()
                break
        out.append((ini, m.end(), int(m.group())))
    return out


# ------------------------------------------------------------------ maestro
def _anio_de(v):
    m = re.match(r"\s*(\d{4})", str(v or ""))
    return int(m[1]) if m else None


def maestro_de(records, entidades) -> list:
    """Clientes del maestro original: cliente_id, ciudad, barrio, ocupacion, anio, nacimiento."""
    res: dict = {}
    for r in records:
        if r.get("table") == "clientes" and isinstance(r.get("columns"), dict):
            c = r["columns"]
            cid = c.get("cliente_id") or r.get("id")
            res[cid] = {"cliente_id": cid, "ciudad": c.get("ciudad", ""), "barrio": c.get("barrio", ""),
                        "ocupacion": c.get("ocupacion", ""), "anio": _anio_de(c.get("fecha_vinculacion")),
                        "nacimiento": c.get("fecha_nacimiento", "")}
    for e in entidades or []:
        a = getattr(e, "atributos", None) or {}
        if getattr(e, "kept", False) or not (a.get("ocupacion") or a.get("barrio")):
            continue
        cid = (getattr(e, "ids", None) or {}).get("cliente_id") or e.entity_id
        res[cid] = {"cliente_id": cid, "ciudad": a.get("ciudad", ""), "barrio": a.get("barrio", ""),
                    "ocupacion": a.get("ocupacion", ""), "anio": _anio_de(a.get("anio_vinculacion")),
                    "nacimiento": a.get("nacimiento", "")}
    return list(res.values())


# ------------------------------------------------------------------ recorrido de textos
def hojas(obj, ruta="", protegidas=CLAVES_PROTEGIDAS):
    """(contenedor, clave, ruta, texto) de cada cadena que no sea una clave protegida."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in protegidas:
                continue
            sub = f"{ruta}.{k}" if ruta else str(k)
            if isinstance(v, str):
                yield obj, k, sub, v
            else:
                yield from hojas(v, sub, protegidas)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            sub = f"{ruta}.{i}"
            if isinstance(v, str):
                yield obj, i, sub, v
            else:
                yield from hojas(v, sub, protegidas)


# texto libre: único lugar donde se reemplaza oficio, barrio y año. Una descripción de transacción
# ("Compra D1 Castilla") es comercio y lugar: nunca se toca.
LIBRES_DOCS = ("body", "title")
LIBRES_TABLA = {"clientes": ("notas",), "pqrs": ("descripcion", "respuesta")}


def campos_libres(r):
    """(contenedor, clave, ruta, texto) de los campos de texto libre de un registro."""
    if "table" in r:
        cols = r.get("columns")
        if isinstance(cols, dict):
            for c in LIBRES_TABLA.get(r.get("table"), ()):
                if isinstance(cols.get(c), str):
                    yield cols, c, "columns." + c, cols[c]
    elif "body" in r:
        for c in LIBRES_DOCS:
            if isinstance(r.get(c), str):
                yield r, c, c, r[c]
    elif isinstance(r.get("text"), str):
        yield r, "text", "text", r["text"]


def _capitaliza(orig: str, nuevo: str) -> str:
    return nuevo[:1].upper() + nuevo[1:] if orig[:1].isupper() else nuevo


# ------------------------------------------------------------------ reglas por persona
class _Persona:
    def __init__(self, entidad, pseudo):
        a = entidad.atributos
        self.id = entidad.entity_id
        self.oficio = a.get("ocupacion") or ""
        self.sector = pseudo.sector(self.oficio) if self.oficio else ""
        self.barrio = plano(a.get("barrio") or "")
        self.ciudad = a.get("ciudad") or ""
        self.anio = _anio_de(a.get("anio_vinculacion"))
        self.rx_oficio = _alt(variantes(self.oficio)) if self.oficio else None
        ok_barrio = self.barrio and self.ciudad and self.barrio != plano(self.ciudad)
        self.rx_barrio = _alt([self.barrio]) if ok_barrio else None

    def spans(self, s: str, p: str) -> list:
        out = []
        if self.rx_oficio:
            for m in self.rx_oficio.finditer(p):
                out.append((m.start(), m.end(), _capitaliza(s[m.start()], self.sector), "ocupacion", self.id))
        if self.rx_barrio:
            for m in self.rx_barrio.finditer(p):
                out.append((m.start(), m.end(), self.ciudad, "barrio", self.id))
        if self.anio:
            for ini, fin, a in anios_vinculacion(s):
                if a == self.anio:
                    out.append((ini, fin, HACE, "anio", self.id))
        return out


# ------------------------------------------------------------------ tuplas sin nombre
class Tuplas:
    """Detecta (oficio + lugar + año) u (oficio + barrio) sin nombre y cuenta clientes del maestro.
    Tres alcances: la frase del oficio y sus vecinas (`spans`, k < K incluido 0), la unidad completa
    (un hilo de chat, un doc o una fila: `spans_unidad`, solo si la combinación existe: 1 <= k < K)
    y las tuplas de empleados (cargo + barrio + año de ingreso)."""

    def __init__(self, maestro, pseudo, k=K, empleados=None):
        self.m, self.pseudo, self.k = maestro, pseudo, k
        oficios = {o for o in (c["ocupacion"] for c in maestro) if o} | set(pseudo.sectores)
        self.var = {}
        for o in oficios:
            for v in variantes(o):
                self.var[v] = canon(o)
        self.rx_ofi = _alt(self.var)
        self.barrios: dict = {}
        for c in maestro:
            if c["barrio"]:
                self.barrios.setdefault(plano(c["barrio"]), set()).add(c["ciudad"])
        self.rx_bar = _alt(self.barrios)
        self.ciudades = {plano(c["ciudad"]): c["ciudad"] for c in maestro if c["ciudad"]}
        self.rx_ciu = _alt(self.ciudades)
        self.emp = [{"cargo": plano(e.get("cargo", "")), "ciudad": plano(e.get("ciudad", "")),
                     "ciudad_txt": e.get("ciudad", ""), "ingreso": _anio_de(e.get("ingreso"))}
                    for e in (empleados or []) if e.get("cargo")]
        self.rx_cargo = _alt({e["cargo"] for e in self.emp})

    def contar(self, ofi=None, barrio=None, ciudad=None, anio=None) -> int:
        return len(self._filtrar(ofi, barrio, ciudad, anio))

    def _filtrar(self, ofi=None, barrio=None, ciudad=None, anio=None) -> list:
        res = []
        for c in self.m:
            if ofi is not None and canon(c["ocupacion"]) != ofi:
                continue
            if barrio is not None and plano(c["barrio"]) != barrio:
                continue
            if ciudad is not None and plano(c["ciudad"]) != ciudad:
                continue
            if anio is not None and c["anio"] != anio:
                continue
            res.append(c)
        return res

    def _sector_de(self, canon_oficio: str) -> str:
        for k, v in self.pseudo.sectores.items():
            if canon(k) == canon_oficio:
                return v
        return self.pseudo.sector_defecto

    def _ciudad_de_barrio(self, barrio, ofi=None, anio=None, ciudad_txt=None, mencionadas=()):
        """Ciudad a la que pertenece un barrio: la del maestro si es única, si no la de los clientes que
        casan con la tupla, si no la única ciudad mencionada en el texto."""
        cs = self.barrios.get(barrio, set())
        if len(cs) == 1:
            return next(iter(cs))
        if ciudad_txt and ciudad_txt in {plano(c) for c in cs}:
            return self.ciudades.get(ciudad_txt)
        casan = {c["ciudad"] for c in self._filtrar(ofi, barrio, None, anio)}
        if len(casan) == 1:
            return next(iter(casan))
        ment = [c for c in cs if plano(c) in set(mencionadas)]
        return ment[0] if len(ment) == 1 else None

    # ---------------------------------------------------------------- alcance: frase y vecinas
    def detectar(self, s: str, ancla=None):
        """Tupla en la ventana `s` (la frase del oficio y sus vecinas): dict o None.
        `ancla` = (ini, fin) restringe el oficio a ese tramo de `s`."""
        if not self.rx_ofi:
            return None
        p = _p(s)
        ofi = [(m.start(), m.end(), self.var[m.group()]) for m in self.rx_ofi.finditer(p)
               if ancla is None or ancla[0] <= m.start() < ancla[1]]
        if not ofi:
            return None
        bar = [(m.start(), m.end(), m.group()) for m in self.rx_bar.finditer(p)] if self.rx_bar else []
        ciu = [(m.start(), m.end(), m.group()) for m in self.rx_ciu.finditer(p)] if self.rx_ciu else []
        anios = anios_vinculacion(s)
        o, a = ofi[0], (anios[0] if anios else None)
        b, c = (bar[0] if bar else None), (ciu[0] if ciu else None)
        if a and (b or c):
            k = self.contar(o[2], b[2] if b else None, c[2] if c else None, a[2])
            tipo = "oficio_lugar_anio"
        elif b:
            k = self.contar(o[2], b[2])
            tipo, a = "oficio_barrio", None
        else:
            return None
        return {"oficio": o, "barrio": b, "ciudad": c, "anio": a, "k": k, "tipo": tipo}

    def spans_ventana(self, s: str, base: int, ancla=None) -> list:
        t = self.detectar(s, ancla)
        if not t or t["k"] >= self.k:
            return []
        o, b, c, a = t["oficio"], t["barrio"], t["ciudad"], t["anio"]
        res = [(o[0] + base, o[1] + base, _capitaliza(s[o[0]], self._sector_de(o[2])), "ocupacion", t["k"], t["tipo"])]
        if b:
            ciudad = self._ciudad_de_barrio(b[2], o[2], a[2] if a else None, c[2] if c else None)
            if ciudad and plano(ciudad) != b[2]:
                res.append((b[0] + base, b[1] + base, ciudad, "barrio", t["k"], t["tipo"]))
        if a:
            res.append((a[0] + base, a[1] + base, HACE, "anio", t["k"], t["tipo"]))
        return res

    def spans(self, texto: str) -> list:
        """Tuplas de un texto libre: por cada frase con oficio, mira esa frase y las dos vecinas."""
        segs = [(b, sg) for b, sg in segmentos(texto)]
        res = []
        for i, (b, sg) in enumerate(segs):
            if not sg.strip() or not self.rx_ofi or not self.rx_ofi.search(_p(sg)):
                continue
            ini = segs[max(i - 1, 0)][0]
            fin = segs[min(i + 1, len(segs) - 1)][0] + len(segs[min(i + 1, len(segs) - 1)][1])
            res += self.spans_ventana(texto[ini:fin], ini, ancla=(b - ini, b - ini + len(sg)))
        return res

    # ---------------------------------------------------------------- alcance: toda la unidad
    def spans_unidad(self, items) -> dict:
        """items = [(clave, texto)] de una unidad (hilo de chat, doc o fila). Devuelve
        {clave: [(ini, fin, nuevo, tipo, k, regla)]}. Une oficio, barrio y año aunque estén en mensajes
        distintos del mismo hilo; solo actúa si la combinación existe en el maestro (1 <= k < K)."""
        ofi, bar, ciu, yrs, cargos = [], [], [], [], []
        for clave, s in items:
            if not s:
                continue
            p = _p(s)
            if self.rx_ofi:
                ofi += [(clave, m.start(), m.end(), self.var[m.group()], s) for m in self.rx_ofi.finditer(p)]
            if self.rx_bar:
                bar += [(clave, m.start(), m.end(), m.group()) for m in self.rx_bar.finditer(p)]
            if self.rx_ciu:
                ciu += [(clave, m.start(), m.end(), m.group()) for m in self.rx_ciu.finditer(p)]
            yrs += [(clave, a, b, y) for a, b, y in anios_vinculacion(s)]
            if self.rx_cargo:
                cargos += [(clave, m.start(), m.end(), m.group()) for m in self.rx_cargo.finditer(p)]
        out: dict = {}
        hechos: set = set()

        def poner(clave, a, b, nuevo, tipo, k, regla):
            if (clave, a, b) not in hechos:
                hechos.add((clave, a, b))
                out.setdefault(clave, []).append((a, b, nuevo, tipo, k, regla))

        ciudades_unidad = {c[3] for c in ciu}
        O, B, Y = {x[3] for x in ofi}, {x[3] for x in bar}, {x[3] for x in yrs}
        combos = []
        for o in sorted(O):
            for b in sorted(B):
                for y in sorted(Y):
                    combos.append((o, b, None, y))
            for c in sorted(ciudades_unidad):
                for y in sorted(Y):
                    combos.append((o, None, c, y))
            for b in sorted(B):
                combos.append((o, b, None, None))
        for o, b, c, y in combos:
            k = self.contar(o, b, c, y)
            if not (1 <= k < self.k):
                continue
            regla = "hilo_" + ("oficio_barrio_anio" if b and y else "oficio_lugar_anio" if y else "oficio_barrio")
            for clave, a, bb, oo, s in ofi:
                if oo == o:
                    poner(clave, a, bb, _capitaliza(s[a], self._sector_de(o)), "ocupacion", k, regla)
            if b:
                ciudad = self._ciudad_de_barrio(b, o, y, None, ciudades_unidad)
                if ciudad and plano(ciudad) != b:
                    for clave, a, bb, bn in bar:
                        if bn == b:
                            poner(clave, a, bb, ciudad, "barrio", k, regla)
            if y:
                for clave, a, bb, yy in yrs:
                    if yy == y:
                        poner(clave, a, bb, HACE, "anio", k, regla)
        # empleados: cargo + barrio + año de ingreso ("agente de soporte ... vive en El Prado ... desde 2024")
        if self.emp and cargos and bar and yrs:
            for cg in sorted({x[3] for x in cargos}):
                for b in sorted(B):
                    for y in sorted(Y):
                        cs = {plano(c) for c in self.barrios.get(b, set())}
                        ment = {c for c in cs if c in ciudades_unidad}
                        cand = [e for e in self.emp if e["cargo"] == cg and e["ingreso"] == y
                                and e["ciudad"] in (ment or cs)]
                        if not (1 <= len(cand) < self.k):
                            continue
                        ciudades = {e["ciudad_txt"] for e in cand}
                        if len(ciudades) != 1:
                            continue
                        ciudad = next(iter(ciudades))
                        regla = "empleado_cargo_barrio_anio"
                        for clave, a, bb, bn in bar:
                            if bn == b:
                                poner(clave, a, bb, ciudad, "barrio", len(cand), regla)
                        for clave, a, bb, yy in yrs:
                            if yy == y:
                                poner(clave, a, bb, HACE, "anio", len(cand), regla)
        return out


def segmentos(s: str):
    ini = 0
    for m in _FRASE.finditer(s):
        yield ini, s[ini:m.start()]
        ini = m.end()
    yield ini, s[ini:]


# ------------------------------------------------------------------ aplicar
def _es_sector(pseudo, v: str) -> bool:
    return v in set(pseudo.sectores.values()) | {pseudo.sector_defecto}


def aplicar(records, entidades, pseudo, k: int = K):
    """Muta `records` y devuelve (records, cambios)."""
    cambios: list = []
    maestro = maestro_de(records, entidades)
    barrios_por_ciudad: dict = {}
    for c in maestro:
        if c["barrio"]:
            barrios_por_ciudad.setdefault(c["ciudad"], []).append(c["barrio"])
    barrios_por_ciudad = {c: sorted(set(b)) for c, b in barrios_por_ciudad.items()}

    # 1) maestro de clientes: siempre
    for r in records:
        if r.get("table") != "clientes" or not isinstance(r.get("columns"), dict):
            continue
        cols = r["columns"]
        ocu = cols.get("ocupacion")
        if isinstance(ocu, str) and ocu and not _es_sector(pseudo, ocu):
            nuevo = pseudo.sector(ocu)
            cambios.append({"record_id": r["id"], "campo": "columns.ocupacion", "tipo": "ocupacion",
                            "antes": ocu, "despues": nuevo, "regla": "maestro"})
            cols["ocupacion"] = nuevo
        bar = cols.get("barrio")
        if isinstance(bar, str) and bar:
            nuevo = pseudo.barrio(bar, cols.get("ciudad", ""), barrios_por_ciudad)
            if nuevo != bar:
                cambios.append({"record_id": r["id"], "campo": "columns.barrio", "tipo": "barrio",
                                "antes": bar, "despues": nuevo, "regla": "maestro"})
                cols["barrio"] = nuevo

    # 2) texto: reglas de cada persona P en P.records, más tuplas sin nombre en todo
    por_registro: dict = {}
    for e in entidades or []:
        a = getattr(e, "atributos", None)
        if getattr(e, "kept", False) or not a:
            continue
        if not (a.get("ocupacion") or a.get("barrio") or a.get("anio_vinculacion")):
            continue
        pr = _Persona(e, pseudo)
        for rid in e.records:
            por_registro.setdefault(rid, []).append(pr)
    empleados = [r["columns"] for r in records if r.get("table") == "empleados" and isinstance(r.get("columns"), dict)]
    tuplas = Tuplas(maestro, pseudo, k, empleados)

    # unidades: un hilo de chat completo, o un doc / fila / pqr con todos sus campos libres
    unidades: dict = {}
    for r in records:
        for cont, clave, ruta, s in campos_libres(r):
            if s:
                u = ("hilo", r["thread_id"]) if "thread_id" in r else ("reg", r.get("id"))
                unidades.setdefault(u, []).append(((r.get("id"), ruta), s))
    de_unidad: dict = {}
    for items in unidades.values():
        for clave, lista in tuplas.spans_unidad(items).items():
            de_unidad[clave] = lista

    for r in records:
        personas = por_registro.get(r.get("id"), [])
        for cont, clave, ruta, s in list(campos_libres(r)):
            if not s:
                continue
            p = _p(s)
            spans = []
            for pr in personas:
                spans += [(a, b, n, t, who, "persona", None) for a, b, n, t, who in pr.spans(s, p)]
            for a, b, n, t, kk, tipo in tuplas.spans(s):
                spans.append((a, b, n, t, None, tipo, kk))
            for a, b, n, t, kk, tipo in de_unidad.get((r.get("id"), ruta), []):
                spans.append((a, b, n, t, None, tipo, kk))
            if not spans:
                continue
            spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
            elegidos, fin_prev = [], -1
            for sp in spans:
                if sp[0] >= fin_prev:
                    elegidos.append(sp)
                    fin_prev = sp[1]
            nuevo = s
            for a, b, n, t, who, regla, kk in reversed(elegidos):
                nuevo = nuevo[:a] + n + nuevo[b:]
            for a, b, n, t, who, regla, kk in elegidos:
                cambios.append({"record_id": r.get("id"), "campo": ruta, "tipo": t, "antes": s[a:b], "despues": n,
                                "entity_id": who, "regla": regla, **({"k": kk} if kk is not None else {})})
            cont[clave] = nuevo
    return records, cambios
