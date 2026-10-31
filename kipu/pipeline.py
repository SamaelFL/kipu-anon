import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from . import ingest

FILES = ("chats.jsonl", "docs.jsonl", "tables.jsonl", "entities.json")


def _jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run(source, out_dir):
    """Regenera los cuatro archivos de salida en out_dir (escritura atómica)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    chats = ingest.ingest_chats(source)
    docs = ingest.ingest_docs(source)
    tables = ingest.ingest_tables(source)
    entities = {"entities": []}
    tmp = Path(tempfile.mkdtemp(prefix=out_dir.name + ".tmp-", dir=out_dir.parent))
    try:
        _jsonl(tmp / "chats.jsonl", chats)
        _jsonl(tmp / "docs.jsonl", docs)
        _jsonl(tmp / "tables.jsonl", tables)
        (tmp / "entities.json").write_text(json.dumps(entities, ensure_ascii=False, indent=1), "utf-8")
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
    return {
        "records": {"chats": len(chats), "docs": len(docs), "tables": len(tables)},
        "cost": {"tokens_in": 0, "tokens_out": 0, "seconds": round(time.time() - t0, 2)},
    }
