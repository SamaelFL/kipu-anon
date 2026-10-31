"""Reemplazo de spans por seudónimos con el formato del original. Nunca vacía un registro ni quita una clave."""
from __future__ import annotations

import copy
import hashlib
import hmac
import re

from . import formas as F
from .grafo import Grafo, persona_de
from .modelo import Mencion

_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BOTS = {"kipi"}


def _a_iso(txt, fmt=None):
    """ISO de una fecha en ISO, d/m/a (o m/d/a con fmt="mdy") o "d de mes de a"; None si no se entiende."""
    from .patrones import MESES
    if fmt == "mdy":
        m = re.fullmatch(r"\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}).*", txt, re.S)
        if m:
            return "%s-%02d-%02d" % (m[3], int(m[1]), int(m[2]))
    m = re.fullmatch(r"\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2}).*", txt, re.S)
    if m:
        return "%s-%02d-%02d" % (m[1], int(m[2]), int(m[3]))
    m = re.fullmatch(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}).*", txt, re.S)
    if m:
        return "%s-%02d-%02d" % (m[3], int(m[2]), int(m[1]))
    m = re.fullmatch(r"\s*(\d{1,2}) de ([A-Za-záéíóúÁÉÍÓÚ]+) de (\d{4}).*", txt, re.S)
    if m and F.plano(m[2]) in MESES:
        return "%s-%02d-%02d" % (m[3], MESES.index(F.plano(m[2])) + 1, int(m[1]))
    return None


class Reemplazador:
    def __init__(self, G: Grafo, ps, genero_fn=None):
        self.G = G
        self.ps = ps
        self.genero_fn = genero_fn
        self._real = {}
        self._seudo = {}
        self.nac_reales = {iso for e in G.values() for iso in e.ids.get("nacimientos", [])}
        self.uso: dict = {}            # eid -> {name,email,phone,...}
        self.kept_vistos: dict = {}    # eid -> True
        self.vistas: dict = {}         # eid -> formas reales que sí se reemplazaron
        self.recs: dict = {}           # eid -> ids de registros donde se reemplazó una forma suya (o es el autor)

    # ------------------------------------------------------------ personas
    def reales(self, eid):
        """Variantes Persona real de la entidad (más completa primero)."""
        if eid not in self._real:
            e = self.G[eid]
            nombres = sorted(set(e.atributos.get("personas") or [e.nombre]), key=lambda x: -len(x.split()))
            self._real[eid] = [persona_de(n, e.genero) for n in nombres if n]
        return self._real[eid]

    def seudo(self, eid):
        if eid not in self._seudo:
            e = self.G[eid]
            reales = self.reales(eid)
            base = reales[0] if reales else persona_de(e.nombre or "X")
            g = e.genero or (self.genero_fn(base.pila, []) if self.genero_fn else "f")
            n_ap = max(len(base.apellidos), 1)
            self._seudo[eid] = self.ps.persona(e.llave, g, max(len(base.nombres), 1), min(n_ap, 2))
        return self._seudo[eid]

    def _uso(self, eid, clave, valor):
        if eid:
            self.uso.setdefault(eid, {}).setdefault(clave, valor)

    def _nacimiento(self, t, fmt=None):
        """Fecha nueva con el formato del original, distinta de cualquier fecha de nacimiento real."""
        mdy = re.fullmatch(r"(\d{1,2})([/.\-])(\d{1,2})\2(\d{4})", t.strip()) if fmt == "mdy" else None
        if mdy:
            ancho = len(mdy[1]) == 2 or len(mdy[3]) == 2
            iso = "%s-%02d-%02d" % (mdy[4], int(mdy[1]), int(mdy[3]))
            for _ in range(9):
                iso = self.ps.nacimiento(iso)
                if iso not in self.nac_reales:
                    break
            y, mo, d = iso.split("-")
            f = (lambda v: v.zfill(2)) if ancho else (lambda v: str(int(v)))
            return "%s%s%s%s%s" % (f(mo), mdy[2], f(d), mdy[2], y)
        nuevo = self.ps.nacimiento(t)
        for _ in range(8):
            if _a_iso(nuevo) not in self.nac_reales and nuevo != t:
                break
            nuevo = self.ps.nacimiento(nuevo)
        return nuevo

    # ------------------------------------------------------------ nombres
    def nombre(self, eid, forma_orig, m=None):
        e = self.G[eid]
        sp = self.seudo(eid)
        self._uso(eid, "name", sp.completo)
        if e.atributos.get("apellido_solo"):
            return F._estilo(forma_orig, "", sp.apellidos[0] if sp.apellidos else sp.completo)
        for real in self.reales(eid):
            r = F.mapear_forma(forma_orig, real, sp)
            if r:
                return r
        letras = [c for c in forma_orig if c.isalpha()]
        toks_ = re.findall(r"[^\W_]+", forma_orig)
        apodos = [a for a in e.atributos.get("apodos", [])]
        if any(F.plano(forma_orig) == F.plano(a) for a in apodos) or (m is not None and m.forma == "apodo"):
            return F._estilo(forma_orig, "", sp.pila)
        sep = re.search(r"[_\-.]", forma_orig)
        if len(toks_) == 1:
            if m is not None and m.tipo in ("handle", "slug") or re.search(r"\d", forma_orig) or sep:
                return self._estilo_handle(forma_orig, sp, eid)
            # un solo token: apellido o pila no mapeable -> pila
            return F._estilo(forma_orig, "", sp.pila)
        if len(toks_) == 2:
            txt = "%s %s" % (sp.pila, sp.apellido1)
        else:
            txt = sp.completo
        if sep and " " not in forma_orig:
            return F._unir(txt.split(), sep.group(0))
        return F._estilo(forma_orig, "", txt)

    def _estilo_handle(self, forma, sp, eid):
        reales = self.reales(eid)
        real = reales[0] if reales else None
        r = self.ps.correo(forma + "@x.co", sp, real)
        return r.split("@")[0]

    # ------------------------------------------------------------ uid de Slack
    def uid_falso(self, uid):
        d = hmac.new(self.ps.secreto, ("uid:" + uid).encode(), hashlib.sha256).digest()
        n = int.from_bytes(d[:8], "big")
        s = ""
        for _ in range(8):
            n, r = divmod(n, 36)
            s += _BASE36[r]
        return "U" + s

    # ------------------------------------------------------------ cada mención
    def reemplazo(self, m: Mencion, eid):
        t = m.texto
        tipo = m.tipo
        ps = self.ps
        if getattr(m, "uid", None):
            nuevo = "<@%s" % self.uid_falso(m.uid)
            if "|" in t:
                nombre = t[t.index("|") + 1:-1]
                if eid and nombre:
                    nuevo += "|" + self.nombre(eid, nombre, m)
            self._uso(eid, "slack_uid", self.uid_falso(m.uid))
            return nuevo + ">"
        if tipo in ("correo", "correo_deletreado"):
            correo = getattr(m, "correo", None) or t
            if tipo == "correo_deletreado":
                orig = correo
            else:
                orig = t
            local, _, dom = orig.rpartition("@")
            etiqueta = ""
            if "+" in local:                      # alias usuario+etiqueta@dominio: la etiqueta se conserva
                local, etiqueta = local.split("+", 1)
                etiqueta = "+" + etiqueta
            base = local + "@" + dom
            if eid:
                sp = self.seudo(eid)
                reales = self.reales(eid)
                nuevo = ps.correo(base, sp, reales[0] if reales else None)
            else:
                nuevo = ps.correo(base, persona_de("Persona Anónima"), None)
            if etiqueta:
                nl, _, nd = nuevo.rpartition("@")
                nuevo = nl + etiqueta + "@" + nd
            if tipo != "correo_deletreado" and orig != orig.lower():
                nuevo = nuevo.lower()
            self._uso(eid, "email", nuevo)
            return F.deletrear(nuevo) if tipo == "correo_deletreado" else nuevo
        if tipo == "cedula":
            nuevo = ps.cedula(t)
            self._uso(eid, "cedula", re.sub(r"\D", "", nuevo))
            return nuevo
        if tipo == "celular":
            nuevo = ps.celular(t)
            self._uso(eid, "phone", re.sub(r"\D", "", nuevo)[-10:])
            return nuevo
        if tipo == "placa":
            nuevo = ps.placa(t)
            self._uso(eid, "plate", nuevo)
            return nuevo
        if tipo == "pasaporte":
            nuevo = ps.pasaporte(t)
            self._uso(eid, "passport", nuevo)
            return nuevo
        if tipo == "credito" and m.forma == "cuenta":
            nuevo = ps.cedula(t)       # mismos grupos y separadores; todos los dígitos cambian
            self._uso(eid, "account", nuevo)
            return nuevo
        if tipo == "credito":
            nuevo = ps.credito(t)
            self._uso(eid, "account", nuevo)
            return nuevo
        if tipo == "direccion":
            nuevo = ps.direccion(t)
            self._uso(eid, "address", nuevo)
            return nuevo
        if tipo == "nacimiento":
            nuevo = self._nacimiento(t, getattr(m, "fmt", None))
            self._uso(eid, "birth_iso", _a_iso(nuevo, getattr(m, "fmt", None)))
            return nuevo
        if eid is None:
            return None
        nuevo = self.nombre(eid, t, m)
        if tipo == "handle" or m.forma in ("handle", "local"):
            self._uso(eid, "handle", nuevo)
        return nuevo

    # ------------------------------------------------------------ registros
    def aplicar(self, rec: dict, menciones: list) -> dict:
        """Devuelve una copia de `rec` con las menciones reemplazadas (sin claves nuevas ni perdidas)."""
        G = self.G
        out = copy.deepcopy(rec)
        por_campo = {}
        for m in menciones:
            if m.kept:
                if m.entity_id and m.entity_id in G:
                    self.kept_vistos[m.entity_id] = True
                continue
            por_campo.setdefault(m.campo, []).append(m)

        def sub(texto, ms):
            ms = sorted(ms, key=lambda x: (x.ini, -(x.fin - x.ini)))
            partes, pos = [], 0
            for m in ms:
                if m.ini < pos:
                    continue
                nuevo = self.reemplazo(m, m.entity_id)
                if nuevo is None:
                    continue
                if m.entity_id and nuevo != texto[m.ini:m.fin]:
                    self.vistas.setdefault(m.entity_id, set()).add(texto[m.ini:m.fin])
                    self.recs.setdefault(m.entity_id, set()).add(rec["id"])
                partes.append(texto[pos:m.ini])
                partes.append(nuevo)
                pos = m.fin
            partes.append(texto[pos:])
            return "".join(partes)

        if "columns" in out:
            cols = {}
            for k, v in out["columns"].items():
                nk = sub(k, por_campo.get("columns.%s#clave" % k, [])) if "columns.%s#clave" % k in por_campo else k
                cols[nk] = sub(v, por_campo["columns." + k]) if "columns." + k in por_campo else v
            out["columns"] = cols
        elif "thread_id" in out:
            if "text" in por_campo:
                out["text"] = sub(out["text"], por_campo["text"])
            for i, a in enumerate(out.get("attachments") or []):
                c = "attachments.%d.filename" % i
                if c in por_campo:
                    a["filename"] = sub(a["filename"], por_campo[c])
        else:
            for c in ("title", "filename", "body"):
                if c in por_campo:
                    out[c] = sub(out[c], por_campo[c])
            md = {}
            for k, v in out.get("metadata", {}).items():
                nk = sub(k, por_campo["metadata.%s#clave" % k]) if "metadata.%s#clave" % k in por_campo else k
                nv = sub(v, por_campo["metadata." + k]) if isinstance(v, str) and ("metadata." + k) in por_campo else v
                md[nk] = nv
            out["metadata"] = md
        return out

    def autor(self, rec: dict, eid):
        """Nuevo `author` de un chat: nombre del seudónimo de la entidad (los bots se conservan)."""
        a = rec.get("author", "")
        if not a or F.plano(a) in BOTS:
            return a
        if eid is None or eid not in self.G or self.G[eid].kept:
            return a
        nuevo = self.nombre(eid, a)
        if nuevo != a:
            self.vistas.setdefault(eid, set()).add(a)
            self.recs.setdefault(eid, set()).add(rec["id"])
        return nuevo
