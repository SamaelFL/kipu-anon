"""Convierte la entrada al formato de salida SIN anonimizar (piso del juez).
Uso: python3 evals/tal_cual.py --input <carpeta> --out <dir>"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entrada


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    E = entrada.cargar_entrada(a.input)
    os.makedirs(a.out, exist_ok=True)

    def vuelca(nombre, filas):
        with open(os.path.join(a.out, nombre), "w", encoding="utf8") as f:
            for r in filas:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    vuelca("chats.jsonl", [{k: c[k] for k in ("id", "thread_id", "author", "ts", "text", "attachments")} for c in E["chats"].values()])
    vuelca("docs.jsonl", list(E["docs"].values()))
    vuelca("tables.jsonl", list(E["tables"].values()))
    json.dump({"entities": []}, open(os.path.join(a.out, "entities.json"), "w"))
    print("escrito", a.out)


if __name__ == "__main__":
    main()
