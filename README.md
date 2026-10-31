# kipu-anon

Servicio del Reto 1 (anonimizar el corpus de Kipu Pay). Python 3.12, solo librería estándar.

Bloque 1: ingesta y normalización al esquema de `output/` (todavía sin anonimizar), servicio HTTP.

```bash
cd kipu-anon
python3 -m kipu run --local sample/input --out /tmp/k_sample   # carpeta local
python3 -m kipu run --api --out /tmp/k_real                    # usa SOURCES_URL y SOURCES_TOKEN
./run.sh                                                       # servicio en :9000 (rutas con y sin /v1)
```

Variables: `SOURCES_URL`, `SOURCES_TOKEN`, `OPENROUTER_API_KEY`, `TEAM_TOKEN` (Bearer opcional), `DATA_DIR`, `PORT`. Ver `.env.example`.

Estructura: `kipu/sources.py` (API o carpeta), `kipu/parsers/` (chats, md, html, pdf, tablas), `kipu/ingest.py`, `kipu/pipeline.py`, `kipu/server.py`.
