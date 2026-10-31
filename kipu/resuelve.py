"""Resolución de menciones a entidades, con evidencia y sin fusionar por nombre.

Orden de evidencia: llave del registro (uid del autor, CL-, radicado, KP-) > identificador fuerte en el
registro o el hilo > fecha + monto que cruza con transacciones > adjunto > participantes del hilo.
Sin evidencia -> entidad nueva (men:/rel:); separar antes que fusionar.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import formas as F
from . import patrones as P
from .detecta import STOP_ALL, detector
from .grafo import Grafo, hid, persona_de, toks
from .modelo import Mencion
from .texto import norm, norm_mapa

CUE_CL_FUERTE = re.compile(r"(?:\bpse de|\bcliente|\bclienta|\bcuenta de|\btitular|\bcredito|\bcuota|\bcobro|"
                           r"\btransferencia|\bpago de|\bdel cliente|\ba nombre de|\bmora|\breclam|\btarjeta de)")
CUE_EMP_FUERTE = re.compile(r"(?:\bagente|\banalista|\bcoordinador|\bgerente|\bjef[ea]|\bequipo|\bresponsable|"
                            r"\baprueba|\brevisado|\belaborado|\bpreparado|\breporta|\bceo\b|\bcto\b|\bdirector|"
                            r"\bcompan|\bde soporte|\bfirma|\bsoy de|\bcontador|\babogad|\bproduct|\bmarketing|"
                            r"\bautorizado|\bautoriza)")
CUE_SELF = re.compile(r"(?:\bsoy\s*$|\bme llamo\s*$|\bhabla\s*$|\bmi nombre es\s*$|\bte escribe\s*$|\bhabla con\s*$|"
                      r"\b(?:te|le|les|os) atiende\s*$|\batiende\s*$|\b(?:saludos|atentamente|cordialmente|gracias)\s*[,.]?\s*$)")
CUE_CONFIRMA = re.compile(r"(?:clienta|cliente|cuenta|credito|tarjeta|tambien tiene|titular|usuari)")


def autor_eid(rec: dict, G: Grafo):
    """Entidad del autor de un mensaje (uid > nombre único)."""
    uid = rec.get("_uid")
    if uid:
        e = G.ident.get(("uid", uid))
        if e:
            return e
    nombre = rec.get("author") or ""
    if not nombre:
        return None
    k = toks(nombre)
    d = G.formas_idx.get(k) or {}
    cand = [eid for eid, t in d.items() if t in ("nombre", "pila", "local")]
    if len(cand) == 1:
        return cand[0]
    return None


def _es_cl(G, eid):
    e = G[eid]
    return e.llave.startswith("cl:") or (e.llave.startswith("uid:") and not e.atributos.get("cargo"))


def _es_emp(G, eid):
    e = G[eid]
    return e.llave.startswith("kp:") or bool(e.atributos.get("cargo"))


class Contexto:
    def __init__(self, G, records, menciones, genero_fn):
        self.G = G
        self.records = records
        self.M = menciones
        self.genero_fn = genero_fn
        self.hilo = {}
        self.hilo_recs = defaultdict(list)
        self.autor = {}
        self.own = {}
        for rid, r in records.items():
            h = r["thread_id"] if "thread_id" in r else rid
            self.hilo[rid] = h
            self.hilo_recs[h].append(rid)
            if "thread_id" in r:
                self.autor[rid] = autor_eid(r, G)
                self.own[rid] = {self.autor[rid]} - {None}
            elif "columns" in r:
                c = r["columns"]
                o = set()
                t = r["table"]
                if t in ("clientes", "transacciones", "pqrs"):
                    e = G.llaves.get("cl:" + c.get("cliente_id", ""))
                    if e:
                        o.add(e)
                if t == "empleados":
                    e = G.llaves.get("kp:" + c.get("id", ""))
                    if e:
                        o.add(e)
                if t == "pqrs":
                    e = G.buscar("handle", c.get("agente", ""))
                    if e:
                        o.add(e)
                self.own[rid] = o
            else:
                self.own[rid] = set()
        self.fuerte_rec = defaultdict(lambda: defaultdict(int))   # rid -> eid -> n
        self.fuerte_hilo = defaultdict(lambda: defaultdict(int))  # hilo -> eid -> n (todos los registros)
        self.nuevas = defaultdict(dict)                           # hilo -> clave -> eid
        self._tx_cache = {}

    def registrar_fuerte(self, rid, eid):
        self.fuerte_rec[rid][eid] += 1
        self.fuerte_hilo[self.hilo[rid]][eid] += 1

    def participantes(self, rid):
        h = self.hilo[rid]
        ps = set()
        for x in self.hilo_recs[h]:
            ps |= self.own.get(x, set()) if "thread_id" in self.records[x] else set()
        return ps

    # ---- fecha + monto
    def evidencia_tx(self, rid):
        h = self.hilo[rid]
        if h in self._tx_cache:
            return self._tx_cache[h]
        montos, fechas = set(), set()
        for x in self.hilo_recs[h]:
            r = self.records[x]
            textos = [r.get("text", "")] if "thread_id" in r else [r.get("body", "")] if "body" in r else \
                [v for v in (r.get("columns") or {}).values()]
            for t in textos:
                n = norm(t)
                for m in P.RX_MONTO.finditer(n):
                    try:
                        montos.add(int(m.group(1).replace(".", "")))
                    except ValueError:
                        pass
                for m in P.RX_FECHA_TXT.finditer(n):
                    fechas.add("-%02d-%02d" % (P.MESES.index(m.group(2)) + 1, int(m.group(1))))
                for m in P.RX_FECHA_ISO.finditer(n):
                    fechas.add("-%s-%s" % (m.group(2), m.group(3)))
        self._tx_cache[h] = (montos, fechas)
        return montos, fechas

    def puntaje_tx(self, eid, rid):
        e = self.G[eid]
        cids = [x for x in [e.ids.get("cliente_id")] + e.atributos.get("cliente_ids", []) if x]
        if not cids:
            return 0
        montos, fechas = self.evidencia_tx(rid)
        if not montos:
            return 0
        s = 0
        for fecha, monto in [t for cid in cids for t in self.G.tx.get(cid, [])]:
            if monto in montos:
                s = max(s, 2 if any(fecha.endswith(f) for f in fechas) else 1)
        return s


def _cue(G, eid, m):
    ctx = (m.izq or "")[-34:] + " | " + (m.der or "")[:30]
    cab = m.cabecera or ""
    cl = bool(CUE_CL_FUERTE.search((m.izq or "")[-30:]) or CUE_CL_FUERTE.search(cab) and not CUE_EMP_FUERTE.search(cab))
    em = bool(CUE_EMP_FUERTE.search((m.izq or "")[-30:]) or CUE_EMP_FUERTE.search(cab) or CUE_EMP_FUERTE.search((m.der or "")[:30]))
    if cab and "cliente" in cab:
        cl, em = True, False
    if cab and any(w in cab for w in ("agente", "analista", "responsable", "aprueba", "revisor", "autor")):
        cl, em = False, True
    if cl and not em:
        return 1 if _es_cl(G, eid) and not _es_emp(G, eid) else -1
    if em and not cl:
        return 1 if _es_emp(G, eid) else -1
    return 0


def _puntaje(cx: Contexto, eid, m, rid, pila_like):
    G = cx.G
    own = eid in cx.own.get(rid, set())
    # una firma ("mi mamá, Ignacio") o "te atiende Brayan" nombran al autor; un saludo, al otro participante
    self_cue = bool(CUE_SELF.search(m.izq or "")) or m.forma == "relacion"
    if pila_like and own and not self_cue:
        own = False
    fr = cx.fuerte_rec[rid].get(eid, 0)
    ft = cx.fuerte_hilo[cx.hilo[rid]].get(eid, 0) - fr
    tx = cx.puntaje_tx(eid, rid)
    en_hilo = eid in cx.participantes(rid)
    propio = eid in cx.own.get(rid, set())
    part = 0 if not en_hilo else (1 if propio else 2)     # el otro participante pesa más que el autor
    return (int(own and (not pila_like or self_cue)), int(fr > 0), tx, _cue(G, eid, m), int(ft > 0), part)


def _mejor(cx, cands, m, rid, pila_like, exigir_presencia=False):
    """Candidato único con mayor evidencia, o None."""
    pts = {c: _puntaje(cx, c, m, rid, pila_like) for c in cands}
    if exigir_presencia:
        pts = {c: p for c, p in pts.items() if p[0] or p[1] or p[2] or p[4] or p[5]}
    if not pts:
        return None
    orden = sorted(pts.items(), key=lambda x: x[1], reverse=True)
    mejor = orden[0]
    if mejor[1][0] == 0 and mejor[1][1] == 0 and mejor[1][2] == 0 and mejor[1][3] <= 0 and mejor[1][4] == 0 and mejor[1][5] == 0:
        return None
    if len(orden) > 1 and orden[1][1] == mejor[1]:
        return None
    return mejor[0]


def _genero_rel(rel, nombre, texto_hon_f, genero_fn):
    r = F.plano(rel or "")
    from .pseudo import FEMENINAS, MASCULINAS
    if r in FEMENINAS:
        return "f"
    if r in MASCULINAS:
        return "m"
    if texto_hon_f is True:
        return "f"
    if texto_hon_f is False:
        return "m"
    return genero_fn(nombre.split()[0], [])


def _nombre_canon(txt):
    t = txt.strip()
    if t.isupper() and len(t) > 3:
        t = " ".join(x.capitalize() for x in t.split())
    return t


def _scope(cx, rid):
    return cx.hilo[rid]


def _participante_con_nombre(cx, rid, tk):
    """Participante del hilo (autor de algún mensaje) cuyo nombre de pila o completo es `tk`."""
    G = cx.G
    hallados = []
    for eid in cx.participantes(rid):
        e = G[eid]
        if e.kept:
            continue
        for nombre in e.atributos.get("personas") or [e.nombre]:
            t = toks(nombre)
            if t and (tk == t[:len(tk)] and len(tk) <= 2 or tk == t):
                hallados.append(eid)
                break
    if len(set(hallados)) == 1:
        return hallados[0]
    return None


def _crear(cx, m, rid, nuevo_llave_base, genero_pistas=None):
    """Crea (o reutiliza) la entidad de una mención sin evidencia."""
    G = cx.G
    nom_norm = " ".join(toks(m.texto))
    h = cx.hilo[rid]
    reuse = cx.nuevas[h].get(nom_norm)
    if reuse:
        return reuse
    tk = toks(m.texto)
    # un nombre de pila suelto reutiliza la persona nueva del hilo que lo empieza
    if len(tk) == 1:
        c = [eid for k, eid in cx.nuevas[h].items() if k.split(" ")[0] == tk[0]]
        if len(set(c)) == 1:
            return c[0]
    # un nombre que coincide con el autor o con un participante del hilo es esa persona
    part = _participante_con_nombre(cx, rid, tk)
    if part:
        return part
    rel = m.rel
    ancla = cx.autor.get(rid)
    if rel and ancla and not G[ancla].kept:
        llave = "rel:%s:%s:%s" % (G[ancla].llave, rel, nom_norm)
    else:
        llave = "men:%s:%s" % (nom_norm, h)
    e = G.nueva(llave)
    if not e.nombre:
        e.nombre = _nombre_canon(m.texto)
        hon_f = getattr(m, "honorifico_f", None) if getattr(m, "hon", None) else None
        e.genero = _genero_rel(rel, e.nombre, hon_f, cx.genero_fn)
        if not (rel or hon_f is not None):
            e.genero = cx.genero_fn(e.nombre.split()[0], genero_pistas or [])
        if getattr(m, "apellido_solo", False):
            e.atributos["apellido_solo"] = True
        G.formas_nombre(e.entity_id, e.nombre)
        if rel:
            e.atributos["relacion"] = rel
    cx.nuevas[h][nom_norm] = e.entity_id
    return e.entity_id


_REL_F = {"mama", "madre", "hermana", "esposa", "novia", "hija", "jefa", "socia", "prima", "tia", "abuela",
          "cunada", "sobrina", "amiga", "vecina", "suegra", "nuera", "companera", "empleada"}
_REL_M = {"papa", "padre", "hermano", "esposo", "marido", "novio", "hijo", "jefe", "socio", "primo", "tio",
          "abuelo", "cunado", "sobrino", "amigo", "vecino", "suegro", "yerno", "companero", "empleado"}


def _ajustar_por_genero(G, m):
    """Si el contexto fija el género (relación o "clienta") y todos los candidatos exactos son del otro género,
    pero hay un único candidato a distancia 1 del género correcto, la mención es esa persona."""
    tk = toks(m.texto)
    if len(tk) < 2:
        return
    ventana = (m.izq or "")[-30:] + " " + (m.der or "")[:30]
    rel = F.plano(m.rel or "")
    quiere = None
    if rel in _REL_F or re.search(r"\bclienta\b", ventana):
        quiere = "f"
    elif rel in _REL_M:
        quiere = "m"
    if not quiere:
        return
    gens = {G[c].genero for c in m.cands if c in G}
    if not gens or gens != {"m" if quiere == "f" else "f"}:
        return
    alt = [c for c in detector(G)._tolerante(tk) if G[c].genero == quiere]
    if len(set(alt)) == 1:
        m.cands = [alt[0]]
        m.forma = "tolerante"
        m.entity_id = None


def resolver(records: dict, menciones: dict, G: Grafo, genero_fn=None) -> dict:
    """Asigna entity_id a las menciones y crea las entidades nuevas. Devuelve estadísticas."""
    if genero_fn is None:
        from .grafo import _genero_defecto
        genero_fn = _genero_defecto()
    cx = Contexto(G, records, menciones, genero_fn)
    stats = defaultdict(int)
    PILA = {"pila", "apodo"}

    # ---- fase 0: género del contexto ("mi novia Daniel Giraldo", "es clienta") frente a candidatos exactos
    for rid, ms in menciones.items():
        for m in ms:
            if not m.kept and m.tipo == "nombre" and len(m.cands) >= 1 and m.forma not in ("tolerante", "honorifico"):
                _ajustar_por_genero(G, m)
    # ---- fase A: asignaciones fuertes
    pendientes = []
    for rid, ms in menciones.items():
        for m in ms:
            if m.kept:
                continue
            if getattr(m, "estructurada", False) or m.tipo in ("correo", "correo_deletreado", "cedula", "celular", "placa",
                                                                 "pasaporte", "credito", "direccion", "nacimiento"):
                if len(m.cands) == 1:
                    m.entity_id = m.cands[0]
                    cx.registrar_fuerte(rid, m.entity_id)
                elif not getattr(m, "estructurada", False) and m.tipo in ("correo", "correo_deletreado"):
                    pendientes.append((rid, m))
                elif len(m.cands) > 1 and not getattr(m, "estructurada", False):
                    pendientes.append((rid, m))
                continue
            if m.forma in ("pila", "apodo", "tolerante", "relacion", "honorifico") and not (
                    m.forma == "relacion" and len(toks(m.texto)) >= 2 and len(m.cands) == 1):
                m.entity_id = None
                if m.cands or m.nuevo:
                    pendientes.append((rid, m))
                continue
            if len(m.cands) == 1:
                m.entity_id = m.cands[0]
                cx.registrar_fuerte(rid, m.entity_id)
            elif len(m.cands) > 1:
                m.entity_id = None
                pendientes.append((rid, m))
            elif m.nuevo:
                pendientes.append((rid, m))
            elif m.tipo in ("nombre", "slug") and not m.cands:
                pendientes.append((rid, m))
    # autores cuentan como presencia en su hilo
    # ---- fase B: ambiguas con candidatos (varias vueltas: lo resuelto aporta evidencia)
    for vuelta in range(2):
        resto = []
        for rid, m in pendientes:
            if m.entity_id is not None:
                continue
            if not m.cands:
                resto.append((rid, m))
                continue
            pila_like = m.forma in PILA or (m.forma == "relacion" and len(toks(m.texto)) == 1)
            if m.forma == "tolerante":
                ok = _mejor(cx, m.cands, m, rid, True, exigir_presencia=True)
                if ok is None and len(m.cands) == 1:
                    ok = m.cands[0]       # un nombre a distancia 1 de una sola persona conocida es esa persona
                if ok is None and vuelta == 1:
                    m.cands = []
                    resto.append((rid, m))
                    continue
            elif m.forma == "honorifico" and len(m.cands) == 1:
                ok = m.cands[0]
            elif pila_like:
                ok = _mejor(cx, m.cands, m, rid, True, exigir_presencia=True)
            else:
                ok = _mejor(cx, m.cands, m, rid, False)
            if ok is not None:
                m.entity_id = ok
                cx.registrar_fuerte(rid, ok)
            else:
                resto.append((rid, m))
        pendientes = resto
    # ---- fase C: entidades nuevas (primero nombres completos y relaciones; luego pilas sueltas)
    def clave_orden(x):
        rid, m = x
        return (m.tipo in ("correo", "correo_deletreado"), len(toks(m.texto)) == 1, rid)

    for rid, m in sorted(pendientes, key=clave_orden):
        if m.entity_id is not None:
            continue
        if m.tipo in ("correo", "correo_deletreado"):
            m.entity_id = _entidad_correo(cx, m, rid, menciones)
            continue
        if m.tipo in ("cedula", "celular", "placa", "pasaporte", "credito", "direccion", "nacimiento"):
            continue    # ids desconocidos o ambiguos: fase E
        if m.tipo == "handle" and m.forma in ("uid",):
            continue
        if not m.texto.strip():
            continue
        m.entity_id = _crear(cx, m, rid, "men")
        stats["nuevas"] += 1
    # ---- fase D: propaga personas nuevas a otras menciones del hilo
    _propagar(cx, records, menciones)
    # ---- fase E: ids sin dueño
    _adjuntar_ids(cx, records, menciones)
    # ---- cierre: records y formas por entidad
    for rid, ms in menciones.items():
        for m in ms:
            if m.entity_id and m.entity_id in G:
                e = G[m.entity_id]
                e.records.add(rid)
                if not e.kept:
                    e.formas.add(m.texto)
    for rid, r in records.items():
        if "thread_id" in r:
            a = cx.autor.get(rid)
            if a:
                G[a].records.add(rid)
    return dict(stats)


def _entidad_correo(cx, m, rid, menciones=None):
    G = cx.G
    correo = getattr(m, "correo", None) or norm(m.texto)
    local = correo.split("@")[0]
    # ¿es el correo de una persona de este registro o hilo? (inicial+apellido, nombre.apellido, ...)
    base = re.sub(r"\d+$", "", local)
    cand = {x.entity_id for x in (menciones or {}).get(rid, []) if x.entity_id and x.tipo in ("nombre", "apodo", "slug")}
    cand |= set(cx.nuevas[cx.hilo[rid]].values()) | set(cx.participantes(rid)) | set(cx.own.get(rid, set()))
    ok = []
    for eid in cand:
        e = G[eid]
        if e.kept:
            continue
        for nombre in e.atributos.get("personas") or [e.nombre]:
            if base in {F.plano(x) for x in F.locales_correo(persona_de(nombre))}:
                ok.append(eid)
                break
    if len(set(ok)) == 1:
        return ok[0]
    llave = "em:" + correo
    e = G.nueva(llave)
    if not e.nombre:
        partes = [p for p in re.split(r"[._\-]+", re.sub(r"\d+$", "", local)) if p]
        nombre = " ".join(p.capitalize() for p in partes) if len(partes) >= 2 else ""
        e.nombre = nombre
        e.genero = cx.genero_fn(partes[0] if partes else "", [])
        e.atributos["solo_correo"] = not nombre
        G.id(e.entity_id, "correo", correo)
        if nombre:
            G.formas_nombre(e.entity_id, nombre)
    return e.entity_id


def _propagar(cx, records, menciones):
    """Busca en el resto del hilo las formas de las personas nuevas y añade sus menciones."""
    G = cx.G
    det = detector(G)
    for h, mapa in cx.nuevas.items():
        if not mapa:
            continue
        # formas: nombre completo y pila (>=4 letras, no parada)
        formas = {}
        for clave, eid in mapa.items():
            tk = tuple(clave.split(" "))
            formas[tk] = eid
            if len(tk) >= 2 and len(tk[0]) >= 4 and tk[0] not in STOP_ALL:
                formas.setdefault((tk[0],), eid)
        for rid in cx.hilo_recs[h]:
            r = records[rid]
            ya = menciones.setdefault(rid, [])
            for campo, texto in det.campos(r):
                if not isinstance(texto, str) or not texto:
                    continue
                n, mp = norm_mapa(texto)
                toksn = [(m_.start(), m_.end(), m_.group(0)) for m_ in re.finditer(r"[a-z0-9]+", n)]
                i = 0
                while i < len(toksn):
                    hit = None
                    for L in (4, 3, 2, 1):
                        seq = tuple(t_[2] for t_ in toksn[i:i + L])
                        if len(seq) == L and seq in formas:
                            hit = (L, seq)
                            break
                    if not hit:
                        i += 1
                        continue
                    L, seq = hit
                    from .texto import span_original
                    a, b = span_original(mp, toksn[i][0], toksn[i + L - 1][1], len(texto))
                    if not any(x.campo == campo and x.ini < b and a < x.fin for x in ya):
                        orig = texto[a:b]
                        if orig[:1].isupper() or L > 1:
                            mm = Mencion(rid, campo, a, b, orig, "nombre", formas[seq], "regla")
                            mm.cands, mm.forma, mm.izq, mm.der, mm.cabecera = [formas[seq]], "propagada", "", "", ""
                            mm.rel, mm.nuevo, mm.kept, mm.estructurada, mm.uid, mm.razon = None, False, False, False, None, ""
                            ya.append(mm)
                    i += L


def _adjuntar_ids(cx, records, menciones):
    """Identificadores sin dueño conocido: a la persona más cercana del registro o a la del hilo."""
    G = cx.G
    TIPOS = ("cedula", "celular", "placa", "pasaporte", "credito", "direccion", "nacimiento")
    for rid, ms in menciones.items():
        sueltos = [m for m in ms if m.entity_id is None and m.tipo in TIPOS and not m.kept]
        if not sueltos:
            continue
        personas = [m for m in ms if m.entity_id and not G[m.entity_id].kept and m.tipo in ("nombre", "apodo", "slug", "handle")]
        for m in sueltos:
            elegido = None
            cerca = [p for p in personas if p.campo == m.campo and abs((p.ini + p.fin) // 2 - (m.ini + m.fin) // 2) <= 90]
            if cerca:
                cerca.sort(key=lambda p: abs((p.ini + p.fin) // 2 - (m.ini + m.fin) // 2))
                elegido = cerca[0].entity_id
            if elegido is None:
                dueno = cx.own.get(rid) or set()
                if len(dueno) == 1 and "thread_id" not in records[rid]:
                    elegido = next(iter(dueno))
            if elegido is None and "thread_id" in records[rid]:
                part = [e for e in cx.participantes(rid) if _es_cl(G, e)]
                if len(part) == 1:
                    elegido = part[0]
                else:
                    elegido = cx.autor.get(rid)
            if elegido is None:
                ents = {p.entity_id for p in personas}
                if len(ents) == 1:
                    elegido = ents.pop()
            if elegido is not None:
                m.entity_id = elegido
