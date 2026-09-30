"""Calcula los vectores (embeddings) del catálogo y los guarda en cache_embeddings/, para no recalcularlos en cada arranque.

La caché no se sube al repositorio: se genera con este script a partir del catálogo (config.CATALOGO) y del modelo
configurado en buscar.py. El nombre del fichero incluye una firma del texto vectorizado, así que si cambia el catálogo
se genera otro fichero nuevo.

Uso:  .venv312/bin/python generar_vectores.py
"""
import time

import buscar

antes = {f.name for f in buscar.CACHE_DIR.glob("*.npy")} if buscar.CACHE_DIR.exists() else set()
t = time.time()
buscar._cargar()  # si no hay caché válida, calcula los vectores y los guarda; si la hay, solo la carga
ficheros = sorted(buscar.CACHE_DIR.glob("*.npy"), key=lambda f: f.stat().st_mtime)
actual = ficheros[-1]
estado = "ya existía (no se ha recalculado)" if actual.name in antes else "calculada ahora"
print(f"Caché de vectores {estado}: {actual.relative_to(buscar.config.BASE)} "
      f"({actual.stat().st_size / 1024:.0f} KB) en {time.time() - t:.1f} s")
