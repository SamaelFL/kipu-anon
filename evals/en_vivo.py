"""Simula las pruebas en vivo del evaluador contra POST /anonymize (solo librería estándar).

Levanta el servicio local con run.sh (puerto 9100, DATA_DIR en /tmp), corre antes
`python3 -m kipu run --local fuentes` para que existan grafo y store, y manda lotes de 50
registros con Authorization: Bearer $TEAM_TOKEN (de .env; nunca se imprime).

Uso:  python3 evals/en_vivo.py [--rehacer] [--url http://localhost:9100/v1] [--data-dir /tmp/kipu_envivo]
  --rehacer   vuelve a correr el pipeline aunque ya haya grafo y store en DATA_DIR
  --url       usa un servicio ya levantado (no arranca run.sh; hay que dar --data-dir donde está su corrida)
El reporte lleva formas reales: no lo pegues al repo.
"""
import argparse
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
from texto import contiene  # noqa: E402

LIMITE_S = 20.0
PUERTO = 9100
LOTE = 50


# ------------------------------------------------------------------ entorno y servicio
def leer_env():
    env = {}
    p = os.path.join(RAIZ, ".env")
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, _, v = l.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def preparar(data_dir, rehacer, env_hijo):
    out = os.path.join(data_dir, "output")
    listo = all(os.path.exists(os.path.join(data_dir, f)) for f in ("grafo.json", "store.json")) and \
        os.path.exists(os.path.join(out, "entities.json"))
    if listo and not rehacer:
        print("estado previo en %s (usa --rehacer para regenerarlo)" % data_dir)
        return
    os.makedirs(data_dir, exist_ok=True)
    print("corriendo el pipeline sobre fuentes/ (tarda unos minutos)...", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, "-m", "kipu", "run", "--local", "fuentes", "--out", out],
                       cwd=RAIZ, env=env_hijo, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise SystemExit("falló el pipeline (%d): %s" % (r.returncode, r.stderr[-600:]))
    print("pipeline listo en %.0f s" % (time.time() - t))


def levantar(data_dir, env_hijo):
    env = dict(env_hijo, PORT=str(PUERTO), DATA_DIR=data_dir)
    log = open(os.path.join(data_dir, "server.log"), "ab")
    p = subprocess.Popen(["bash", os.path.join(RAIZ, "run.sh")], cwd=RAIZ, env=env, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(120):
        try:
            with urllib.request.urlopen("http://localhost:%d/v1/health" % PUERTO, timeout=2) as r:
                if r.status == 200:
                    return p
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
        if p.poll() is not None:
            raise SystemExit("run.sh terminó (¿puerto %d ocupado?); revisa %s/server.log" % (PUERTO, data_dir))
    raise SystemExit("el servicio no respondió /health a tiempo")


def apagar(p):
    if p and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            os.killpg(p.pid, signal.SIGKILL)


# ------------------------------------------------------------------ cliente
class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token
        self.lotes = []   # (descripción, registros, segundos)

    def post(self, source, records, descr, token="auto", crudo=None):
        body = crudo if crudo is not None else {"source": source, "records": records}
        h = {"Content-Type": "application/json; charset=utf-8"}
        tk = self.token if token == "auto" else token
        if tk:
            h["Authorization"] = "Bearer " + tk
        req = urllib.request.Request(self.base + "/anonymize", data=json.dumps(body).encode("utf-8"), headers=h)
        t = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                code, data = r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                data = json.loads(e.read().decode("utf-8"))
            except ValueError:
                data = {}
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            code, data = 0, {"error": type(e).__name__}
        dt = time.time() - t
        self.lotes.append((descr, len(records) if isinstance(records, list) else 0, dt))
        return code, data, dt


# ------------------------------------------------------------------ utilidades
def plano(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def volcar(x):
    return json.dumps(x, ensure_ascii=False)


def registro_salida(resp, rid):
    return next((r for r in resp.get("records", []) if r.get("id") == rid), None)


def entidad_de(resp, rid):
    return [e for e in resp.get("entities", []) if rid in e.get("records", []) and not e.get("kept")]


def nombres_de(resp, rid):
    return {e["pseudonyms"].get("name") for e in entidad_de(resp, rid) if e.get("pseudonyms", {}).get("name")}


def leer_lista(nombre):
    with open(os.path.join(RAIZ, "kipu", "data", nombre), encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]


def chat(texto, autor="Kipi", hilo=None):
    n = random.randint(100000, 999999)
    return {"id": str(uuid.uuid4()), "thread_id": hilo or "soporte-cobros:1790000000.%06d" % n,
            "author": autor, "ts": "1790000000.%06d" % n, "text": texto, "attachments": []}


def rellenar(registros, fillers):
    """Completa a LOTE registros con chats reales de fuentes/."""
    return registros + fillers[:max(LOTE - len(registros), 0)]


class Reporte:
    def __init__(self):
        self.casos = []   # (nombre, ok, detalles[(ok, texto)])

    def caso(self, nombre, checks):
        ok = all(c[0] for c in checks)
        self.casos.append((nombre, ok, checks))
        print("\n%s %s" % ("✓ PASA " if ok else "✗ FALLA", nombre))
        for okc, txt in checks:
            print("    %s %s" % ("✓" if okc else "✗", txt))
        return ok


# ------------------------------------------------------------------ datos de la clienta existente
def elegir_clienta(entidades, mujeres):
    fem = {plano(x.split()[0]).lower() for x in mujeres}
    with open(os.path.join(RAIZ, "kipu", "data", "genero_reales.json"), encoding="utf-8") as f:
        fem |= {k for k, v in json.load(f).items() if v == "f"}   # los nombres reales no están en los catálogos
    for e in entidades:
        ps = e.get("pseudonyms") or {}
        if e.get("kept") or not all(ps.get(k) for k in ("name", "cedula", "phone", "email")):
            continue
        if not any(r.startswith("clientes:") for r in e.get("records", [])):
            continue
        orig = e.get("originals", [])
        nombres = [o for o in orig if " " in o and not re.search(r"[\d@#]", o) and len(o.split()) >= 3]
        cedulas = [o for o in orig if re.fullmatch(r"\d{8,10}", o) and not o.startswith("3")]
        cels = [o for o in orig if re.fullmatch(r"3\d{9}", o)]
        mails = [o for o in orig if "@" in o]
        if not (nombres and cedulas and cels and mails):
            continue
        nombre = max(nombres, key=len)
        if plano(nombre.split()[0]).lower() not in fem or plano(nombre) == nombre:
            continue   # mujer y con alguna tilde (para probar la variante sin tildes)
        return {"e": e, "nombre": nombre, "cedula": cedulas[0], "celular": cels[0], "correo": mails[0],
                "ps": ps, "reales": [o for o in orig if len(o) >= 4]}
    return None


CIRILICO = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "A": "А", "E": "Е", "O": "О",
            "P": "Р", "C": "С", "X": "Х"}


def variantes_nombre(nombre):
    p = nombre.split()
    pila, resto = p[0], " ".join(p[1:])
    # una letra cambiada: la tercera letra del nombre de pila pasa a la siguiente del alfabeto
    i = min(2, len(pila) - 1)
    c = pila[i]
    cambiada = pila[:i] + (chr(ord(c) + 1) if c.isalpha() and c not in "zZ" else "x") + pila[i + 1:] + " " + resto
    cirilico = "".join(CIRILICO.get(ch, ch) for ch in nombre)
    invisibles = "\u200b".join(pila) + " " + "\u00ad".join(p[1]) + (" " + " ".join(p[2:]) if len(p) > 2 else "")
    invisibles2 = pila + "\u200d " + resto.replace(" ", "\u2060 ")
    return [
        ("exacto", nombre),
        ("sin tildes", plano(nombre)),
        ("MAYÚSCULAS", nombre.upper()),
        ("MAYÚSCULAS sin tildes", plano(nombre).upper()),
        ("una letra cambiada", cambiada),
        ("confusables cirílicos", cirilico),
        ("invisibles (ZWSP + soft hyphen)", invisibles),
        ("invisibles (ZWJ + word joiner)", invisibles2),
    ]


def agrupa(d, sep):
    return sep.join([d[:-9] or d[:1], d[-9:-6], d[-6:-3], d[-3:]]) if len(d) >= 9 else d


def variantes_cedula(c):
    return [("cédula con puntos", f"{c[:-6]}.{c[-6:-3]}.{c[-3:]}"),
            ("cédula con espacios", f"{c[:-6]} {c[-6:-3]} {c[-3:]}"),
            ("cédula con guiones", f"{c[:-6]}-{c[-6:-3]}-{c[-3:]}")]


def variantes_celular(c):
    return [("celular con espacios", f"{c[:3]} {c[3:6]} {c[6:]}"),
            ("celular con guiones", f"{c[:3]}-{c[3:6]}-{c[6:]}"),
            ("celular +57 con espacios", f"+57 {c[:3]} {c[3:6]} {c[6:]}"),
            ("celular 57 pegado", f"57{c}")]


# ------------------------------------------------------------------ casos
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehacer", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--data-dir", default="/tmp/kipu_envivo")
    a = ap.parse_args()
    random.seed(11)

    env = leer_env()
    token = env.get("TEAM_TOKEN") or os.environ.get("TEAM_TOKEN", "")
    env_hijo = dict(os.environ, **env, DATA_DIR=a.data_dir)
    srv = None
    try:
        preparar(a.data_dir, a.rehacer, env_hijo)
        base = a.url or "http://localhost:%d/v1" % PUERTO
        if not a.url:
            srv = levantar(a.data_dir, env_hijo)
            print("servicio arriba en %s (DATA_DIR=%s)" % (base, a.data_dir))
        api = Api(base, token)
        rep = Reporte()
        with open(os.path.join(a.data_dir, "output", "entities.json"), encoding="utf-8") as f:
            ents = json.load(f)["entities"]
        todos_seud = {e["pseudonyms"]["name"].lower() for e in ents if (e.get("pseudonyms") or {}).get("name")}
        mujeres, hombres = leer_lista("nombres_mujer.txt"), leer_lista("nombres_hombre.txt")
        cl = elegir_clienta(ents, mujeres)
        if not cl:
            raise SystemExit("no encontré una clienta con nombre, cédula, celular y correo en entities.json")
        ps = cl["ps"]

        # registros de relleno: chats reales de fuentes/ (sin tocar el servicio)
        sys.path.insert(0, RAIZ)
        from kipu import ingest
        from kipu.sources import LocalSource
        reales = ingest.ingest_chats(LocalSource(os.path.join(RAIZ, "fuentes")))
        random.shuffle(reales)
        relleno = [r for r in reales if r.get("text")][:LOTE]

        def fuga(salida_txt, formas):
            return [f for f in formas if f and (contiene(salida_txt, f) or f in salida_txt)]

        # ---- (1) mensaje nuevo que nombra a una clienta existente
        r1 = chat("Buenas, la señora %s dice que ya pagó la cuota de este mes. ¿Pueden revisar?" % cl["nombre"])
        code, resp, dt = api.post("chats", rellenar([r1], relleno), "caso 1: clienta existente")
        out = registro_salida(resp, r1["id"]) or {}
        txt = volcar(out)
        rep.caso("1. mensaje nuevo con una clienta que ya está en output/ → mismo seudónimo", [
            (code == 200, "HTTP %s" % code),
            (contiene(txt, ps["name"]), "aparece el seudónimo de entities.json (%s)" % ("sí" if contiene(txt, ps["name"]) else "no")),
            (not fuga(txt, [cl["nombre"]] + cl["nombre"].split()[:1]), "el nombre real no sale"),
            (ps["name"] in nombres_de(resp, r1["id"]), "la entidad devuelta lleva el mismo seudónimo"),
            (dt < LIMITE_S, "latencia del lote de %d: %.1f s (< %.0f s)" % (len(rellenar([r1], relleno)), dt, LIMITE_S)),
        ])

        # ---- (2) la misma clienta con el nombre alterado, cédula y celular con otros formatos
        regs, meta = [], []
        for etiqueta, v in variantes_nombre(cl["nombre"]):
            r = chat("Escribió %s para preguntar por su tarjeta." % v)
            regs.append(r)
            meta.append((etiqueta, r, v, "name"))
        for etiqueta, v in variantes_cedula(cl["cedula"]):
            r = chat("Mi cédula es %s, ayúdenme por favor." % v)
            regs.append(r)
            meta.append((etiqueta, r, v, "cedula"))
        for etiqueta, v in variantes_celular(cl["celular"]):
            r = chat("Pueden llamarme al %s en la tarde." % v)
            regs.append(r)
            meta.append((etiqueta, r, v, "phone"))
        lote = rellenar(regs, relleno)
        code, resp, dt = api.post("chats", lote, "caso 2: variantes de la clienta")
        checks = [(code == 200, "HTTP %s" % code), (dt < LIMITE_S, "latencia del lote de %d: %.1f s" % (len(lote), dt))]
        for etiqueta, r, v, campo in meta:
            out = registro_salida(resp, r["id"]) or {}
            txt = volcar(out)
            esperado = ps[campo]
            ok_seud = contiene(txt, esperado)
            reales_fuga = fuga(txt, [v] + ([cl["nombre"]] if campo == "name" else [cl[{"cedula": "cedula", "phone": "celular"}[campo]]]))
            checks.append((ok_seud and not reales_fuga,
                           "%s: %s%s" % (etiqueta, "mismo seudónimo" if ok_seud else "NO sale el seudónimo de la clienta",
                                         "" if not reales_fuga else " | FUGA del dato real")))
        rep.caso("2. misma clienta con el nombre/cédula/celular alterados → mismo seudónimo", checks)

        # ---- (3) persona nueva: seudónimo nuevo, único y del mismo género
        nuevos = [("mujer", "Anyelina Marcela Quintanilla Escandón", "52876431", "anyelina.quintanilla@gmail.com", mujeres),
                  ("hombre", "Wilmer Esneider Cotes Villadiego", "1052398741", "wcotes@outlook.com", hombres)]
        regs = [chat("Hola, soy %s, cédula %s y mi correo es %s. Quiero abrir una cuenta." % (n, c, m))
                for _, n, c, m, _ in nuevos]
        lote = rellenar(regs, relleno)
        code, resp, dt = api.post("chats", lote, "caso 3: personas nuevas")
        checks = [(code == 200, "HTTP %s" % code), (dt < LIMITE_S, "latencia del lote de %d: %.1f s" % (len(lote), dt))]
        vistos = {}
        for (gen, nom, ced, mail, cat), r in zip(nuevos, regs):
            txt = volcar(registro_salida(resp, r["id"]) or {})
            nm = nombres_de(resp, r["id"])
            seudo = next(iter(nm), "")
            vistos[gen] = seudo
            pila = plano(seudo.split()[0]).lower() if seudo else ""
            mismo = pila in {plano(x.split()[0]).lower() for x in cat}
            checks += [
                (bool(seudo) and not fuga(txt, [nom, ced, mail]), "%s: el nombre, cédula y correo reales no salen" % gen),
                (bool(seudo) and seudo.lower() not in todos_seud, "%s: seudónimo nuevo y único (%s)" % (gen, "no choca con ninguno de entities.json" if seudo else "sin seudónimo")),
                (mismo, "%s: mismo género (nombre de pila del catálogo %s)" % (gen, gen)),
            ]
        # el mismo registro en otro lote conserva su seudónimo
        code2, resp2, dt2 = api.post("chats", rellenar([regs[0]], relleno), "caso 3b: repetir persona nueva")
        checks.append((vistos["mujer"] in nombres_de(resp2, regs[0]["id"]), "repetir la persona nueva en otro lote da el mismo seudónimo"))
        checks.append((dt2 < LIMITE_S, "latencia del segundo lote: %.1f s" % dt2))
        rep.caso("3. persona nueva → seudónimo nuevo, único y del mismo género", checks)

        # ---- (4) dos personas nuevas con el mismo nombre y evidencia distinta
        r_a = chat("Soy Yuranis Patiño Lemus, cédula 1012345678, correo ypatino@gmail.com. Necesito un paz y salvo.")
        r_b = chat("Soy Yuranis Patiño Lemus, cédula 1098765432, correo yuranis.patino@hotmail.com. Quiero cerrar mi cuenta.")
        lote = rellenar([r_a, r_b], relleno)
        code, resp, dt = api.post("chats", lote, "caso 4: homónimos")
        na, nb = nombres_de(resp, r_a["id"]), nombres_de(resp, r_b["id"])
        ta, tb = volcar(registro_salida(resp, r_a["id"]) or {}), volcar(registro_salida(resp, r_b["id"]) or {})
        rep.caso("4. dos personas nuevas con el mismo nombre y cédulas distintas → dos seudónimos", [
            (code == 200, "HTTP %s" % code),
            (bool(na) and bool(nb) and na.isdisjoint(nb), "seudónimos distintos (%s)" % ("sí" if na and nb and na.isdisjoint(nb) else "NO: %s / %s" % (sorted(na), sorted(nb)))),
            (not fuga(ta + tb, ["Yuranis Patiño Lemus", "1012345678", "1098765432"]), "ningún dato real sale"),
            (dt < LIMITE_S, "latencia del lote de %d: %.1f s" % (len(lote), dt)),
        ])

        # ---- (5) canarios de inyección
        ruta = os.path.join(AQUI, "inyecciones.jsonl")
        if not os.path.exists(ruta):
            subprocess.run([sys.executable, os.path.join(AQUI, "gen_inyecciones.py"), "--input", os.path.join(RAIZ, "fuentes"),
                            "--out", ruta], cwd=RAIZ, check=False, capture_output=True)
        checks = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                canarios = [json.loads(l) for l in f if l.strip()]
            for c in canarios:
                code, resp, dt = api.post(c["source"], c["records"], "caso 5: " + c["id"])
                txt = volcar(resp.get("records", []))
                f_ = fuga(txt, c["forbidden"])
                checks.append((code == 200 and not f_ and dt < LIMITE_S,
                               "%s %s: %s, %.1f s%s" % (c["id"], c["mechanism"], "HTTP %s" % code, dt, " | FUGA" if f_ else "")))
        else:
            checks.append((False, "no hay evals/inyecciones.jsonl ni se pudo generar"))
        rep.caso("5. canarios de inyección → el nombre real nunca sale (%d)" % len(checks), checks)

        # ---- (6) docs y tables, no solo chats
        doc = {"id": str(uuid.uuid4()), "format": "md", "filename": "nota_en_vivo.md", "title": "Nota de seguimiento",
               "body": "# Seguimiento\n\nLa clienta %s (cédula %s, celular %s) pidió revisión.\n\nTambién contactó %s, cédula 52876431, "
                       "correo anyelina.quintanilla@gmail.com.\n" % (cl["nombre"], cl["cedula"], cl["celular"], "Anyelina Marcela Quintanilla Escandón"),
               "metadata": {"author": "Kipi", "title": "Nota de seguimiento"}}
        code, resp, dt = api.post("docs", [doc], "caso 6a: doc")
        out = registro_salida(resp, doc["id"]) or {}
        txt = volcar(out)
        checks = [
            (code == 200, "docs: HTTP %s, %.1f s" % (code, dt)),
            (contiene(txt, ps["name"]) and contiene(txt, ps["cedula"]) and contiene(txt, ps["phone"]),
             "docs: la clienta sale con su seudónimo, cédula y celular de entities.json"),
            (not fuga(txt, [cl["nombre"], cl["cedula"], cl["celular"], "Anyelina Marcela Quintanilla Escandón", "52876431"]), "docs: ningún dato real sale"),
            (dt < LIMITE_S, "docs: latencia %.1f s" % dt),
        ]
        fila = {"id": "clientes:CL-ENVIVO1", "table": "clientes", "columns": {
            "cliente_id": "CL-ENVIVO1", "nombre_completo": cl["nombre"], "tipo_doc": "CC", "num_doc": cl["cedula"],
            "correo": cl["correo"], "celular": cl["celular"], "ciudad": "Cali", "barrio": "Granada",
            "direccion": "Calle 10 # 20-30", "fecha_nacimiento": "1990-05-05", "fecha_vinculacion": "2024-01-10",
            "ocupacion": "fotógrafa", "notas": "Sin novedades."}}
        fila2 = {"id": "clientes:CL-ENVIVO2", "table": "clientes", "columns": {
            "cliente_id": "CL-ENVIVO2", "nombre_completo": "Wilmer Esneider Cotes Villadiego", "tipo_doc": "CC",
            "num_doc": "1052398741", "correo": "wcotes@outlook.com", "celular": "3017778899", "ciudad": "Cali",
            "barrio": "Granada", "direccion": "Cra 5 # 10-20", "fecha_nacimiento": "1988-03-03",
            "fecha_vinculacion": "2025-02-02", "ocupacion": "mecánico", "notas": ""}}
        code, resp, dt = api.post("tables", [fila, fila2], "caso 6b: tables")
        o1 = (registro_salida(resp, fila["id"]) or {}).get("columns", {})
        o2 = (registro_salida(resp, fila2["id"]) or {}).get("columns", {})
        checks += [
            (code == 200, "tables: HTTP %s, %.1f s" % (code, dt)),
            (contiene(o1.get("nombre_completo", ""), ps["name"]) and contiene(o1.get("num_doc", ""), ps["cedula"])
             and contiene(o1.get("celular", ""), ps["phone"]) and o1.get("correo", "").lower() == ps["email"].lower(),
             "tables: la fila de la clienta lleva su seudónimo, cédula, celular y correo de entities.json"),
            (o1.get("cliente_id") == "CL-ENVIVO1" and o1.get("ciudad") == "Cali", "tables: cliente_id y ciudad intactos"),
            (o1.get("ocupacion", "x") != "fotógrafa" and o2.get("ocupacion", "x") != "mecánico", "tables: la ocupación sale como sector"),
            (not fuga(volcar([o1, o2]), [cl["nombre"], cl["cedula"], cl["celular"], cl["correo"],
                                          "Wilmer Esneider Cotes Villadiego", "1052398741", "wcotes@outlook.com"]),
             "tables: ningún dato real sale"),
            (bool(o2.get("nombre_completo")) and not contiene(o2["nombre_completo"], "Wilmer Esneider Cotes Villadiego")
             and o2["nombre_completo"].lower() not in todos_seud, "tables: la persona nueva recibe un seudónimo nuevo (nombre_completo cambia y es único)"),
            (not contiene(o1.get("nombre_completo", ""), cl["nombre"]), "tables: nombre_completo de la clienta ya no es el real"),
            (dt < LIMITE_S, "tables: latencia %.1f s" % dt),
        ]
        rep.caso("6. registros de docs y tables, no solo chats", checks)

        # ---- (7) fuera de esquema y autenticación
        checks = []
        malo_chat = {"id": str(uuid.uuid4()), "thread_id": "x:1", "author": "a", "ts": "1"}   # sin text
        malo_doc = {"id": str(uuid.uuid4()), "format": "md", "filename": "a.md", "title": "t", "body": "b", "metadata": "no es dict"}
        malo_tab = {"id": "t:1", "table": "t", "columns": {"a": 5}}
        for etiqueta, src, regs in (("chat sin text", "chats", [malo_chat]), ("doc con metadata no-dict", "docs", [malo_doc]),
                                    ("tabla con valor no-string", "tables", [malo_tab]), ("source inválido", "videos", [chat("hola")]),
                                    ("51 registros", "chats", [chat("hola %d" % i) for i in range(51)])):
            code, _, dt = api.post(src, regs, "caso 7: " + etiqueta)
            checks.append((code == 422, "%s → HTTP %s (esperado 422)" % (etiqueta, code)))
        code, _, _ = api.post("chats", [chat("hola")], "caso 7: sin token", token=None)
        checks.append((code == 401, "sin Authorization → HTTP %s (esperado 401)" % code))
        code, _, _ = api.post("chats", [chat("hola")], "caso 7: token malo", token="token-incorrecto")
        checks.append((code == 401, "token incorrecto → HTTP %s (esperado 401)" % code))
        rep.caso("7. registro fuera de esquema → 422; sin token → 401", checks)

        # ---- resumen
        print("\n=== latencia por lote (límite %.0f s) ===" % LIMITE_S)
        peor = 0.0
        for descr, n, dt in api.lotes:
            peor = max(peor, dt)
            print("  %-46s %3d reg  %6.2f s  %s" % (descr[:46], n, dt, "" if dt < LIMITE_S else "<-- LENTO"))
        print("\n=== resumen ===")
        for nombre, ok, _ in rep.casos:
            print("  %s %s" % ("PASA " if ok else "FALLA", nombre))
        malos = [c for c in rep.casos if not c[1]]
        print("\n%d/%d casos pasan; peor latencia %.1f s" % (len(rep.casos) - len(malos), len(rep.casos), peor))
        return 1 if malos or peor >= LIMITE_S else 0
    finally:
        apagar(srv)


if __name__ == "__main__":
    sys.exit(main())
