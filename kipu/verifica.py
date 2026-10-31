"""Verificación adversarial antes de publicar (solo librería estándar).

verificar(output_records, entidades) -> reporte (dict). El reporte lleva formas reales:
va a /tmp o a evals/out/ (ignorado), nunca al repo.

  (a) barrido global: toda forma real (Entidad.formas, ids y atributos de PII) en todo el
      texto de la salida, claves incluidas, con contiene() de evals/texto.py.
  (b) ataque de enlace: reidentificar a cada cliente cruzando ciudad, barrio, ocupación,
      año y nacimiento de la salida contra el maestro original.
  (c) las dos reglas de entities.json de validar.mjs: cada seudónimo aparece en al menos
      uno de sus records y ninguna forma original declarada sigue en la salida.

`entidades` acepta objetos Entidad (kipu.modelo) o dicts de entities.json. Para (c) los
seudónimos se leen de `e.pseudonimos` (dict tipo -> valor), o de `e.atributos["pseudonimos"]`,
o de la clave `pseudonyms` si es dict.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))
from texto import contiene, digitos_compactos, norm  # noqa: E402

from . import cuasi  # noqa: E402

IDS_LLAVE = {"cliente_id", "empleado_id", "radicados", "uids"}  # unen tablas: se conservan
MIN_LARGO = 3


# ------------------------------------------------------------------ adaptación de entidades
def _vista(e) -> dict:
    if isinstance(e, dict):
        a = e.get("atributos") or {}
        return {"id": str(e.get("entity_id", "")), "kept": bool(e.get("kept")), "tipo": e.get("type", "person"),
                "formas": list(e.get("originals") or []), "ids": e.get("ids") or {}, "atributos": a,
                "records": list(e.get("records") or []),
                "pseudonimos": e.get("pseudonyms") or {}, "nombre": ""}
    a = getattr(e, "atributos", None) or {}
    pseud = getattr(e, "pseudonimos", None) or a.get("pseudonimos") or {}
    return {"id": e.entity_id, "kept": bool(e.kept), "tipo": e.tipo, "formas": list(e.formas),
            "ids": e.ids or {}, "atributos": a, "records": list(e.records), "pseudonimos": pseud,
            "nombre": e.nombre or ""}


def _formas_pii(v: dict) -> list:
    """Formas reales de la persona: formas vistas + ids de PII + atributos de PII."""
    out = list(v["formas"])
    if v["nombre"]:
        out.append(v["nombre"])
    for k, val in v["ids"].items():
        if k in IDS_LLAVE:
            continue
        out += [str(x) for x in (val if isinstance(val, (list, tuple, set)) else [val]) if x]
    for k in ("direccion", "nacimiento", "cedula", "celular", "correo"):
        x = v["atributos"].get(k)
        if x:
            out.append(str(x))
    vistas, res = set(), []
    for f in out:
        f = str(f).strip()
        if len(f) >= MIN_LARGO and f not in vistas:
            vistas.add(f)
            res.append(f)
    return res


# ------------------------------------------------------------------ textos de un registro
def _cadenas(obj):
    """Cada cadena de un registro, valores y claves."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield "clave", str(k)
            yield from _cadenas(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _cadenas(v)
    elif isinstance(obj, str):
        yield "valor", obj


def _campos(obj, ruta=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{ruta}.{k}" if ruta else str(k)
            yield f"clave:{sub}", str(k)
            yield from _campos(v, sub)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _campos(v, f"{ruta}.{i}")
    elif isinstance(obj, str):
        yield ruta, obj


def _blob(r) -> str:
    return "\n".join(s for _, s in _cadenas(r))


# ------------------------------------------------------------------ (a) barrido global
class _Indice:
    """Índice por palabras y por 6-gramas de dígitos para no cruzar todas las formas con todos los registros."""

    def __init__(self, records):
        self.records = records
        self.blobs = [_blob(r) for r in records]
        self.norms = [norm(b) for b in self.blobs]
        self.palabras: dict = {}
        self.gramas: dict = {}
        for i, (b, n) in enumerate(zip(self.blobs, self.norms)):
            for w in set(re.findall(r"[a-z0-9]+", n)):
                self.palabras.setdefault(w, set()).add(i)
            d = digitos_compactos(b)
            for run in re.findall(r"\d+", d):
                for j in range(len(run) - 5):
                    self.gramas.setdefault(run[j:j + 6], set()).add(i)

    def candidatos(self, forma: str):
        n = norm(forma)
        d = re.sub(r"\D", "", forma)
        if len(d) >= 6 and not re.search("[a-zA-Z]", forma):
            return set(self.gramas.get(d[:6], ())) | set(self.gramas.get(d[2:8], ()) if d.startswith("57") else ())
        if "@" in n or not re.fullmatch(r"[\w .'_-]+", n):
            return {i for i, t in enumerate(self.norms) if n in t}
        ws = re.findall(r"[a-z0-9]+", n)
        if not ws:
            return set()
        sets = [self.palabras.get(w, set()) for w in ws]
        base = set.intersection(*sorted(sets, key=len)) if sets else set()
        return base


def barrido(records, entidades, indice: _Indice | None = None) -> list:
    """Fugas: [{entity_id, forma, record_id, campo, donde}]."""
    vistas = [_vista(e) for e in entidades]
    indice = indice or _Indice(records)
    conservadas = [str(f) for v in vistas if v["kept"] for f in v["formas"] if len(str(f)) >= 4 and re.search(r"[^\W\d_]", str(f))]
    fugas = []
    for v in vistas:
        if v["kept"]:
            continue
        for forma in _formas_pii(v):
            if any(contiene(k, forma) for k in conservadas):
                continue
            for i in sorted(indice.candidatos(forma)):
                if not contiene(indice.blobs[i], forma):
                    continue
                r = indice.records[i]
                hallado = False
                for campo, texto in _campos(r):
                    if contiene(texto, forma):
                        fugas.append({"entity_id": v["id"], "forma": forma, "record_id": r.get("id"),
                                      "campo": campo, "donde": "clave" if campo.startswith("clave:") else "valor"})
                        hallado = True
                if not hallado:
                    fugas.append({"entity_id": v["id"], "forma": forma, "record_id": r.get("id"),
                                  "campo": "(entre campos)", "donde": "valor"})
    return fugas


# ------------------------------------------------------------------ (b) ataque de enlace
def _fila_cliente(records):
    res = {}
    for r in records:
        if r.get("table") == "clientes" and isinstance(r.get("columns"), dict):
            res[r["columns"].get("cliente_id") or r.get("id")] = r["columns"]
    return res


def ataque_enlace(output_records, entidades, maestro=None, k=cuasi.K) -> dict:
    """Intenta reidentificar a cada cliente con los cuasi-identificadores que quedan en la salida."""
    vistas = [_vista(e) for e in entidades]
    if maestro is None:
        maestro = cuasi.maestro_de([], [e for e in entidades if not isinstance(e, dict)])
    filas = _fila_cliente(output_records)
    reid, chicos = [], []
    for c in maestro:
        f = filas.get(c["cliente_id"])
        if not f:
            continue
        o_ocu, o_bar, o_ciu = cuasi.canon(f.get("ocupacion", "")), cuasi.plano(f.get("barrio", "")), cuasi.plano(f.get("ciudad", ""))
        o_anio, o_nac = cuasi._anio_de(f.get("fecha_vinculacion")), str(f.get("fecha_nacimiento", ""))
        niveles = [("ciudad+barrio+ocupacion+año", dict(ciudad=o_ciu, barrio=o_bar, ocu=o_ocu, anio=o_anio)),
                   ("ciudad+barrio+ocupacion+año+nacimiento", dict(ciudad=o_ciu, barrio=o_bar, ocu=o_ocu, anio=o_anio, nac=o_nac))]
        for nombre, q in niveles:
            ms = [m for m in maestro
                  if cuasi.plano(m["ciudad"]) == q["ciudad"] and cuasi.plano(m["barrio"]) == q["barrio"]
                  and cuasi.canon(m["ocupacion"]) == q["ocu"] and m["anio"] == q["anio"]
                  and ("nac" not in q or str(m["nacimiento"]) == q["nac"])]
            if len(ms) == 1 and ms[0]["cliente_id"] == c["cliente_id"]:
                reid.append({"cliente_id": c["cliente_id"], "via": nombre})
                break
            if ms and len(ms) < k and any(m["cliente_id"] == c["cliente_id"] for m in ms) and nombre.endswith("año"):
                chicos.append({"cliente_id": c["cliente_id"], "via": nombre, "k": len(ms)})
    # tuplas sin nombre que sobreviven en el texto y apuntan a menos de k clientes
    tuplas = []
    det = cuasi.Tuplas(maestro, _SectorFalso(), k)
    for r in output_records:
        for _, _, ruta, texto in cuasi.campos_libres(r):
            for t in _tuplas_en(det, texto):
                if t["k"] < k:
                    tuplas.append({"record_id": r.get("id"), "tipo": t["tipo"], "k": t["k"], "fragmento": t["fragmento"]})
    return {"reidentificados": reid, "grupos_chicos": chicos, "tuplas_en_texto": tuplas}


def _tuplas_en(det, texto):
    segs = list(cuasi.segmentos(texto))
    for i, (b, sg) in enumerate(segs):
        if not sg.strip():
            continue
        ini = segs[max(i - 1, 0)][0]
        ult = segs[min(i + 1, len(segs) - 1)]
        ventana = texto[ini:ult[0] + len(ult[1])]
        t = det.detectar(ventana, ancla=(b - ini, b - ini + len(sg)))
        if t:
            t["fragmento"] = ventana.strip()[:160]
            yield t


class _SectorFalso:
    """Para detectar tuplas con el oficio ORIGINAL en la salida solo se necesita el catálogo del maestro."""
    sectores: dict = {}
    sector_defecto = ""


# ------------------------------------------------------------------ (c) reglas de entities.json
def _texto_registro(r) -> str:
    return _blob(r)


def declaraciones(records, entidades) -> list:
    """Las dos reglas de validar.mjs: seudónimo presente y forma original ausente."""
    por_id = {r.get("id"): r for r in records}
    vistas = [_vista(e) for e in entidades]
    textos = {rid: _texto_registro(r) for rid, r in por_id.items()}
    entero = "\n".join(textos.values())
    conservados = [str(f) for v in vistas if v["kept"] for f in v["formas"]
                   if len(str(f)) >= 4 and re.search(r"[^\W\d_]", str(f))]
    errores = []
    for v in vistas:
        if v["kept"]:
            continue
        recs = [por_id[x] for x in v["records"] if x in por_id]
        for tipo, val in (v["pseudonimos"] or {}).items():
            if not isinstance(val, str) or not val:
                continue
            if recs and not any(contiene(textos[r["id"]], val) for r in recs):
                errores.append({"regla": "seudonimo_ausente", "entity_id": v["id"], "tipo": tipo, "valor": val})
        for orig in v["formas"]:
            orig = str(orig)
            if len(orig) < 3 or any(contiene(k, orig) for k in conservados):
                continue
            if " " not in orig and "@" not in orig and not re.search(r"\d", orig) and orig[:1].isupper() and orig[:1].lower() != orig[:1]:
                continue  # nombre suelto: validar.mjs no lo exige
            if not contiene(entero, orig):
                continue
            hits = [rid for rid, t in textos.items() if contiene(t, orig)]
            if hits:
                errores.append({"regla": "original_persiste", "entity_id": v["id"], "forma": orig, "records": hits[:5]})
    return errores


# ------------------------------------------------------------------ reporte
def verificar(output_records, entidades, maestro=None, k=cuasi.K) -> dict:
    entidades = list(entidades)
    indice = _Indice(output_records)
    fugas = barrido(output_records, entidades, indice)
    enlace = ataque_enlace(output_records, entidades, maestro, k)
    decl = declaraciones(output_records, entidades)
    segunda = [{"entity_id": f["entity_id"], "forma": f["forma"], "record_id": f["record_id"], "campo": f["campo"]}
               for f in fugas]
    for d in decl:
        if d["regla"] == "original_persiste":
            for rid in d["records"]:
                segunda.append({"entity_id": d["entity_id"], "forma": d["forma"], "record_id": rid, "campo": "(registro)"})
    vistos, unicas = set(), []
    for s in segunda:
        t = (s["entity_id"], s["forma"], s["record_id"], s["campo"])
        if t not in vistos:
            vistos.add(t)
            unicas.append(s)
    ok = not fugas and not enlace["reidentificados"] and not enlace["tuplas_en_texto"] and not decl
    return {
        "ok": ok,
        "resumen": {"fugas": len(fugas), "reidentificados": len(enlace["reidentificados"]),
                    "grupos_chicos": len(enlace["grupos_chicos"]), "tuplas_en_texto": len(enlace["tuplas_en_texto"]),
                    "declaraciones": len(decl)},
        "fugas": fugas,
        "enlace": enlace,
        "declaraciones": decl,
        "segunda_pasada": unicas,
    }
