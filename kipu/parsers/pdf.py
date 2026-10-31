"""PDF sin librerías: texto de operadores Tj/TJ tras zlib e Info dict."""
import re
import zlib

MAX_INFLATE = 20 * 1024 * 1024
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def _inflate(data):
    d = zlib.decompressobj()
    try:
        out = d.decompress(data, MAX_INFLATE + 1)
    except zlib.error:
        return None
    if len(out) > MAX_INFLATE:
        raise ValueError("PDF: stream excede 20 MB descomprimido")
    return out


def _lit(b, i):
    """b[i] == '(' -> (bytes, índice tras ')')."""
    out = bytearray()
    depth, i = 1, i + 1
    n = len(b)
    while i < n:
        c = b[i]
        if c == 0x5C:
            i += 1
            if i >= n:
                break
            c = b[i]
            if c in _ESC:
                out.append(_ESC[c])
            elif 0x30 <= c <= 0x37:
                j = i
                while j < n and j < i + 3 and 0x30 <= b[j] <= 0x37:
                    j += 1
                out.append(int(b[i:j], 8) & 0xFF)
                i = j - 1
            elif c == 13:
                if i + 1 < n and b[i + 1] == 10:
                    i += 1
            elif c == 10:
                pass
            else:
                out.append(c)
        elif c == 0x28:
            depth += 1
            out.append(c)
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(c)
        else:
            out.append(c)
        i += 1
    return bytes(out), n


def _hex(b, i):
    j = b.find(b">", i)
    if j < 0:
        j = len(b)
    h = re.sub(rb"[^0-9A-Fa-f]", b"", b[i + 1:j])
    if len(h) % 2:
        h += b"0"
    return bytes.fromhex(h.decode()), j + 1


def _text(raw):
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", "replace")
    return raw.decode("latin-1")


_TOK = re.compile(rb"\(|<(?!<)|\[|\]|[-+]?\d*\.?\d+|/[^\s/\[\]()<>]+|[A-Za-z'\"*]+")


def _content_lines(data):
    items = []  # (y, x, texto)
    x = y = 0.0
    nums, strs = [], []
    i, n = 0, len(data)
    in_arr = False
    while i < n:
        m = _TOK.search(data, i)
        if not m:
            break
        t = m.group()
        i = m.end()
        if t == b"(":
            s, i = _lit(data, m.start())
            strs.append(_text(s))
        elif t == b"<":
            s, i = _hex(data, m.start())
            strs.append(_text(s))
        elif t == b"[":
            in_arr = True
        elif t == b"]":
            in_arr = False
        elif re.fullmatch(rb"[-+]?\d*\.?\d+", t):
            try:
                nums.append(float(t))
            except ValueError:
                pass
        elif t.startswith(b"/"):
            nums.clear()
        else:
            if t == b"BT":
                x = y = 0.0
            elif t == b"Td" or t == b"TD":
                if len(nums) >= 2:
                    x += nums[-2]
                    y += nums[-1]
            elif t == b"Tm":
                if len(nums) >= 6:
                    x, y = nums[-2], nums[-1]
            elif t in (b"Tj", b"TJ", b"'", b'"'):
                if strs:
                    items.append((y, x, "".join(strs)))
            if not in_arr:
                nums.clear()
                strs.clear()
    return items


def _info(raw):
    m = re.search(rb"/Info\s+(\d+)\s+\d+\s+R", raw)
    if not m:
        return {}
    om = re.search(rb"(?<!\d)%s\s+\d+\s+obj\s*<<(.*?)>>\s*endobj" % m.group(1), raw, re.S)
    if not om:
        return {}
    d = om.group(1)
    meta = {}
    i = 0
    while True:
        k = re.compile(rb"/([A-Za-z0-9_]+)\s*").search(d, i)
        if not k:
            break
        j = k.end()
        key = k.group(1).decode("latin-1").lower()
        if j < len(d) and d[j] == 0x28:
            v, i = _lit(d, j)
            meta[key] = _text(v)
        elif j < len(d) and d[j] == 0x3C:
            v, i = _hex(d, j)
            meta[key] = _text(v)
        else:
            i = j
            vm = re.compile(rb"[^/\s]+").match(d, j)
            if vm:
                meta[key] = vm.group().decode("latin-1")
                i = vm.end()
    return meta


def parse(raw: bytes, filename=""):
    if not raw.startswith(b"%PDF"):
        raise ValueError("no es un PDF")
    lines = []
    for sm in _STREAM.finditer(raw):
        data = _inflate(sm.group(1))
        if data is None:
            data = sm.group(1)
        if b"Tj" not in data and b"TJ" not in data:
            continue
        rows = {}
        order = []
        for y, x, s in _content_lines(data):
            k = round(y, 1)
            if k not in rows:
                rows[k] = []
                order.append(k)
            rows[k].append((x, s))
        for k in order:
            cells = [s for _, s in sorted(rows[k], key=lambda p: p[0])]
            lines.append(" | ".join(c.strip() for c in cells) if len(cells) > 1 else cells[0])
    meta = _info(raw)
    title = meta.get("title") or ""
    return title, "\n".join(lines) + "\n", meta
