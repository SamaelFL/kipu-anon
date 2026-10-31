#!/usr/bin/env python3
"""Juez local: estima el puntaje del juez oficial del Reto 1 (Kipu Pay).

Solo libreria estandar, sin LLM. Usa el mismo contiene() que validar.mjs.

  python3 evals/juez.py --out <salida> [--ref <salida_ideal>] --input <carpeta> \
      --tests <json>... [--trampas evals/trampas.jsonl] [--public <carpeta con record_index.json>]

Pesos del ENUNCIADO: fuga 45 (35 tests + 10 barrido), utilidad 35 (10 parecido,
9 falsos positivos, 8 categoria del seudonimo, 8 estructura), consistencia 20
(8 misma persona x unicidad, 5 homonimos, 4 reporta_a, 3 honestidad).
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
import entrada  # noqa: E402
from entrada import plano, texto_de  # noqa: E402
from texto import contiene, digitos_compactos, norm, solo_digitos  # noqa: E402

FUENTES = ("chats", "docs", "tables")
OBLIG = {"chats": ["id", "thread_id", "author", "ts", "text", "attachments"],
         "docs": ["id", "format", "filename", "title", "body", "metadata"],
         "tables": ["id", "table", "columns"]}
FAMILIAS = ["directa", "indirecta", "oculta", "falso_positivo", "homonimos", "consistencia"]
FUGA = ("directa", "indirecta", "oculta")
RX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
GENERICOS = {"soporte", "info", "contacto", "ayuda", "hola", "noreply", "no-reply", "legal", "privacidad", "datos", "prensa"}


# ------------------------------------------------------------------ carga
def leer_jsonl(ruta):
    if not os.path.exists(ruta):
        return None
    out = []
    for linea in open(ruta, encoding="utf8"):
        if linea.strip():
            try:
                out.append(json.loads(linea))
            except ValueError:
                pass
    return out


def cargar_salida(d):
    o = {f: {} for f in FUENTES}
    o["entities"] = []
    o["faltan_archivos"] = []
    for f in FUENTES:
        filas = leer_jsonl(os.path.join(d, f + ".jsonl"))
        if filas is None:
            o["faltan_archivos"].append(f + ".jsonl")
            continue
        for r in filas:
            if isinstance(r, dict) and isinstance(r.get("id"), str):
                o[f][r["id"]] = r
    ruta = os.path.join(d, "entities.json")
    if os.path.exists(ruta):
        try:
            o["entities"] = json.load(open(ruta, encoding="utf8")).get("entities", [])
        except Exception:
            o["faltan_archivos"].append("entities.json (invalido)")
    else:
        o["faltan_archivos"].append("entities.json")
    return o


def cargar_tests(rutas):
    tests = []
    for r in rutas:
        etiqueta = os.path.basename(r)
        if r.endswith(".jsonl"):
            lista = leer_jsonl(r) or []
        else:
            lista = json.load(open(r, encoding="utf8"))
        for t in lista:
            t = dict(t)
            t["_origen"] = etiqueta
            tests.append(t)
    return tests


class Salida:
    """Salida lista para consultar: textos por registro, texto entero, busqueda de fugas."""

    def __init__(self, o):
        self.o = o
        self.regs = {}  # rid -> (fuente, rec)
        for f in FUENTES:
            for rid, r in o[f].items():
                self.regs[rid] = (f, r)
        self.textos = {rid: texto_de(r) for rid, (f, r) in self.regs.items()}
        self.entero = "\n".join(self.textos.values())
        self._cache = {}

    def rec(self, src, rid):
        x = self.o.get(src, {}).get(rid)
        return x

    def hay(self, forma):
        if forma not in self._cache:
            self._cache[forma] = contiene(self.entero, forma)
        return self._cache[forma]

    def donde(self, forma, max_hits=3):
        """[(rid, campo)] donde aparece la forma (solo se llama si hay())."""
        hits = []
        for rid, (f, r) in self.regs.items():
            if not contiene(self.textos[rid], forma):
                continue
            campo = "?"
            for nombre, tx in campos(f, r):
                if contiene(tx, forma):
                    campo = nombre
                    break
            hits.append((rid, campo))
            if len(hits) >= max_hits:
                break
        return hits


def campos(f, r):
    if f == "tables":
        for k, v in (r.get("columns") or {}).items():
            yield "columns." + k, " | ".join(plano(v))
        yield "(claves)", " | ".join(plano(list((r.get("columns") or {}).keys())))
        return
    for k, v in r.items():
        if k == "id":
            continue
        yield k, " | ".join(plano(v))
        if isinstance(v, dict):
            yield k + "(claves)", " | ".join(plano(list(v.keys())))


def hashes(p):
    vs = {p, p.lower(), norm(p)}
    d = solo_digitos(p)
    if len(d) >= 6:
        vs.add(d)
    res = set()
    for v in vs:
        for alg in (hashlib.md5, hashlib.sha1, hashlib.sha256):
            res.add(alg(v.encode("utf8")).hexdigest())
    return res


# ------------------------------------------------------------------ entidades
def ents_persona(ents):
    return [e for e in ents if isinstance(e, dict) and not e.get("kept")]


def es_fuerte(forma):
    d = solo_digitos(forma)
    return "@" in forma or (len(d) >= 6 and not re.search(r"[A-Za-z]{3,}", forma))


def originales(e):
    return [x for x in (e.get("originals") or []) if isinstance(x, str)]


def entidades_con_forma(ents, forma):
    return [e for e in ents if any(contiene(o, forma) for o in originales(e))]


def seudonimos(e):
    p = e.get("pseudonyms") or {}
    return {k: v for k, v in p.items() if isinstance(v, str) and v}


def nombre_seudonimo(e):
    return seudonimos(e).get("name")


def vaciado(E, S, src, rid):
    """El registro sigue siendo texto y no fue vaciado ni reescrito entero."""
    if E is None:
        return False
    ent = E[src].get(rid)
    if ent is None:
        return False
    a = norm(texto_de(ent) if src != "chats" else ent["text"])
    out = S.rec(src, rid)
    b = norm(texto_de(out)) if out else ""
    ta = re.findall(r"[a-z0-9]+", a)
    if len(ta) < 6:
        return False
    tb = collections.Counter(re.findall(r"[a-z0-9]+", b))
    comunes = sum(min(c, tb[w]) for w, c in collections.Counter(ta).items())
    return comunes / len(ta) < 0.35


# ------------------------------------------------------------------ tests
def aplica(t, E):
    """El test se puede evaluar solo si sus registros existen en la entrada."""
    if E is None:
        return True
    src = t.get("source")
    if src == "cross":
        recs = t.get("records") or []
        if recs:
            return any(r in E["chats"] or r in E["docs"] or r in E["tables"] for r in recs)
        blob = E["_blob"]
        return any(contiene(blob, f) for f in t.get("lookup_forms", []) if es_fuerte(f))
    rid = (t.get("locator") or {}).get("record")
    return rid in E.get(src, {})


def evaluar(t, S, E, ents):
    fam = t["family"]
    return {"directa": t_directa, "oculta": t_oculta, "falso_positivo": t_fp, "indirecta": t_indirecta,
            "homonimos": t_homonimos, "consistencia": t_consistencia}[fam](t, S, E, ents)


def t_directa(t, S, E, ents):
    src, rid, campo = t["source"], t["locator"]["record"], t["locator"].get("field")
    rec = S.rec(src, rid)
    if rec is None:
        return False, f"el registro {rid} no está en la salida"
    if vaciado(E, S, src, rid):
        return False, f"registro {rid} vaciado o reescrito"
    for p in t["payload"]:
        if S.hay(p):
            h = S.donde(p, 2)
            return False, f"{p!r} sigue en {', '.join(f'{r}:{c}' for r, c in h)}"
        hs = hashes(p)
        low = S.entero.lower()
        if any(x in low for x in hs):
            return False, f"hash sin sal de {p!r} en la salida"
    return True, ""


def t_oculta(t, S, E, ents):
    src, rid, campo = t["source"], t["locator"]["record"], t["locator"].get("field")
    rec = S.rec(src, rid)
    if rec is None:
        return False, f"el registro {rid} no está en la salida"
    if vaciado(E, S, src, rid):
        return False, f"registro {rid} vaciado o reescrito"
    tx = texto_de(rec, campo)
    for p in t["payload"]:
        if contiene(tx, p):
            return False, f"{p!r} sigue en {rid}:{campo}"
    return True, ""


def t_fp(t, S, E, ents):
    src, rid, campo = t["source"], t["locator"]["record"], t["locator"].get("field")
    rec = S.rec(src, rid)
    if rec is None:
        return False, f"el registro {rid} no está en la salida"
    tx = texto_de(rec, campo)
    for p in t["payload"]:
        if p not in tx:
            return False, f"{p!r} cambió o desapareció en {rid}:{campo}"
    return True, ""


def t_indirecta(t, S, E, ents):
    src, rid = t["source"], t["locator"]["record"]
    if S.rec(src, rid) is None:
        return False, f"el registro {rid} no está en la salida"
    if vaciado(E, S, src, rid):
        return False, f"registro {rid} vaciado o reescrito"
    ids = [rid] + list(t.get("join_records") or [])
    textos = [S.textos[i] for i in ids if i in S.textos]
    comps = t["payload"]
    for i in ids:
        if i in S.textos and all(contiene(S.textos[i], c) for c in comps):
            return False, f"toda la tupla {comps} sigue junta en {i}"
    if all(any(contiene(x, c) for x in textos) for c in comps):
        return False, f"la tupla {comps} sigue completa en la unión {ids}"
    return True, ""


def t_homonimos(t, S, E, ents):
    par = t.get("par")
    nombre = t["payload"][0]
    toks = norm(nombre).split()
    corto = " ".join(toks[:2])
    if par:
        nombres = []
        for r in par:
            tabla = r.split(":")[0]
            rec = S.rec("tables", r)
            if rec is None:
                return False, f"falta {r} en la salida"
            c = rec["columns"]
            nombres.append(norm(c.get("nombre_completo") or c.get("nombre") or ""))
        if nombres[0] == nombres[1] or (nombres[0].split()[:2] == nombres[1].split()[:2] and nombres[0].split()[-1] == nombres[1].split()[-1]):
            return False, f"las dos filas quedaron con el mismo nombre: {nombres[0]!r}"
    cand = [e for e in ents_persona(ents) if any(contiene(o, corto) for o in originales(e))]
    if par:
        propias = []
        for r in par:
            m = [e for e in cand if r in (e.get("records") or [])]
            propias.append(m[0] if m else None)
        if None in propias:
            return False, "no hay entidad en entities.json para las dos filas"
        if propias[0] is propias[1] or propias[0].get("entity_id") == propias[1].get("entity_id"):
            return False, "las dos personas quedaron en una sola entidad"
        a, b = nombre_seudonimo(propias[0]), nombre_seudonimo(propias[1])
        if not a or not b or norm(a) == norm(b):
            return False, f"mismo seudónimo para las dos: {a!r}"
        return True, ""
    if len(cand) < 2:
        return False, f"solo {len(cand)} entidad(es) con el nombre {corto!r}"
    nombres = {norm(nombre_seudonimo(e) or "") for e in cand}
    if len(nombres) < 2:
        return False, "las entidades homónimas comparten seudónimo"
    return True, ""


def resolver_entidad(ents, formas):
    """Entidad(es) cuyas formas originales casan con las llaves fuertes del test."""
    fuertes = [f for f in formas if es_fuerte(f)]
    hit = {}
    for f in fuertes:
        for e in entidades_con_forma(ents, f):
            hit.setdefault(id(e), (e, set()))[1].add(f)
    return [x[0] for x in hit.values()], fuertes


def pseud_en(texto, e):
    ps = seudonimos(e)
    for k, v in ps.items():
        if k in ("birth_iso", "address"):
            continue
        if contiene(texto, v):
            return True
    n = ps.get("name")
    if n:
        t0 = n.split()[0]
        if len(t0) >= 3 and contiene(texto, t0):
            return True
    return False


def t_consistencia(t, S, E, ents):
    formas = t.get("lookup_forms") or []
    cands, fuertes = resolver_entidad(ents_persona(ents), formas)
    if not cands:
        return False, "ninguna entidad declara esas formas"
    if len(cands) > 1:
        return False, f"la persona está partida en {len(cands)} entidades: {[c.get('entity_id') for c in cands]}"
    e = cands[0]
    for f in formas:
        if es_fuerte(f):
            continue
        otras = [x for x in entidades_con_forma(ents_persona(ents), f) if x is not e]
        propia = any(contiene(o, f) for o in originales(e))
        if otras and not propia and len(f.split()) >= 3:
            return False, f"el nombre {f!r} quedó en otra entidad"
    if not seudonimos(e):
        return False, "la entidad no tiene seudónimos"
    recs = t.get("records") or e.get("records") or []
    faltan = []
    for r in recs:
        if r.endswith(":*"):
            continue
        tx = S.textos.get(r)
        if tx is None:
            faltan.append(f"{r}(ausente)")
        elif not pseud_en(tx, e):
            faltan.append(r)
    if faltan:
        return False, f"el seudónimo no aparece en {len(faltan)} de {len(recs)} records, p. ej. {faltan[:2]}"
    return True, ""


# ------------------------------------------------------------------ formas reales
def formas_de_ref(ref_ents):
    out = set()
    kept = [o for e in ref_ents if e.get("kept") for o in originales(e)]
    for e in ref_ents:
        if e.get("kept"):
            continue
        for o in originales(e):
            if forma_barrible(o) and not any(contiene(k, o) for k in kept if len(k) >= 4):
                out.add(o)
    return sorted(out)


def forma_barrible(o):
    d = solo_digitos(o)
    if "@" in o:
        return True
    if len(d) >= 6:
        return True
    if "_" in o and len(o) >= 6:
        return True
    return len(o.split()) >= 2 and len(o) >= 7


def nombre_y_primer_apellido(n):
    t = n.split()
    out = []
    if len(t) >= 2:
        out.append(n)
    if len(t) == 3:
        out.append(" ".join(t[:2]))
    if len(t) >= 4:
        out.append(" ".join(t[:3]))
    return out


def formas_de_entrada(E):
    """Sin ref: formas reales sacadas de las tablas de la entrada y de las notas."""
    f = set()
    for r in E["tables"].values():
        c = r["columns"]
        t = r["table"]
        if t == "clientes":
            for n in nombre_y_primer_apellido(c.get("nombre_completo", "")):
                f.add(n)
            for k in ("correo", "num_doc", "celular", "direccion", "fecha_nacimiento"):
                if c.get(k):
                    f.add(c[k])
        elif t == "empleados":
            for n in nombre_y_primer_apellido(c.get("nombre", "")):
                f.add(n)
            for k in ("correo", "celular", "documento", "fecha_nacimiento"):
                if c.get(k):
                    f.add(c[k])
        elif t == "pqrs":
            if c.get("cedula"):
                f.add(c["cedula"])
    for u in E["users"].values():
        p = u.get("profile", {})
        if not u.get("is_bot") and u.get("real_name") and len(u["real_name"].split()) >= 2:
            for n in nombre_y_primer_apellido(u["real_name"]):
                f.add(n)
        for k in ("email", "phone"):
            if p.get(k):
                f.add(p[k])
    blob = E["_blob"]
    for m in RX_EMAIL.findall(blob):
        if m.split("@")[0].lower() not in GENERICOS:
            f.add(m)
    for m in re.findall(r"(?<![A-Za-z0-9])[A-Z]{3}-?\d{3}(?![A-Za-z0-9])", blob):
        f.add(m)
    for m in re.findall(r"(?<![A-Za-z0-9])[A-Z]{2}\d{6}(?![A-Za-z0-9])", blob):
        f.add(m)
    return sorted(x for x in f if x and forma_barrible(x))


def blob_entrada(E):
    partes = []
    for f in FUENTES:
        for r in E[f].values():
            partes.append(texto_de(r))
    return "\n".join(partes)


# ------------------------------------------------------------------ estructura
def revisar_estructura(S, E, indice):
    res = {}
    faltan = {}
    for f in FUENTES:
        esperados = set(E[f]) if E else set(indice.get(f, []))
        llegan = set(S.o[f])
        faltan[f] = (len(esperados - llegan), len(llegan - esperados))
    res["uno_a_uno"] = faltan
    claves_mal = 0
    total_claves = 0
    llaves_ok = llaves_tot = 0
    for f in FUENTES:
        for rid, r in S.o[f].items():
            total_claves += 1
            if any(k not in r for k in OBLIG[f]):
                claves_mal += 1
                continue
            ent = E[f].get(rid) if E else None
            if not ent:
                continue
            if f == "docs" and set((r.get("metadata") or {}).keys()) != set(ent["metadata"].keys()):
                claves_mal += 1
            if f == "tables" and set((r.get("columns") or {}).keys()) != set(ent["columns"].keys()):
                claves_mal += 1
            if f == "chats":
                if len(r.get("attachments") or []) != len(ent["attachments"]):
                    claves_mal += 1
                for k in ("thread_id", "ts"):
                    llaves_tot += 1
                    llaves_ok += r.get(k) == ent[k]
            if f == "tables":
                for k in ("cliente_id", "tx_id", "radicado", "id"):
                    if k in ent["columns"]:
                        llaves_tot += 1
                        llaves_ok += (r.get("columns") or {}).get(k) == ent["columns"][k]
    res["claves_mal"] = (claves_mal, total_claves)
    res["llaves"] = (llaves_ok, llaves_tot)
    # hilos: quien habla en cada hilo
    hilos_in = collections.defaultdict(set)
    hilos_out = collections.defaultdict(set)
    mapa = collections.defaultdict(collections.Counter)
    if E:
        for rid, ent in E["chats"].items():
            o = S.o["chats"].get(rid)
            if not o:
                continue
            hilos_in[ent["thread_id"]].add(ent["author"])
            hilos_out[ent["thread_id"]].add(o.get("author"))
            mapa[ent["author"]][o.get("author")] += 1
    ok = sum(1 for h in hilos_in if len(hilos_in[h]) == len(hilos_out[h]))
    res["hilos"] = (ok, len(hilos_in))
    # un autor real -> un solo seudonimo; seudonimos distintos para autores distintos
    msgs = sum(sum(c.values()) for c in mapa.values())
    mayor = sum(max(c.values()) for c in mapa.values()) if mapa else 0
    inv = collections.defaultdict(set)
    for a, c in mapa.items():
        for b in c:
            inv[b].add(a)
    fusion = sum(1 for b, s in inv.items() if len(s) > 1)
    res["autor_estable"] = (mayor, msgs)
    res["autores_fusionados"] = fusion
    return res


def reporta_a(S, E):
    if not E:
        return None
    emp = {rid: r for rid, r in E["tables"].items() if r["table"] == "empleados"}
    bien = tot = 0
    detalle = []
    for rid, r in emp.items():
        rep = r["columns"].get("reporta_a", "")
        o = S.o["tables"].get(rid)
        if o is None:
            continue
        orep = (o["columns"] or {}).get("reporta_a", "")
        tot += 1
        if not rep:
            bien += (orep == "")
            continue
        jefes = [j for j in emp.values() if norm(j["columns"]["nombre"]).startswith(norm(rep))]
        if len(jefes) != 1:
            tot -= 1
            continue
        oj = S.o["tables"].get(jefes[0]["id"])
        onombre = (oj["columns"] or {}).get("nombre", "") if oj else ""
        if orep and not contiene(orep, rep) and contiene(onombre, orep) and norm(orep) != norm(rep):
            bien += 1
        else:
            detalle.append((rid, rep, orep, onombre))
    return bien, tot, detalle


# ------------------------------------------------------------------ seudonimos
FEM = {"maría", "carmen", "beatriz", "ingrid", "mercedes", "pilar", "luz", "inés", "rocío", "belén", "consuelo", "esther", "ruth", "raquel", "isabel", "abril", "soledad", "dolores", "jazmín", "karen", "yuliana"}
MAS_A = {"luca", "joshua", "elías", "jonatán", "nicolás", "tomás", "andrés", "matías", "isaías", "josué", "jeremías", "zacarías", "borja"}


def genero(nombre):
    p = norm(nombre.split()[0]) if nombre.split() else ""
    if p in {norm(x) for x in FEM}:
        return "F"
    if p in {norm(x) for x in MAS_A}:
        return "M"
    return "F" if p.endswith("a") else "M"


def categoria_seudonimos(ents):
    ok = tot = 0
    problemas = []
    for e in ents_persona(ents):
        ps = seudonimos(e)
        ors = originales(e)
        if not ps:
            continue
        n = ps.get("name")
        if n:
            tot += 1
            nombres = [o for o in ors if len(o.split()) >= 2 and "@" not in o and not solo_digitos(o) and "_" not in o]
            bien = len(n.split()) >= 2 and not any(contiene(n, o) or contiene(o, n) for o in nombres)
            if nombres and bien and genero(n) != genero(nombres[0]):
                bien = False
            ok += bien
            if not bien:
                problemas.append((e.get("entity_id"), "name", n))
        if ps.get("email"):
            tot += 1
            ems = [o for o in ors if "@" in o]
            bien = bool(RX_EMAIL.fullmatch(ps["email"])) and not any(norm(o) == norm(ps["email"]) for o in ems)
            ok += bien
            if not bien:
                problemas.append((e.get("entity_id"), "email", ps["email"]))
        for k, rx in (("cedula", r"\d{6,10}"), ("phone", r"3\d{9}")):
            if ps.get(k):
                tot += 1
                orig = [solo_digitos(o) for o in ors if solo_digitos(o)]
                bien = bool(re.fullmatch(rx, solo_digitos(ps[k]))) and solo_digitos(ps[k]) not in orig
                ok += bien
                if not bien:
                    problemas.append((e.get("entity_id"), k, ps[k]))
    return ok, tot, problemas


def unicidad(ents):
    ns = [norm(nombre_seudonimo(e) or "") for e in ents_persona(ents) if nombre_seudonimo(e)]
    return (len(set(ns)) / len(ns)) if ns else 0.0, len(ns), len(set(ns))


# ------------------------------------------------------------------ particion
def particion(ours, ref):
    """Por cada entidad ref, la nuestra con mejor Jaccard de records; pureza, cobertura, fusiones, divisiones."""
    po = [e for e in ents_persona(ours) if e.get("records")]
    pr = [e for e in ents_persona(ref) if e.get("records")]
    sets_o = [set(x for x in e["records"] if not x.endswith(":*")) for e in po]
    sets_r = [set(x for x in e["records"] if not x.endswith(":*")) for e in pr]
    idx = collections.defaultdict(list)
    for i, s in enumerate(sets_o):
        for r in s:
            idx[r].append(i)

    def jac(rs, i):
        c = len(rs & sets_o[i])
        return c / len(rs | sets_o[i]) if c else 0.0

    mejor_ref = {}  # para cada nuestra, su ref de mayor Jaccard
    idx_r = collections.defaultdict(list)
    for j, s in enumerate(sets_r):
        for r in s:
            idx_r[r].append(j)
    for i, so in enumerate(sets_o):
        cand = {j for r in so for j in idx_r.get(r, [])}
        if cand:
            mejor_ref[i] = max(cand, key=lambda j: len(sets_r[j] & so) / len(sets_r[j] | so))
    res = []
    mejor_de = collections.defaultdict(list)
    for j, rs in enumerate(sets_r):
        if not rs:
            continue
        cand = {i for x in rs for i in idx.get(x, [])}
        if not cand:
            res.append({"ref": pr[j].get("entity_id"), "pureza": 0.0, "cobertura": 0.0, "mejor": None, "split": 0})
            continue
        i = max(cand, key=lambda k: jac(rs, k))
        c = len(rs & sets_o[i])
        split = sum(1 for k in cand if k != i and mejor_ref.get(k) == j)
        res.append({"ref": pr[j].get("entity_id"), "pureza": c / len(sets_o[i]), "cobertura": c / len(rs), "mejor": i, "split": split})
        mejor_de[i].append(pr[j].get("entity_id"))
    fusiones = {i: v for i, v in mejor_de.items() if len(v) >= 2}
    return res, fusiones, po


# ------------------------------------------------------------------ parecido
def valores(r):
    if "columns" in r:
        return " ".join(plano(list((r["columns"] or {}).values())))
    return " ".join(x for k, v in r.items() if k not in ("id",) for x in plano(v))


def parecido(S, ref):
    tot = n = 0
    por_fuente = {}
    for f in FUENTES:
        sf = c = 0
        for rid, r in ref[f].items():
            o = S.o[f].get(rid)
            a = valores(r)
            b = valores(o) if o else ""
            if len(a) > 6000 or len(b) > 6000:
                a, b = a[:6000], b[:6000]
            ratio = difflib.SequenceMatcher(None, a, b, autojunk=True).ratio() if (a or b) else 1.0
            sf += ratio
            c += 1
        if c:
            por_fuente[f] = sf / c
            tot += sf
            n += c
    return (tot / n if n else None), por_fuente


# ------------------------------------------------------------------ informe
class Puntos:
    def __init__(self):
        self.filas = []

    def add(self, grupo, nombre, ganados, maximo, tipo, nota=""):
        self.filas.append((grupo, nombre, ganados, maximo, tipo, nota))


def pct(a, b):
    return (a / b) if b else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref")
    ap.add_argument("--input", required=True)
    ap.add_argument("--tests", nargs="*", default=[])
    ap.add_argument("--trampas")
    ap.add_argument("--public", help="carpeta con record_index.json para validar.mjs")
    ap.add_argument("--verbose", action="store_true", help="lista todos los tests fallidos")
    ap.add_argument("--no-node", action="store_true")
    ap.add_argument("--json", help="guarda el resumen en este archivo")
    a = ap.parse_args()

    E = entrada.cargar_entrada(a.input)
    E["_blob"] = blob_entrada(E)
    o = cargar_salida(a.out)
    S = Salida(o)
    ref = cargar_salida(a.ref) if a.ref else None
    ents = o["entities"]
    P = Puntos()
    resumen = {}

    print(f"== Juez local · salida={a.out} · ref={a.ref or '—'} · entrada={a.input}")
    print(f"   registros salida: chats={len(o['chats'])} docs={len(o['docs'])} tables={len(o['tables'])} entidades={len(ents)}")
    if o["faltan_archivos"]:
        print("   ⚠ faltan archivos:", ", ".join(o["faltan_archivos"]))

    # ---------------------------------------------------------- tests
    rutas = list(a.tests) + ([a.trampas] if a.trampas else [])
    tests = cargar_tests(rutas)
    res_fam = {f: {"pasa": 0, "falla": 0, "w_pasa": 0, "w_tot": 0} for f in FAMILIAS}
    fallos = []
    omitidos = 0
    for t in tests:
        if t["family"] not in res_fam:
            continue
        if not aplica(t, E):
            omitidos += 1
            continue
        ok, why = evaluar(t, S, E, ents)
        w = t.get("weight", 1)
        r = res_fam[t["family"]]
        r["w_tot"] += w
        if ok:
            r["pasa"] += 1
            r["w_pasa"] += w
        else:
            r["falla"] += 1
            fallos.append((t, why))
    print("\n-- Tests por familia (peso pasado / peso total)")
    print(f"   {'familia':<16}{'pasa':>6}{'falla':>7}{'peso':>12}")
    for f in FAMILIAS:
        r = res_fam[f]
        print(f"   {f:<16}{r['pasa']:>6}{r['falla']:>7}{r['w_pasa']:>7}/{r['w_tot']:<4}")
    print(f"   (tests omitidos por no aplicar a esta entrada: {omitidos}; cargados: {len(tests)})")
    if fallos:
        lim = len(fallos) if a.verbose else 25
        print(f"   Fallos ({len(fallos)}; mostrando {min(lim, len(fallos))}):")
        for t, why in fallos[:lim]:
            print(f"    ✗ {t['id']:<10}{t['family']:<15}{t['mechanism']:<42} {why}")
    resumen["tests"] = res_fam

    def frac(familias):
        wp = sum(res_fam[f]["w_pasa"] for f in familias)
        wt = sum(res_fam[f]["w_tot"] for f in familias)
        return pct(wp, wt)

    # ---------------------------------------------------------- barrido
    if ref and ref["entities"]:
        formas = formas_de_ref(ref["entities"])
        origen = "ref/entities.json"
    else:
        formas = formas_de_entrada(E)
        origen = "tablas y notas de la entrada"
    todas = len(formas)
    formas = [f for f in formas if contiene(E["_blob"], f)]  # solo las que existen en la entrada pueden fugarse
    fugas = []
    for f in formas:
        if S.hay(f):
            fugas.append(f)
    print(f"\n-- Barrido global: {len(formas)} formas reales presentes en la entrada (de {todas} de {origen}); {len(fugas)} se fugan")
    for f in fugas[:20]:
        h = S.donde(f, 1)
        loc = f"{h[0][0]} · {h[0][1]}" if h else "(solo en la unión del texto)"
        print(f"    ✗ {f!r:<44} {loc}")
    if len(fugas) > 20:
        print(f"    … y {len(fugas) - 20} más")
    resumen["barrido"] = {"formas": len(formas), "fugas": len(fugas)}

    # ---------------------------------------------------------- partición
    part = None
    if ref and ref["entities"] and ents:
        part, fusiones, po = particion(ents, ref["entities"])
        if part:
            pur = sum(x["pureza"] for x in part) / len(part)
            cob = sum(x["cobertura"] for x in part) / len(part)
            divs = sum(1 for x in part if x["split"] > 0)
            print(f"\n-- Partición de personas vs ref ({len(part)} entidades ref)")
            print(f"    pureza media {pur:.3f} · cobertura media {cob:.3f} · fusiones {len(fusiones)} · divisiones {divs}")
            for i, v in list(fusiones.items())[:5]:
                print(f"    fusión: {po[i].get('entity_id')} absorbe {v}")
            peores = sorted(part, key=lambda x: x["cobertura"] * x["pureza"])[:3]
            for x in peores:
                if x["cobertura"] * x["pureza"] < 0.99:
                    print(f"    débil: ref {x['ref']} pureza {x['pureza']:.2f} cobertura {x['cobertura']:.2f}")
            resumen["particion"] = {"pureza": pur, "cobertura": cob, "fusiones": len(fusiones), "divisiones": divs}
    elif ref:
        print("\n-- Partición de personas vs ref: sin entities.json en la salida → 0")

    # ---------------------------------------------------------- parecido
    sim = None
    if ref:
        sim, por = parecido(S, ref)
        print(f"\n-- Parecido (difflib, texto no personal) vs ref: {sim:.3f}  " + " ".join(f"{k}={v:.3f}" for k, v in por.items()))
        resumen["parecido"] = sim

    # ---------------------------------------------------------- estructura
    indice = {}
    for base in (a.public, a.input, os.path.join(a.input, ".."), os.path.join(a.input, "..", "..")):
        if base and os.path.exists(os.path.join(base, "record_index.json")):
            indice = json.load(open(os.path.join(base, "record_index.json")))
            public = base
            break
    else:
        public = None
    est = revisar_estructura(S, E, indice)
    print("\n-- Estructura")
    for f, (fa, so) in est["uno_a_uno"].items():
        print(f"    {f}: faltan {fa}, sobran {so}")
    print(f"    registros con claves/campos distintos a la entrada: {est['claves_mal'][0]} de {est['claves_mal'][1]}")
    print(f"    llaves intactas (thread_id, ts, cliente_id, tx_id, radicado…): {est['llaves'][0]}/{est['llaves'][1]}")
    print(f"    hilos con los mismos interlocutores: {est['hilos'][0]}/{est['hilos'][1]} · "
          f"autor→un seudónimo: {est['autor_estable'][0]}/{est['autor_estable'][1]} · seudónimos que fusionan autores: {est['autores_fusionados']}")
    rep = reporta_a(S, E)
    if rep:
        print(f"    reporta_a apuntando al seudónimo del jefe: {rep[0]}/{rep[1]}")
        for d in rep[2][:3]:
            print(f"      ✗ {d[0]}: reporta_a {d[1]!r} → {d[2]!r}; jefe = {d[3]!r}")
    resumen["estructura"] = {k: v for k, v in est.items() if k != "uno_a_uno"}

    # ---------------------------------------------------------- seudónimos
    ok_cat, tot_cat, prob = categoria_seudonimos(ents)
    u, n_ps, n_unicos = unicidad(ents)
    print(f"\n-- Seudónimos: categoría correcta {ok_cat}/{tot_cat} · únicos {n_unicos}/{n_ps} (unicidad {u:.3f})")
    for p in prob[:5]:
        print(f"    ✗ {p}")

    # ---------------------------------------------------------- honestidad
    verdad = formas if formas else []
    decl = " | ".join(x for e in ents for x in originales(e))
    if verdad and ents:
        rec = sum(1 for f in verdad if contiene(decl, f)) / len(verdad)
    else:
        rec = 0.0
    print(f"-- Honestidad del diccionario (aprox.): {rec:.3f} de las formas reales están declaradas")

    # ---------------------------------------------------------- node
    if not a.no_node:
        validar = os.path.join(RAIZ, "material", "frontier-reto-1", "validar.mjs")
        pub = public or a.input
        print(f"\n-- node validar.mjs {a.out} --public {pub}")
        try:
            r = subprocess.run(["node", validar, a.out, "--public", pub], capture_output=True, text=True, timeout=300)
            lines = (r.stdout + r.stderr).strip().splitlines()
            for ln in lines[:12]:
                print("   ", ln)
            if len(lines) > 12:
                print(f"    … ({len(lines) - 12} líneas más)")
            resumen["validar_ok"] = r.returncode == 0
        except Exception as ex:
            print("    no se pudo correr node:", ex)

    # ---------------------------------------------------------- puntaje
    f_fuga = frac(FUGA)
    f_fp = frac(["falso_positivo"])
    f_hom = frac(["homonimos"])
    f_con = frac(["consistencia"])
    P.add("Fuga", "tests puntuales (directa+indirecta+oculta)", 35 * f_fuga if f_fuga is not None else 0, 35, "aprox" if f_fuga is not None else "sin tests",
          "peso pasado/peso total de nuestros tests; los ocultos son otros")
    P.add("Fuga", "barrido global", 10 * (1 - len(fugas) / len(formas)) if formas else 0, 10, "aprox",
          "1 − formas fugadas/formas; el oficial usa su propia lista")
    if sim is not None:
        P.add("Utilidad", "parecido con la salida ideal", 10 * sim, 10, "aprox", "difflib por registro vs ref")
    else:
        P.add("Utilidad", "parecido con la salida ideal", 0, 10, "sin ref")
    P.add("Utilidad", "falsos positivos intactos", 9 * f_fp if f_fp is not None else 0, 9, "aprox" if f_fp is not None else "sin tests")
    P.add("Utilidad", "categoría del seudónimo", 8 * (ok_cat / tot_cat) if tot_cat else 0, 8, "aprox", "género por heurística de nombre")
    comp = []
    if est["llaves"][1]:
        comp.append(est["llaves"][0] / est["llaves"][1])
    if est["hilos"][1]:
        comp.append(0.5 * est["hilos"][0] / est["hilos"][1] + 0.5 * est["autor_estable"][0] / max(1, est["autor_estable"][1]))
    if part:
        comp.append(sum(x["cobertura"] * x["pureza"] for x in part) / len(part))
    ceros = sum(1 for x in est["uno_a_uno"].values() if x != (0, 0))
    p_est = (sum(comp) / len(comp)) if comp else 0
    if ceros:
        p_est *= 0.5
    P.add("Utilidad", "estructura (llaves, personas, hilos)", 8 * p_est, 8, "aprox", "promedio de llaves, hilos y partición" + ("; salida no 1:1 → ×0.5" if ceros else ""))
    # consistencia
    mp = []
    if f_con is not None:
        mp.append(f_con)
    if part:
        mp.append(sum(x["cobertura"] for x in part) / len(part))
    P.add("Consistencia", "misma persona, mismo seudónimo × unicidad", 8 * (sum(mp) / len(mp)) * u if mp else 0, 8, "aprox" if mp else "sin datos")
    P.add("Consistencia", "homónimos", 5 * f_hom if f_hom is not None else 0, 5, "aprox" if f_hom is not None else "sin tests")
    P.add("Consistencia", "reporta_a", 4 * rep[0] / rep[1] if rep and rep[1] else 0, 4, "aprox" if rep and rep[1] else "sin datos")
    P.add("Consistencia", "honestidad del diccionario", 3 * rec, 3, "aprox")

    print("\n== Estimación (0-100)")
    print(f"   {'':<13}{'parte':<46}{'puntos':>7}{'máx':>5}  tipo")
    total = maxmed = maxtot = 0.0
    for g, n, got, mx, tipo, nota in P.filas:
        print(f"   {g:<13}{n:<46}{got:>7.2f}{mx:>5}  {tipo}")
        total += got
        maxtot += mx
        if not tipo.startswith("sin"):
            maxmed += mx
    print(f"   {'':<13}{'TOTAL (partes sin medir cuentan 0)':<46}{total:>7.2f}{maxtot:>5.0f}")
    if maxmed < maxtot:
        print(f"   {'':<13}{'sobre lo medible (' + str(int(maxmed)) + ' pts) escalado a 100':<46}{100 * total / maxmed:>7.1f}")
    print("   Aproximado: todo salvo la estructura 1:1 y el validador oficial. Los tests ocultos usan otros mecanismos;")
    print("   un 100 aquí no garantiza 100 allá. 'sin ref' / 'sin tests' = parte no medible con lo dado.")
    resumen["total"] = total
    resumen["total_escalado"] = 100 * total / maxmed if maxmed else None
    if a.json:
        json.dump(resumen, open(a.json, "w"), ensure_ascii=False, indent=1, default=str)
    print(f"\nPUNTAJE ESTIMADO: {100 * total / maxmed if maxmed else 0:.1f}/100 (total con partes sin medir en 0: {total:.1f}) · fugas en barrido: {len(fugas)} · tests fallidos: {len(fallos)}")


if __name__ == "__main__":
    main()
