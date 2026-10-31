"""Contrato compartido entre las etapas del pipeline.

ingest -> grafo.construir -> detecta.detectar (+ llm.recall) -> resuelve.resolver
-> seudonimos (pseudo.Pseudonimizador) -> reemplaza.aplicar -> cuasi.aplicar
-> verifica.verificar -> output/ + entities.json

/anonymize reutiliza las mismas etapas con el grafo y el store cargados.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TIPOS_MENCION = (
    "nombre", "apodo", "handle", "slug", "correo", "correo_deletreado", "cedula",
    "celular", "placa", "pasaporte", "credito", "direccion", "nacimiento",
    "barrio", "ocupacion", "anio",
)


@dataclass
class Entidad:
    """Una persona (o algo conservado). El nombre es etiqueta, nunca llave."""

    entity_id: str                 # p_xxx o kept_xxx, estable entre corridas (se deriva de `llave`)
    llave: str                     # "cl:CL-12345", "kp:KP-005", "uid:U0ABC", "rel:<ancla>:<relacion>:<nombre_norm>", "men:<nombre_norm>:<record>"
    tipo: str = "person"           # person | organization_or_place
    genero: str = ""               # f | m | ""
    nombre: str = ""               # nombre real canónico más completo
    ids: dict = field(default_factory=dict)        # cedula, correos[], celulares[], placas[], pasaportes[], creditos[], uids[], handles[], cliente_id, empleado_id, radicados[]
    atributos: dict = field(default_factory=dict)  # ciudad, barrio, ocupacion, anio_vinculacion, direccion, nacimiento, cargo, reporta_a
    formas: set = field(default_factory=set)       # todas las formas reales vistas (originals de entities.json y barrido)
    records: set = field(default_factory=set)      # ids de registros donde aparece
    kept: bool = False
    reason: str = ""


@dataclass
class Mencion:
    record_id: str
    campo: str                     # "text", "body", "title", "filename", "metadata.author", "attachments.0.filename", "columns.notas"
    ini: int
    fin: int
    texto: str
    tipo: str                      # uno de TIPOS_MENCION
    entity_id: str | None = None
    fuente: str = "regla"          # regla | grafo | tolerante | llm
