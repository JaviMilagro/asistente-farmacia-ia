"""Asistente de farmacia por terminal: Claude con tool use sobre el buscador híbrido de buscar.py.

Uso:  export ANTHROPIC_API_KEY=...   y luego   .venv312/bin/python asistente.py
Cada conversación se guarda en logs/ como JSONL (mensajes, llamadas a herramientas y resultados).
"""
import json
import sys
import threading
import warnings
from datetime import datetime

import anthropic

import buscar
import config

BASE = config.BASE
MODELO = "claude-haiku-4-5-20251001"
MAX_TOKENS = 16000  # margen para modelos con thinking; el bucle comprueba stop_reason == "max_tokens"
MAX_RONDAS_HERRAMIENTAS = 8  # tope de vueltas modelo -> herramientas -> modelo por mensaje del usuario
MAX_CHARS_DESCRIPCION = 1500
MAX_CHARS_DESC_CORTA = 200
CANDIDATOS_PRECIO = 30  # con orden='precio_asc' se ordenan por precio los N más relevantes
RUTA_PROMPT = BASE / "prompt_sistema.md"
RUTA_CATALOGO = config.CATALOGO
DIR_LOGS = BASE / "logs"
ORDENES = ("relevancia", "precio_asc")

HERRAMIENTAS = [
    {
        "name": "buscar_productos",
        "description": (
            "Busca productos en el catálogo de la farmacia (búsqueda híbrida por texto y significado). "
            "Devuelve hasta 8 productos con id, nombre, marca, precio (con IVA), en_stock, nivel_info, url_producto, "
            "descripcion_corta (recortada a 200 caracteres) y variantes (ids de productos agrupados con este, que solo "
            "se diferencian en talla, color o graduación). Por defecto solo devuelve productos con stock. "
            "Por defecto van ordenados por relevancia (orden='relevancia'). Usa orden='precio_asc' solo cuando el cliente "
            "pida lo más barato o económico: toma los 30 productos más relevantes y los ordena por precio ascendente, "
            "así que 'el más barato' lo es entre los que encajan con la búsqueda, no en todo el catálogo; aclaráselo al "
            "cliente. Si el resultado trae 'avisos', léelos: indican por ejemplo que la marca no existe o no tiene stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Qué busca el cliente, en lenguaje natural (p. ej. 'crema para piel atópica').",
                },
                "marca": {
                    "type": "string",
                    "description": "Opcional. Filtra por marca; admite nombre parcial y no distingue tildes ni mayúsculas.",
                },
                "incluir_sin_stock": {
                    "type": "boolean",
                    "description": "Opcional, false por defecto. Ponlo a true solo para consultar productos agotados.",
                },
                "orden": {
                    "type": "string",
                    "enum": list(ORDENES),
                    "description": "Opcional, 'relevancia' por defecto. 'precio_asc' ordena por precio ascendente los 30 más relevantes.",
                },
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "ver_producto",
        "description": (
            "Devuelve la ficha de un producto por su id: nombre, marca, precio, en_stock, nivel_info, url_producto, "
            "descripcion_corta, descripcion (máx. 1.500 caracteres), modo_empleo y precauciones. "
            "Úsala antes de explicar para qué sirve o cómo se usa un producto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Id del producto, tal como lo devuelve buscar_productos."}},
            "required": ["id"],
        },
    },
]

# El buscador y el catálogo se comparten entre hilos (ejecutar_casos.py lanza conversaciones en paralelo).
# warnings.catch_warnings no es seguro entre hilos, así que todo el acceso a buscar() va bajo este bloqueo.
_BLOQUEO = threading.Lock()
_catalogo = {}


def cargar_catalogo():
    with _BLOQUEO:
        if not _catalogo:
            with open(RUTA_CATALOGO, encoding="utf-8") as f:
                for r in json.load(f):
                    buscar._corregir_marca(r)  # mismas correcciones de marca que ve el buscador
                    _catalogo[r["id"]] = r
    return _catalogo


def _recortar(texto, maximo):
    if not texto or len(texto) <= maximo:
        return texto
    return texto[: maximo - 1].rstrip() + "…"


# ---------------------------------------------------------------- herramientas
def buscar_productos(consulta, marca=None, incluir_sin_stock=False, orden="relevancia"):
    if orden not in ORDENES:
        raise ValueError(f"orden no válido: {orden!r} (usa {' o '.join(ORDENES)})")
    catalogo = cargar_catalogo()
    with _BLOQUEO:
        buscar._cargar()  # dentro del bloqueo y fuera del bloque de avisos, para no recoger warnings de las librerías
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            resultados = buscar.buscar(
                consulta, solo_en_stock=not incluir_sin_stock,
                k=CANDIDATOS_PRECIO if orden == "precio_asc" else 8, marca=marca,
            )
    if orden == "precio_asc":
        resultados = sorted(resultados, key=lambda r: r["precio"])[:8]  # estable: a igual precio, manda la relevancia
    campos = ("id", "nombre", "marca", "precio", "en_stock", "nivel_info", "url_producto")
    items = []
    for r in resultados:
        item = {c: r[c] for c in campos}
        item["descripcion_corta"] = _recortar(catalogo[r["id"]]["descripcion_corta"], MAX_CHARS_DESC_CORTA)
        item["variantes"] = r["variantes"]
        items.append(item)
    salida = {"resultados": items}
    if orden == "precio_asc":
        salida["orden"] = f"precio ascendente entre los {CANDIDATOS_PRECIO} productos más relevantes"
    textos = [str(a.message) for a in avisos if issubclass(a.category, UserWarning)]
    if textos:
        salida["avisos"] = textos
    return json.dumps(salida, ensure_ascii=False)


def ver_producto(id):
    catalogo = cargar_catalogo()
    try:
        r = catalogo.get(int(id))
    except (TypeError, ValueError):
        raise ValueError(f"id no válido: {id!r}")
    if r is None:
        raise ValueError(f"No existe ningún producto con id {id}")
    desc = r["descripcion"]
    salida = {
        "id": r["id"], "nombre": r["nombre"], "marca": r["marca"], "precio": r["precio_con_iva"],
        "en_stock": r["en_stock"], "nivel_info": r["nivel_info"], "url_producto": r["url_producto"],
        "descripcion_corta": r["descripcion_corta"], "descripcion": desc,
        "modo_empleo": r["modo_empleo"], "precauciones": r["precauciones"],
    }
    if desc and len(desc) > MAX_CHARS_DESCRIPCION:
        salida["descripcion"] = desc[:MAX_CHARS_DESCRIPCION].rstrip() + "…"
        salida["descripcion_truncada"] = True
    return json.dumps(salida, ensure_ascii=False)


FUNCIONES = {"buscar_productos": buscar_productos, "ver_producto": ver_producto}


def ejecutar_herramienta(nombre, argumentos):
    """Devuelve (texto, es_error). Un fallo de la herramienta se devuelve al modelo, no rompe el chat."""
    try:
        return FUNCIONES[nombre](**argumentos), False
    except KeyError:
        return f"Herramienta desconocida: {nombre}", True
    except Exception as e:  # noqa: BLE001 - se informa al modelo del error
        return f"Error al ejecutar {nombre}: {type(e).__name__}: {e}", True


# ---------------------------------------------------------------- conversación
def cargar_prompt():
    """Lee prompt_sistema.md y sustituye los nombres configurables (ver config.py)."""
    texto = RUTA_PROMPT.read_text(encoding="utf-8")
    for marcador, valor in (("{{ASISTENTE_NOMBRE}}", config.ASISTENTE_NOMBRE), ("{{FARMACIA_NOMBRE}}", config.FARMACIA_NOMBRE),
                            ("{{MARCA_PROPIA}}", config.MARCA_PROPIA)):
        texto = texto.replace(marcador, valor)
    return texto


def gris(texto):
    return f"\033[90m{texto}\033[0m" if sys.stdout.isatty() else texto


class Asistente:
    def __init__(self, cliente=None, etiqueta=None, verbose=True, modelo=MODELO):
        self.cliente = cliente or anthropic.Anthropic()  # lee ANTHROPIC_API_KEY del entorno
        self.modelo = modelo
        self.sistema = cargar_prompt()
        self.messages = []
        self.verbose = verbose
        self.uso = {"entrada": 0, "salida": 0}  # tokens acumulados de la conversación
        self.ids_devueltos = set()  # ids de producto que las herramientas han devuelto en esta conversación
        DIR_LOGS.mkdir(exist_ok=True)
        marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.ruta_log = DIR_LOGS / (f"{marca_tiempo}_{etiqueta}.jsonl" if etiqueta else f"{marca_tiempo}.jsonl")
        self._log("sesion", modelo=self.modelo, prompt_sistema=self.sistema, herramientas=[h["name"] for h in HERRAMIENTAS])

    def _log(self, tipo, **datos):
        with open(self.ruta_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "tipo": tipo, **datos}, ensure_ascii=False) + "\n")

    def _registrar_ids(self, nombre, resultado):
        datos = json.loads(resultado)
        if nombre == "buscar_productos":
            self.ids_devueltos.update(r["id"] for r in datos["resultados"])
        elif nombre == "ver_producto":
            self.ids_devueltos.add(datos["id"])

    def enviar(self, texto):
        """Procesa un mensaje del usuario.

        Devuelve {'respuesta': str, 'herramientas': [{'herramienta', 'argumentos', 'resultado', 'es_error'}], 'uso': {...}}.
        """
        self.messages.append({"role": "user", "content": texto})
        self._log("usuario", texto=texto)
        usadas, respuesta = [], ""

        for _ in range(MAX_RONDAS_HERRAMIENTAS + 1):
            try:
                resp = self.cliente.messages.create(
                    model=self.modelo, max_tokens=MAX_TOKENS, system=self.sistema,
                    tools=HERRAMIENTAS, messages=self.messages,
                )
            except anthropic.APIError as e:
                self._log("error_api", tipo_error=type(e).__name__, mensaje=str(e))
                raise
            self.messages.append({"role": "assistant", "content": resp.content})
            respuesta = "".join(b.text for b in resp.content if b.type == "text")
            self.uso["entrada"] += resp.usage.input_tokens
            self.uso["salida"] += resp.usage.output_tokens
            self._log(
                "asistente", stop_reason=resp.stop_reason,
                contenido=[b.model_dump(mode="json", exclude_none=True) for b in resp.content],
                uso={"entrada": resp.usage.input_tokens, "salida": resp.usage.output_tokens},
            )
            if resp.stop_reason != "tool_use":
                if resp.stop_reason == "max_tokens":
                    respuesta += "\n[respuesta cortada por límite de longitud]"
                elif resp.stop_reason == "refusal":
                    respuesta = respuesta or "[el modelo ha rechazado responder a esta petición]"
                break

            # Todas las llamadas de este turno (pueden ser varias) se responden en un único mensaje de usuario
            resultados = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                argumentos = dict(b.input)
                if self.verbose:
                    print(gris(f"  ⚙ {b.name}({json.dumps(argumentos, ensure_ascii=False)})"))
                self._log("llamada_herramienta", id=b.id, herramienta=b.name, argumentos=argumentos)
                resultado, es_error = ejecutar_herramienta(b.name, argumentos)
                if not es_error:
                    self._registrar_ids(b.name, resultado)
                self._log("resultado_herramienta", id=b.id, herramienta=b.name, es_error=es_error, resultado=resultado)
                bloque = {"type": "tool_result", "tool_use_id": b.id, "content": resultado}
                if es_error:
                    bloque["is_error"] = True
                resultados.append(bloque)
                usadas.append({"herramienta": b.name, "argumentos": argumentos, "resultado": resultado, "es_error": es_error})
            self.messages.append({"role": "user", "content": resultados})
        else:
            respuesta = (respuesta + "\n" if respuesta else "") + "[se alcanzó el máximo de llamadas a herramientas]"
            self._log("aviso", mensaje="máximo de rondas de herramientas alcanzado")

        return {"respuesta": respuesta, "herramientas": usadas, "uso": dict(self.uso)}


def main():
    if not config.env("ANTHROPIC_API_KEY"):
        sys.exit("Falta la variable de entorno ANTHROPIC_API_KEY (export ANTHROPIC_API_KEY=...).")
    asistente = Asistente()
    print(gris(f"Modelo: {asistente.modelo} | log: {asistente.ruta_log.relative_to(BASE)} | escribe 'salir' para terminar"))
    while True:
        try:
            texto = input("\nTú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not texto:
            continue
        if texto.lower() in {"salir", "exit", "quit"}:
            break
        try:
            resultado = asistente.enviar(texto)
        except anthropic.APIError as e:
            print(f"\n[Error de la API: {type(e).__name__}: {e}]")
            continue
        print(f"\nAsistente: {resultado['respuesta']}")


if __name__ == "__main__":
    main()
