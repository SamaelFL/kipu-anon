"""Genera un modulo .mjs con la logica de texto del validador oficial (sin su CLI)
y lo ejecuta con node sobre casos JSON. Sirve de oraculo para test_texto.py."""
import json
import os
import subprocess
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDAR = os.path.join(RAIZ, "material", "frontier-reto-1", "validar.mjs")

DRIVER = """
export { clean, norm, digitosCompactos, digitosEn, contiene };
"""

RUNNER = """
import { clean, norm, digitosCompactos, digitosEn, contiene } from "./texto_ref.mjs";
import { readFileSync } from "node:fs";
const casos = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = casos.map(c => ({
  clean: clean(c.h), norm: norm(c.h), compactos: digitosCompactos(c.h),
  contiene: contiene(c.h, c.n),
  digitosEn: (c.d ? digitosEn(c.h, c.d) : null),
}));
console.log(JSON.stringify(out));
"""


def correr_node(casos):
    src = open(VALIDAR, encoding="utf8").read()
    a = src.index("// juez/texto.ts")
    b = src.index("// juez/esquema.ts")
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "texto_ref.mjs"), "w", encoding="utf8").write(src[a:b] + DRIVER)
        open(os.path.join(d, "run.mjs"), "w", encoding="utf8").write(RUNNER)
        open(os.path.join(d, "casos.json"), "w", encoding="utf8").write(json.dumps(casos))
        r = subprocess.run(["node", os.path.join(d, "run.mjs"), os.path.join(d, "casos.json")],
                           capture_output=True, text=True, encoding="utf8")
        if r.returncode:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)
