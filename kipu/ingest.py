"""Fuente -> registros normalizados (chats, docs, tables)."""
import os
import re
import sys

from .parsers import chats as pchats, html as phtml, md as pmd, pdf as ppdf, tables as ptables


def _humanize(filename):
    stem = os.path.splitext(filename)[0]
    s = re.sub(r"[_\-]+", " ", stem).strip()
    return s[:1].upper() + s[1:]


def ingest_chats(src):
    authors = pchats.author_map(src.users())
    out, seen = [], set()
    for canal in src.channels():
        for fecha in src.dates(canal):
            for m in src.messages(canal, fecha):
                rec = pchats.message_record(canal, m, authors)
                if not rec["id"]:
                    print("mensaje sin client_msg_id en %s/%s, omitido" % (canal, fecha), file=sys.stderr)
                    continue
                if rec["id"] in seen:
                    print("id de chat duplicado omitido", file=sys.stderr)
                    continue
                seen.add(rec["id"])
                out.append(rec)
    return out


def ingest_docs(src):
    out = []
    for e in src.docs_index():
        raw = src.doc_bytes(e)
        fmt = e["format"]
        if fmt == "md":
            body, meta = pmd.parse(raw)
            h1 = re.search(r"^# +(.+?)\s*$", body, re.M)
            title = meta.get("title") or (h1.group(1) if h1 else _humanize(e["filename"]))
        elif fmt == "html":
            title, body, meta = phtml.parse(raw)
            title = title or _humanize(e["filename"])
        elif fmt == "pdf":
            title, body, meta = ppdf.parse(raw, e["filename"])
            title = title or _humanize(e["filename"])
        else:
            raise ValueError("formato de documento no soportado: %s" % fmt)
        out.append({"id": e["id"], "format": fmt, "filename": e["filename"],
                    "title": title, "body": body, "metadata": meta})
    return out


def ingest_tables(src):
    out, seen = [], set()
    for name in src.tables():
        for rec in ptables.parse(name, src.table_bytes(name)):
            if rec["id"] in seen:
                print("fila duplicada omitida en %s" % name, file=sys.stderr)
                continue
            seen.add(rec["id"])
            out.append(rec)
    return out
