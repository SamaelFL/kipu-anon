"""Manda los canarios de inyecciones.jsonl a POST /anonymize y falla si sale un valor real.
Uso: python3 evals/probar_inyecciones.py [--url http://localhost:9000/v1] [--inyecciones evals/inyecciones.jsonl]"""
import argparse
import json
import os
import sys
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from texto import contiene  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:9000/v1")
    ap.add_argument("--inyecciones", default=os.path.join(AQUI, "inyecciones.jsonl"))
    a = ap.parse_args()
    malos = 0
    for linea in open(a.inyecciones, encoding="utf8"):
        c = json.loads(linea)
        req = urllib.request.Request(a.url.rstrip("/") + "/anonymize", data=json.dumps({"source": c["source"], "records": c["records"]}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=90))
        except Exception as e:
            print(f"✗ {c['id']} {c['mechanism']}: error {e}")
            malos += 1
            continue
        salida = json.dumps(resp.get("records", []), ensure_ascii=False)
        fugas = [f for f in c["forbidden"] if contiene(salida, f) or f in salida]
        print(("✗" if fugas else "✓"), c["id"], c["mechanism"], fugas or "")
        malos += bool(fugas)
    print(f"{malos} canarios con fuga")
    return 1 if malos else 0


if __name__ == "__main__":
    sys.exit(main())
