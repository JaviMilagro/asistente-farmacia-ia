"""Búsqueda híbrida (BM25 + embeddings, fusionados con RRF) sobre el catálogo configurado (config.CATALOGO).

Uso:  .venv312/bin/python buscar.py "crema para piel atópica de bebé"
"""
import hashlib
import json
import re
import sys
import unicodedata
import warnings

import numpy as np
from rank_bm25 import BM25Okapi

import config

CATALOGO = config.CATALOGO
CACHE_DIR = config.BASE / "cache_embeddings"  # vectores calculados por generar_vectores.py (no se suben al repositorio)
MODELO = "intfloat/multilingual-e5-base"
RRF_K = 60          # constante de Reciprocal Rank Fusion
PESO_BM25 = 1.0     # peso de cada ranking en la fusión
PESO_EMB = 2.0
CANDIDATOS = 100    # profundidad de cada ranking antes de fusionar
MIN_LONG_GRUPO = 60  # solo se agrupan descripciones idénticas de al menos estos caracteres

STOPWORDS = {
    "a", "al", "algo", "con", "de", "del", "el", "la", "las", "los", "en", "para", "por", "un", "una",
    "unos", "unas", "y", "o", "que", "mi", "mis", "su", "sus", "me", "se", "es", "lo", "productos", "producto",
}

_estado = {}


# ---------------------------------------------------------------- texto
def _sin_acentos(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def tokenizar(texto):
    """Minúsculas, sin tildes, sin stopwords y con un stemming mínimo de plurales."""
    toks = re.findall(r"[a-z0-9]+", _sin_acentos((texto or "").lower()))
    salida = []
    for t in toks:
        if t in STOPWORDS:
            continue
        if len(t) > 4 and t.endswith("es"):
            t = t[:-2]
        elif len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        salida.append(t)
    return salida


def _texto_bm25(r):
    return " ".join(filter(None, [r["nombre"], r["marca"], r["categoria"], r["descripcion_corta"]]))


def _texto_embedding(r):
    desc = (r["descripcion"] or "")[:500].replace("\n", " ")
    partes = [r["nombre"], r["marca"], r["categoria"], r["descripcion_corta"], desc]
    return " | ".join(p.replace("\n", " ") for p in partes if p)


def _prefijos(modelo):
    return ("query: ", "passage: ") if "e5" in modelo.lower() else ("", "")


# ---------------------------------------------------------------- marcas y variantes
# Correcciones de marca aplicadas al cargar, sin modificar el catálogo: {"marca tal como está": "marca corregida"}.
CORRECCIONES_MARCA = {}


def _corregir_marca(r):
    if r["marca"] in CORRECCIONES_MARCA:
        r["marca"] = CORRECCIONES_MARCA[r["marca"]]


_UNIDADES = (r"u|uds?|unidad(?:es)?|caps?|capsulas?|comprimidos?|comp|sobres?|ampollas?|monodosis|bolsitas?"
             r"|sticks?|batidos?|tabletas?|pastillas?|parches?|apositos?|tiras?|discos?|dosis|viales?|barritas?|bar")


def atributos_variante(nombre):
    """(spf, tamaños, unidades, edad): lo que hace distintos a dos productos con la misma descripción.
    Graduación, talla y color NO se extraen a propósito: esos casos siguen agrupándose."""
    n = " ".join(re.findall(r"[a-z0-9.,+]+", _sin_acentos(nombre.lower())))
    spf = tuple(sorted(set(re.findall(r"(?:spf|fps)\s*(\d+)", n))))
    tam = tuple(sorted({(v.replace(",", "."), "g" if u == "gr" else u)
                        for v, u in re.findall(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l|g|gr|kg|mg)\b", n)}))
    uni = tuple(sorted(set(re.findall(rf"(\d+)\s*(?:{_UNIDADES})\b", n)) | set(re.findall(r"(\d+)\s*x\s*\d", n))))
    edad = set()
    if re.search(r"\bbebes?\b", n):  # 'baby'/'kids' se ignoran: suelen ser nombre de línea o de diseño
        edad.add("bebe")
    if re.search(r"\b(ninos?|infantil(?:es)?|junior|pediatric\w*)\b", n):
        edad.add("nino")
    if re.search(r"\badultos?\b", n):
        edad.add("adulto")
    return spf, tam, uni, tuple(sorted(edad))


def clave_descripcion(r):
    """Clave base: descripción sin números + marca (None si no hay texto suficiente para agrupar)."""
    d = r["descripcion"]
    if d and len(d) >= MIN_LONG_GRUPO:
        return (re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", d), r["marca"])
    return None


def clave_grupo(r):
    base = clave_descripcion(r)
    return base + atributos_variante(r["nombre"]) if base else ("__unico__", r["id"])


# ---------------------------------------------------------------- carga / índices
def _cargar():
    if _estado:
        return _estado
    with open(CATALOGO, encoding="utf-8") as f:
        productos = json.load(f)
    for r in productos:
        _corregir_marca(r)

    bm25 = BM25Okapi([tokenizar(_texto_bm25(r)) for r in productos])

    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(MODELO)
    _, pref_passage = _prefijos(MODELO)
    textos = [pref_passage + _texto_embedding(r) for r in productos]

    firma = hashlib.sha256((MODELO + "\n" + "\n".join(textos)).encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(exist_ok=True)
    ruta = CACHE_DIR / f"{MODELO.split('/')[-1]}_{firma}.npy"
    if ruta.exists():
        vectores = np.load(ruta)
    else:
        if config.env("EXIGIR_CACHE_VECTORES") == "1":  # en el servidor: fallar rápido antes que recalcular (pico > 2 GB)
            raise RuntimeError(f"Falta la caché de vectores {ruta.name}; no se recalcula porque EXIGIR_CACHE_VECTORES=1.")
        vectores = modelo.encode(textos, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
        np.save(ruta, vectores)

    grupos = {i: clave_grupo(r) for i, r in enumerate(productos)}

    _estado.update(productos=productos, bm25=bm25, modelo=modelo, vectores=vectores, grupos=grupos,
                   en_stock=np.array([r["en_stock"] for r in productos]))
    return _estado


# ---------------------------------------------------------------- búsqueda
def _ranking(puntuaciones, permitido):
    idx = np.where(permitido)[0]
    orden = idx[np.argsort(-puntuaciones[idx], kind="stable")][:CANDIDATOS]
    return orden.tolist()


def _norm_marca(s):
    """Sin tildes, en minúsculas y con cualquier separador reducido a un espacio ('Marca-Ejemplo' -> 'marca ejemplo')."""
    return " ".join(re.findall(r"[a-z0-9]+", _sin_acentos(s.lower())))


def listar_marcas():
    """Todas las marcas únicas del catálogo (con las correcciones de _corregir_marca), ordenadas."""
    if _estado:
        productos = _estado["productos"]
    else:  # sin cargar el modelo ni los vectores
        with open(CATALOGO, encoding="utf-8") as f:
            productos = json.load(f)
        for r in productos:
            _corregir_marca(r)
    return sorted({r["marca"] for r in productos if r["marca"]}, key=str.lower)


def buscar(consulta, solo_en_stock=True, k=8, marca=None):
    e = _cargar()
    permitido = e["en_stock"] if solo_en_stock else np.ones(len(e["productos"]), dtype=bool)

    if marca is not None and marca.strip():  # '' o solo espacios equivale a no filtrar
        if "marca_norm" not in e:
            e["marca_norm"] = [_norm_marca(r["marca"]) if r["marca"] else "" for r in e["productos"]]
        buscada = _norm_marca(marca)
        coincide = np.array([bool(buscada) and buscada in m for m in e["marca_norm"]])
        if not coincide.any():
            warnings.warn(f"Ninguna marca coincide con {marca!r}; no se devuelven resultados "
                          "(usa listar_marcas() para ver las disponibles).", stacklevel=2)
            return []
        if not (permitido & coincide).any():
            warnings.warn(f"La marca {marca!r} existe pero no tiene productos en stock.", stacklevel=2)
            return []
        permitido = permitido & coincide

    # (1) BM25: solo entran candidatos con puntuación > 0
    s_bm25 = np.asarray(e["bm25"].get_scores(tokenizar(consulta)))
    rank_bm25 = [i for i in _ranking(s_bm25, permitido) if s_bm25[i] > 0]

    # (2) embeddings (coseno; vectores normalizados)
    pref_query, _ = _prefijos(MODELO)
    q = e["modelo"].encode([pref_query + consulta], normalize_embeddings=True)[0]
    s_emb = e["vectores"] @ q
    rank_emb = _ranking(s_emb, permitido)

    # (3) Reciprocal Rank Fusion
    rrf = {}
    for peso, ranking in ((PESO_BM25, rank_bm25), (PESO_EMB, rank_emb)):
        for pos, i in enumerate(ranking, start=1):
            rrf[i] = rrf.get(i, 0.0) + peso / (RRF_K + pos)
    fusion = sorted(rrf, key=lambda i: -rrf[i])

    # agrupar variantes con descripción idéntica: se devuelve el mejor de cada grupo
    vistos, resultados = {}, []
    for i in fusion:
        g = e["grupos"][i]
        if g in vistos:
            vistos[g]["variantes"].append(e["productos"][i]["id"])
            continue
        r = e["productos"][i]
        item = {
            "id": r["id"], "nombre": r["nombre"], "marca": r["marca"], "precio": r["precio_con_iva"],
            "en_stock": r["en_stock"], "nivel_info": r["nivel_info"], "url_producto": r["url_producto"],
            "variantes": [], "score": round(rrf[i], 5),
        }
        vistos[g] = item
        resultados.append(item)
    return resultados[:k]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Uso: buscar.py "consulta"')
    for r in buscar(" ".join(sys.argv[1:])):
        print(f"{r['id']:>6} | {r['nombre'][:60]:<60} | {r['marca']} | {r['precio']}€ | {r['nivel_info']}"
              + (f" (+{len(r['variantes'])} variantes)" if r["variantes"] else ""))
