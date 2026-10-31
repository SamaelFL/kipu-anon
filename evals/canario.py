"""Canario de las fuentes: avisa cuando GET /record_index cambia (ETag o ids por fuente).

Uso:  nohup python3 evals/canario.py >/dev/null 2>&1 &      (loguea en evals/out/canario.log)
      python3 evals/canario.py --una-vez                     (una consulta y sale)
Lee SOURCES_URL y SOURCES_TOKEN de .env o del entorno; nunca los imprime.
Estado entre arranques: evals/out/canario_estado.json. Cambios: evals/out/record_index_<hora>.json.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "evals" / "out"
LOG = OUT / "canario.log"
ESTADO = OUT / "canario_estado.json"


def log(msg):
    linea = "%s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    if sys.stdout.isatty():
        print(linea, flush=True)


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


def url_indice(base):
    u = urllib.parse.urlsplit(base.strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise SystemExit("SOURCES_URL debe ser https://host[/ruta] sin credenciales")
    return base.strip().rstrip("/") + "/record_index"


def consultar(url, token, etag):
    """Devuelve (codigo, etag, cuerpo_bytes|None)."""
    h = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if etag:
        h["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("ETag"), r.read(50 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, etag, None
        return e.code, None, None


def conteos(idx):
    return {k: len(v) for k, v in idx.items() if isinstance(v, list)}


def cargar_estado():
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return None


def guardar_estado(e):
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e), encoding="utf-8")
    os.replace(tmp, ESTADO)


def avisar(msg):
    log("*" * 8 + " " + msg)
    if sys.stdout.isatty():
        print("\a", end="", flush=True)
    if shutil.which("say"):
        try:
            subprocess.Popen(["say", "cambiaron las fuentes"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def ciclo(url, token, estado):
    """Una consulta. Devuelve el estado nuevo."""
    etag = estado.get("etag") if estado else None
    try:
        code, et, cuerpo = consultar(url, token, etag)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        log("sin respuesta (%s); reintento en el siguiente ciclo" % type(e).__name__)
        return estado
    if code == 304:
        log("sin cambios (304)")
        return estado
    if code != 200 or cuerpo is None:
        log("respuesta HTTP %d; reintento en el siguiente ciclo" % code)
        return estado
    try:
        idx = json.loads(cuerpo.decode("utf-8"))
    except ValueError:
        log("respuesta 200 que no es JSON; la ignoro")
        return estado
    cuenta = conteos(idx)
    sha = hashlib.sha256(cuerpo).hexdigest()
    nuevo = {"etag": et, "sha": sha, "conteos": cuenta, "ids": {k: sorted(v) for k, v in idx.items() if isinstance(v, list)}}
    OUT.mkdir(parents=True, exist_ok=True)
    if not estado:
        (OUT / "record_index_base.json").write_bytes(cuerpo)
        log("línea base: %s (ETag %s)" % (", ".join("%s=%d" % kv for kv in sorted(cuenta.items())), "sí" if et else "no"))
        guardar_estado(nuevo)
        return nuevo
    cambio_etag = bool(et) and et != estado.get("etag")
    cambio_conteo = cuenta != estado.get("conteos")
    cambio_cuerpo = not et and sha != estado.get("sha")
    if not (cambio_etag or cambio_conteo or cambio_cuerpo):
        log("sin cambios (200, mismo contenido)")
        guardar_estado(nuevo)
        return nuevo
    previo_ids = estado.get("ids", {})
    hora = datetime.now().strftime("%Y%m%d_%H%M%S")
    (OUT / ("record_index_%s.json" % hora)).write_bytes(cuerpo)
    partes = []
    for fuente in sorted(set(cuenta) | set(estado.get("conteos", {}))):
        antes, despues = estado.get("conteos", {}).get(fuente, 0), cuenta.get(fuente, 0)
        nuevos = len(set(nuevo["ids"].get(fuente, [])) - set(previo_ids.get(fuente, [])))
        quitados = len(set(previo_ids.get(fuente, [])) - set(nuevo["ids"].get(fuente, [])))
        partes.append("%s: %d -> %d (+%d nuevos%s)" % (fuente, antes, despues, nuevos, ", -%d quitados" % quitados if quitados else ""))
    avisar("CAMBIARON LAS FUENTES a las %s | %s | guardado en evals/out/record_index_%s.json"
           % (datetime.now().strftime("%H:%M:%S"), "; ".join(partes), hora))
    guardar_estado(nuevo)
    return nuevo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervalo", type=int, default=300, help="segundos entre consultas (300)")
    ap.add_argument("--una-vez", action="store_true")
    a = ap.parse_args()
    env = leer_env()
    if not env.get("SOURCES_URL") or not env.get("SOURCES_TOKEN"):
        raise SystemExit("faltan SOURCES_URL y SOURCES_TOKEN en .env")
    url, token = url_indice(env["SOURCES_URL"]), env["SOURCES_TOKEN"]
    log("canario iniciado (cada %ds, pid %d)" % (a.intervalo, os.getpid()))
    estado = cargar_estado()
    while True:
        estado = ciclo(url, token, estado)
        if a.una_vez:
            return
        time.sleep(a.intervalo)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("canario detenido")
