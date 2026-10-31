"""Pruebas del núcleo: coincidencia tolerante sobre la corrida completa y filas de tabla desconocidas."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["KIPU_SIN_LLM"] = "1"
from kipu import grafo, pipeline  # noqa: E402
from kipu.pseudo import Pseudonimizador  # noqa: E402


def cliente(cid, nombre, doc, correo, cel, ocupacion="fotógrafa", barrio="Granada"):
    return {"id": "clientes:" + cid, "table": "clientes", "columns": {
        "cliente_id": cid, "nombre_completo": nombre, "tipo_doc": "CC", "num_doc": doc, "correo": correo,
        "celular": cel, "ciudad": "Cali", "barrio": barrio, "direccion": "Calle 10 # 20-30",
        "fecha_nacimiento": "1990-05-05", "fecha_vinculacion": "2021-01-10", "ocupacion": ocupacion, "notas": ""}}


def empleado(kid, nombre, doc, correo, cel, reporta=""):
    return {"id": "empleados:" + kid, "table": "empleados", "columns": {
        "id": kid, "cargo": "Agente de Soporte", "ciudad": "Cali", "ingreso": "2022", "reporta_a": reporta,
        "nombre": nombre, "correo": correo, "celular": cel, "documento": doc, "documento_tipo": "CC",
        "fecha_nacimiento": "1985-02-02"}}


def chat(i, texto):
    return {"id": i, "thread_id": "c:1", "author": "Kipi", "ts": "1", "text": texto, "attachments": []}


def motor(filas):
    G = grafo.construir(filas, [])
    ps = Pseudonimizador("secreto-de-prueba", Path(tempfile.mkdtemp()) / "store.json")
    return pipeline.Motor(G, ps)


def texto_de(mo, t):
    return mo.anonimizar([chat("t", t)])[0][0]["text"]


class Tolerante(unittest.TestCase):
    def setUp(self):
        self.mo = motor([
            cliente("CL-1", "Camilo Arango Ruiz", "11111111", "camilo.arango@gmail.com", "3001110001"),
            cliente("CL-2", "Camila Arango Mejía", "22222222", "camila.arango@gmail.com", "3001110002"),
            cliente("CL-3", "Nauhalia Quintero López", "33333333", "nquintero@gmail.com", "3001110003"),
        ])

    def test_pila_con_una_letra_cambiada_se_reemplaza_con_el_seudonimo_de_la_persona(self):
        exacto = texto_de(self.mo, "Escribió Nauhalia Quintero López para preguntar.")
        alterado = texto_de(self.mo, "Escribió Nauhxlia Quintero López para preguntar.")
        self.assertNotIn("Nauhxlia", alterado)
        self.assertNotIn("Quintero", alterado)
        self.assertEqual(exacto, alterado)

    def test_la_exacta_gana_entre_nombres_que_distan_uno(self):
        o = texto_de(self.mo, "Hablé con Camilo Arango y con Camila Arango.")
        self.assertNotIn("Camilo", o)
        self.assertNotIn("Camila", o)
        solo_o = texto_de(self.mo, "Hablé con Camilo Arango.")
        solo_a = texto_de(self.mo, "Hablé con Camila Arango.")
        self.assertNotEqual(solo_o, solo_a)
        self.assertEqual(o, "Hablé con %s y con %s." % (solo_o[len("Hablé con "):-1], solo_a[len("Hablé con "):-1]))

    def test_dos_candidatos_a_distancia_uno_nunca_dejan_el_original(self):
        o = texto_de(self.mo, "Escribió Camilx Arango para preguntar.")
        self.assertNotIn("Camilx", o)
        self.assertNotIn("Arango", o)
        for real in ("Camilo Arango", "Camila Arango"):
            self.assertNotIn(texto_de(self.mo, "Escribió %s para preguntar." % real), o)


class FilaDesconocida(unittest.TestCase):
    def setUp(self):
        self.mo = motor([cliente("CL-1", "Marisol Quintana Duque", "44444444", "mquintana@gmail.com", "3001110004"),
                         empleado("KP-1", "Lucero Vargas Pino", "55555555", "lucero.vargas@kipupay.co", "3001110005"),
                         empleado("KP-2", "Hernán Soto Rey", "66666666", "hernan.soto@kipupay.co", "3001110006")])

    def salida(self, fila):
        return self.mo.anonimizar([fila])[0][0]["columns"]

    def test_cliente_desconocido_es_persona_nueva_con_todas_las_columnas_reemplazadas(self):
        fila = cliente("CL-NUEVO", "Wilmer Esneider Cotes Villadiego", "1052398741", "wcotes@outlook.com",
                       "3017778899", ocupacion="mecánico")
        o = self.salida(fila)
        self.assertEqual(o["cliente_id"], "CL-NUEVO")
        self.assertEqual(o["ciudad"], "Cali")
        for col in ("nombre_completo", "num_doc", "correo", "celular", "direccion", "fecha_nacimiento"):
            self.assertNotEqual(o[col], fila["columns"][col], col)
        self.assertNotIn("Wilmer", o["nombre_completo"])
        self.assertNotEqual(o["ocupacion"], "mecánico")      # sector, vía cuasi
        self.assertEqual(self.salida(fila), o)                # llave estable: mismo resultado

    def test_cliente_desconocido_con_cedula_de_uno_conocido_es_la_misma_persona(self):
        conocida = self.salida(cliente("CL-1", "Marisol Quintana Duque", "44444444", "mquintana@gmail.com", "3001110004"))
        otra = self.salida(cliente("CL-OTRO", "Marisol Quintana Duque", "44444444", "mquintana@gmail.com", "3001110004"))
        for col in ("nombre_completo", "num_doc", "correo", "celular"):
            self.assertEqual(conocida[col], otra[col], col)

    def test_empleado_desconocido_igual_que_cliente_nuevo(self):
        fila = empleado("KP-NUEVO", "Evelio Rincón Sastoque", "77777777", "evelio.rincon@kipupay.co", "3017770000",
                        reporta="Lucero Vargas")
        o = self.salida(fila)
        self.assertEqual(o["id"], "KP-NUEVO")
        for col in ("nombre", "correo", "celular", "documento", "fecha_nacimiento"):
            self.assertNotEqual(o[col], fila["columns"][col], col)
        jefa = self.salida(empleado("KP-1", "Lucero Vargas Pino", "55555555", "lucero.vargas@kipupay.co", "3001110005"))
        self.assertNotIn("Lucero", o["reporta_a"])
        self.assertEqual(o["reporta_a"], jefa["nombre"].rsplit(" ", 1)[0] if len(jefa["nombre"].split()) > 2 else jefa["nombre"])


if __name__ == "__main__":
    unittest.main()
