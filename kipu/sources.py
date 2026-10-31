"""Fuentes intercambiables: API de fuentes (Bearer, 8 req/s, backoff, ETag) o carpeta local."""
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.parse
from pathlib import Path

MAX_RPS = 8
MAX_BYTES = 50 * 1024 * 1024


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data"))


class SourceError(Exception):
    pass


def parse_sources_url(url):
    """Solo https, sin credenciales, puerto 443. Devuelve (host, puerto, prefijo de ruta)."""
    try:
        u = urllib.parse.urlsplit(url.strip())
        port = u.port or 443
    except ValueError:
        raise SourceError("sources_url inválida")
    if u.scheme != "https" or not u.hostname or u.username or u.password or port != 443:
        raise SourceError("sources_url debe ser https://host[/ruta] sin credenciales")
    if u.query or u.fragment:
        raise SourceError("sources_url no admite query ni fragmento")
    return u.hostname.lower(), port, u.path.rstrip("/")


def _public_ips(host, port):
    """Resuelve el host y exige que TODAS sus IPs sean públicas (global)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceError("no se resuelve el host de sources_url")
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise SourceError("sources_url resuelve a una IP no pública")
        ips.append(str(ip))
    if not ips:
        raise SourceError("no se resuelve el host de sources_url")
    return ips


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Conecta a la IP ya validada (evita DNS rebinding) con SNI/verificación del host original."""

    def __init__(self, host, port, ips):
        super().__init__(host, port, timeout=60, context=ssl.create_default_context())
        self._ips = ips

    def connect(self):
        last = None
        for ip in self._ips:
            try:
                sock = socket.create_connection((ip, self.port), self.timeout)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as e:
                last = e
        raise last or OSError("sin IPs")


class _Limiter:
    def __init__(self, rps):
        self.gap = 1.0 / rps
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


class ApiSource:
    kind = "api"

    def __init__(self, base_url, token, cache_dir=None, retries=6):
        self.host, self.port, self.prefix = parse_sources_url(base_url)
        _public_ips(self.host, self.port)  # falla pronto si el host no es público
        self.base = "https://%s%s" % (self.host, self.prefix)
        self._token = token
        self.cache = Path(cache_dir) if cache_dir else data_dir() / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.retries = retries
        self.limiter = _Limiter(MAX_RPS)

    def _get(self, path):
        url = self.base + path
        key = hashlib.sha256(url.encode()).hexdigest()
        body_f, etag_f = self.cache / (key + ".body"), self.cache / (key + ".etag")
        headers = {"Authorization": "Bearer " + self._token, "Accept": "*/*", "Host": self.host}
        if body_f.exists() and etag_f.exists():
            headers["If-None-Match"] = etag_f.read_text()
        last = None
        for attempt in range(self.retries):
            self.limiter.wait()
            try:
                conn = _PinnedHTTPS(self.host, self.port, _public_ips(self.host, self.port))
                try:
                    conn.request("GET", self.prefix + path, headers=headers)
                    r = conn.getresponse()
                    code = r.status
                    if code == 200:
                        data = r.read(MAX_BYTES + 1)
                        if len(data) > MAX_BYTES:
                            raise SourceError("respuesta demasiado grande: " + path)
                        etag = r.getheader("ETag")
                        if etag:
                            body_f.write_bytes(data)
                            etag_f.write_text(etag)
                        return data
                    retry_after = r.getheader("Retry-After")
                    r.read(0)
                finally:
                    conn.close()
            except (OSError, http.client.HTTPException) as e:
                last = type(e).__name__
                time.sleep(min(2 ** attempt * 0.5, 20))
                continue
            if code == 304 and body_f.exists():
                return body_f.read_bytes()
            if 300 <= code < 400:
                raise SourceError("redirección rechazada en " + path)
            if code == 404:
                raise SourceError("404 " + path)
            if code == 429 or code >= 500:
                try:
                    wait = min(float(retry_after), 60)
                except (TypeError, ValueError):
                    wait = min(2 ** attempt * 0.5, 20)
                last = "HTTP %d" % code
                print("fuente %s %s, reintento en %.1fs" % (path, last, wait), file=sys.stderr)
                time.sleep(wait)
                continue
            raise SourceError("HTTP %d en %s" % (code, path))
        raise SourceError("sin respuesta de %s (%s)" % (path, last))

    def _json(self, path):
        return json.loads(self._get(path).decode("utf-8"))

    def users(self):
        return self._json("/chats/users")

    def channels(self):
        return [c["name"] for c in self._json("/chats/channels")]

    def dates(self, canal):
        return self._json("/chats/" + canal)

    def messages(self, canal, fecha):
        return self._json("/chats/%s/%s" % (canal, fecha))

    def docs_index(self):
        return self._json("/docs")

    def doc_bytes(self, entry):
        return self._get("/docs/" + entry["id"])

    def tables(self):
        return [t["name"] for t in self._json("/tables")]

    def table_bytes(self, name):
        return self._get("/tables/" + name)


class LocalSource:
    """Acepta el layout de sample/input (chats/users.json, docs/index.json) y el de fuentes/."""
    kind = "local"

    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir():
            raise SourceError("carpeta inexistente: %s" % root)

    def _first(self, *rels):
        for r in rels:
            p = self.root / r
            if p.exists():
                return p
        raise SourceError("no encuentro " + " ni ".join(rels))

    def users(self):
        return json.loads(self._first("users.json", "chats/users.json").read_text("utf-8"))

    def _chat_root(self):
        return self.root / "chats"

    def channels(self):
        return sorted(p.name for p in self._chat_root().iterdir() if p.is_dir())

    def dates(self, canal):
        return sorted(p.stem for p in (self._chat_root() / canal).glob("*.json"))

    def messages(self, canal, fecha):
        return json.loads((self._chat_root() / canal / (fecha + ".json")).read_text("utf-8"))

    def docs_index(self):
        return json.loads(self._first("docs_index.json", "docs/index.json").read_text("utf-8"))

    def doc_bytes(self, entry):
        for n in (entry["id"], entry["filename"]):
            p = self.root / "docs" / n
            if p.is_file():
                return p.read_bytes()
        raise SourceError("falta el documento " + entry["id"])

    def tables(self):
        d = self.root / "tables"
        return sorted(p.name for p in d.iterdir() if p.suffix in (".csv", ".xml"))

    def table_bytes(self, name):
        return (self.root / "tables" / name).read_bytes()
