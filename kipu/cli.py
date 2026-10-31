import argparse
import json
import os
import sys

from . import pipeline
from .sources import ApiSource, LocalSource


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kipu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="regenera output/")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--local", metavar="CARPETA")
    g.add_argument("--api", action="store_true", help="usa SOURCES_URL y SOURCES_TOKEN")
    r.add_argument("--out", required=True)
    s = sub.add_parser("serve", help="levanta el servicio HTTP")
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", "9000")))
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from . import server
        server.serve(a.port)
        return 0
    if a.local:
        src = LocalSource(a.local)
    else:
        url, tok = os.environ.get("SOURCES_URL"), os.environ.get("SOURCES_TOKEN")
        if not url or not tok:
            print("faltan SOURCES_URL / SOURCES_TOKEN en el entorno", file=sys.stderr)
            return 2
        src = ApiSource(url, tok)
    res = pipeline.run(src, a.out)
    print(json.dumps(res))
    return 0
