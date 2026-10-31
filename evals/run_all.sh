#!/usr/bin/env bash
# Corre todo el juez local. Primero regenera las trampas desde fuentes/ (llevan datos reales, no se versionan).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evals/out
python3 evals/gen_trampas.py --input fuentes --out evals/trampas.jsonl
[ -f evals/gen_inyecciones.py ] && python3 evals/gen_inyecciones.py --input fuentes --out evals/inyecciones.jsonl
python3 -m unittest discover -s evals -p "test_*.py"
# Reportes o salidas con formas reales: a evals/out/ (ignorado) o /tmp, nunca al repo.
