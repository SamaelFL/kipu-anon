import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from kipu import cuasi, verifica  # noqa: E402
from kipu.modelo import Entidad  # noqa: E402
from kipu.pseudo import Pseudonimizador  # noqa: E402


def pseudo():
    return Pseudonimizador("t", Path(tempfile.mkdtemp()) / "s.json")


def cliente(cid, ciudad, barrio, ocu, vinc, nac="1990-01-01", notas=""):
    return {"id": f"clientes:{cid}", "table": "clientes",
            "columns": {"cliente_id": cid, "nombre_completo": "X Y", "ciudad": ciudad, "barrio": barrio,
                        "ocupacion": ocu, "fecha_vinculacion": f"{vinc}-05-01", "fecha_nacimiento": nac, "notas": notas}}


def chat(i, texto, hilo="t"):
    return {"id": i, "thread_id": hilo, "author": "a", "ts": "1", "text": texto, "attachments": []}


def maestro_base():
    m = [cliente("CL-1", "Bucaramanga", "Cabecera", "arquitecto", 2021),
         cliente("CL-2", "Bogotá", "Chapinero", "arquitecto", 2022),
         cliente("CL-3", "Bogotá", "Chapinero", "arquitecta", 2020),
         cliente("CL-4", "Pereira", "Centro", "contadora", 2023),
         cliente("CL-5", "Medellín", "Castilla", "administrador", 2020),
         cliente("CL-6", "Cali", "Granada", "fotógrafa", 2025),
         cliente("CL-7", "Cali", "El Peñón", "mecánico", 2019)]
    return m


class Muestra(unittest.TestCase):
    """Casos de sample/ (la carpeta no se versiona: se omite si falta)."""

    def test_sample(self):
        base = RAIZ / "sample"
        if not (base / "input").exists():
            self.skipTest("sin sample/")
        from kipu import ingest
        from kipu.sources import LocalSource
        src = LocalSource(str(base / "input"))
        recs = ingest.ingest_chats(src) + ingest.ingest_docs(src) + ingest.ingest_tables(src)
        esperado = {}
        for f in ("chats", "docs", "tables"):
            with open(base / "expected_output" / f"{f}.jsonl", encoding="utf-8") as fh:
                for l in fh:
                    r = json.loads(l)
                    esperado[r["id"]] = r
        with open(base / "expected_output" / "entities.json", encoding="utf-8") as fh:
            ents = {e["entity_id"]: e for e in json.load(fh)["entities"]}
        orig = originales(base)
        barrios = {}
        for ciudad, barrio in orig.values():
            barrios.setdefault(ciudad, set()).add(barrio)
        P = Entidad("p_057", "cl:CL-88627", genero="f",
                    atributos={"ciudad": "Cali", "barrio": "Granada", "ocupacion": "fotógrafa", "anio_vinculacion": 2025},
                    records=set(ents["p_057"]["records"]))
        recs, cambios = cuasi.aplicar(recs, [P], pseudo())
        por_id = {r["id"]: r for r in recs}
        # ocupación de los tres clientes
        for rid, r in por_id.items():
            if r.get("table") == "clientes":
                self.assertEqual(r["columns"]["ocupacion"], esperado[rid]["columns"]["ocupacion"])
                self.assertEqual(r["columns"]["ciudad"], esperado[rid]["columns"]["ciudad"])
                self.assertEqual(r["columns"]["cliente_id"], esperado[rid]["columns"]["cliente_id"])
                self.assertEqual(r["columns"]["fecha_vinculacion"], esperado[rid]["columns"]["fecha_vinculacion"])
                ciudad, barrio = orig[rid.split(":")[1]]
                self.assertIn(r["columns"]["barrio"], barrios[ciudad])  # misma ciudad, sacado del maestro
                if len(barrios[ciudad]) > 1:
                    self.assertNotEqual(r["columns"]["barrio"], barrio)
        # el mensaje de la fotógrafa
        mid = "4e704abc-9da7-5ce6-8744-80fa0d699110"
        self.assertEqual(por_id[mid]["text"], esperado[mid]["text"])
        self.assertIn("profesional de las industrias creativas", por_id[mid]["text"])
        self.assertIn("Cali", por_id[mid]["text"])
        self.assertIn("hace unos años", por_id[mid]["text"])
        self.assertTrue(any(c["tipo"] == "anio" for c in cambios))


def originales(base):
    import csv
    import io
    with open(base / "input" / "tables" / "clientes.csv", encoding="latin-1") as f:
        return {row["cliente_id"]: (row["ciudad"], row["barrio"])
                for row in csv.DictReader(io.StringIO(f.read()), delimiter=";")}


class Maestro(unittest.TestCase):
    def test_ocupacion_y_barrio_en_clientes(self):
        recs = maestro_base()
        recs, cambios = cuasi.aplicar(recs, [], pseudo())
        c = {r["columns"]["cliente_id"]: r["columns"] for r in recs}
        self.assertEqual(c["CL-6"]["ocupacion"], "profesional de las industrias creativas")
        self.assertEqual(c["CL-7"]["ocupacion"], "profesional del transporte")
        self.assertEqual(c["CL-5"]["ocupacion"], "profesional de servicios")
        self.assertEqual(c["CL-6"]["barrio"], "El Peñón")  # único otro barrio de Cali en el maestro
        self.assertEqual(c["CL-7"]["barrio"], "Granada")
        self.assertEqual(c["CL-2"]["barrio"], "Chapinero")  # Bogotá solo tiene un barrio: no hay otro
        self.assertEqual(c["CL-6"]["ciudad"], "Cali")
        self.assertEqual(c["CL-6"]["fecha_vinculacion"], "2025-05-01")
        self.assertTrue(any(x["campo"] == "columns.ocupacion" for x in cambios))

    def test_barrio_de_la_misma_ciudad(self):
        recs = [cliente(f"CL-{i}", "Cali", b, "chef", 2020) for i, b in enumerate(["A", "B", "C", "D"])]
        antes = {r["columns"]["cliente_id"]: r["columns"]["barrio"] for r in recs}
        cuasi.aplicar(recs, [], pseudo())
        for r in recs:
            self.assertIn(r["columns"]["barrio"], "ABCD")
            self.assertNotEqual(r["columns"]["barrio"], antes[r["columns"]["cliente_id"]])


class TextoDePersona(unittest.TestCase):
    def ent(self, **kw):
        a = {"ciudad": "Cali", "barrio": "Granada", "ocupacion": "fotógrafa", "anio_vinculacion": 2025}
        a.update(kw)
        return Entidad("p_1", "cl:CL-6", atributos=a, records={"m1"})

    def test_oficio_barrio_anio(self):
        r = [chat("m1", "Soy fotógrafo, vivo en Granada y entré en 2025. Pagué 2025 pesos en Granada Hills.")]
        cuasi.aplicar(maestro_base() + r, [self.ent()], pseudo())
        t = r[0]["text"]
        self.assertIn("Soy profesional de las industrias creativas, vivo en Cali y entré en hace unos años.", t)
        self.assertIn("Pagué 2025 pesos", t)  # un año que no habla de la vinculación no se toca

    def test_variantes_de_genero(self):
        for forma in ("fotógrafa", "fotógrafo", "Fotógrafa", "fotografa"):
            r = [chat("m1", f"{forma} de profesión")]
            cuasi.aplicar(maestro_base() + r, [self.ent()], pseudo())
            self.assertIn("rofesional de las industrias creativas", r[0]["text"], forma)

    def test_cliente_desde(self):
        r = [chat("m1", "Es cliente desde 2025 y nunca ha fallado.")]
        cuasi.aplicar(maestro_base() + r, [self.ent()], pseudo())
        self.assertEqual(r[0]["text"], "Es cliente desde hace unos años y nunca ha fallado.")

    def test_solo_registros_de_la_persona(self):
        r = [chat("otro", "Un fotógrafo en Granada entró en 2025")]
        # sin P.records ni tupla (el chat de otro registro tiene oficio+barrio y apunta a <5 clientes, así que
        # lo generaliza la regla de tuplas, no la de la persona)
        _, cambios = cuasi.aplicar(maestro_base() + r, [self.ent()], pseudo())
        self.assertTrue(all(c.get("entity_id") is None for c in cambios if c["record_id"] == "otro"))

    def test_otros_anios_montos_y_lugares_intactos(self):
        r = [chat("m1", "Pagó $2.025.000 el 2025-08-21 en Medellín; la factura 2025 de Bancolombia.")]
        cuasi.aplicar(maestro_base() + r, [self.ent()], pseudo())
        self.assertEqual(r[0]["text"], "Pagó $2.025.000 el 2025-08-21 en Medellín; la factura 2025 de Bancolombia.")


class TuplasSinNombre(unittest.TestCase):
    def correr(self, texto, maestro=None):
        r = [chat("x1", texto)]
        _, cambios = cuasi.aplicar((maestro or maestro_base()) + r, [], pseudo())
        return r[0]["text"], cambios

    def test_oficio_ciudad_anio(self):
        t, cambios = self.correr("Cliente de Bucaramanga, arquitecto, vinculado desde 2021")
        self.assertEqual(t, "Cliente de Bucaramanga, profesional de la construcción, vinculado desde hace unos años")
        self.assertTrue(all(c["k"] < 5 for c in cambios if c["record_id"] == "x1"))

    def test_oficio_barrio(self):
        t, _ = self.correr("Ahí hay alguien que es arquitecto, vive en Chapinero.")
        self.assertEqual(t, "Ahí hay alguien que es profesional de la construcción, vive en Bogotá.")

    def test_contadora_vinculada(self):
        t, _ = self.correr("una contadora de Pereira, vinculada en 2023, que nunca se ha atrasado")
        self.assertEqual(t, "una profesional de servicios de Pereira, vinculada en hace unos años, que nunca se ha atrasado")

    def test_administrador_barrio_anio(self):
        t, _ = self.correr("el afectado es administrador, vive en Castilla y es cliente desde 2020")
        self.assertEqual(t, "el afectado es profesional de servicios, vive en Medellín y es cliente desde hace unos años")

    def test_no_generaliza_si_hay_k_o_mas(self):
        m = maestro_base() + [cliente(f"CL-9{i}", "Bogotá", "Chapinero", "arquitecto", 2022) for i in range(6)]
        t, _ = self.correr("es arquitecto, vive en Chapinero", m)
        self.assertEqual(t, "es arquitecto, vive en Chapinero")

    def test_sin_tupla_no_toca(self):
        for s in ("Mi hermano es arquitecto.", "Vivo en Chapinero.", "Cliente de Bucaramanga desde 2021",
                  "Bucaramanga, 2021, vinculado"):
            t, _ = self.correr(s)
            self.assertEqual(t, s, s)


class Verifica(unittest.TestCase):
    def persona(self):
        return Entidad("p_9", "cl:CL-1", nombre="Manuela Castaño Ruiz",
                       ids={"cedula": "1107360039", "correos": ["mcastano@gmail.com"], "cliente_id": "CL-1"},
                       formas={"Manuela Castaño", "manuela_castano"},
                       atributos={"ciudad": "Cali", "barrio": "Granada", "ocupacion": "fotógrafa",
                                  "anio_vinculacion": 2025, "pseudonimos": {"name": "Sofía Zambrano"}},
                       records={"a", "b"})

    def test_limpio(self):
        out = [chat("a", "Hola Sofía Zambrano"), chat("b", "ok")]
        rep = verifica.verificar(out, [self.persona()], maestro=[])
        self.assertTrue(rep["ok"], rep)

    def test_barrido_valores_y_claves(self):
        out = [chat("a", "Hola Sofía Zambrano, cédula 1.107.360.039"), chat("b", "ok"),
               {"id": "c", "columns": {"manuela_castano": "x"}}]
        rep = verifica.verificar(out, [self.persona()], maestro=[])
        donde = {(f["forma"], f["donde"]) for f in rep["fugas"]}
        self.assertIn(("1107360039", "valor"), donde)
        self.assertIn(("manuela_castano", "clave"), donde)
        self.assertFalse(rep["ok"])
        self.assertTrue(rep["segunda_pasada"])

    def test_declaraciones(self):
        out = [chat("a", "Hola Manuela Castaño"), chat("b", "ok")]
        rep = verifica.verificar(out, [self.persona()], maestro=[])
        reglas = {d["regla"] for d in rep["declaraciones"]}
        self.assertEqual(reglas, {"seudonimo_ausente", "original_persiste"})

    def test_conservadas_no_cuentan(self):
        kept = Entidad("kept_1", "kp", tipo="organization_or_place", kept=True, formas={"Plaza Botero", "Botero"})
        p = self.persona()
        p.formas = {"Botero Ruiz", "Manuela Castaño"}
        out = [chat("a", "Nos vemos en Plaza Botero. Sofía Zambrano"), chat("b", "ok")]
        rep = verifica.verificar(out, [p, kept], maestro=[])
        self.assertEqual([f for f in rep["fugas"] if f["forma"] == "Botero Ruiz"], [])

    def test_ataque_de_enlace(self):
        maestro = cuasi.maestro_de(maestro_base(), [])
        # salida sin tocar: ciudad+barrio+oficio+año identifican a todos
        sin = verifica.verificar(maestro_base(), [], maestro=maestro)
        self.assertEqual(len(sin["enlace"]["reidentificados"]), len(maestro))
        # salida con cuasi.aplicar: nadie se reidentifica
        recs = maestro_base()
        cuasi.aplicar(recs, [], pseudo())
        con = verifica.verificar(recs, [], maestro=maestro)
        self.assertEqual(con["enlace"]["reidentificados"], [])

    def test_tuplas_que_sobreviven(self):
        maestro = cuasi.maestro_de(maestro_base(), [])
        rep = verifica.verificar([chat("z", "es arquitecto, vive en Chapinero")], [], maestro=maestro)
        self.assertEqual(len(rep["enlace"]["tuplas_en_texto"]), 1)


class SoloTextoLibre(unittest.TestCase):
    def test_transaccion_intacta(self):
        tx = {"id": "transacciones:TX-1", "table": "transacciones",
              "columns": {"tx_id": "TX-1", "descripcion": "Compra D1 Castilla", "monto": "5000"}}
        pq = {"id": "pqrs:1", "table": "pqrs", "columns": {"radicado": "PQR-1", "ciudad": "Medellín",
              "descripcion": "Soy administrador, vivo en Castilla y soy cliente desde 2020.",
              "respuesta": "Gracias por escribir"}}
        e = Entidad("p_5", "cl:CL-5", atributos={"ciudad": "Medellín", "barrio": "Castilla",
                                                 "ocupacion": "administrador", "anio_vinculacion": 2020},
                    records={"transacciones:TX-1", "pqrs:1"})
        recs = maestro_base() + [tx, pq]
        cuasi.aplicar(recs, [e], pseudo())
        self.assertEqual(tx["columns"]["descripcion"], "Compra D1 Castilla")
        self.assertEqual(pq["columns"]["descripcion"],
                         "Soy profesional de servicios, vivo en Medellín y soy cliente desde hace unos años.")

    def test_campos_libres(self):
        c = chat("c1", "x")
        d = {"id": "d1", "format": "md", "filename": "a.md", "title": "t", "body": "b", "metadata": {"x": "y"}}
        tx = {"id": "t", "table": "transacciones", "columns": {"descripcion": "Compra"}}
        cl = cliente("CL-1", "Cali", "Granada", "chef", 2020, notas="n")
        self.assertEqual([x[2] for x in cuasi.campos_libres(c)], ["text"])
        self.assertEqual([x[2] for x in cuasi.campos_libres(d)], ["body", "title"])
        self.assertEqual(list(cuasi.campos_libres(tx)), [])
        self.assertEqual([x[2] for x in cuasi.campos_libres(cl)], ["columns.notas"])

    def test_notas_de_clientes_si(self):
        m = maestro_base()
        m[5]["columns"]["notas"] = "Es fotógrafa y vive en Granada"
        cuasi.aplicar(m, [], pseudo())
        self.assertEqual(m[5]["columns"]["notas"], "Es profesional de las industrias creativas y vive en Cali")


class TuplaSinBarrio(unittest.TestCase):
    def test_caso_real_contadora_barranquilla_2024(self):
        m = maestro_base() + [cliente("CL-20", "Barranquilla", "Riomar", "contadora", 2024)]
        t = ("Hablé con la afectada (la de Barranquilla). Es contadora, lleva con nosotros desde 2024, y está más "
             "molesta por el tono del correo que por el dato. Le ofrecí 6 meses sin cuota de manejo.")
        r = [chat("80e0b943-4ec1-571c-a4cf-14ab90b15605", t)]
        _, cambios = cuasi.aplicar(m + r, [], pseudo())
        self.assertEqual(r[0]["text"], t.replace("Es contadora", "Es profesional de servicios")
                         .replace("desde 2024", "desde hace unos años"))
        self.assertIn("Barranquilla", r[0]["text"])  # la ciudad se conserva
        self.assertIn("6 meses", r[0]["text"])
        self.assertTrue(all(c["k"] < 5 for c in cambios if c["record_id"].startswith("80e0")))

    def test_misma_frase_sin_barrio(self):
        m = maestro_base() + [cliente("CL-20", "Barranquilla", "Riomar", "contadora", 2024)]
        r = [chat("x", "una contadora de Barranquilla, vinculada en 2024, siempre paga")]
        cuasi.aplicar(m + r, [], pseudo())
        self.assertEqual(r[0]["text"], "una profesional de servicios de Barranquilla, vinculada en hace unos años, siempre paga")

    def test_fuentes_reales(self):
        base = RAIZ / "fuentes"
        if not base.exists():
            self.skipTest("sin fuentes/")
        from kipu import ingest
        from kipu.sources import LocalSource
        src = LocalSource(str(base))
        recs = ingest.ingest_chats(src) + ingest.ingest_docs(src) + ingest.ingest_tables(src)
        antes = {r["id"]: json.dumps(r, ensure_ascii=False) for r in recs if r.get("table") == "transacciones"}
        cuasi.aplicar(recs, [], pseudo())
        por = {r["id"]: r for r in recs}
        t = por["80e0b943-4ec1-571c-a4cf-14ab90b15605"]["text"]
        self.assertIn("profesional de servicios", t)
        self.assertNotIn("2024", t)
        self.assertIn("Barranquilla", t)
        for rid, original in antes.items():
            self.assertEqual(json.dumps(por[rid], ensure_ascii=False), original)


def empleado(eid, cargo, ciudad, ingreso):
    return {"id": f"empleados:{eid}", "table": "empleados",
            "columns": {"id": eid, "cargo": cargo, "ciudad": ciudad, "ingreso": str(ingreso), "nombre": "N N"}}


def doc(i, body):
    return {"id": i, "format": "md", "filename": i + ".md", "title": "t", "body": body, "metadata": {}}


class FormasDelOficioBarrioYAnio(unittest.TestCase):
    """Giros del texto real: "soy contador", "trabajo como fotógrafa", "de profesión arquitecto", barrio con
    preposiciones y años como "desde 2021", "en el 2024", "hace dos años, en 2024"."""

    def correr(self, texto, extra=()):
        m = maestro_base() + list(extra)
        r = [chat("z1", texto)]
        cuasi.aplicar(m + r, [], pseudo())
        return r[0]["text"]

    def test_soy_y_vivo_en(self):
        self.assertEqual(self.correr("Soy arquitecto y vivo en Chapinero."),
                         "Soy profesional de la construcción y vivo en Bogotá.")

    def test_trabajo_como(self):
        self.assertEqual(self.correr("Trabajo como fotógrafa por los lados de Granada."),
                         "Trabajo como profesional de las industrias creativas por los lados de Cali.")

    def test_de_profesion(self):
        self.assertEqual(self.correr("De profesión arquitecto, vivo en Chapinero"),
                         "De profesión profesional de la construcción, vivo en Bogotá")

    def test_anio_en_el(self):
        m = [cliente("CL-30", "Cali", "Granada", "fotógrafa", 2024)]
        t = self.correr("Soy fotógrafa de Cali y me vinculé en el 2024", m)
        self.assertEqual(t, "Soy profesional de las industrias creativas de Cali y me vinculé hace unos años")

    def test_hace_dos_anios_en(self):
        m = [cliente("CL-30", "Cali", "Granada", "fotógrafa", 2024)]
        t = self.correr("Soy fotógrafa de Cali, cliente hace dos años, en 2024, y paso por Granada", m)
        self.assertNotIn("2024", t)
        self.assertNotIn("fotógrafa", t)
        self.assertIn("hace unos años", t)

    def test_desde_el(self):
        m = [cliente("CL-30", "Cali", "Granada", "fotógrafa", 2024)]
        t = self.correr("Es fotógrafa de Cali, cliente desde el 2024", m)
        self.assertEqual(t, "Es profesional de las industrias creativas de Cali, cliente desde hace unos años")

    def test_cliente_nuestro_desde_caso_doc_08(self):
        m = [cliente("CL-13198", "Medellín", "Itagüí", "chef", 2021)]
        r = [doc("doc_08", "## Cuenta destino\n\nTitular: chef de Medellín, cliente nuestro desde 2021. Niega conocer al afectado.")]
        cuasi.aplicar(maestro_base() + m + r, [], pseudo())
        self.assertEqual(r[0]["body"], "## Cuenta destino\n\nTitular: profesional de las industrias creativas de Medellín, "
                                       "cliente nuestro desde hace unos años. Niega conocer al afectado.")

    def test_barrio_ambiguo_usa_la_ciudad_del_cliente(self):
        m = [cliente("CL-A", "Medellín", "Castilla", "administrador", 2020),
             cliente("CL-B", "Bogotá", "Castilla", "contador", 2022)]
        t = self.correr("Para que dimensionen: el afectado es administrador, vive en Castilla y es cliente desde 2020.", m)
        self.assertEqual(t, "Para que dimensionen: el afectado es profesional de servicios, vive en Medellín y es cliente desde hace unos años.")


class TuplasEnElMismoHilo(unittest.TestCase):
    def hilo(self, textos, hilo="h1"):
        return [chat("m%d" % i, t, hilo=hilo) for i, t in enumerate(textos)]

    def test_oficio_y_barrio_en_mensajes_distintos(self):
        r = self.hilo(["Hola, necesito ayuda con mi cuenta.", "Soy arquitecto, por cierto.",
                       "Y vivo por los lados de Chapinero."])
        cuasi.aplicar(maestro_base() + r, [], pseudo())
        self.assertEqual(r[1]["text"], "Soy profesional de la construcción, por cierto.")
        self.assertEqual(r[2]["text"], "Y vivo por los lados de Bogotá.")
        self.assertEqual(r[0]["text"], "Hola, necesito ayuda con mi cuenta.")

    def test_oficio_barrio_y_anio_en_tres_mensajes(self):
        r = self.hilo(["Soy contadora.", "Estoy en Centro, Pereira.", "Y llevo con ustedes desde 2023."])
        cuasi.aplicar(maestro_base() + r, [], pseudo())
        self.assertEqual(r[0]["text"], "Soy profesional de servicios.")
        self.assertEqual(r[2]["text"], "Y llevo con ustedes desde hace unos años.")
        self.assertIn("Pereira", r[1]["text"])
        self.assertNotIn("Centro", r[1]["text"].replace("Pereira", ""))

    def test_hilos_distintos_no_se_mezclan(self):
        a = self.hilo(["Soy arquitecto, gracias."], hilo="h1")
        b = [chat("otro", "Vivo en Chapinero.", hilo="h2")]
        cuasi.aplicar(maestro_base() + a + b, [], pseudo())
        self.assertEqual(a[0]["text"], "Soy arquitecto, gracias.")
        self.assertEqual(b[0]["text"], "Vivo en Chapinero.")

    def test_combinacion_que_no_existe_no_se_toca(self):
        # arquitecto + Granada no existe en el maestro: en mensajes distintos no se generaliza
        r = self.hilo(["Soy arquitecto, gracias.", "Mi hermana vive en Granada."])
        cuasi.aplicar(maestro_base() + r, [], pseudo())
        self.assertEqual(r[0]["text"], "Soy arquitecto, gracias.")
        self.assertEqual(r[1]["text"], "Mi hermana vive en Granada.")


class TuplasDeEmpleados(unittest.TestCase):
    def test_doc_25_cargo_barrio_anio(self):
        m = maestro_base() + [cliente("CL-X", "Barranquilla", "El Prado", "chef", 2020),
                              empleado("KP-020", "Agente de Soporte", "Barranquilla", 2024),
                              empleado("KP-012", "Agente de Soporte", "Cali", 2024),
                              empleado("KP-023", "Agente de Soporte", "Medellín", 2024)]
        d = doc("doc_25", "Hoy aplica a una agente de soporte en Barranquilla, con nosotros desde 2024; "
                          "su lugar de trabajo registrado es su casa en El Prado.")
        cuasi.aplicar(m + [d], [], pseudo())
        self.assertEqual(d["body"], "Hoy aplica a una agente de soporte en Barranquilla, con nosotros desde hace unos años; "
                                    "su lugar de trabajo registrado es su casa en Barranquilla.")

    def test_evaluacion_con_ingreso_y_vive_en(self):
        m = maestro_base() + [empleado("KP-022", "Agente de Soporte", "Cali", 2025),
                              empleado("KP-021", "Agente de Soporte", "Bogotá", 2025)]
        d = doc("doc_15", "Cargo: Agente de Soporte\nIngreso: 2025\nComo vive en Granada, a diez minutos del coworking de Cali, apoya.")
        cuasi.aplicar(m + [d], [], pseudo())
        self.assertNotIn("Granada", d["body"])
        self.assertIn("Cali", d["body"])
        self.assertNotIn("2025", d["body"])

    def test_sin_empleados_no_hay_cambio(self):
        d = doc("d", "Una agente de soporte en Barranquilla, con nosotros desde 2024, vive en El Prado.")
        antes = d["body"]
        cuasi.aplicar(maestro_base() + [d], [], pseudo())
        self.assertEqual(d["body"], antes)


class CorridaRealIndirectas(unittest.TestCase):
    """Los casos que la corrida 1 dejó pasar, sobre fuentes/ reales."""

    def test_fuentes(self):
        base = RAIZ / "fuentes"
        if not base.exists():
            self.skipTest("sin fuentes/")
        from kipu import ingest
        from kipu.sources import LocalSource
        src = LocalSource(str(base))
        recs = ingest.ingest_chats(src) + ingest.ingest_docs(src) + ingest.ingest_tables(src)
        cuasi.aplicar(recs, [], pseudo())
        por = {r["id"]: r for r in recs}
        b8 = por["doc_08"]["body"]
        self.assertNotIn("chef de Medellín", b8)
        self.assertNotIn("cliente nuestro desde 2021", b8)
        self.assertIn("cliente nuestro desde hace unos años", b8)
        for rid, barrio in (("doc_12", "Itagüí"), ("doc_15", "Granada"), ("doc_25", "El Prado")):
            self.assertNotIn(barrio, por[rid]["body"], rid)
        self.assertNotIn("con nosotros desde 2024", por["doc_25"]["body"])
        self.assertIn("Vive en Medellín", por["doc_12"]["body"])
        self.assertIn("Barranquilla", por["doc_25"]["body"])
        t = por["56ff388c-7104-580c-b0d3-aff18b955d24"]["text"]
        self.assertNotIn("Castilla", t)
        self.assertNotIn("administrador", t)


if __name__ == "__main__":
    unittest.main()
