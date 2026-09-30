"""Paso 3: limpia el catálogo crudo y genera el catálogo final con el esquema que usa el buscador.

Qué hace, por cada producto (sin borrar ninguno):
  - Convierte el HTML de la ficha en texto, con saltos de línea en <p>, <br> y <li>.
  - Separa la ficha en secciones: descripcion, modo_empleo y precauciones (se quitan las cabeceras).
  - Quita de la descripción la primera línea si solo repite el nombre del producto.
  - Pone descripcion = null si está vacía, repite el nombre o es texto basura (en ese caso, revisar = true).
  - Calcula nivel_info según la longitud de la descripción: completa (>= 300), parcial (100-299) o minima.
  - Normaliza las marcas (mayúsculas coherentes, alias) guardando la original en marca_original, y marca la marca propia.
  - Deriva en_stock = stock > 0 y construye url_producto.

Uso:  .venv312/bin/python limpiar_catalogo.py [crudo.json] [salida.json] [--ver ID]
      (--ver ID muestra el antes y el después de un producto)
"""
import argparse
import html
import json
import re
import unicodedata
from pathlib import Path

import config

ENTRADA = config.BASE / "datos" / "catalogo_ejemplo_crudo.json"
SALIDA = config.CATALOGO

# ---------------------------------------------------------------- HTML -> texto
BLOQUE_CIERRE = re.compile(r"</(?:p|div|li|ul|ol|tr|table|h[1-6])\s*>|<br\s*/?>|<li\b[^>]*>", re.I)
BLOQUE_APERTURA = re.compile(r"<(?:p|div|tr|h[1-6])\b[^>]*>", re.I)
CABECERA_DOC = re.compile(r"<(head|style|script)\b.*?</\1>", re.I | re.S)
ETIQUETAS = re.compile(r"<[^>]+>")


def html_a_lineas(s):
    """HTML -> texto con saltos de línea en </p>, <br>, <li>...; espacios normalizados."""
    if not s:
        return ""
    s = CABECERA_DOC.sub(" ", s)
    s = BLOQUE_CIERRE.sub("\n", s)
    s = BLOQUE_APERTURA.sub("\n", s)
    s = ETIQUETAS.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    lineas = (re.sub(r"[ \t\r\f\v]+", " ", l).strip() for l in s.split("\n"))
    return "\n".join(l for l in lineas if l)


def html_a_texto(s):
    """Texto plano en una sola línea (se guarda como descripcion_original)."""
    return " ".join(html_a_lineas(s).split("\n")) or None


# ---------------------------------------------------------------- secciones
H_DESC = r"ACCI[ÓO]N Y DESCRIPCI[ÓO]N|DESCRIPCI[ÓO]N"
H_MODO = (r"MODO DE EMPLEO(?: RECOMENDADO)?(?: ?/ ?(?:CONSEJOS|RECOMENDACIONES))?"
          r"|MODO DE USO|MODO DE APLICACI[ÓO]N|RECOMENDACIONES DE USO")
H_PREC = r"ADVERTENCIAS Y PRECAUCIONES(?: IMPORTANTES)?|PRECAUCIONES Y ADVERTENCIAS|PRECAUCIONES|ADVERTENCIAS"
# Cabeceras que solo delimitan: se conservan dentro de descripcion, con su etiqueta
H_OTRAS = (r"COMPOSICI[ÓO]N|INGREDIENTES|CONSERVACI[ÓO]N|INDICACIONES|CARACTER[ÍI]STICAS|BENEFICIOS|FUNCI[ÓO]N"
           r"|¿PARA QU[ÉE] SIRVE\?")
TODAS = f"{H_DESC}|{H_MODO}|{H_PREC}|{H_OTRAS}"
RE_CAB = re.compile(rf"(?<![\wÁÉÍÓÚÑáéíóúñ])(?P<h>{TODAS})(?![\wÁÉÍÓÚÑáéíóúñ])\s*:?", re.S)
RE_LINEA = re.compile(rf"^(?P<h>{TODAS})\s*(?::|$)", re.I)  # cabecera en cualquier caso al inicio de línea


def _tipo(h):
    for tipo, pat in (("desc", H_DESC), ("modo", H_MODO), ("prec", H_PREC)):
        if re.fullmatch(pat, h):
            return tipo
    return "otra"


def separar_secciones(texto):
    lineas = []
    for l in texto.split("\n"):
        m = RE_LINEA.match(l)
        if m:
            l = m.group("h").upper() + l[m.end("h"):]
        lineas.append(l)
    t = "\n".join(lineas)

    partes = {"desc": [], "modo": [], "prec": []}
    pos, tipo_actual, etiqueta = 0, "desc", None

    def cerrar(fin):
        cuerpo = t[pos:fin].strip()
        if not cuerpo and etiqueta is None:
            return
        if tipo_actual == "otra":
            partes["desc"].append(f"{etiqueta}: {cuerpo}" if cuerpo else etiqueta)
        elif cuerpo:
            partes[tipo_actual].append(cuerpo)

    for m in RE_CAB.finditer(t):
        cerrar(m.start())
        tipo_actual, etiqueta, pos = _tipo(m.group("h")), m.group("h"), m.end()
        if tipo_actual != "otra":
            etiqueta = None
    cerrar(len(t))
    return {k: ("\n".join(v).strip() or None) for k, v in partes.items()}


# ---------------------------------------------------------------- reglas de calidad
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


PATRONES_BASURA = [
    r"lorem ipsum", r"traduzir esta", r"traducir esta", r"texto pendiente", r"pendiente de (?:completar|rellenar)",
    r"^x{3,}$", r"^(?:n/?a|sin descripci[oó]n|sin informaci[oó]n)\.?$",
]


def quitar_nombre_inicial(desc, nombre):
    """Quita las primeras líneas de la descripción mientras repitan el nombre del producto."""
    while desc:
        primera, _, resto = desc.partition("\n")
        if norm(primera) != norm(nombre):
            break
        desc = resto.strip() or None
    return desc


def clasificar(desc, nombre):
    """None si la descripción sirve; si no, 'vacia', 'basura' o 'repite_nombre'."""
    d, n = norm(desc), norm(nombre)
    if not d:
        return "vacia"
    if any(re.search(p, (desc or "").strip().lower()) for p in PATRONES_BASURA):
        return "basura"
    if d == n or (n in d and len(d) <= len(n) + 15) or (d in n and len(d) >= 0.8 * len(n)):
        return "repite_nombre"
    return None


def nivel(desc):
    n = len(desc) if desc else 0
    return "completa" if n >= 300 else "parcial" if n >= 100 else "minima"


# ---------------------------------------------------------------- marcas
SIGLAS = set()  # siglas que deben quedar en mayúsculas, p. ej. {"XYZ"}
MINUSCULAS = {"by", "de", "del", "y"}
ALIAS = {"SOLENZA ESPAÑA": "SOLENZA"}  # variantes de nombre de una misma marca (clave en mayúsculas)


def _palabra(p, primera):
    nucleo = p.strip("()")
    if nucleo.upper() in SIGLAS or (re.search(r"\d", nucleo) and re.search(r"[A-Za-z]", nucleo)):
        return p.upper()
    if not primera and p.lower() in MINUSCULAS:
        return p.lower()
    return re.sub(r"(^|[-(/])(\w)", lambda m: m.group(1) + m.group(2).upper(), p.lower())


def normalizar_marca(m):
    if m is None:
        return None
    m = ALIAS.get(re.sub(r"\s+", " ", m).strip().upper(), m)
    return " ".join(_palabra(p, i == 0) for i, p in enumerate(re.sub(r"\s+", " ", m).strip().split(" ")))


# ---------------------------------------------------------------- pipeline
def limpiar_producto(r):
    lineas = html_a_lineas(r["description"])
    secc = separar_secciones(lineas)
    desc = quitar_nombre_inicial(secc["desc"], r["nombre"])
    estado = clasificar(desc, r["nombre"]) if desc else "vacia"
    revisar = estado == "basura"
    if estado:
        desc = None

    corta = html_a_texto(r["description_short"])
    if corta and any(re.search(p, corta.strip().lower()) for p in PATRONES_BASURA):
        corta, revisar = None, True  # texto basura en la descripción corta

    marca = normalizar_marca(r["marca"])
    return {
        "id": r["id"], "referencia": r["referencia"], "nombre": r["nombre"], "categoria": r["categoria"],
        "precio_sin_iva": r["precio_sin_iva"], "precio_con_iva": r["precio_con_iva"],
        "stock": r["stock"], "en_stock": r["stock"] > 0, "estado_raw": r["estado_raw"], "imagen": r["imagen"],
        "descripcion": desc, "active": r["active"], "ean13": r["ean13"],
        "marca": marca, "descripcion_corta": corta, "descripcion_original": html_a_texto(r["description"]),
        "modo_empleo": secc["modo"], "precauciones": secc["prec"], "revisar": revisar,
        "marca_original": r["marca"], "marca_propia": bool(marca) and norm(marca) == norm(config.MARCA_PROPIA),
        "url_producto": f"{config.URL_TIENDA_BASE}/producto/{r['id']}-{r['link_rewrite']}",
        "nivel_info": nivel(desc),
    }


def limpiar(entrada=ENTRADA, salida=SALIDA):
    crudo = json.loads(Path(entrada).read_text(encoding="utf-8"))
    limpio = [limpiar_producto(r) for r in crudo]
    assert len(limpio) == len(crudo) and len({r["id"] for r in limpio}) == len(crudo)  # no se pierde ningún producto
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(limpio, ensure_ascii=False, indent=2), encoding="utf-8")
    return crudo, limpio


def mostrar(crudo, limpio, pid):
    antes = next(r for r in crudo if r["id"] == pid)
    despues = next(r for r in limpio if r["id"] == pid)
    print(f"=== ANTES (producto {pid})")
    for k in ("nombre", "marca", "stock", "description_short", "description"):
        print(f"  {k}: {antes[k]!r}")
    print("=== DESPUÉS")
    for k in ("nombre", "marca", "marca_propia", "en_stock", "descripcion_corta", "descripcion", "modo_empleo",
              "precauciones", "revisar", "nivel_info", "url_producto"):
        print(f"  {k}: {despues[k]!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", nargs="?", default=ENTRADA)
    ap.add_argument("salida", nargs="?", default=SALIDA)
    ap.add_argument("--ver", type=int, help="muestra el antes y el después de un producto")
    a = ap.parse_args()
    crudo, limpio = limpiar(a.entrada, a.salida)
    print(f"{len(limpio)} productos -> {a.salida}")
    if a.ver is not None:
        mostrar(crudo, limpio, a.ver)
