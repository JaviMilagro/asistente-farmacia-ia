"""Muestra los 5 primeros resultados del buscador para consultas de ejemplo sobre el catálogo sintético.

Uso:  .venv312/bin/python probar_buscar.py
"""
from buscar import buscar

CONSULTAS = [
    "protector solar para niños",
    "algo para la boca seca",
    "champú anticaspa",
    "crema de manos para piel muy seca",
    "lentillas diarias",
    "suero fisiológico",
    "barrita de proteínas",
    "termómetro",
    "crema para piel atópica de bebé",
    "mascarilla para cabello teñido",
    "productos de Farmacia Ejemplo para el pelo",
    "crema para el culito del bebé con irritación del pañal",
]

for c in CONSULTAS:
    print(f"\n### {c}")
    for n, r in enumerate(buscar(c, k=5), 1):
        extra = f" (+{len(r['variantes'])} variantes)" if r["variantes"] else ""
        print(f"{n}. [{r['id']}] {r['nombre'][:66]} | {r['marca']} | {r['precio']}€ | {r['nivel_info']}{extra}")
