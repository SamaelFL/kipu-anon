"""Compara dos entities.json (antes, después) para comprobar que el grafo crece sin renumerar.

Uso: python3 evals/diff_entities.py antes.json despues.json [--detalle]
Sale con 1 si el seudónimo de alguna persona vieja cambió. Imprime solo conteos y entity_id
(sin nombres ni seudónimos) salvo con --detalle, que muestra valores: no lo pegues en el repo.
Una persona vieja es la misma si conserva entity_id; si no está, se busca por originals en común.
"""
import argparse
import json
import sys


def cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    ents = d["entities"] if isinstance(d, dict) else d
    return {e["entity_id"]: e for e in ents}


def personas(ents):
    return {k: e for k, e in ents.items() if not e.get("kept") and e.get("pseudonyms")}


def valores(e):
    return {t: v for t, v in (e.get("pseudonyms") or {}).items() if isinstance(v, str) and v}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("antes")
    ap.add_argument("despues")
    ap.add_argument("--detalle", action="store_true")
    a = ap.parse_args(argv)
    A, D = cargar(a.antes), cargar(a.despues)
    pa, pd = personas(A), personas(D)

    # persona vieja -> entidad nueva (mismo id, o por originals en común si se renumeró)
    por_original = {}
    for k, e in pd.items():
        for o in e.get("originals", []):
            por_original.setdefault(o, set()).add(k)
    pareja, desaparecidas = {}, []
    for k, e in pa.items():
        if k in pd:
            pareja[k] = k
            continue
        cand = set()
        for o in e.get("originals", []):
            cand |= por_original.get(o, set())
        cand -= set(pareja.values())
        if len(cand) == 1:
            pareja[k] = next(iter(cand))
        else:
            desaparecidas.append(k)

    cambiaron, renumeradas, con_ids_nuevos = [], [], []
    for k, k2 in pareja.items():
        if k != k2:
            renumeradas.append((k, k2))
        va, vd = valores(pa[k]), valores(pd[k2])
        malos = {t: (v, vd.get(t)) for t, v in va.items() if vd.get(t) != v}
        if malos:
            cambiaron.append((k, malos))
        nuevos = sorted(set(pd[k2].get("originals", [])) - set(pa[k].get("originals", [])))
        if nuevos:
            con_ids_nuevos.append((k, nuevos))

    nuevas = sorted(set(pd) - set(pareja.values()))
    viejos = {}
    for k, e in pa.items():
        for t, v in valores(e).items():
            viejos.setdefault((t, v), k)
    choques = []
    for k in nuevas:
        for t, v in valores(pd[k]).items():
            if (t, v) in viejos:
                choques.append((k, t, viejos[(t, v)], v))
    # choque también entre campos distintos con el mismo valor (p. ej. name vs name)
    valores_viejos = {}
    for (t, v), k in viejos.items():
        valores_viejos.setdefault(v, k)
    for k in nuevas:
        for t, v in valores(pd[k]).items():
            if v in valores_viejos and (k, t, valores_viejos[v], v) not in choques:
                choques.append((k, t, valores_viejos[v], v))

    def ids(lista):
        return ", ".join(x if isinstance(x, str) else x[0] for x in lista[:10]) + (" ..." if len(lista) > 10 else "")

    print("personas antes: %d | después: %d" % (len(pa), len(pd)))
    print("seudónimo de persona vieja cambió: %d (debe ser 0)%s" % (len(cambiaron), "  <-- FALLA" if cambiaron else ""))
    if cambiaron:
        print("   ", ids(cambiaron))
    print("personas viejas desaparecidas: %d" % len(desaparecidas))
    if desaparecidas:
        print("   ", ids(desaparecidas))
    print("personas viejas renumeradas (otro entity_id, mismos originals): %d" % len(renumeradas))
    print("personas nuevas: %d" % len(nuevas))
    if nuevas:
        print("   ", ids(nuevas))
    print("seudónimos nuevos que chocan con viejos: %d%s" % (len(choques), "  <-- FALLA" if choques else ""))
    if choques:
        print("   ", ", ".join("%s.%s~%s" % (c[0], c[1], c[2]) for c in choques[:10]))
    print("personas viejas con identificadores nuevos (originals agregados): %d" % len(con_ids_nuevos))
    if con_ids_nuevos:
        print("   ", ids(con_ids_nuevos))
    if a.detalle:
        for k, malos in cambiaron:
            for t, (v0, v1) in malos.items():
                print("  CAMBIÓ %s.%s: %r -> %r" % (k, t, v0, v1))
        for k, nuevos in con_ids_nuevos:
            print("  %s +originals: %s" % (k, nuevos))
        for c in choques:
            print("  CHOQUE %s.%s = %r (ya era de %s)" % (c[0], c[1], c[3], c[2]))
    return 1 if cambiaron else 0


if __name__ == "__main__":
    sys.exit(main())
