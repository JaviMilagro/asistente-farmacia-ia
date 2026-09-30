"""Recall@8 sobre evaluacion.json: [{"consulta": str, "ids_esperados": [int, ...]}].

Una consulta acierta si algún id esperado aparece en el top 8, ya sea como resultado o como
variante agrupada dentro de uno. Las consultas con ids_esperados vacío se ignoran.

Uso:  .venv312/bin/python evaluar.py [evaluacion.json] [--todo]   (--todo incluye productos sin stock)
"""
import json
import sys
from pathlib import Path

from buscar import CATALOGO, buscar

K = 8


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ruta = Path(args[0]) if args else Path(__file__).parent / "evaluacion.json"
    solo_en_stock = "--todo" not in sys.argv

    casos = json.loads(ruta.read_text(encoding="utf-8"))
    etiquetados = [c for c in casos if c["ids_esperados"]]
    if not etiquetados:
        print(f"Ninguna de las {len(casos)} consultas de {ruta.name} tiene ids_esperados; nada que evaluar.")
        return

    # los ids se comparan siempre como str, vengan como número o como texto
    ids_catalogo = {str(r["id"]) for r in json.loads(CATALOGO.read_text(encoding="utf-8"))}

    aciertos = []
    for c in etiquetados:
        esperados = {str(i).strip() for i in c["ids_esperados"]}
        inexistentes = sorted(esperados - ids_catalogo)
        if inexistentes:
            print(f"AVISO: {c['consulta']!r}: ids esperados que no existen en el catálogo: {', '.join(inexistentes)}")
        resultados = buscar(c["consulta"], solo_en_stock=solo_en_stock, k=K)
        vistos = {str(r["id"]) for r in resultados} | {str(v) for r in resultados for v in r["variantes"]}
        encontrados = esperados & vistos
        aciertos.append(bool(encontrados))
        print(f"{'OK ' if encontrados else 'NO '} {c['consulta']}  ({len(encontrados)}/{len(esperados)} esperados en top {K})")

    print(f"\nrecall@{K} medio: {sum(aciertos) / len(aciertos):.3f}  "
          f"({sum(aciertos)}/{len(aciertos)} consultas)  | sin etiquetar: {len(casos) - len(etiquetados)}")


if __name__ == "__main__":
    main()
