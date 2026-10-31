#!/usr/bin/env bash
# Corre todo el juez local: pruebas, pipeline sobre sample/input y sobre fuentes, y el juez sobre ambas salidas.
# Primero regenera las trampas y canarios desde fuentes/ (llevan datos reales, no se versionan).
# Reportes y salidas con formas reales: a evals/out/ (ignorado) o /tmp, nunca al repo.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evals/out
python3 evals/gen_trampas.py --input fuentes --out evals/trampas.jsonl
[ -f evals/gen_inyecciones.py ] && python3 evals/gen_inyecciones.py --input fuentes --out evals/inyecciones.jsonl
python3 -m unittest discover -s evals -p "test_*.py"

echo; echo "##### pipeline sobre sample/input"
rm -rf evals/out/sample && python3 -m kipu run --local sample/input --out evals/out/sample
echo; echo "##### pipeline sobre fuentes"
rm -rf evals/out/fuentes && python3 -m kipu run --local fuentes --out evals/out/fuentes

echo; echo "##### juez: sample (ref = salida ideal)"
python3 evals/juez.py --out evals/out/sample --ref sample/expected_output --input sample/input \
  --tests sample/tests_sample.json | tee evals/out/juez_sample.txt
echo; echo "##### juez: fuentes (tests públicos + trampas; sin ref)"
python3 evals/juez.py --out evals/out/fuentes --input fuentes \
  --tests fuentes/tests_public.json --trampas evals/trampas.jsonl | tee evals/out/juez_fuentes.txt

# Canarios de inyección: con el servicio arriba, PROBAR_URL=http://localhost:9000/v1 evals/run_all.sh
if [ -n "${PROBAR_URL:-}" ]; then
  echo; echo "##### inyecciones contra $PROBAR_URL"
  python3 evals/probar_inyecciones.py --url "$PROBAR_URL"
fi
