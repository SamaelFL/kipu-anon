"""HTML -> markdown sencillo con html.parser; conserva comentarios literales."""
import re
from html.parser import HTMLParser

_SKIP = {"style", "script", "head"}
_BLOCK = {"p", "div", "section", "article", "header", "footer", "ul", "ol", "table", "blockquote", "pre"}


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.meta = {}
        self.title = ""
        self.skip = 0
        self.in_title = False
        self.row = None
        self.row_has_th = False
        self.cell = None
        self.href = None
        self.link_text = None
        self.list_stack = []

    def _w(self, s):
        if self.cell is not None:
            self.cell.append(s)
        elif self.link_text is not None:
            self.link_text.append(s)
        else:
            self.out.append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
            return
        if tag == "meta":
            if a.get("name") and a.get("content") is not None:
                self.meta[a["name"]] = a["content"]
            return
        if tag in ("style", "script"):
            self.skip += 1
            return
        if self.skip or tag == "head":
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._w("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self.list_stack.append([tag, 0])
            self._w("\n")
        elif tag == "li":
            depth = max(len(self.list_stack) - 1, 0)
            if self.list_stack and self.list_stack[-1][0] == "ol":
                self.list_stack[-1][1] += 1
                mark = "%d." % self.list_stack[-1][1]
            else:
                mark = "-"
            self._w("\n" + "  " * depth + mark + " ")
        elif tag == "tr":
            self.row, self.row_has_th = [], False
        elif tag in ("td", "th"):
            self.cell = []
            if tag == "th":
                self.row_has_th = True
        elif tag == "br":
            self._w(" " if self.cell is not None else "\n")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "a":
            self.href, self.link_text = a.get("href"), []
        elif tag in _BLOCK:
            self._w("\n\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
            return
        if tag in ("style", "script"):
            self.skip = max(self.skip - 1, 0)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._w("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self._w("\n")
        elif tag in ("td", "th"):
            if self.cell is not None and self.row is not None:
                self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr":
            if self.row is not None:
                self.out.append("\n| " + " | ".join(self.row) + " |")
                if self.row_has_th:
                    self.out.append("\n|" + " --- |" * len(self.row))
            self.row = None
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "a":
            text = "".join(self.link_text or [])
            href, self.link_text, self.href = self.href, None, None
            if href and href.startswith("mailto:") or not href or href.startswith("#") or text.strip() == href:
                self._w(text)
            else:
                self._w("[%s](%s)" % (text, href))
        elif tag in _BLOCK:
            self._w("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        self._w(re.sub(r"\s+", " ", data) if self.cell is not None or "\n" not in data.strip("\n ") else re.sub(r"\s+", " ", data))

    def handle_comment(self, data):
        if self.cell is not None:
            self.cell.append("<!--%s-->" % data)
        else:
            self.out.append("\n\n<!--%s-->\n\n" % data)


def parse(raw: bytes):
    p = _P()
    p.feed(raw.decode("utf-8-sig"))
    p.close()
    text = "".join(p.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    title = re.sub(r"\s+", " ", p.title).strip()
    meta = {}
    if title:
        meta["title"] = title
    meta.update(p.meta)
    return title, text, meta
