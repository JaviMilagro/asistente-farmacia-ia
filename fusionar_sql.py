"""Paso 2: fusiona el JSON base con la exportación SQL (descripciones en HTML, marca, EAN...) usando id_product como clave.

El resultado es la versión "cruda" del catálogo: conserva el HTML y las marcas tal cual salen de la base de datos.
Los productos que están en la exportación SQL pero no en el JSON base (p. ej. los inactivos) se ignoran.

Uso:  .venv312/bin/python fusionar_sql.py [base.json] [export_sql.csv] [salida.json]
"""
import argparse
import csv
import json
from pathlib import Path

import config

BASE_JSON = config.BASE / "datos" / "intermedio" / "catalogo_base.json"
SQL_CSV = config.BASE / "datos" / "crudo" / "export_sql_ejemplo.csv"
SALIDA = config.BASE / "datos" / "catalogo_ejemplo_crudo.json"


def fusionar(base_json=BASE_JSON, sql_csv=SQL_CSV, salida=SALIDA):
    base = json.loads(Path(base_json).read_text(encoding="utf-8"))
    with open(sql_csv, encoding="utf-8", newline="") as f:
        sql = {int(fila["id_product"]): fila for fila in csv.DictReader(f, delimiter=";")}

    faltan = [r["id"] for r in base if r["id"] not in sql]
    if faltan:
        raise SystemExit(f"Hay {len(faltan)} productos del JSON base sin fila en la exportación SQL, p. ej. {faltan[:5]}")

    for r in base:
        fila = sql[r["id"]]
        r["ean13"] = fila["ean13"].strip() or None
        r["active"] = int(fila["active"])
        r["marca"] = fila["marca"].strip() or None       # tal cual: con sus mayúsculas inconsistentes
        r["description_short"] = fila["description_short"] or None  # HTML sin tocar
        r["description"] = fila["description"] or None              # HTML sin tocar
        r["link_rewrite"] = fila["link_rewrite"]

    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return base, len(sql) - len(base)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base_json", nargs="?", default=BASE_JSON)
    ap.add_argument("sql_csv", nargs="?", default=SQL_CSV)
    ap.add_argument("salida", nargs="?", default=SALIDA)
    a = ap.parse_args()
    regs, ignorados = fusionar(a.base_json, a.sql_csv, a.salida)
    print(f"{len(regs)} productos fusionados -> {a.salida} ({ignorados} filas de la exportación SQL sin producto activo, ignoradas)")
