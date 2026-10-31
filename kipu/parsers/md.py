import re

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def parse(raw: bytes):
    body = raw.decode("utf-8-sig")
    meta = {}
    m = _FM.match(body)
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if not sep or not k.strip() or line[:1] in " \t#":
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            meta[k.strip()] = v
    return body, meta
