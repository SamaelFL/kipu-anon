"""Servicio HTTP (librería estándar). Rutas bajo /v1 y sin prefijo."""
import hmac
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import VERSION, pipeline
from .sources import ApiSource, SourceError, data_dir

MAX_BODY = 2 * 1024 * 1024
MAX_RECORDS = 50
TEAM = "Ismael"
MODELS = []
OUTPUT_FILES = {"chats.jsonl": "application/x-ndjson", "docs.jsonl": "application/x-ndjson",
                "tables.jsonl": "application/x-ndjson", "entities.json": "application/json"}


def log(msg):
    print("%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.dir = data_dir()
        (self.dir / "jobs").mkdir(parents=True, exist_ok=True)
        self.current = None
        self._recover()

    def _path(self, jid):
        return self.dir / "jobs" / (jid + ".json")

    def _save(self, job):
        p = self._path(job["job_id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job), "utf-8")
        os.replace(tmp, p)

    def _recover(self):
        for p in (self.dir / "jobs").glob("*.json"):
            try:
                j = json.loads(p.read_text("utf-8"))
                if j.get("status") in ("queued", "running"):
                    j.update(status="failed", finished_at=now(), error="servicio reiniciado durante la corrida")
                    self._save(j)
            except Exception:
                log("job corrupto ignorado")

    def get(self, jid):
        if not re.fullmatch(r"[0-9a-f]{32}", jid):
            return None
        with self.lock:
            if self.current and self.current["job_id"] == jid:
                return dict(self.current)
        p = self._path(jid)
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            return None

    def start(self, sources_url, token):
        with self.lock:
            c = self.current
            if c and c["status"] in ("queued", "running"):
                return c["job_id"]
            job = {"job_id": uuid.uuid4().hex, "status": "queued", "started_at": now(),
                   "records": {"chats": 0, "docs": 0, "tables": 0},
                   "cost": {"tokens_in": 0, "tokens_out": 0, "seconds": 0}}
            self.current = job
            self._save(job)
        threading.Thread(target=self._work, args=(job["job_id"], sources_url, token), daemon=True).start()
        return job["job_id"]

    def _update(self, **kw):
        with self.lock:
            self.current.update(kw)
            self._save(self.current)

    def _work(self, jid, url, token):
        t0 = time.time()
        self._update(status="running")
        log("job %s inicia" % jid)
        try:
            src = ApiSource(url, token)
            res = pipeline.run(src, self.dir / "output")
            self._update(status="done", finished_at=now(), records=res["records"], cost=res["cost"])
            (self.dir / "latest").write_text(jid)
            log("job %s done %s" % (jid, res["records"]))
        except BaseException as e:
            msg = str(e) if isinstance(e, (SourceError, ValueError)) else type(e).__name__
            log("job %s falló: %s" % (jid, type(e).__name__))
            self._update(status="failed", finished_at=now(), error=msg[:300],
                         cost={"tokens_in": 0, "tokens_out": 0, "seconds": round(time.time() - t0, 2)})


def _is_str(v):
    return isinstance(v, str)


def validate_record(source, r):
    if not isinstance(r, dict) or not _is_str(r.get("id")):
        return False
    if source == "chats":
        att = r.get("attachments")
        return (all(_is_str(r.get(k)) for k in ("thread_id", "author", "ts", "text"))
                and isinstance(att, list) and all(isinstance(a, dict) and _is_str(a.get("filename")) for a in att))
    if source == "docs":
        return (all(_is_str(r.get(k)) for k in ("format", "filename", "title", "body"))
                and isinstance(r.get("metadata"), dict))
    if source == "tables":
        c = r.get("columns")
        return _is_str(r.get("table")) and isinstance(c, dict) and all(_is_str(k) and _is_str(v) for k, v in c.items())
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "kipu"
    protocol_version = "HTTP/1.1"
    jobs = None

    def log_message(self, fmt, *args):
        log("%s %s" % (self.command, self.path.split("?")[0]))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/v1" or path.startswith("/v1/"):
            path = path[3:] or "/"
        return path

    def _auth_ok(self):
        tok = os.environ.get("TEAM_TOKEN")
        h = self.headers.get("Authorization")
        if not tok or not h:
            return True
        m = re.fullmatch(r"Bearer\s+(.+)", h.strip(), re.I)
        return bool(m) and hmac.compare_digest(m.group(1).encode(), tok.encode())

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, 400
        if n > MAX_BODY:
            return None, 413
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")), 0
        except (ValueError, UnicodeDecodeError):
            return None, 400

    def _dispatch(self, method):
        path = self._route()
        if path == "/health" and method == "GET":
            return self._send(200, {"status": "ok", "team": TEAM, "version": VERSION, "models": MODELS})
        if not self._auth_ok():
            return self._send(401, {"error": "token inválido"})
        if method == "POST" and path == "/run":
            body, err = self._body_json()
            if err or not isinstance(body, dict):
                return self._send(err or 400, {"error": "cuerpo inválido"})
            url, tok = body.get("sources_url"), body.get("token")
            if not _is_str(url) or not _is_str(tok) or not url.startswith(("http://", "https://")):
                return self._send(422, {"error": "se requieren sources_url y token"})
            return self._send(202, {"job_id": self.jobs.start(url, tok)})
        m = re.fullmatch(r"/run/([^/]+)", path)
        if method == "GET" and m:
            j = self.jobs.get(m.group(1))
            if not j:
                return self._send(404, {"error": "job inexistente"})
            return self._send(200, {k: v for k, v in j.items() if k != "job_id"} | {"job_id": j["job_id"]})
        m = re.fullmatch(r"/output/([^/]+)", path)
        if method == "GET" and m:
            return self._output(m.group(1))
        if method == "GET" and path == "/entities":
            return self._output("entities.json")
        if method == "POST" and path == "/anonymize":
            return self._anonymize()
        self._send(404, {"error": "no encontrado"})

    def _output(self, name):
        if name not in OUTPUT_FILES:
            return self._send(404, {"error": "archivo desconocido"})
        p = data_dir() / "output" / name
        if not (data_dir() / "latest").exists() or not p.is_file():
            return self._send(404, {"error": "no hay corrida terminada"})
        self._send(200, p.read_bytes(), OUTPUT_FILES[name] + "; charset=utf-8")

    def _anonymize(self):
        body, err = self._body_json()
        if err:
            return self._send(err, {"error": "cuerpo inválido o demasiado grande"})
        if not isinstance(body, dict):
            return self._send(422, {"error": "cuerpo inválido"})
        source, recs = body.get("source"), body.get("records")
        if source not in ("chats", "docs", "tables") or not isinstance(recs, list):
            return self._send(422, {"error": "source o records inválidos"})
        if len(recs) > MAX_RECORDS:
            return self._send(422, {"error": "máximo %d registros" % MAX_RECORDS})
        if not all(validate_record(source, r) for r in recs):
            return self._send(422, {"error": "registro fuera del esquema de " + source})
        self._send(200, {"records": recs, "entities": []})

    def _handle(self, method):
        try:
            self._dispatch(method)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log("error en %s: %s" % (method, type(e).__name__))
            try:
                self._send(500, {"error": "error interno"})
            except Exception:
                pass

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        log("error de conexión: %s" % sys.exc_info()[0].__name__)


def serve(port):
    Handler.jobs = Jobs()
    srv = Server(("0.0.0.0", port), Handler)
    log("escuchando en :%d, DATA_DIR=%s" % (port, data_dir()))
    srv.serve_forever()
