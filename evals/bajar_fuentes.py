"""Espeja el API de fuentes a una carpeta con el layout de fuentes/ y resume qué cambió contra otra.

Uso:  python3 evals/bajar_fuentes.py --out fuentes_v2 [--base fuentes]
Lee SOURCES_URL y SOURCES_TOKEN de .env o del entorno; nunca los imprime.
El resumen solo da conteos y nombres de canales, fechas, docs y tablas (sin contenido).
"""
import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from kipu.sources import ApiSource  # noqa: E402


def leer_env():
    env = {}
    p = RAIZ / ".env"
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, _, v = l.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SOURCES_URL", "SOURCES_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def escribir(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def espejar(src, out):
    escribir(out / "users.json", src.users())
    canales = src._json("/chats/channels")
    escribir(out / "channels.json", canales)
    for c in [c["name"] for c in canales]:
        for f in src.dates(c):
            escribir(out / "chats" / c / (f + ".json"), src.messages(c, f))
    idx = src.docs_index()
    escribir(out / "docs_index.json", idx)
    for e in idx:
        escribir(out / "docs" / e["id"], src.doc_bytes(e))
    tabs = src._json("/tables")
    escribir(out / "tables.json", tabs)
    for t in [t["name"] for t in tabs]:
        escribir(out / "tables" / t, src.table_bytes(t))
    escribir(out / "record_index.json", src._json("/record_index"))
    try:
        escribir(out / "tests_public.json", src._json("/tests/public"))
    except Exception as e:  # noqa: BLE001
        print("tests/public:", type(e).__name__, file=sys.stderr)


def filas(p):
    b = p.read_bytes()
    if p.suffix == ".csv":
        for enc in ("utf-8", "latin-1"):
            try:
                return sum(1 for _ in csv.reader(io.StringIO(b.decode(enc)))) - 1
            except UnicodeDecodeError:
                continue
    return b.count(b"</") and None


def resumen(base, out):
    def fechas(r):
        d = r / "chats"
        return {(c.name, f.stem) for c in d.iterdir() if c.is_dir() for f in c.glob("*.json")} if d.exists() else set()
    rb, ro = json.loads((base / "record_index.json").read_text()), json.loads((out / "record_index.json").read_text())
    print("record_index:", {k: (len(rb.get(k, [])), len(v)) for k, v in ro.items() if isinstance(v, list)})
    nb = {k: set(v) for k, v in rb.items() if isinstance(v, list)}
    for k, v in ro.items():
        if isinstance(v, list):
            ids = set(v)
            print("  %s: nuevos %d, desaparecidos %d" % (k, len(ids - nb.get(k, set())), len(nb.get(k, set()) - ids)))
    fb, fo = fechas(base), fechas(out)
    canales_b, canales_o = {c for c, _ in fb}, {c for c, _ in fo}
    print("canales nuevos:", sorted(canales_o - canales_b))
    print("fechas nuevas:", len(fo - fb), sorted(fo - fb)[:40])
    ub = {u.get("id") for u in json.loads((base / "users.json").read_text())}
    uo = {u.get("id") for u in json.loads((out / "users.json").read_text())}
    print("usuarios: %d -> %d (nuevos %d)" % (len(ub), len(uo), len(uo - ub)))
    db = {e["id"] for e in json.loads((base / "docs_index.json").read_text())}
    do = json.loads((out / "docs_index.json").read_text())
    print("docs nuevos:", [(e["id"], e.get("filename"), e.get("content_type") or e.get("type")) for e in do if e["id"] not in db])
    for t in sorted(p.name for p in (out / "tables").iterdir()):
        a, b = base / "tables" / t, out / "tables" / t
        print("tabla %s: %s -> %s bytes, filas %s -> %s" % (
            t, a.stat().st_size if a.exists() else "NUEVA", b.stat().st_size,
            filas(a) if a.exists() else "-", filas(b)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="fuentes")
    ap.add_argument("--solo-resumen", action="store_true")
    a = ap.parse_args()
    out, base = RAIZ / a.out, RAIZ / a.base
    if not a.solo_resumen:
        env = leer_env()
        cache = RAIZ / "evals" / "out" / "cache_api"
        src = ApiSource(env["SOURCES_URL"], env["SOURCES_TOKEN"], cache_dir=cache)
        espejar(src, out)
    if base.exists():
        resumen(base, out)


if __name__ == "__main__":
    main()
