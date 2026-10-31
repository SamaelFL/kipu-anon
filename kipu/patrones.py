"""Patrones y listas compartidas por grafo, detecta y reemplaza (solo librería estándar).

Los regex corren sobre texto normalizado con texto.norm_mapa (minúsculas, sin tildes).
"""
from __future__ import annotations

import re

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

RX_EMAIL = re.compile(r"(?<![a-z0-9._%+\-])[a-z0-9][a-z0-9._%+\-]*@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+")
RX_CEDULA_PUNTOS = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{3}){2,3}(?![\d]|\.\d)")
RX_CEL = re.compile(r"(?<![\d])(?:\+?\s?57[\s.\-]?)?\(?3\d{2}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?![\d])")
RX_NUM_LARGO = re.compile(r"(?<![\d.])\d{7,10}(?![\d]|\.\d)")
RX_PLACA = re.compile(r"(?<![a-z0-9])([a-z]{3})([\- ]?)(\d{3})(?![a-z0-9])")
RX_PASAPORTE = re.compile(r"(?<![a-z0-9])[a-z]{2}\d{6}(?![a-z0-9])")
RX_CREDITO = re.compile(r"(?<![\d])4471[\-\s]?\d{4}(?![\d])")
_VIA = (r"(?:calle|cll|cl|carrera|cra|cr|kr|kra|transversal|transv|trans|trv|tv|tr|diagonal|diag|dg|avenida|av|"
        r"autopista|circular|circunvalar)\.?")
_COMP = (r"(?:apto|apartamento|casa|of|oficina|int|interior|torre|piso|local|bodega|manzana|mz)\.?"
         r"\s*\d+[a-z]?")
RX_DIRECCION = re.compile(
    rf"(?<![a-z0-9]){_VIA}\s*\d+[a-z]?(?:\s+bis)?(?:\s+(?:sur|norte|este|oeste))?(?:\s+[a-z](?![a-z]))?"
    rf"\s*(?:#|no\.?|n°|nro\.?|numero|num\.?)\s*\d+[a-z]?(?:\s+bis)?(?:\s*-\s*|\s+)\d+(?:\s+(?:sur|norte|este|oeste))?"
    rf"(?:\s*,?\s*{_COMP})*")
RX_HONORIFICO = re.compile(r"(?<![a-z])(senor(?:a|es|as)?|sr\.?|sra\.?|srta\.?|senorita|dr\.?|dra\.?|doctor(?:a)?|"
                           r"don|dona|doc)\s+")
RX_HANDLE = re.compile(r"(?<![a-z0-9._%+\-/])@([a-z][a-z0-9._\-]{2,})")
RX_UID = re.compile(r"<@(U[A-Z0-9]{6,})(\|[^>]*)?>")
RX_URL = re.compile(r"https?://[^\s<>\"')\]]+")
RX_MONTO = re.compile(r"(?<![\d.,])\$?\s?(\d{1,3}(?:\.\d{3})+|\d{4,9})(?![\d])")
RX_FECHA_TXT = re.compile(r"(\d{1,2}) de (" + "|".join(MESES) + r")(?: de (\d{4}))?")
RX_FECHA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
CUE_CEDULA = re.compile(r"(?:\bc\.?\s?c\.?\b|cedula|documento|identificacion|\bcc\b|titular|\bdni\b|cedula de ciudadania"
                        r"|identificad[oa] con|identified with|identification|(?<!tax )\bid\s*(?:no\b|number\b|nro\b|#))"
                        r"[^\d]{0,24}$")
CUE_PASAPORTE = re.compile(r"(?:pasaporte|passport)[^a-z0-9]{0,24}$")
CUE_PLACA = re.compile(r"(?:placa|plate|carro|vehiculo|moto|license)[^a-z0-9]{0,20}$")

PLACA_NO = {"usd", "cop", "eur", "pqr", "inc", "sms", "nit", "cdt", "tel", "ext", "iva", "pse", "atm", "app",
            "cel", "min", "max", "ley", "cod", "ref", "num", "ver", "gps", "pdf", "csv", "api", "url", "vip",
            "doc", "nro", "mes", "dia", "cla", "ips", "eps", "arl", "dian", "tax", "fax", "tec", "sku", "tid"}

HONORIFICOS_F = {"senora", "sra", "srta", "senorita", "dra", "doctora", "dona", "senoras"}

# Relaciones: palabra -> (canon, género por pista)
RELACIONES = {
    "mama": "mamá", "madre": "mamá", "papa": "papá", "padre": "papá", "hermano": "hermano", "hermana": "hermana",
    "esposo": "esposo", "esposa": "esposa", "marido": "esposo", "mujer": "esposa", "novio": "novio", "novia": "novia",
    "hijo": "hijo", "hija": "hija", "jefe": "jefe", "jefa": "jefa", "socio": "socio", "socia": "socia",
    "primo": "primo", "prima": "prima", "tio": "tío", "tia": "tía", "abuelo": "abuelo", "abuela": "abuela",
    "cunado": "cuñado", "cunada": "cuñada", "sobrino": "sobrino", "sobrina": "sobrina", "amigo": "amigo",
    "amiga": "amiga", "vecino": "vecino", "vecina": "vecina", "suegro": "suegro", "suegra": "suegra",
    "compadre": "compadre", "colega": "colega", "companero": "compañero", "companera": "compañera",
    "yerno": "yerno", "nuera": "nuera", "pareja": "pareja", "empleado": "empleado", "empleada": "empleada",
}

# Organizaciones, marcas, lugares y figuras públicas que se conservan (no son personas naturales).
KEPT_ORGS = [
    "Kipu Pay", "Kipu", "Kipi", "Kipu Pay S.A.S.", "Bancolombia", "Davivienda", "Banco de Bogotá", "BBVA", "Nequi",
    "Daviplata", "Avianca", "Superfinanciera", "Superintendencia Financiera", "SIC", "DataCrédito", "Datacrédito",
    "TransUnion", "Experian", "Juan Valdez", "Plaza Botero", "Museo de Antioquia", "Gabriel García Márquez",
    "García Márquez", "Egan Bernal", "Jorge Isaacs", "Shakira", "Andes Capital", "Rappi", "Éxito", "Carulla",
    "Nutresa", "Spotify", "Netflix", "Tigo", "Claro", "Movistar", "EPM", "Enel", "Emcali", "Terpel", "Farmatodo",
    "DN", "Colsubsidio", "Sura", "SURA", "Seguros Bolívar", "Banco Santander", "Santander", "Veloz",
    "Mensajería Veloz", "Mensajeria Veloz", "Los Andes", "Universidad de los Andes", "Feria de las Flores",
    "Simón Bolívar", "Parque Simón Bolívar", "Parque de Bolívar", "Fernando Botero", "Botero", "Pablo Escobar",
    "Gustavo Petro", "Álvaro Uribe", "Juan Manuel Santos", "Iván Duque", "James Rodríguez", "Falcao", "Mercado Libre",
    "Mercadolibre", "Google", "Apple", "Amazon", "Microsoft", "WhatsApp", "Instagram", "Facebook", "Visa", "Mastercard",
    "PSE", "ACH", "DIAN", "Fedecafé", "Policía Nacional", "Fiscalía", "Presidencia", "Habeas Data",
    "Alcaldía de Medellín", "Metro de Medellín", "TransMilenio", "Uber", "DiDi", "InDrive", "Cabify",
    "Sodimac", "Homecenter", "Falabella", "Alkosto", "Ktronix", "Olímpica", "Jumbo", "Cencosud", "Zara",
    "Starbucks", "McDonald's", "Domino's", "Crepes & Waffles", "Oma", "Frisby", "El Corral", "Rappi Pay",
    "Lisboa", "Plaza Mayor", "Unicentro", "Santafé", "Viva Envigado", "Centro Comercial Andino", "Parque Lleras",
]
KEPT_RAZON = "organización, lugar, marca o figura pública; no es persona natural"
NIT_KIPU = "901.456.789-3"
DIR_KIPU = "Cra 43A # 1-50"
