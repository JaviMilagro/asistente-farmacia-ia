"""Paso 1 del pipeline del catálogo: exportación de productos (CSV de PrestaShop) -> JSON base, un registro por producto.

Uso:  .venv312/bin/python convertir_json.py [productos.csv] [salida.json]
"""
import argparse
import csv
import json
import re
from pathlib import Path

import config

ENTRADA = config.BASE / "datos" / "crudo" / "productos_ejemplo.csv"
SALIDA = config.BASE / "datos" / "intermedio" / "catalogo_base.json"


def limpiar_texto(s):
    """Normaliza espacios; devuelve None si queda vacío."""
    s = re.sub(r"\s+", " ", s or "").strip()
    return s or None


def convertir(entrada=ENTRADA, salida=SALIDA):
    registros = []
    # La referencia se lee como texto: conserva los ceros iniciales ("009463")
    with open(entrada, encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f, delimiter=";"):
            registros.append({
                "id": int(fila["Product ID"]),
                "referencia": fila["Referencia"].strip(),
                "nombre": limpiar_texto(fila["Nombre"]),
                "categoria": limpiar_texto(fila["Categoría"]),
                "precio_sin_iva": round(float(fila["Precio (imp. excl.)"]), 2),
                "precio_con_iva": round(float(fila["Precio (imp. incl.)"]), 2),
                "stock": int(fila["Cantidad"]),
                "estado_raw": int(fila["Estado"]),  # valor original de la columna Estado; no se interpreta
                "imagen": fila["Imagen"].strip(),
            })
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")
    return registros


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entrada", nargs="?", default=ENTRADA)
    ap.add_argument("salida", nargs="?", default=SALIDA)
    a = ap.parse_args()
    regs = convertir(a.entrada, a.salida)
    print(f"{len(regs)} productos -> {a.salida}")
