"""Descarga el modelo de embeddings durante la fase de build (se guarda en HF_HOME), para que el arranque no dependa
de la red ni tarde un minuto extra. Uso en el build:  python descargar_modelo.py"""
from sentence_transformers import SentenceTransformer

import buscar

SentenceTransformer(buscar.MODELO, device="cpu")
print(f"Modelo {buscar.MODELO} descargado.")
