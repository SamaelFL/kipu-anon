"""Grafo de identificadores: cada entidad es una persona con todas sus llaves y formas.

Los nombres son etiquetas, nunca llaves. Las componentes se unen solo por identificadores fuertes
(CL-, KP-, uid, correo, cédula, radicado, crédito). Solo librería estándar.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import formas as F
from . import patrones as P
from .modelo import Entidad
from .texto import norm

DATA = Path(__file__).parent / "data"
VERSION = 2


def hid(llave: str, prefijo: str = "p_") -> str:
    return prefijo + hashlib.sha1(llave.encode("utf-8")).hexdigest()[:8]


def toks(s: str) -> tuple:
    return tuple(re.findall(r"[a-z0-9]+", norm(s)))


def digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def celular10(s: str) -> str:
    d = digitos(s)
    return d[2:] if len(d) == 12 and d.startswith("57") else d


def alnum(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s or "").upper()


# ------------------------------------------------------------------ catálogos de nombres
_CAT: dict = {}


def catalogos() -> dict:
    if not _CAT:
        def leer(n):
            return [x.strip() for x in open(DATA / n, encoding="utf-8") if x.strip()]
        pil = {}
        for g, n in (("f", "nombres_mujer.txt"), ("m", "nombres_hombre.txt")):
            for x in leer(n):
                for t in x.split():
                    pil[F.plano(t)] = g
        reales = json.load(open(DATA / "genero_reales.json", encoding="utf-8"))
        given = set(pil) | set(reales)
        _CAT["given"] = given
        _CAT["surnames"] = {F.plano(t) for x in leer("apellidos.txt") for t in x.split()}
    return _CAT


VOCAB = {"given": set(), "surnames": set()}


def fijar_vocab(nombres):
    """Aprende del corpus qué tokens son de pila (1.º) y cuáles apellidos (últimos / 2.º de nombres de 2)."""
    given, sur = set(), set()
    for n in nombres:
        t = [F.plano(x) for x in n.split()]
        if not t:
            continue
        given.add(t[0])
        if len(t) == 2:
            sur.add(t[1])
        elif len(t) >= 3:
            sur.add(t[-1])
    VOCAB["given"], VOCAB["surnames"] = given, sur


def persona_de(nombre: str, genero: str = "") -> F.Persona:
    """Parte un nombre completo en nombres/apellidos (2 nombres si el 2.º es de pila y no apellido)."""
    cat = catalogos()
    cat = {"given": cat["given"] | VOCAB["given"], "surnames": (cat["surnames"] | VOCAB["surnames"])}
    pal = []
    buf = []
    toks_ = nombre.split()
    for i, t in enumerate(toks_):
        if t.lower() in F.PARTICULAS and i < len(toks_) - 1:
            buf.append(t)
        else:
            pal.append(" ".join(buf + [t]))
            buf = []
    n = len(pal)
    if n <= 1:
        return F.Persona(tuple(pal), (), genero)
    if n == 2:
        return F.Persona((pal[0],), (pal[1],), genero)
    def es_pila(t):
        t = F.plano(t)
        return t in cat["given"] and t not in cat["surnames"]
    k = 1
    while k < n - 1 and k < n - 1 and es_pila(pal[k]) and (n - k) >= 2:
        k += 1
        if n - k < 2 and n >= 3:
            break
    k = min(k, n - 1)
    if n == 3 and k > 2:
        k = 2
    return F.Persona(tuple(pal[:k]), tuple(pal[k:]), genero)


class Grafo(dict):
    """dict entity_id -> Entidad, con índices."""

    def __init__(self):
        super().__init__()
        self.users: dict = {}        # uid -> {real_name, display, handle, email, title, bot, deleted}
        self.ident: dict = {}        # (tipo, clave) -> eid | None (ambiguo)
        self.formas_idx: dict = {}   # tuple(tokens) -> {eid: tipo}
        self.gaz: dict = {"ciudades": [], "barrios": {}, "lugares": [], "comercios": []}
        self.tx: dict = {}           # cliente_id -> [(fecha_iso, monto)]
        self.jefe: dict = {}         # eid -> eid del jefe
        self.llaves: dict = {}       # llave -> eid
        self.pila_ap: dict = {}      # (pila, ap1) planos -> [eid]

    # ------------------------------------------------------------ altas
    def nueva(self, llave: str, **kw) -> Entidad:
        eid = hid(llave)
        if eid in self:
            return self[eid]
        e = Entidad(entity_id=eid, llave=llave, **kw)
        self[eid] = e
        self.llaves[llave] = eid
        return e

    def forma(self, eid: str, forma: str, tipo: str = "nombre", declarar: bool = False):
        if not forma or not forma.strip():
            return
        k = toks(forma)
        if not k:
            return
        self.formas_idx.setdefault(k, {})
        self.formas_idx[k].setdefault(eid, tipo)
        if declarar:
            self[eid].formas.add(forma)

    def id(self, eid: str, tipo: str, valor: str):
        """Registra un identificador de la entidad y su índice (None si lo reclaman dos entidades)."""
        e = self[eid]
        if not valor:
            return
        clave = self.clave_id(tipo, valor)
        if not clave:
            return
        lista = {"correo": "correos", "celular": "celulares", "placa": "placas", "pasaporte": "pasaportes",
                 "credito": "creditos", "uid": "uids", "handle": "handles", "radicado": "radicados",
                 "cedula": "cedulas", "direccion": "direcciones", "nacimiento": "nacimientos"}.get(tipo)
        if lista:
            l = e.ids.setdefault(lista, [])
            if valor not in l:
                l.append(valor)
        previo = self.ident.get((tipo, clave), eid)
        self.ident[(tipo, clave)] = eid if previo == eid else None
        if tipo in ("correo", "celular", "placa", "pasaporte", "credito", "cedula", "direccion", "nacimiento"):
            e.formas.add(valor)

    @staticmethod
    def clave_id(tipo: str, valor: str) -> str:
        if tipo in ("correo", "handle"):
            return valor.strip().lower()
        if tipo in ("cedula", "credito"):
            return digitos(valor)
        if tipo == "celular":
            return celular10(valor)
        if tipo in ("placa", "pasaporte"):
            return alnum(valor)
        if tipo == "direccion":
            return " ".join(toks(valor))
        if tipo == "nacimiento":
            return valor.strip()
        return valor.strip()

    def buscar(self, tipo: str, valor: str):
        return self.ident.get((tipo, self.clave_id(tipo, valor)))

    # ------------------------------------------------------------ formas de nombre
    def formas_nombre(self, eid: str, nombre: str):
        e = self[eid]
        if nombre and nombre not in e.atributos.setdefault("personas", []):
            e.atributos["personas"].append(nombre)
        if nombre:
            e.formas.add(nombre)
        p = persona_de(nombre)
        for f in F.formas_reales(p):
            toks_f = toks(f)
            if not toks_f:
                continue
            if len(toks_f) >= 2 or len(toks_f[0]) >= 5 and any(c.isdigit() for c in toks_f[0]) is False and f == f.lower() and f.isalpha() is False:
                tipo = "nombre"
            else:
                tipo = "nombre"
            if len(toks_f) == 1:
                t = toks_f[0]
                if p.nombres and t == F.plano(p.nombres[0]).replace(" ", ""):
                    tipo = "pila"
                elif p.apellidos and t == F.plano(p.apellidos[0]).replace(" ", ""):
                    tipo = "ap"
                else:
                    tipo = "local"
            self.forma(eid, f, tipo)
        if p.nombres and p.apellidos:
            self.pila_ap.setdefault((F.plano(p.nombres[0]), F.plano(p.apellidos[0])), []).append(eid)
        return p

    def conservar(self, forma: str, razon: str) -> Entidad:
        """Entidad conservada (organización, lugar o figura pública), kept: true."""
        llave = "kept:" + " ".join(toks(forma))
        eid = hid(llave, "kept_")
        if eid not in self:
            self[eid] = Entidad(entity_id=eid, llave=llave, tipo="organization_or_place", nombre=forma,
                                kept=True, reason=razon)
            self.llaves[llave] = eid
        return self[eid]

    # ------------------------------------------------------------ acceso
    def por_llave(self, llave: str):
        return self.get(self.llaves.get(llave))

    def personas(self):
        return [e for e in self.values() if e.tipo == "person" and not e.kept]

    # ------------------------------------------------------------ persistencia
    def a_json(self) -> dict:
        ents = []
        for e in self.values():
            ents.append({"entity_id": e.entity_id, "llave": e.llave, "tipo": e.tipo, "genero": e.genero,
                         "nombre": e.nombre, "ids": e.ids, "atributos": e.atributos,
                         "formas": sorted(e.formas), "records": sorted(e.records), "kept": e.kept,
                         "reason": e.reason})
        return {"version": VERSION, "entidades": ents, "users": self.users, "gaz": self.gaz,
                "tx": self.tx, "jefe": self.jefe, "vocab": {k: sorted(v) for k, v in VOCAB.items()},
                "ident": [[t, c, v] for (t, c), v in self.ident.items()],
                "formas_idx": [[list(k), v] for k, v in self.formas_idx.items()],
                "pila_ap": [[list(k), v] for k, v in self.pila_ap.items()]}

    @classmethod
    def de_json(cls, d: dict) -> "Grafo":
        g = cls()
        VOCAB["given"], VOCAB["surnames"] = set(d.get("vocab", {}).get("given", [])), set(d.get("vocab", {}).get("surnames", []))
        for x in d["entidades"]:
            e = Entidad(entity_id=x["entity_id"], llave=x["llave"], tipo=x["tipo"], genero=x["genero"],
                        nombre=x["nombre"], ids=x["ids"], atributos=x["atributos"], formas=set(x["formas"]),
                        records=set(x["records"]), kept=x["kept"], reason=x["reason"])
            g[e.entity_id] = e
            g.llaves[e.llave] = e.entity_id
        g.users, g.gaz, g.tx, g.jefe = d["users"], d["gaz"], {k: [tuple(t) for t in v] for k, v in d["tx"].items()}, d["jefe"]
        g.ident = {(t, c): v for t, c, v in d["ident"]}
        g.formas_idx = {tuple(k): v for k, v in d["formas_idx"]}
        g.pila_ap = {tuple(k): v for k, v in d["pila_ap"]}
        return g

    def guardar(self, ruta):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.a_json(), ensure_ascii=False), "utf-8")
        tmp.replace(ruta)

    @classmethod
    def cargar(cls, ruta):
        return cls.de_json(json.loads(Path(ruta).read_text("utf-8")))


# ------------------------------------------------------------------ construcción
_RX_PLACA_NOTA = re.compile(r"\b([A-Z]{3})[- ]?(\d{3})\b")
_RX_PASAP_NOTA = re.compile(r"\b([A-Z]{2}\d{6})\b")


def _origen(r: dict):
    if "columns" in r:
        return "tables", r["table"]
    if "thread_id" in r:
        return "chats", None
    return "docs", None


def _ids_fuertes(G, c: dict, tipo: str) -> set:
    """Entidades que ya reclaman la cédula, el correo o el celular de una fila."""
    cols = ({"cedula": c.get("num_doc", ""), "correo": c.get("correo", ""), "celular": c.get("celular", "")}
            if tipo == "clientes" else
            {"cedula": c.get("documento", ""), "correo": c.get("correo", ""), "celular": c.get("celular", "")})
    out = set()
    for t, v in cols.items():
        if v:
            e = G.buscar(t, v)
            if e:
                out.add(e)
    return out


def sembrar_cliente(G: Grafo, r: dict, genero_fn, enlazar: bool = False) -> Entidad:
    """Entidad de una fila de clientes (llave estable cl:<cliente_id>).

    Con enlazar=True (fila desconocida en /anonymize): si su cédula, correo o celular ya son de una sola
    entidad del grafo, la fila es esa persona; si no, es una persona nueva."""
    c = r["columns"]
    cid = c["cliente_id"]
    nombre = c.get("nombre_completo", "")
    if enlazar:
        previa = G.por_llave("cl:" + cid)
        if previa is not None:
            return previa
        fuertes = _ids_fuertes(G, c, "clientes")
        if len(fuertes) == 1:
            e = G[next(iter(fuertes))]
            G.llaves["cl:" + cid] = e.entity_id
            e.records.add(r["id"])
            return e
    e = G.nueva("cl:" + cid)
    e.nombre = nombre
    e.genero = genero_fn(nombre.split()[0] if nombre else "", [c.get("ocupacion", ""), c.get("notas", "")])
    e.ids["cliente_id"] = cid
    e.records.add(r["id"])
    G.id(e.entity_id, "cedula", c.get("num_doc", ""))
    G.id(e.entity_id, "correo", c.get("correo", ""))
    G.id(e.entity_id, "celular", c.get("celular", ""))
    if c.get("direccion"):
        G.id(e.entity_id, "direccion", c["direccion"])
    if c.get("fecha_nacimiento"):
        G.id(e.entity_id, "nacimiento", c["fecha_nacimiento"])
    e.atributos.update({"ciudad": c.get("ciudad", ""), "barrio": c.get("barrio", ""),
                        "ocupacion": c.get("ocupacion", ""), "direccion": c.get("direccion", ""),
                        "nacimiento": c.get("fecha_nacimiento", ""),
                        "anio_vinculacion": (c.get("fecha_vinculacion") or "")[:4]})
    G.formas_nombre(e.entity_id, nombre)
    if c.get("correo"):
        G.forma(e.entity_id, c["correo"].split("@")[0], "local", declarar=False)
    notas = c.get("notas", "")
    for m in _RX_PLACA_NOTA.finditer(notas):
        if m.group(1).lower() not in P.PLACA_NO:
            G.id(e.entity_id, "placa", m.group(0))
    for m in _RX_PASAP_NOTA.finditer(notas):
        G.id(e.entity_id, "pasaporte", m.group(1))
    for m in P.RX_CREDITO.finditer(notas):
        G.id(e.entity_id, "credito", m.group(0))
    for m in re.finditer(r"(?i)\b(?:cl|calle|cra|carrera|tv|dg|av)\.?\s*\d+[A-Za-z]?[^.;]{0,30}#\s*\d+[A-Za-z]?\s*-\s*\d+(?:\s+\w+\s*\d+)?", notas):
        G.id(e.entity_id, "direccion", m.group(0))
    if c.get("ciudad"):
        G.gaz["ciudades"].append(c["ciudad"])
    if c.get("barrio"):
        G.gaz["barrios"].setdefault(c.get("ciudad", ""), [])
        if c["barrio"] not in G.gaz["barrios"][c.get("ciudad", "")]:
            G.gaz["barrios"][c.get("ciudad", "")].append(c["barrio"])
    return e


def sembrar_empleado(G: Grafo, r: dict, genero_fn, enlazar: bool = False) -> Entidad:
    """Entidad de una fila de empleados (llave estable kp:<id>); mismas reglas que sembrar_cliente."""
    c = r["columns"]
    kid = c["id"]
    if enlazar:
        previa = G.por_llave("kp:" + kid)
        if previa is not None:
            return previa
        fuertes = _ids_fuertes(G, c, "empleados")
        if len(fuertes) == 1:
            e = G[next(iter(fuertes))]
            G.llaves["kp:" + kid] = e.entity_id
            e.records.add(r["id"])
            return e
    e = G.nueva("kp:" + kid)
    e.nombre = c.get("nombre", "")
    e.genero = genero_fn(e.nombre.split()[0] if e.nombre else "", [c.get("cargo", "")])
    e.ids["empleado_id"] = kid
    e.records.add(r["id"])
    G.id(e.entity_id, "correo", c.get("correo", ""))
    G.id(e.entity_id, "celular", c.get("celular", ""))
    G.id(e.entity_id, "cedula", c.get("documento", ""))
    if c.get("fecha_nacimiento"):
        G.id(e.entity_id, "nacimiento", c["fecha_nacimiento"])
    e.atributos.update({"cargo": c.get("cargo", ""), "reporta_a": c.get("reporta_a", ""),
                        "ciudad": c.get("ciudad", ""), "anio_ingreso": c.get("ingreso", ""),
                        "nacimiento": c.get("fecha_nacimiento", "")})
    G.formas_nombre(e.entity_id, e.nombre)
    if c.get("correo"):
        G.forma(e.entity_id, c["correo"].split("@")[0], "local", declarar=False)
    if c.get("ciudad"):
        G.gaz["ciudades"].append(c["ciudad"])
    if enlazar:
        resolver_jefe(G, e.entity_id)
    return e


def resolver_jefe(G: Grafo, eid: str):
    """Liga reporta_a (nombre completo o pila + apellido) con el único empleado que lo lleva."""
    e = G[eid]
    ra = e.atributos.get("reporta_a")
    if not ra:
        return
    tk = toks(ra)
    cand = []
    for x in G.values():
        if not x.llave.startswith("kp:") or x.entity_id == eid:
            continue
        p = persona_de(x.nombre)
        if tk == toks(x.nombre) or (len(tk) == 2 and p.nombres and p.apellidos
                                     and tk == (toks(p.nombres[0])[0], toks(p.apellidos[0])[0])):
            cand.append(x.entity_id)
    if len(cand) == 1:
        G.jefe[eid] = cand[0]


_GEN = {}


def genero_defecto():
    if "f" not in _GEN:
        _GEN["f"] = _genero_defecto()
    return _GEN["f"]


def construir(records, users=None, genero_fn=None) -> Grafo:
    """records: todos los registros normalizados (chats, docs, tables). users: users.json."""
    G = Grafo()
    recs = list(records.values()) if isinstance(records, dict) else list(records)
    tablas: dict = {"clientes": [], "empleados": [], "pqrs": [], "transacciones": []}
    for r in recs:
        if "columns" in r and r["table"] in tablas:
            tablas[r["table"]].append(r)
    if genero_fn is None:
        genero_fn = _genero_defecto()
    fijar_vocab([r["columns"].get("nombre_completo") or r["columns"].get("nombre") or ""
                 for r in tablas["clientes"] + tablas["empleados"]]
                + [(u.get("real_name") or "") for u in (users or [])])

    # ---- clientes
    for r in tablas["clientes"]:
        sembrar_cliente(G, r, genero_fn)

    # ---- empleados
    for r in tablas["empleados"]:
        sembrar_empleado(G, r, genero_fn)
    for eid, e in list(G.items()):
        if e.llave.startswith("kp:"):
            resolver_jefe(G, eid)

    # ---- usuarios
    cl_por_nombre: dict = {}
    for e in G.values():
        if e.llave.startswith("cl:"):
            p = persona_de(e.nombre)
            cl_por_nombre.setdefault((F.plano(p.nombres[0]) if p.nombres else "", F.plano(p.apellidos[0]) if p.apellidos else ""), []).append(e.entity_id)
            cl_por_nombre.setdefault(("full", norm(e.nombre)), []).append(e.entity_id)
    for u in users or []:
        prof = u.get("profile") or {}
        real = (u.get("real_name") or prof.get("real_name") or "").strip()
        info = {"real_name": real, "display": (prof.get("display_name") or "").strip(), "handle": u.get("name", ""),
                "email": (prof.get("email") or "").strip().lower(), "title": prof.get("title", ""),
                "phone": prof.get("phone", ""), "bot": bool(u.get("is_bot")), "deleted": bool(u.get("deleted"))}
        G.users[u["id"]] = info
        if info["bot"] or not real or info["deleted"]:
            continue
        email, titulo = info["email"], info["title"]
        eid = G.buscar("correo", email) if email else None
        if eid is None:
            if titulo == "Cliente" or u.get("is_restricted"):
                p = persona_de(real)
                cands = []
                if len(p.nombres) == 1 and len(p.apellidos) == 1:
                    cands = cl_por_nombre.get((F.plano(p.nombres[0]), F.plano(p.apellidos[0])), [])
                if not cands:
                    cands = cl_por_nombre.get(("full", norm(real)), [])
                cands = list(dict.fromkeys(cands))
                if len(cands) > 1:  # homónimos: el handle = parte local del correo del maestro
                    h = info["handle"].lower()
                    por_h = [c for c in cands if any(x.lower().split("@")[0] == h for x in G[c].ids.get("correos", []))]
                    cands = por_h if len(por_h) == 1 else cands
                if len(cands) == 1 and not any(u2 for u2 in [] ):
                    eid = cands[0]
            else:
                p = persona_de(real)
                cands = [x.entity_id for x in G.values() if x.llave.startswith("kp:") and norm(x.nombre) == norm(real)]
                if len(cands) == 1:
                    eid = cands[0]
        if eid is not None and any(("uid", x) in G.ident for x in []):
            pass
        if eid is not None and G[eid].ids.get("uids"):
            eid = None   # el cliente ya tiene otro usuario: este es otra persona
        if eid is None:
            e = G.nueva("uid:" + u["id"])
            e.nombre = real
            e.genero = genero_fn(real.split()[0], [titulo])
            eid = e.entity_id
            G.formas_nombre(eid, real)
            if email:
                G.id(eid, "correo", email)
                G.forma(eid, email.split("@")[0], "local", declarar=False)
        e = G[eid]
        e.ids.setdefault("uids", [])
        G.id(eid, "uid", u["id"])
        if info["handle"]:
            G.id(eid, "handle", info["handle"])
            G.forma(eid, info["handle"], "local", declarar=True)
        if real and real not in e.atributos.get("personas", []):
            G.formas_nombre(eid, real)
        pila = real.split()[0]
        d = info["display"]
        if d and norm(d) != norm(pila) and norm(d) != norm(real):
            G.forma(eid, d, "apodo", declarar=True)
            e.atributos.setdefault("apodos", [])
            if d not in e.atributos["apodos"]:
                e.atributos["apodos"].append(d)
        if info["phone"]:
            G.id(eid, "celular", info["phone"])
        if titulo and titulo != "Cliente":
            e.atributos.setdefault("cargo", titulo)
        if len(real) > len(e.nombre):
            e.nombre = real

    # ---- pqrs
    por_handle = {}
    for x in G.values():
        for h in x.ids.get("handles", []):
            por_handle[h.lower()] = x.entity_id
    for r in tablas["pqrs"]:
        c = r["columns"]
        cl = G.por_llave("cl:" + c.get("cliente_id", ""))
        if cl is None and c.get("cliente_id"):
            cl = G.nueva("cl:" + c["cliente_id"])
            cl.ids["cliente_id"] = c["cliente_id"]
            cl.genero = ""
        if cl is not None:
            cl.records.add(r["id"])
            G.id(cl.entity_id, "radicado", c.get("radicado", ""))
            if c.get("cedula") and not cl.ids.get("cedulas"):
                G.id(cl.entity_id, "cedula", c["cedula"])
            cl.atributos.setdefault("ciudad", c.get("ciudad", ""))
        ag = por_handle.get((c.get("agente") or "").lower())
        if ag:
            G[ag].records.add(r["id"])

    # ---- transacciones
    for r in tablas["transacciones"]:
        c = r["columns"]
        cl = G.por_llave("cl:" + c.get("cliente_id", ""))
        try:
            monto = int(float(c.get("monto") or 0))
        except ValueError:
            monto = 0
        G.tx.setdefault(c.get("cliente_id", ""), []).append((c.get("fecha", ""), monto))
        if cl is None:
            continue
        cl.records.add(r["id"])
        d = c.get("descripcion", "")
        for m in P.RX_CREDITO.finditer(d):
            G.id(cl.entity_id, "credito", m.group(0))
        for m in re.finditer(r"\bplaca\s+([A-Z]{3}-?\d{3})\b", d):
            G.id(cl.entity_id, "placa", m.group(1))
        for m in re.finditer(r"\bCC\s+(\d{1,3}(?:\.\d{3}){2,3})", d):
            G.id(cl.entity_id, "cedula", m.group(1))

    # ---- gazetteer del corpus: comercios y lugares de las descripciones de transacciones
    pref = re.compile(r"^(?:Compra|Retiro cajero|Retiro corresponsal|Parqueadero|Peaje)\s+(?P<resto>[^\d\-(]+?)\s*$")
    comercios_conocidos = {"Éxito", "Carulla", "Bancolombia", "Davivienda", "DN", "Terpel", "Farmatodo",
                           "Juan Valdez", "Avianca", "Rappi", "Spotify", "Netflix", "Tigo", "Claro", "EPM", "Enel",
                           "Emcali", "Nequi", "Santander", "SURA"}
    lugares, comercios = set(), set()
    for r in tablas["transacciones"]:
        d = r["columns"].get("descripcion", "")
        m = pref.match(d)
        if not m:
            continue
        s_ = m.group("resto").strip()
        for c in sorted(comercios_conocidos, key=len, reverse=True):
            if s_.startswith(c + " ") or s_ == c:
                comercios.add(c)
                s_ = s_[len(c):].strip()
                break
        if s_ and len(s_.split()) <= 4 and re.fullmatch(r"[A-Za-zÁÉÍÓÚÑáéíóúñü ]+", s_):
            lugares.add(s_)
    G.gaz["comercios"] = sorted(comercios)
    G.gaz["lugares"] = sorted(lugares)
    G.gaz["ciudades"] = sorted(set(G.gaz["ciudades"]))
    return G


def _genero_defecto():
    from .pseudo import Pseudonimizador
    ps = Pseudonimizador(b"grafo-genero", "/nonexistent/none.json")
    return lambda pila, pistas=(): ps.genero(pila, pistas) if pila else "f"
