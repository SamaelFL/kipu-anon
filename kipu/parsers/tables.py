import csv
import io
import re
import xml.etree.ElementTree as ET

KEYS = {"clientes": "cliente_id", "transacciones": "tx_id", "pqrs": "radicado", "empleados": "id"}
_FORBIDDEN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


def _decode(raw, charset):
    try:
        return raw.decode(charset)
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _csv(name, raw, charset, sep):
    text = _decode(raw, charset).lstrip("\ufeff")
    key = KEYS[name]
    rows = []
    for row in csv.DictReader(io.StringIO(text, newline=""), delimiter=sep):
        cols = {k: (v if v is not None else "") for k, v in row.items() if k is not None}
        rows.append((cols[key], cols))
    return rows


def _xml(name, raw):
    if _FORBIDDEN.search(raw):
        raise ValueError("%s: XML con DOCTYPE/ENTITY rechazado" % name)
    root = ET.fromstring(raw)
    rows = []
    for el in root:
        if not isinstance(el.tag, str):
            continue
        cols = dict(el.attrib)
        for ch in el:
            if not isinstance(ch.tag, str):
                continue
            cols[ch.tag] = (ch.text or "").strip()
            for ak, av in ch.attrib.items():
                cols["%s_%s" % (ch.tag, ak)] = av
        rows.append((cols[KEYS[name]], cols))
    return rows


def parse(filename, raw):
    name, _, ext = filename.rpartition(".")
    if name not in KEYS:
        raise ValueError("tabla desconocida: " + filename)
    if ext == "csv":
        if name == "clientes":
            rows = _csv(name, raw, "latin-1", ";")
        else:
            rows = _csv(name, raw, "utf-8", ",")
    else:
        rows = _xml(name, raw)
    return [{"id": "%s:%s" % (name, key), "table": name, "columns": cols} for key, cols in rows]
