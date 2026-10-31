"""ingest -> grafo -> detectar (+ llm.recall) -> resolver -> reemplazar -> cuasi -> verifica -> output/."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import detecta, grafo as grafo_mod, ingest, resuelve
from . import reemplaza as rz_mod
from .modelo import Mencion
from .pseudo import Pseudonimizador
from .texto import contiene

try:                                    # módulos de otras piezas: si no existen, se omiten
    from . import cuasi
except Exception:                       # noqa: BLE001
    cuasi = None
try:
    from . import verifica
except Exception:                       # noqa: BLE001
    verifica = None
try:
    from . import llm
except Exception:                       # noqa: BLE001
    llm = None

FILES = ("chats.jsonl", "docs.jsonl", "tables.jsonl", "entities.json")
SECRETO_DEV = "kipu-dev-secreto-no-usar-en-produccion"


def log(msg):
    print("[pipeline] " + msg, file=sys.stderr, flush=True)


def secreto() -> str:
    s = os.environ.get("KIPU_SECRET")
    if not s:
        log("KIPU_SECRET no está definida: se usa un secreto de desarrollo")
        s = SECRETO_DEV
    return s


def _jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _publico(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


# ------------------------------------------------------------------ núcleo reutilizable
class Motor:
    """Grafo + seudónimos listos para anonimizar lotes (/run y /anonymize usan lo mismo)."""

    def __init__(self, G, ps, preparado=False):
        self.G = G
        self.ps = ps
        self.recall_lote = 0       # segundos de corte para llm.recall en lotes (0 = sin LLM)
        self.rz = rz_mod.Reemplazador(G, ps, ps.genero)
        if not preparado:
            ps.agregar_formas_reales(self._formas_reales())

    def _formas_reales(self):
        for e in self.G.values():
            if e.kept:
                continue
            for f in e.formas:
                yield f
            for lista in e.ids.values():
                if isinstance(lista, list):
                    for v in lista:
                        yield v

    def anonimizar(self, records: list, llm_menciones=None):
        """records normalizados (con o sin `_uid`) -> (registros anonimizados, menciones por id)."""
        G = self.G
        rec_map = {r["id"]: r for r in records}
        D = detecta.detector(G)
        menciones = {r["id"]: D.detectar(r) for r in records}
        for rid, extra in (llm_menciones or {}).items():
            menciones.setdefault(rid, []).extend(extra)
        if llm_menciones is None and self.recall_lote:
            for m in _recall_con_corte(records, menciones, G, self.recall_lote):
                menciones.setdefault(m.record_id, []).append(m)
        resuelve.resolver(rec_map, menciones, G, self.ps.genero)
        salida = []
        for r in records:
            rid = r["id"]
            nuevo = self.rz.aplicar(r, menciones.get(rid, []))
            if "thread_id" in nuevo:
                eid = resuelve.autor_eid(r, G)
                if eid is None:
                    eid = self._entidad_autor(r, menciones.get(rid, []))
                nuevo["author"] = self.rz.autor(r, eid)
            salida.append(nuevo)
        return salida, menciones

    def _entidad_autor(self, r, ms):
        """Autor sin uid conocido (p. ej. en /anonymize): el nombre único del grafo o una persona del hilo."""
        a = r.get("author") or ""
        k = grafo_mod.toks(a)
        d = self.G.formas_idx.get(k) or {}
        c = [e for e, t in d.items() if t in ("nombre", "pila", "local")]
        if len(c) == 1:
            return c[0]
        return None


def _recall_con_corte(records, menciones, G, corte):
    """llm.recall sobre un lote, con corte duro: si no responde a tiempo se sigue con reglas."""
    if llm is None or not os.environ.get("OPENROUTER_API_KEY") or os.environ.get("KIPU_SIN_LLM"):
        return []
    import concurrent.futures as cf

    def trabajo():
        unidades = llm.unidades_de([_publico(r) for r in records])
        conocidas = [m for ms in menciones.values() for m in ms]
        return llm.recall(unidades, conocidas)

    ex = cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(trabajo)
    try:
        res = fut.result(timeout=corte)
    except Exception as e:  # noqa: BLE001
        log("recall del lote sin resultado (%s); sigue con reglas" % type(e).__name__)
        ex.shutdown(wait=False, cancel_futures=True)
        return []
    ex.shutdown(wait=False)
    out = []
    for ml in res:
        m = _desde_llm(ml, G)
        if m is not None:
            out.append(m)
    return out


def _desde_llm(ml, G):
    """MencionLLM validada -> Mencion del pipeline (persona nueva o forma conocida)."""
    if getattr(ml, "clase", "persona") not in ("persona", "tercero"):
        return None
    m = Mencion(ml.record_id, ml.campo, ml.ini, ml.fin, ml.texto, "nombre", None, "llm")
    tk = grafo_mod.toks(ml.texto)
    d = G.formas_idx.get(tk)
    m.cands = list(d) if d else []
    m.forma = "pila" if (d and len(tk) == 1) else ("completo" if d else "llm")
    m.izq = m.der = m.cabecera = ""
    m.rel = getattr(ml, "relacion", "") or None
    m.nuevo = not d
    m.kept = False
    m.estructurada = False
    m.uid = None
    m.razon = ""
    return m


# ------------------------------------------------------------------ entities.json
def _entidades_json(G, rz, salida, menciones):
    por_id = {r["id"]: r for r in salida}

    def texto_de(rid):
        r = por_id.get(rid)
        return json.dumps(r, ensure_ascii=False) if r else ""

    ents = []
    for e in G.values():
        if e.kept:
            if rz.kept_vistos.get(e.entity_id):
                ents.append({"entity_id": e.entity_id, "type": "organization_or_place",
                             "originals": [e.nombre], "pseudonyms": {}, "kept": True,
                             "reason": e.reason or "organización, lugar, marca o figura pública; no es persona natural",
                             "records": []})
            continue
        recs = sorted(r for r in e.records if r in por_id)
        if not recs:
            continue
        blob = "\n".join(_texto_plano(por_id[r]) for r in recs)
        ps = {}
        uso = rz.uso.get(e.entity_id, {})
        sp = rz.seudo(e.entity_id)
        candidatos = [("name", sp.completo), ("name", "%s %s" % (sp.pila, sp.apellido1))]
        for k, v in candidatos:
            if k not in ps and v.strip() and contiene(blob, v):
                ps[k] = v
        if "name" not in ps:
            vistos = [v for v in (uso.get("name_vistos") or [])]
        for k, v in uso.items():
            if k in ("name", "handle_uid", "name_vistos") or not isinstance(v, str) or not v:
                continue
            if contiene(blob, v):
                ps[k] = v
        if not ps:
            continue
        originals = sorted({f for f in e.formas if isinstance(f, str) and f.strip()})
        ents.append({"entity_id": e.entity_id, "type": "person", "originals": originals, "pseudonyms": ps,
                     "records": recs})
    return ents


def _texto_plano(r):
    if "columns" in r:
        return " | ".join(list(r["columns"].keys()) + [str(v) for v in r["columns"].values()])
    out = []
    for k, v in r.items():
        if k == "id":
            continue
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            out.extend(list(v.keys()) + [str(x) for x in v.values()])
        elif isinstance(v, list):
            out.extend(str(x.get("filename", "")) if isinstance(x, dict) else str(x) for x in v)
    return " | ".join(out)


# ------------------------------------------------------------------ corrida completa
def run(source, out_dir, state_dir=None):
    """Regenera los cuatro archivos de salida en out_dir (escritura atómica)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    if state_dir is None:
        state_dir = Path(os.environ["DATA_DIR"]) if os.environ.get("DATA_DIR") else out_dir.parent / (out_dir.name + ".state")
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    chats = ingest.ingest_chats(source)
    docs = ingest.ingest_docs(source)
    tables = ingest.ingest_tables(source)
    try:
        users = source.users()
    except Exception:   # noqa: BLE001
        users = []
    records = chats + docs + tables
    log("ingesta: chats=%d docs=%d tables=%d" % (len(chats), len(docs), len(tables)))

    G = grafo_mod.construir(records, users, genero_fn=None)
    ps = Pseudonimizador(secreto(), state_dir / "store.json")
    motor = Motor(G, ps)
    D = detecta.detector(G)
    rec_map = {r["id"]: r for r in records}
    menciones = {r["id"]: D.detectar(r) for r in records}

    if llm is not None and os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("KIPU_SIN_LLM"):
        try:
            unidades = llm.unidades_de([_publico(r) for r in records])
            conocidas = [m for ms in menciones.values() for m in ms]
            for ml in llm.recall(unidades, conocidas):
                m = _desde_llm(ml, G)
                if m is not None:
                    menciones.setdefault(m.record_id, []).append(m)
        except Exception as e:  # noqa: BLE001
            log("llm.recall falló (%s); sigue con reglas" % type(e).__name__)

    resuelve.resolver(rec_map, menciones, G, ps.genero)
    rz = motor.rz
    salida = []
    for r in records:
        rid = r["id"]
        nuevo = rz.aplicar(r, menciones.get(rid, []))
        if "thread_id" in nuevo:
            nuevo["author"] = rz.autor(r, resuelve.autor_eid(r, G))
        salida.append(nuevo)
    # para cuasi, las filas de transacciones no cuentan como texto de la persona (el lugar de un
    # comercio no es su barrio)
    entidades_obj = []
    for e in G.values():
        c = copy.copy(e)
        c.records = {r for r in e.records if not str(r).startswith("transacciones:")}
        entidades_obj.append(c)

    if cuasi is not None:
        try:
            cuasi.aplicar(salida, entidades_obj, ps)
        except Exception as e:  # noqa: BLE001
            log("cuasi.aplicar falló: %s" % type(e).__name__)
    salida = [_publico(r) for r in salida]

    ents = _entidades_json(G, rz, salida, menciones)
    for e in G.values():
        pu = next((x for x in ents if x["entity_id"] == e.entity_id), None)
        if pu:
            e.atributos["pseudonimos"] = pu["pseudonyms"]
    if verifica is not None:
        try:
            rep = verifica.verificar(salida, [e for e in G.values()])
            log("verifica: %s" % json.dumps(rep.get("resumen", {})))
        except Exception as e:  # noqa: BLE001
            log("verifica falló: %s" % type(e).__name__)

    tmp = Path(tempfile.mkdtemp(prefix=out_dir.name + ".tmp-", dir=out_dir.parent))
    try:
        _jsonl(tmp / "chats.jsonl", [r for r in salida if "thread_id" in r])
        _jsonl(tmp / "docs.jsonl", [r for r in salida if "format" in r and "thread_id" not in r])
        _jsonl(tmp / "tables.jsonl", [r for r in salida if "columns" in r])
        (tmp / "entities.json").write_text(json.dumps({"entities": ents}, ensure_ascii=False, indent=1), "utf-8")
        old = None
        if out_dir.exists():
            old = out_dir.parent / (out_dir.name + ".old-%d" % os.getpid())
            os.rename(out_dir, old)
        os.rename(tmp, out_dir)
        if old:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    ps.guardar()
    G.guardar(state_dir / "grafo.json")
    seg = time.time() - t0
    c = llm.costo() if (llm is not None and hasattr(llm, "costo")) else {}
    return {
        "records": {"chats": len(chats), "docs": len(docs), "tables": len(tables)},
        "cost": {"tokens_in": int(c.get("tokens_in", 0)), "tokens_out": int(c.get("tokens_out", 0)),
                 "seconds": round(seg, 2)},
    }


# ------------------------------------------------------------------ /anonymize
class Servicio:
    """Estado cargado de la última corrida: grafo + store. Cada lote trabaja sobre una copia del grafo."""

    def __init__(self, state_dir):
        import threading
        self.dir = Path(state_dir)
        self.lock = threading.Lock()
        self.G = None
        self.ps = None

    def cargar(self):
        ruta = self.dir / "grafo.json"
        if not ruta.exists():
            return False
        self.G = grafo_mod.Grafo.cargar(ruta)
        self.ps = Pseudonimizador(secreto(), self.dir / "store.json")
        self.ps.agregar_formas_reales(Motor(self.G, self.ps)._formas_reales())
        return True

    def listo(self):
        return self.G is not None

    def anonimizar(self, fuente: str, registros: list):
        """-> (registros anonimizados, entidades que intervinieron)."""
        with self.lock:
            if self.G is None and not self.cargar():
                # sin corrida previa: grafo vacío; las personas se detectan por reglas y quedan como nuevas
                self.G = grafo_mod.Grafo()
                self.ps = Pseudonimizador(secreto(), self.dir / "store.json")
            G = copy.deepcopy(self.G)
            motor = Motor(G, self.ps, preparado=True)
            motor.recall_lote = 35
            entrada = [copy.deepcopy(r) for r in registros]
            salida, menciones = motor.anonimizar(entrada)
            ents = _entidades_lote(G, motor.rz, entrada, salida, menciones)
            self.ps.guardar()
            return [_publico(r) for r in salida], ents


def _entidades_lote(G, rz, entrada, salida, menciones):
    por_ent = {}
    for r in entrada:
        for m in menciones.get(r["id"], []):
            if m.entity_id and m.entity_id in G:
                por_ent.setdefault(m.entity_id, {"records": set(), "originals": set()})
                por_ent[m.entity_id]["records"].add(r["id"])
                if not m.kept:
                    por_ent[m.entity_id]["originals"].add(m.texto)
        if "thread_id" in r:
            eid = resuelve.autor_eid(r, G)
            if eid:
                por_ent.setdefault(eid, {"records": set(), "originals": set()})
                por_ent[eid]["records"].add(r["id"])
                por_ent[eid]["originals"].add(r.get("author", ""))
    ents = []
    for eid, d in por_ent.items():
        e = G[eid]
        if e.kept:
            ents.append({"entity_id": eid, "type": "organization_or_place", "originals": [e.nombre],
                         "pseudonyms": {}, "kept": True, "reason": e.reason, "records": sorted(d["records"])})
            continue
        uso = dict(rz.uso.get(eid, {}))
        ps = {k: v for k, v in uso.items() if isinstance(v, str) and v and k not in ("handle_uid",)}
        try:
            ps.setdefault("name", rz.seudo(eid).completo)
        except Exception:   # noqa: BLE001
            pass
        ents.append({"entity_id": eid, "type": "person", "originals": sorted(x for x in d["originals"] if x),
                     "pseudonyms": ps, "records": sorted(d["records"])})
    return ents
