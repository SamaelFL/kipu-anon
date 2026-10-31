"""Lector de la entrada (carpeta con chats/, docs/, tables/) a registros normalizados.

Acepta dos disposiciones:
  - muestra: chats/users.json, chats/channels.json, docs/index.json, tables/*
  - fuentes: users.json, channels.json, docs_index.json, docs/doc_XX (sin extension), tables/*
Los ids son los del record_index: client_msg_id, id de doc, <tabla>:<llave>.
El texto se entrega crudo (HTML, front matter, comentarios) para buscar ahi las trampas.
"""
import csv
import glob
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zlib


def _json(*rutas):
    for r in rutas:
        if os.path.exists(r):
            with open(r, encoding="utf8") as f:
                return json.load(f)
    return None


# ---------- PDF minimo ----------
def _pdf_cadena(tok: str) -> str:
    tok = tok.strip()
    if tok.startswith("<"):
        h = re.sub(r"\s", "", tok[1:-1])
        b = bytes.fromhex(h + ("0" if len(h) % 2 else ""))
        if b.startswith(b"\xfe\xff"):
            return b[2:].decode("utf-16-be", "replace")
        return b.decode("cp1252", "replace")
    s = tok[1:-1]
    s = re.sub(r"\\([nrtbf()\\])", lambda m: {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(m.group(1), m.group(1)), s)
    s = re.sub(r"\\([0-7]{1,3})", lambda m: chr(int(m.group(1), 8)), s)
    b = s.encode("latin-1", "replace")
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    return b.decode("cp1252", "replace")


_RX_LIT = r"\((?:\\.|[^\\()])*\)"
_RX_HEX = r"<[0-9A-Fa-f\s]*>"


def leer_pdf(ruta):
    raw = open(ruta, "rb").read()
    texto_lineas = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        datos = m.group(1)
        try:
            datos = zlib.decompress(datos)
        except Exception:
            pass
        s = datos.decode("latin-1")
        linea = []
        for op in re.finditer(r"(\[(?:%s|%s|[^\]])*\]|%s|%s)\s*(TJ|Tj)|(T\*|Td|TD|ET)\b" % (_RX_LIT, _RX_HEX, _RX_LIT, _RX_HEX), s):
            if op.group(3):
                if linea:
                    texto_lineas.append("".join(linea))
                    linea = []
                continue
            for c in re.finditer("%s|%s" % (_RX_LIT, _RX_HEX), op.group(1)):
                linea.append(_pdf_cadena(c.group(0)))
        if linea:
            texto_lineas.append("".join(linea))
    meta = {}
    for m in re.finditer(r"/(Author|Title|Subject|Keywords|Creator|Producer)\s*(%s|%s)" % (_RX_LIT, _RX_HEX), raw.decode("latin-1")):
        meta[m.group(1).lower()] = _pdf_cadena(m.group(2))
    return "\n".join(texto_lineas), meta


# ---------- docs ----------
def _meta_html(t):
    meta = {}
    for m in re.finditer(r"<meta\s+name=[\"']([^\"']+)[\"']\s+content=[\"']([^\"']*)[\"']", t, re.I):
        meta[m.group(1).lower()] = m.group(2)
    m = re.search(r"<title>(.*?)</title>", t, re.S | re.I)
    if m:
        meta["title"] = m.group(1)
    return meta


def _meta_md(t):
    meta = {}
    m = re.match(r"---\n(.*?)\n---", t, re.S)
    if m:
        for linea in m.group(1).splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def cargar_docs(base):
    idx = _json(os.path.join(base, "docs", "index.json"), os.path.join(base, "docs_index.json"),
                os.path.join(base, "docs", "docs_index.json")) or []
    docs = {}
    for d in idx:
        ruta = None
        for cand in (os.path.join(base, "docs", d["filename"]), os.path.join(base, "docs", d["id"])):
            if os.path.exists(cand):
                ruta = cand
                break
        if not ruta:
            continue
        if d["format"] == "pdf":
            body, meta = leer_pdf(ruta)
        else:
            body = open(ruta, encoding="utf8").read()
            meta = _meta_html(body) if d["format"] == "html" else _meta_md(body)
        docs[d["id"]] = {"id": d["id"], "format": d["format"], "filename": d["filename"],
                         "title": meta.get("title", ""), "body": body, "metadata": meta}
    return docs


# ---------- chats ----------
def cargar_chats(base):
    users_l = _json(os.path.join(base, "chats", "users.json"), os.path.join(base, "users.json")) or []
    users = {u["id"]: u for u in users_l}
    chats = {}
    for ruta in sorted(glob.glob(os.path.join(base, "chats", "*", "*.json"))):
        canal = os.path.basename(os.path.dirname(ruta))
        msgs = json.load(open(ruta, encoding="utf8"))
        for m in msgs:
            mid = m.get("client_msg_id")
            if not mid:
                continue
            u = users.get(m.get("user"), {})
            autor = m.get("username") or u.get("real_name") or m.get("user")
            tts = m.get("thread_ts") or m["ts"]
            adj = [{"filename": f.get("name") or f.get("title") or ""} for f in (m.get("files") or [])]
            chats[mid] = {"id": mid, "thread_id": f"{canal}:{tts}", "author": autor, "ts": m["ts"],
                          "text": m.get("text", ""), "attachments": adj, "canal": canal,
                          "user": m.get("user"), "raw": m}
    return chats, users


# ---------- tablas ----------
def _xml_filas(ruta, tag, prefijo, llave):
    t = ET.parse(ruta).getroot()
    out = {}
    for el in t.iter(tag):
        cols = dict(el.attrib)
        for h in el:
            cols[h.tag] = (h.text or "").strip()
            for k, v in h.attrib.items():
                cols[f"{h.tag}_{k}"] = v
        out[f"{prefijo}:{cols[llave]}"] = {"id": f"{prefijo}:{cols[llave]}", "table": prefijo, "columns": cols}
    return out


def _comentarios_xml(ruta):
    return re.findall(r"<!--(.*?)-->", open(ruta, encoding="utf8").read(), re.S)


def cargar_tablas(base):
    tablas = {}
    d = os.path.join(base, "tables")
    ruta = os.path.join(d, "clientes.csv")
    if os.path.exists(ruta):
        txt = open(ruta, encoding="latin-1", newline="").read()
        for fila in csv.DictReader(io.StringIO(txt), delimiter=";"):
            tablas[f"clientes:{fila['cliente_id']}"] = {"id": f"clientes:{fila['cliente_id']}", "table": "clientes", "columns": dict(fila)}
    ruta = os.path.join(d, "transacciones.csv")
    if os.path.exists(ruta):
        txt = open(ruta, encoding="utf8", newline="").read()
        for fila in csv.DictReader(io.StringIO(txt)):
            tablas[f"transacciones:{fila['tx_id']}"] = {"id": f"transacciones:{fila['tx_id']}", "table": "transacciones", "columns": dict(fila)}
    ruta = os.path.join(d, "pqrs.xml")
    if os.path.exists(ruta):
        tablas.update(_xml_filas(ruta, "pqr", "pqrs", "radicado"))
    ruta = os.path.join(d, "empleados.xml")
    if os.path.exists(ruta):
        tablas.update(_xml_filas(ruta, "empleado", "empleados", "id"))
    return tablas


def cargar_entrada(base):
    chats, users = cargar_chats(base)
    return {"chats": chats, "docs": cargar_docs(base), "tables": cargar_tablas(base), "users": users}


def plano(v):
    """Igual que plano() del validador: valores y claves aplanados."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, bool):
        return ["True" if v else "False"]
    if isinstance(v, (int, float)):
        return [str(v)]
    if isinstance(v, list):
        return [x for e in v for x in plano(e)]
    if isinstance(v, dict):
        return [x for k, e in v.items() for x in [k] + plano(e)]
    return [str(v)]


def texto_de(rec, campo=None):
    """Texto del registro (o de un campo) como lo ve el juez oficial."""
    if campo in (None, "", "any", "raw", "*"):
        return " | ".join(plano({k: v for k, v in rec.items() if k not in ("id", "raw", "canal", "user")}))
    if campo.startswith("columns."):
        col = ".".join(campo.split(".")[1:])
        cols = rec.get("columns") or {}
        if col == "*":
            return " | ".join(plano(cols))
        return " | ".join(plano(cols.get(col)))
    return " | ".join(plano(rec.get(campo)))
