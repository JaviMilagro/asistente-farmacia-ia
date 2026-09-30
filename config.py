"""Configuración por variables de entorno. Todas son opcionales; un valor vacío equivale a no definirla."""
import os
from pathlib import Path

BASE = Path(__file__).parent


def env(nombre, por_defecto=None):
    """Valor de la variable de entorno; vacía, solo con espacios o sin definir => por_defecto."""
    return (os.environ.get(nombre) or "").strip() or por_defecto


def env_int(nombre, por_defecto):
    valor = env(nombre)
    if valor is None:
        return por_defecto
    try:
        return int(valor)
    except ValueError:
        raise SystemExit(f"{nombre} debe ser un número entero (valor recibido: {valor!r}).") from None


ASISTENTE_NOMBRE = env("ASISTENTE_NOMBRE", "Lía")   # cómo se presenta la asistente
FARMACIA_NOMBRE = env("FARMACIA_NOMBRE", "Farmacia Ejemplo")
MARCA_PROPIA = env("MARCA_PROPIA", "Marca Ejemplo")        # marca propia de la farmacia (la regla del prompt se refiere a ella)
URL_TIENDA_BASE = env("URL_TIENDA_BASE", "https://ejemplo.invalid").rstrip("/")  # base de las URLs de producto
CATALOGO = Path(env("CATALOGO_RUTA", str(BASE / "datos" / "catalogo_ejemplo.json")))
