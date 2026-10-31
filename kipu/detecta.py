"""Detección de menciones por capas (solo librería estándar).

(a) diccionario de formas del grafo (normalización del juez), (b) patrones (correo, deletreado, cédula,
celular, placa, pasaporte, crédito, dirección, honorífico, @handles, uid de Slack, URLs), (c) coincidencia
tolerante a distancia 1 y (d) nombres capitalizados fuera del grafo (personas nuevas, relaciones).
Un gazetteer del corpus y una lista curada protegen organizaciones, marcas, lugares y figuras públicas.
Cada Mencion lleva atributos extra: cands, forma, izq, der, cabecera, rel, nuevo, kept.
"""
from __future__ import annotations

import re

from . import formas as F
from . import patrones as P
from .grafo import (Grafo, alnum, celular10, digitos, genero_defecto, hid, sembrar_cliente,
                    sembrar_empleado, toks)
from .modelo import Entidad, Mencion
from .texto import norm_mapa, span_original

COMUN = {"luz", "sol", "paz", "mar", "rosa", "julio", "pilar", "gloria", "esperanza", "victoria", "cielo", "dolores",
         "mercedes", "consuelo", "amparo", "mayo", "abril", "marzo", "alba", "perla", "flor", "nieves", "lucero",
         "estrella", "milagros", "soledad", "fe", "caridad", "belen", "guadalupe", "rocio", "socorro", "trinidad",
         "pastor", "leon", "bella", "linda", "dulce", "joya", "reina", "princesa", "marcial", "justo", "bueno",
         "cruz", "angel", "santos", "carmen", "clara"}
MESES_TOK = set(P.MESES)
STOP_START = {"hola", "gracias", "buenas", "buenos", "buen", "estimado", "estimada", "estimados", "senor", "senora",
              "senores", "sr", "sra", "srta", "dr", "dra", "don", "dona", "cliente", "clienta", "agente", "analista",
              "perfecto", "listo", "claro", "ok", "hey", "hi", "dear", "hello", "thanks", "thank", "soy", "yo", "mi",
              "su", "tu", "con", "para", "por", "de", "del", "la", "el", "los", "las", "un", "una", "en", "a", "y",
              "o", "que", "se", "me", "te", "le", "lo", "si", "no", "ya", "ah", "uy", "bienvenido", "bienvenida",
              "kipu", "pay", "cc", "cl", "cra", "tv", "av", "dg", "sur", "norte", "este", "oeste", "bis", "titular",
              "caso", "tarjeta", "cuenta", "credito", "pse", "nota", "total", "valor", "monto", "fecha", "asunto",
              "atentamente", "cordialmente", "saludos", "att", "att.", "ref", "tel", "nit", "pregunta", "respuesta"}
COMERCIO = {"compra", "retiro", "pago", "transferencia", "parqueadero", "peaje", "cajero", "corresponsal", "calle",
            "carrera", "avenida", "abono", "cuota", "debito", "nomina", "acuerdo", "cuenta", "tarjeta", "credito",
            "recibida", "recibido", "plaza", "parque", "centro", "comercial", "estacion", "terminal", "barrio"}
STOP_ALL = STOP_START | COMERCIO | {"nos", "es", "son", "fue", "era", "esta", "este", "estos", "esos", "ese", "eso", "tengo",
                         "tiene", "tienes", "hay", "como", "pero", "mas", "muy", "todo", "toda", "todos", "cuando",
                         "donde", "porque", "cual", "cuales", "quien", "tambien", "aqui", "alli", "ahora", "luego",
                         "entonces", "gracias", "favor", "puedes", "puede", "pueden"}
STOP_START = STOP_START | COMERCIO
CUE_FUERTE = re.compile(r"(?:\bsoy|me llamo|mi nombre es|a nombre de|de parte de|habla con|hablas con|te escribe|"
                        r"le escribe|titular|se llama|llamad[oa]|atiende|atendido por|con el senor|con la senora)\s*:?\s*$")
CUE_HOLA = re.compile(r"(?:\bhola|buenas|buenos dias|buenas tardes|buenas noches|\bgr?a?s?c?ias|gracias|hi|hey|dear|thanks|"
                      r"thank you|saludos|cordial saludo|estimad[oa]|bienvenid[oa]|perfecto|listo|claro|"
                      r"entiendo|tranquil[oa]|ok|okey|oye|mira)[\s,!.¡:]*$")
RX_CAP_TOK = re.compile(r"[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü'’]+")
RX_REL = re.compile(
    r"(?i:\b(?:mi|su|tu|mis|sus|nuestr[oa]|el|la|un|una)\s+"
    r"(?P<rel>mam[aá]|madre|pap[aá]|padre|hermano|hermana|esposo|esposa|marido|novio|novia|hij[oa]|jef[ea]|soci[oa]|"
    r"prim[oa]|t[ií][oa]|abuel[oa]|cu[ñn]ad[oa]|sobrin[oa]|amig[oa]|vecin[oa]|suegr[oa]|compadre|colega|"
    r"compa[ñn]er[oa]|yerno|nuera|pareja|emplead[oa])\b\s*(?:,|:|\(|-)?\s*(?:(?:se llama|llamad[oa]|es)\s+)?)"
    r"(?P<nombre>[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü'’]+(?:\s+(?:(?:de|del|la|los|las|y)\s+)?"
    r"[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü'’]+){0,2})")
GENERICOS_EMAIL = {"soporte", "info", "contacto", "ayuda", "hola", "noreply", "no-reply", "legal", "privacidad",
                   "datos", "prensa", "support", "help", "notificaciones", "cobranza", "servicio", "atencion",
                   "protecciondedatos", "pqr", "pqrs", "sic", "comunicaciones", "marketing", "ventas"}

# columnas estructuradas conocidas: tabla -> columna -> tipo
COLUMNAS = {
    "clientes": {"nombre_completo": "nombre", "num_doc": "cedula", "correo": "correo", "celular": "celular",
                 "direccion": "direccion", "fecha_nacimiento": "nacimiento"},
    "empleados": {"nombre": "nombre", "correo": "correo", "celular": "celular", "documento": "cedula",
                  "fecha_nacimiento": "nacimiento", "reporta_a": "nombre"},
    "pqrs": {"cedula": "cedula", "agente": "handle"},
}


def lev1(a: str, b: str) -> bool:
    """Distancia de edición <= 1 (insertar, borrar, sustituir o transponer dos vecinos)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        d = [i for i in range(la) if a[i] != b[i]]
        if len(d) == 1:
            return True
        return len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


class _Cand:
    __slots__ = ("a", "b", "tipo", "eids", "fuente", "prio", "extra")

    def __init__(self, a, b, tipo, eids=None, fuente="regla", prio=50, **extra):
        self.a, self.b, self.tipo, self.eids, self.fuente, self.prio, self.extra = a, b, tipo, eids, fuente, prio, extra


class Detector:
    def __init__(self, G: Grafo):
        self.G = G
        self.maxL = max([len(k) for k in G.formas_idx] + [1])
        self.dim = {}                     # n tokens -> [(joined, eid)] formas multi-token para tolerante
        for k, d in G.formas_idx.items():
            if len(k) >= 2:
                for eid, tipo in d.items():
                    if tipo == "nombre":
                        self.dim.setdefault(len(k), []).append((" ".join(k), k, eid))
        # pilas conocidas = tokens de pila/apodo del grafo
        self.pilas = {k[0] for k, d in G.formas_idx.items() if len(k) == 1 and any(t in ("pila", "apodo") for t in d.values())}
        from .grafo import catalogos
        cat = catalogos()
        self.given = (cat["given"] | self.pilas) - COMUN
        from .grafo import VOCAB
        self.surnames = (cat["surnames"] | VOCAB["surnames"]) - COMUN
        # gazetteer
        self.kept_idx = {}                # tokens -> (forma, razon)
        for o in P.KEPT_ORGS + list(G.gaz.get("comercios", [])):
            k = toks(o)
            if k:
                self.kept_idx[k] = (o, P.KEPT_RAZON)
        self.lugares = {}
        self.place_tok = set()
        for o in G.gaz.get("ciudades", []) + G.gaz.get("lugares", []) + [b for l in G.gaz.get("barrios", {}).values() for b in l]:
            k = toks(o)
            if k and len(o) > 2 and o[0].isalpha():
                self.lugares[k] = o
                self.place_tok.update(k)
        self.kipu_dir = toks(P.DIR_KIPU)

    # ------------------------------------------------------------------ campos
    @staticmethod
    def campos(r: dict):
        if "columns" in r:
            for k, v in r["columns"].items():
                yield "columns." + k, v
        elif "thread_id" in r:
            yield "text", r.get("text", "")
            for i, a in enumerate(r.get("attachments") or []):
                yield "attachments.%d.filename" % i, a.get("filename", "")
        else:
            yield "title", r.get("title", "")
            yield "filename", r.get("filename", "")
            yield "body", r.get("body", "")
            for k, v in (r.get("metadata") or {}).items():
                yield "metadata." + k, v if isinstance(v, str) else str(v)

    # ------------------------------------------------------------------ API
    def detectar(self, r: dict, ctx_autor: str | None = None) -> list:
        out = []
        for campo, texto in self.campos(r):
            if not isinstance(texto, str) or not texto.strip():
                continue
            out.extend(self.en_texto(r, campo, texto, ctx_autor))
        for campo, texto in self._claves(r):
            out.extend(self.en_texto(r, campo, texto, ctx_autor))
        est = self._estructuradas(r)
        if est:
            campos_est = {m.campo for m in est}
            out = [m for m in out if m.campo not in campos_est]
        out.extend(est)
        return out

    @staticmethod
    def _claves(r):
        """Claves de metadata y columnas, que también pueden esconder un nombre."""
        if "columns" in r:
            for k in r["columns"]:
                yield "columns." + k + "#clave", k
        elif "metadata" in r:
            for k in r["metadata"]:
                yield "metadata." + k + "#clave", k

    def _estructuradas(self, r):
        """Columnas con tipo conocido: una mención con el valor entero."""
        out = []
        if "columns" not in r:
            return out
        tabla = r["table"]
        G = self.G
        dueno = None
        if tabla == "clientes":
            dueno = G.llaves.get("cl:" + r["columns"].get("cliente_id", ""))
            if dueno is None and r["columns"].get("cliente_id"):
                # fila de un cliente desconocido: persona nueva (o la que ya tiene su cédula/correo/celular)
                dueno = sembrar_cliente(G, r, genero_defecto(), enlazar=True).entity_id
        elif tabla == "empleados":
            dueno = G.llaves.get("kp:" + r["columns"].get("id", ""))
            if dueno is None and r["columns"].get("id"):
                dueno = sembrar_empleado(G, r, genero_defecto(), enlazar=True).entity_id
        for col, tipo in COLUMNAS.get(tabla, {}).items():
            v = r["columns"].get(col)
            if not v or not v.strip():
                continue
            m = Mencion(r["id"], "columns." + col, 0, len(v), v, tipo, None, "grafo")
            m.cands, m.forma, m.izq, m.der, m.cabecera, m.rel, m.nuevo, m.kept = [], "completo", "", "", "", None, False, False
            m.estructurada = True
            if tipo == "nombre" and col == "reporta_a":
                jefe = G.jefe.get(dueno) if dueno else None
                m.entity_id = jefe
                m.cands = [jefe] if jefe else []
            elif tipo == "nombre":
                m.entity_id = dueno
                m.cands = [dueno] if dueno else []
            elif tipo == "handle":
                e = G.buscar("handle", v)
                m.entity_id = e
                m.cands = [e] if e else []
            elif tipo in ("correo", "celular", "direccion", "nacimiento") and dueno:
                m.entity_id, m.cands = dueno, [dueno]
            elif tipo == "cedula":
                e = G.buscar("cedula", v)
                m.entity_id, m.cands = e, [e] if e else []
            out.append(m)
        return out

    # ------------------------------------------------------------------ núcleo
    def en_texto(self, r, campo, t, ctx_autor=None):
        G = self.G
        n, mapa = norm_mapa(t)
        if "%" in n:   # URL codificada: %20 -> espacios (misma longitud, los offsets no cambian)
            for k_, v_ in (("%20", "   "), ("%2e", " . "), ("%2d", " - "), ("%5f", " _ ")):
                n = n.replace(k_, v_)
        L = len(t)
        cs: list = []

        def add(a, b, tipo, eids=None, fuente="regla", prio=50, **extra):
            if b > a:
                cs.append(_Cand(a, b, tipo, eids, fuente, prio, **extra))

        def o(i, j):  # offsets del normalizado -> original
            return span_original(mapa, i, j, L)

        # ---- uid de Slack <@U...>
        for m in P.RX_UID.finditer(t):
            e = G.ident.get(("uid", m.group(1)))
            add(m.start(), m.end(), "handle", [e] if e else [], "grafo", 100, uid=m.group(1), forma="uid")

        # ---- correos y deletreados
        for m in P.RX_EMAIL.finditer(n):
            a, b = o(m.start(), m.end())
            self._correo(add, t, a, b, m.group(0), "correo", 95)
        for a, b, correo in F.buscar_deletreados(t):
            self._correo(add, t, a, b, correo, "correo_deletreado", 96)

        # ---- números
        self._numeros(add, n, mapa, t, o)

        # ---- direcciones
        for m in P.RX_DIRECCION.finditer(n):
            a, b = o(m.start(), m.end())
            tk = toks(t[a:b])
            if self.kipu_dir and tk[:len(self.kipu_dir)] == self.kipu_dir:
                add(a, b, "direccion", [], "gazetteer", 97, kept=True, forma="oficina")
                continue
            e = G.ident.get(("direccion", " ".join(tk)))
            add(a, b, "direccion", [e] if e else [], "grafo" if e else "regla", 90, forma="direccion")

        # ---- fechas de nacimiento conocidas / con cue
        self._nacimientos(add, n, o, t)

        # ---- handles @algo
        for m in P.RX_HANDLE.finditer(n):
            a, b = o(m.start(), m.end())
            h = m.group(1)
            e = G.ident.get(("handle", h))
            cands = [e] if e else self._por_forma((tuple(re.findall(r"[a-z0-9]+", h)),))
            if cands or "." in h or "_" in h:
                add(a + 1, b, "handle", cands, "grafo" if cands else "regla", 88, forma="handle", sin_arroba=True)

        # ---- gazetteer / kept y diccionario por tokens
        tokens = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[a-z0-9]+", n)]
        self._diccionario(add, t, n, mapa, tokens, o)

        # ---- honoríficos
        self._honorificos(add, t, n, mapa, tokens, o)

        # ---- relaciones y nuevos nombres
        self._nuevos(add, t, n, mapa, tokens, o)

        # ---- selección sin solapes: más largo primero, luego prioridad
        cs.sort(key=lambda c: (-(c.b - c.a), -c.prio, c.a))
        elegidos, ocupado = [], []
        for c in cs:
            if any(c.a < y and x < c.b for x, y in ocupado):
                continue
            ocupado.append((c.a, c.b))
            elegidos.append(c)
        elegidos.sort(key=lambda c: c.a)
        res = []
        cab_cache = {}
        for c in elegidos:
            if c.fuente == "proteger":
                continue
            ni = c.extra.get("kept")
            m = Mencion(r["id"], campo, c.a, c.b, t[c.a:c.b], c.tipo,
                        c.eids[0] if c.eids and len(c.eids) == 1 and not c.extra.get("tolerante") else None,
                        c.fuente if c.fuente in ("regla", "grafo", "tolerante", "llm") else "regla")
            m.cands = list(c.eids or [])
            m.forma = c.extra.get("forma", "")
            m.izq = n[max(0, self._ni(mapa, c.a) - 48): self._ni(mapa, c.a)]
            m.der = n[self._ni(mapa, c.b): self._ni(mapa, c.b) + 48]
            m.cabecera = self._cabecera(t, c.a) if "|" in t else ""
            m.rel = c.extra.get("rel")
            m.nuevo = bool(c.extra.get("nuevo"))
            m.kept = bool(ni)
            m.razon = c.extra.get("razon", "")
            m.uid = c.extra.get("uid")
            m.estructurada = False
            for k_, v_ in c.extra.items():
                if k_ not in ("kept", "forma", "rel", "nuevo", "razon", "uid"):
                    setattr(m, k_, v_)
            res.append(m)
        return res

    @staticmethod
    def _ni(mapa, i):
        """Índice normalizado del primer carácter cuyo original es >= i."""
        import bisect
        return bisect.bisect_left(mapa, i)

    @staticmethod
    def _cabecera(t, pos):
        ini = t.rfind("\n", 0, pos) + 1
        fin = t.find("\n", pos)
        linea = t[ini: fin if fin >= 0 else len(t)]
        if not linea.lstrip().startswith("|"):
            return ""
        celda = t[ini:pos].count("|") - 1
        lineas = t[:max(ini - 1, 0)].split("\n") if ini > 0 else []
        k = len(lineas) - 1
        while k >= 0 and lineas[k].lstrip().startswith("|"):
            k -= 1
        cab = (lineas[k + 1] if k + 1 < len(lineas) and lineas[k + 1].lstrip().startswith("|") else linea)
        celdas = [c.strip() for c in cab.strip().strip("|").split("|")]
        if 0 <= celda < len(celdas):
            return F.plano(celdas[celda])
        return ""

    # ------------------------------------------------------------------ capas
    def _por_forma(self, claves):
        res = []
        for k in claves:
            for eid in self.G.formas_idx.get(k, {}):
                if eid not in res:
                    res.append(eid)
        return res

    def _correo(self, add, t, a, b, correo, tipo, prio):
        G = self.G
        correo = correo.lower()
        local, _, dom = correo.partition("@")
        e = G.ident.get(("correo", correo))
        if e is None and "+" in local:           # alias con etiqueta: usuario+tag@dominio
            e = G.ident.get(("correo", local.split("+")[0] + "@" + dom))
        if e:
            add(a, b, tipo, [e], "grafo", prio, forma="correo", correo=correo)
            return
        if dom == "kipupay.co" and local.split(".")[0] in GENERICOS_EMAIL or local in GENERICOS_EMAIL:
            add(a, b, tipo, [], "gazetteer", prio, kept=True, forma="correo_generico", razon="buzón corporativo genérico")
            return
        cands = self._por_forma([tuple(re.findall(r"[a-z0-9]+", local.split("+")[0]))])
        # un correo desconocido cuya parte local coincide con una forma conocida
        add(a, b, tipo, cands, "grafo" if cands else "regla", prio, forma="correo", correo=correo, desconocido=not cands)

    def _numeros(self, add, n, mapa, t, o):
        G = self.G
        usados = []

        def tomar(m, tipo, prio, forma, cands=None, fuente="regla", **ex):
            a, b = o(m.start(), m.end())
            add(a, b, tipo, cands or [], fuente, prio, forma=forma, **ex)
            usados.append((m.start(), m.end()))

        for m in P.RX_CREDITO.finditer(n):
            e = G.buscar("credito", m.group(0))
            tomar(m, "credito", 92, "credito", [e] if e else [], "grafo" if e else "regla")
        for m in P.RX_CEL.finditer(n):
            d = celular10(m.group(0))
            if len(d) != 10:
                continue
            e = G.buscar("celular", d)
            tomar(m, "celular", 91, "celular", [e] if e else [], "grafo" if e else "regla")
        for m in P.RX_CEDULA_PUNTOS.finditer(n):
            if any(m.start() < y and x < m.end() for x, y in usados):
                continue
            txt = m.group(0)
            e = G.buscar("cedula", txt)
            if txt == "901.456.789":
                fin = m.end() + 2 if n[m.end():m.end() + 2] == "-3" else m.end()
                a, b = o(m.start(), fin)
                add(a, b, "cedula", [], "gazetteer", 98, kept=True, forma="nit", razon="NIT de Kipu Pay (organización)")
                usados.append((m.start(), fin))
                continue
            grupos = txt.count(".") + 1
            izq = n[max(0, m.start() - 40): m.start()]
            if e is None and grupos == 3 and not P.CUE_CEDULA.search(izq):
                continue   # 2.390.000: casi siempre un monto
            if e is None and re.search(r"(?:\$|cop|pesos|valor|monto|total|saldo)\s*$", izq):
                continue
            tomar(m, "cedula", 91, "cedula", [e] if e else [], "grafo" if e else "regla")
        # runs de dígitos con separadores: conocidos con otro formato, o con cue de cédula
        for m in re.finditer(r"(?<![\d])\d(?:[ .,'`·/_\-]{0,2}\d){5,12}(?![\d])", n):
            if any(m.start() < y and x < m.end() for x, y in usados):
                continue
            d = re.sub(r"\D", "", m.group(0))
            if m.group(0).count("-") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0)):
                continue
            izq = n[max(0, m.start() - 40): m.start()]
            e = G.buscar("cedula", d) if len(d) >= 6 else None
            if e is None and len(d) == 10 and d.startswith("3"):
                e2 = G.buscar("celular", d)
                if e2:
                    tomar(m, "celular", 90, "celular", [e2], "grafo")
                    continue
            if e is None and len(d) == 12 and d.startswith("57"):
                e2 = G.buscar("celular", d)
                if e2:
                    tomar(m, "celular", 90, "celular", [e2], "grafo")
                    continue
            if e is not None:
                tomar(m, "cedula", 89, "cedula", [e], "grafo")
            elif 6 <= len(d) <= 10 and P.CUE_CEDULA.search(izq) and not (len(d) == 10 and d.startswith("3")):
                tomar(m, "cedula", 80, "cedula")
        # números de cuenta: "cuenta 9120 9765 655"
        for m in re.finditer(r"(?:cuenta|cta|account|acct)[a-z]*\.?\s*(?:n[o°º.]*\s*|numero\s*|#\s*|de ahorros?\s*|corriente\s*)?"
                             r"(\d(?:[ \-.]?\d){7,17})(?!\d)", n):
            a0, b0 = m.start(1), m.end(1)
            if any(a0 < y and x < b0 for x, y in usados):
                continue
            d = re.sub(r"\D", "", m.group(1))
            if d.startswith("4471") and len(d) == 8:
                continue
            a, b = o(a0, b0)
            e = G.buscar("cedula", d) or G.buscar("celular", d)
            add(a, b, "credito", [e] if e else [], "grafo" if e else "regla", 93, forma="cuenta")
            usados.append((a0, b0))
        # placas y pasaportes
        for m in P.RX_PLACA.finditer(n):
            if any(m.start() < y and x < m.end() for x, y in usados):
                continue
            a, b = o(m.start(), m.end())
            orig = t[a:b]
            letras = m.group(1)
            if letras in P.PLACA_NO:
                continue
            e = G.buscar("placa", m.group(0))
            izq = n[max(0, m.start() - 24): m.start()]
            mayus = orig[:3].isupper()
            if e or (mayus and (m.group(2) == "-" or not m.group(2) or P.CUE_PLACA.search(izq))
                     and not (m.group(2) == " " and not P.CUE_PLACA.search(izq))):
                add(a, b, "placa", [e] if e else [], "grafo" if e else "regla", 90, forma="placa")
        for m in P.RX_PASAPORTE.finditer(n):
            a, b = o(m.start(), m.end())
            orig = t[a:b]
            e = G.buscar("pasaporte", m.group(0))
            izq = n[max(0, m.start() - 36): m.start()]
            if e or P.CUE_PASAPORTE.search(izq) or orig[:2].isupper():
                add(a, b, "pasaporte", [e] if e else [], "grafo" if e else "regla", 90, forma="pasaporte")

    def _nacimientos(self, add, n, o, t):
        G = self.G
        conocidas = {}
        for e in G.values():
            for iso in e.ids.get("nacimientos", []):
                conocidas.setdefault(iso, []).append(e.entity_id)
        fechas = []
        for m in P.RX_FECHA_ISO.finditer(n):
            fechas.append((m.start(), m.end(), "%s-%s-%s" % m.groups(), "iso"))
        for m in re.finditer(r"(?<![\d/])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?![\d])", n):
            d1, d2, y = int(m.group(1)), int(m.group(2)), m.group(3)
            dmy = "%s-%02d-%02d" % (y, d2, d1) if d2 <= 12 and d1 <= 31 else None
            mdy = "%s-%02d-%02d" % (y, d1, d2) if d1 <= 12 and d2 <= 31 else None
            if mdy and mdy in conocidas and not (dmy and dmy in conocidas):
                fechas.append((m.start(), m.end(), mdy, "mdy"))
            elif dmy:
                fechas.append((m.start(), m.end(), dmy, "dmy"))
            elif mdy:
                fechas.append((m.start(), m.end(), mdy, "mdy"))
        for m in P.RX_FECHA_TXT.finditer(n):
            if m.group(3):
                fechas.append((m.start(), m.end(), "%s-%02d-%02d" % (m.group(3), P.MESES.index(m.group(2)) + 1, int(m.group(1))), "texto"))
        for i, j, iso, fmt in fechas:
            izq = n[max(0, i - 44): i]
            cue = re.search(r"\b(?:nacimiento|nacid[oa]|nacio|cumple\w*|born|dob|birth\w*|fecha de nac\w*)\b", izq)
            cands = conocidas.get(iso, [])
            if cands or cue:
                a, b = o(i, j)
                add(a, b, "nacimiento", cands, "grafo" if cands else "regla", 89, forma="nacimiento", iso=iso, fmt=fmt)

    def _diccionario(self, add, t, n, mapa, tokens, o):
        G = self.G
        N = len(tokens)
        maxk = max(self.maxL, max([len(k) for k in self.kept_idx] + [1]), max([len(k) for k in self.lugares] + [1]))
        for i in range(N):
            for L in range(min(maxk, N - i), 0, -1):
                seq = tuple(tk[2] for tk in tokens[i:i + L])
                if L >= 2:
                    bad = False
                    for j in range(i, i + L - 1):
                        gap = n[tokens[j][1]:tokens[j + 1][0]]
                        # un salto de línea suelto entre nombre y apellido (texto de PDF partido) sí une
                        if not re.fullmatch(r"(?:[\s._\-+]|%20|%2e|%2d|%5f){1,3}", gap) or gap.count("\n") > 1 \
                                or (gap.count("\n") == 1 and not re.fullmatch(r"[ \t]*\n[ \t]*", gap)):
                            bad = True
                            break
                    if bad:
                        continue
                ini, fin = tokens[i][0], tokens[i + L - 1][1]
                # gazetteer curado: se conserva
                if seq in self.kept_idx:
                    f, razon = self.kept_idx[seq]
                    if not (L == 1 and self._es_persona_unica(seq)):
                        a, b = o(ini, fin)
                        add(a, b, "nombre", [], "gazetteer", 70, kept=True, razon=razon, forma="organizacion", clave=f)
                        continue
                if seq in self.lugares and seq not in G.formas_idx:
                    a, b = o(ini, fin)
                    add(a, b, "nombre", [], "proteger", 60, forma="lugar")
                    continue
                d = G.formas_idx.get(seq)
                if not d:
                    continue
                tipos = set(d.values())
                a, b = o(ini, fin)
                orig = t[a:b]
                if L == 1:
                    if tipos <= {"ap"}:
                        continue             # apellido suelto: solo con honorífico
                    if "pila" in tipos or "apodo" in tipos:
                        if not self._pila_ok(seq[0], orig, n, ini, fin, tipos):
                            continue
                        add(a, b, "apodo" if tipos == {"apodo"} else "nombre", list(d), "grafo", 60,
                            forma="pila" if "pila" in tipos else "apodo")
                        continue
                    # local / handle / slug de un token
                    if len(seq[0]) < 5:
                        continue
                    add(a, b, "handle" if "local" in tipos else "nombre", list(d), "grafo", 78, forma="local")
                    continue
                forma = "completo"
                if re.search(r"[_\-]", n[ini:fin]) and not re.search(r"\s", n[ini:fin]):
                    forma = "slug"
                add(a, b, "slug" if forma == "slug" else "nombre", list(d), "grafo", 75, forma=forma)

    def _es_persona_unica(self, seq):
        d = self.G.formas_idx.get(seq)
        return bool(d) and False

    def _pila_ok(self, tok, orig, n, ini, fin, tipos):
        if tok in MESES_TOK:
            izq = n[max(0, ini - 10): ini]
            der = n[fin: fin + 8]
            if re.search(r"(?:de|del|en|a|desde|hasta|mes)\s*$", izq) or re.match(r"\s*(?:de\s*)?\d", der):
                return False
        if not orig[:1].isupper():
            if "apodo" in tipos and "pila" not in tipos:
                return False
            if len(tok) < 4 or tok in COMUN:
                return False
            # en minúscula solo es nombre con un saludo, firma o vocativo ("gracias isabel!"), no en "muy clara la"
            izq = n[max(0, ini - 24): ini]
            der = n[fin: fin + 3]
            vocativo = bool(re.search(r"(?:[,;:¡¿]|[!.?]\s|^)\s*$", izq)) and bool(re.match(r"\s*[.!?,;:]", der))
            if not (CUE_FUERTE.search(izq) or CUE_HOLA.search(izq) or vocativo):
                return False
        elif tok in COMUN:
            izq = n[max(0, ini - 24): ini]
            der = n[fin: fin + 3]
            vocativo = bool(re.search(r"(?:[,;:¡¿]|[!.?]\s|^)\s*$", izq)) and bool(re.match(r"\s*[.!?,;:]", der))
            if not (CUE_FUERTE.search(izq) or CUE_HOLA.search(izq) or vocativo):
                return False
        return True

    def _honorificos(self, add, t, n, mapa, tokens, o):
        G = self.G
        for m in P.RX_HONORIFICO.finditer(n):
            ini = m.end()
            sig = [tk for tk in tokens if tk[0] >= ini][:3]
            if not sig or sig[0][0] - ini > 0:
                continue
            a0, _ = o(sig[0][0], sig[0][1])
            if not t[a0:a0 + 1].isupper():
                continue
            hon = m.group(1).strip(". ")
            for L in (3, 2, 1):
                if len(sig) < L:
                    continue
                seq = tuple(tk[2] for tk in sig[:L])
                if L > 1 and any(not re.fullmatch(r"[\s._\-]{1,3}", n[sig[j][1]:sig[j + 1][0]]) for j in range(L - 1)):
                    continue
                if L > 1 and not t[o(sig[L - 1][0], sig[L - 1][1])[0]:][:1].isupper():
                    continue
                d = G.formas_idx.get(seq)
                if d:
                    a, b = o(sig[0][0], sig[L - 1][1])
                    add(a, b, "nombre", list(d), "grafo", 85, forma="honorifico", hon=hon,
                        honorifico_f=hon in P.HONORIFICOS_F)
                    break
            else:
                tk = sig[0]
                if tk[2] in STOP_ALL or tk[2] in self.place_tok and False:
                    continue
                a, b = o(tk[0], tk[1])
                if len(tk[2]) >= 3 and not any(x in self.kept_idx for x in [(tk[2],)]):
                    add(a, b, "nombre", [], "regla", 84, forma="honorifico", nuevo=True, hon=hon,
                        honorifico_f=hon in P.HONORIFICOS_F, apellido_solo=True)

    def _nuevos(self, add, t, n, mapa, tokens, o):
        G = self.G
        # ---- relaciones: "mi mamá, Ignacio"
        for m in RX_REL.finditer(t):
            nom = m.group("nombre")
            rel = F.plano(m.group("rel")).strip()
            a, b = m.start("nombre"), m.end("nombre")
            pal = nom.split()
            # recorta palabras de parada al final ("Daniel Me" no existe por ser capitalizadas)
            while pal and F.plano(pal[-1]) in STOP_ALL:
                pal.pop()
            if not pal or F.plano(pal[0]) in STOP_ALL:
                continue
            b = a + len(" ".join(pal)) if " ".join(pal) == nom[:len(" ".join(pal))] else b
            base = P.RELACIONES.get(rel, rel)
            tk = toks(t[a:b])
            if tk in self.kept_idx or (tk[:1] and (tk[0],) in self.kept_idx and len(tk) == 1):
                continue
            d = G.formas_idx.get(tk)
            add(a, b, "nombre", list(d) if d else [], "grafo" if d else "regla", 74, forma="relacion", rel=base,
                nuevo=not d)
        # ---- runs capitalizados
        posiciones = [(m.start(), m.end(), m.group(0)) for m in RX_CAP_TOK.finditer(t)]
        runs, cur = [], []
        for p in posiciones:
            if cur and re.fullmatch(r"[ \t]+(?:(?:de|del|la|los|las)[ \t]+)?", t[cur[-1][1]:p[0]]):
                cur.append(p)
            else:
                if cur:
                    runs.append(cur)
                cur = [p]
        if cur:
            runs.append(cur)
        for run in runs:
            self._run(add, t, n, mapa, run)

    def _protegidos(self, pl):
        """Índices de tokens cubiertos por gazetteer, lugares o formas del grafo (frases más largas)."""
        G = self.G
        prot = set()
        N = len(pl)
        for i in range(N):
            for L in range(min(5, N - i), 0, -1):
                seq = tuple(pl[i:i + L])
                if seq in self.kept_idx or seq in self.lugares or (L >= 2 and seq in G.formas_idx):
                    prot.update(range(i, i + L))
                    break
        return prot

    def _tolerante_corrida(self, add, t, run, pl0):
        """Coincidencia a distancia 1 sobre la corrida completa de palabras, antes de partirla.

        La exacta siempre gana: si la subcorrida es una forma conocida no se toca. Varios candidatos
        a distancia 1 se pasan al resolvedor, que usa evidencia o la trata como persona nueva."""
        N = len(run)
        usados = []
        for L in range(min(N, 4), 1, -1):
            for i in range(N - L + 1):
                if any(i < y and x < i + L for x, y in usados):
                    continue
                sub = run[i:i + L]
                tk = toks(t[sub[0][0]:sub[-1][1]])
                if len(tk) != L or tk in self.G.formas_idx or tk in self.kept_idx or tk in self.lugares:
                    continue
                if any(x in STOP_ALL for x in pl0[i:i + L]):
                    continue
                cands = self._tolerante(tk)
                if cands:
                    add(sub[0][0], sub[-1][1], "nombre", cands, "tolerante", 53, forma="tolerante", tolerante=True)
                    usados.append((i, i + L))

    def _run(self, add, t, n, mapa, run):
        pl0 = [F.plano(x[2]) for x in run]
        self._tolerante_corrida(add, t, run, pl0)
        prot = self._protegidos(pl0)
        if prot:
            seg = []
            for idx, p in enumerate(run):
                if idx in prot:
                    if seg:
                        self._run1(add, t, n, mapa, seg)
                    seg = []
                else:
                    seg.append(p)
            if seg:
                self._run1(add, t, n, mapa, seg)
            return
        self._run1(add, t, n, mapa, run)

    def _run1(self, add, t, n, mapa, run):
        G = self.G
        pl = [F.plano(x[2]) for x in run]
        # recorta paradas al inicio y al final
        i, j = 0, len(run)
        while i < j and pl[i] in STOP_START:
            i += 1
        while j > i and pl[j - 1] in STOP_ALL:
            j -= 1
        if i >= j:
            return
        # el nombre arranca en el primer token de pila conocida; los previos se descartan
        k = i
        while k < j and pl[k] not in self.given:
            k += 1
        if k >= j:
            # sin pila conocida: dos o más palabras con algún apellido conocido (p. ej. "Isidora Quintana")
            if j - i >= 2 and any(x in self.surnames for x in pl[i + 1:j]) and not any(x in self.place_tok for x in pl[i:j]):
                k = i
            else:
                return
        run, pl = run[k:j], pl[k:j]
        # corta en lugares que no son parte del nombre (p.ej. "Daniel Cali")
        a, b = run[0][0], run[-1][1]
        tk = toks(t[a:b])
        if tk in self.kept_idx or tk in self.lugares:
            return
        izq = self._izq(t, a)
        if tk in G.formas_idx:
            return   # ya lo cubre el diccionario
        if len(run) == 1:
            tok = pl[0]
            if tok in COMUN or tok in MESES_TOK or tok in self.place_tok:
                return
            if not (CUE_FUERTE.search(izq) or CUE_HOLA.search(izq)):
                if tok not in self.given:
                    return
                if tok in {x[0] for x in G.formas_idx if len(x) == 1}:
                    return    # ya lo trata el diccionario con evidencia
            add(a, b, "nombre", [], "regla", 55, forma="pila_nueva", nuevo=True)
            return
        # 2+ palabras: ninguna debe ser parada ni lugar suelto
        if any(x in STOP_ALL for x in pl[1:]):
            # recorta en la primera parada
            cut = next(x for x in range(1, len(pl)) if pl[x] in STOP_ALL)
            run, pl = run[:cut], pl[:cut]
            if len(run) == 1:
                return
            a, b = run[0][0], run[-1][1]
            tk = toks(t[a:b])
        if tk in self.kept_idx or tk in self.lugares or tk in G.formas_idx:
            return
        cands = self._tolerante(tk)
        if cands:
            add(a, b, "nombre", cands, "tolerante", 52, forma="tolerante", tolerante=True)
            return
        if all(x in self.place_tok for x in pl[1:]) and pl[0] not in self.given:
            return
        add(a, b, "nombre", [], "regla", 56, forma="nombre_nuevo", nuevo=True)

    @staticmethod
    def _izq(t, a):
        from .texto import norm
        return norm(t[max(0, a - 36): a])

    def _tolerante(self, tk):
        if len(tk) < 2 or len(tk) > 4 or any(len(x) < 3 for x in tk):
            return []
        s = " ".join(tk)
        res = []
        for joined, k, eid in self.dim.get(len(tk), []):
            if joined != s and abs(len(joined) - len(s)) <= 1 and sum(1 for x, y in zip(k, tk) if x != y) <= 1 and lev1(joined, s):
                if eid not in res:
                    res.append(eid)
        return res


_CACHE: dict = {}


def detector(grafo: Grafo) -> Detector:
    k = id(grafo)
    d = _CACHE.get(k)
    if d is None or d.G is not grafo or d.nforms != len(grafo.formas_idx):
        d = Detector(grafo)
        d.nforms = len(grafo.formas_idx)
        _CACHE.clear()
        _CACHE[k] = d
    return d


def detectar(record: dict, grafo: Grafo, ctx_autor: str | None = None) -> list:
    """Menciones de un registro (todas sus capas)."""
    return detector(grafo).detectar(record, ctx_autor)
