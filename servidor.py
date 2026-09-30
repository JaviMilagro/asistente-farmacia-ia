"""Servidor web del asistente virtual de la farmacia (FastAPI).

Variables de entorno (ver .env.example):
  ANTHROPIC_API_KEY   obligatoria; solo vive en el servidor
  DEMO_PASSWORD       opcional; si se define, el acceso pide esa contraseña
  WHATSAPP_NUMERO     opcional; en formato internacional sin '+' (p. ej. 34XXXXXXXXX). Sin ella no hay botón de WhatsApp
  LIMITE_MENSAJES     opcional; mensajes por sesión (30 por defecto)
  ASISTENTE_NOMBRE, FARMACIA_NOMBRE, MARCA_PROPIA, URL_TIENDA_BASE: nombres configurables (ver config.py)

Arranque:  .venv312/bin/uvicorn servidor:app --host 127.0.0.1 --port 8000

El historial de cada conversación vive en el servidor (una Asistente por sesión), no en el navegador: así el límite
de mensajes no se puede saltar recargando y las marcas [[producto:ID]] se validan contra los ids que las herramientas
devolvieron realmente en esa conversación. Cada conversación se guarda en logs/ como JSONL.
"""
import asyncio
import hmac
import re
import secrets
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from urllib.parse import quote

import anthropic
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import asistente as A
import buscar
import config as cfg

BASE = A.BASE
ESTATICOS = BASE / "static"
MODELO_WEB = "claude-sonnet-5-5"
LIMITE_MENSAJES = cfg.env_int("LIMITE_MENSAJES", 30)
MAX_CHARS_MENSAJE = 1000
MAX_SESIONES = 500
COOKIE = "asistente_sid"
DURACION_COOKIE = 24 * 3600

DEMO_PASSWORD = cfg.env("DEMO_PASSWORD")  # opcional: sin contraseña, el acceso es libre
if not cfg.env("ANTHROPIC_API_KEY"):
    raise SystemExit("Falta la variable de entorno ANTHROPIC_API_KEY.")

_numero = re.sub(r"\D", "", cfg.env("WHATSAPP_NUMERO", ""))
WHATSAPP_URL = f"https://wa.me/{_numero}?text={quote('Hola, tengo una consulta')}" if _numero else None

CLIENTE = anthropic.Anthropic(timeout=120)


# ---------------------------------------------------------------- sesiones
class Sesion:
    def __init__(self):
        self.mensajes = 0  # mensajes del usuario en esta sesión de acceso (no se reinicia al recargar)
        self.lock = threading.Lock()  # una petición a la vez por sesión
        self._asistente = None

    @property
    def asistente(self):
        if self._asistente is None:  # se crea al primer mensaje: no deja logs vacíos
            self._asistente = A.Asistente(cliente=CLIENTE, etiqueta="web", verbose=False, modelo=MODELO_WEB)
        return self._asistente

    def nueva_conversacion(self):
        self._asistente = None


SESIONES = {}
_lock_sesiones = threading.Lock()


def crear_sesion(request: Request, response: Response):
    """Crea una sesión nueva y la asocia al navegador con una cookie."""
    sid = secrets.token_urlsafe(32)
    with _lock_sesiones:
        if len(SESIONES) >= MAX_SESIONES:
            SESIONES.pop(next(iter(SESIONES)))  # descarta la más antigua
        SESIONES[sid] = Sesion()
    response.set_cookie(COOKIE, sid, max_age=DURACION_COOKIE, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")


def sesion_de(request: Request) -> Sesion:
    ses = SESIONES.get(request.cookies.get(COOKIE, ""))
    if ses is None:
        raise HTTPException(401, "Sesión no iniciada")
    return ses


# ---------------------------------------------------------------- marcas [[producto:ID]] -> tarjetas
RE_MARCA = re.compile(r"\[\[producto:([^\]]*)\]\]")
RE_VINETA_FINAL = re.compile(r"(?:^|\n)[ \t]*(?:[-*•]|\d+[.)])[ \t]*$")


def precio_es(valor):
    s = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def tarjeta(p):
    return {
        "id": p["id"], "marca": p["marca"], "nombre": p["nombre"], "precio": p["precio_con_iva"],
        "precio_texto": precio_es(p["precio_con_iva"]), "en_stock": p["en_stock"],
        "url_producto": p["url_producto"], "imagen": p.get("imagen"),
    }


def _sin_acentos_min(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _sin_nombre_final(previo, producto):
    """Si la última línea del texto previo a una marca es solo la marca comercial o el nombre del producto
    (el modelo a veces los escribe delante de la etiqueta), se elimina: la tarjeta ya los muestra."""
    lineas = previo.rstrip().split("\n")
    if lineas and _sin_acentos_min(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", lineas[-1])) in {_sin_acentos_min(producto["marca"]), _sin_acentos_min(producto["nombre"])} - {""}:
        return "\n".join(lineas[:-1])
    return previo


def construir_bloques(asistente, texto):
    """Convierte la respuesta del modelo en bloques {texto} y {producto}. Sustituye cada marca por los datos del
    catálogo y descarta (registrándolo en el log) las que apuntan a un id inexistente o no devuelto por las herramientas."""
    catalogo = A.cargar_catalogo()
    partes = RE_MARCA.split(texto)  # [texto0, ref1, texto1, ref2, texto2, ...]
    bloques = []

    def anadir_texto(t):
        t = t.strip()
        if t:
            bloques.append({"tipo": "texto", "texto": t})

    previo = partes[0]  # texto pendiente de emitir: aún no sabemos si la siguiente marca es válida
    for i in range(1, len(partes), 2):
        ref, segmento = partes[i].strip(), partes[i + 1]
        previo = RE_VINETA_FINAL.sub("", previo)  # viñeta ("- ", "1. ") que precede a la marca
        primera, _, resto = segmento.strip().partition("\n")
        frase = primera.strip(" \t:-–—")

        pid = int(ref) if ref.isdigit() else None
        motivo = None
        if pid is None or pid not in catalogo:
            motivo = "id inexistente"
        elif pid not in asistente.ids_devueltos:
            motivo = "id no devuelto por las herramientas de esta conversación"
        if motivo:
            asistente._log("marca_descartada", marca=f"[[producto:{ref}]]", motivo=motivo, frase=frase)
            previo = previo.rstrip() + ("\n\n" + resto.strip() if resto.strip() else "")  # se descarta marca y frase
            continue
        anadir_texto(_sin_nombre_final(previo, catalogo[pid]))
        bloques.append({"tipo": "producto", "frase": frase, "producto": tarjeta(catalogo[pid])})
        previo = resto
    anadir_texto(previo)

    if not bloques:
        asistente._log("aviso", mensaje="respuesta vacía tras validar las marcas de producto")
        anadir_texto("Perdona, no he podido mostrarte esos productos. ¿Puedes reformular tu pregunta?")
    return bloques


# ---------------------------------------------------------------- app
@asynccontextmanager
async def ciclo_vida(_app):
    # Carga catálogo e índice de búsqueda al arrancar para que la primera consulta no tarde
    await asyncio.to_thread(lambda: (A.cargar_catalogo(), buscar._cargar()))
    yield


app = FastAPI(title=f"{cfg.ASISTENTE_NOMBRE} · {cfg.FARMACIA_NOMBRE}", lifespan=ciclo_vida)
app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


class ChatIn(BaseModel):
    mensaje: str = Field(min_length=1, max_length=MAX_CHARS_MENSAJE)


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/salud", include_in_schema=False)
def salud():
    """Comprobación de salud para el hosting: no toca el modelo ni la API de Claude."""
    return {"ok": True}


@app.get("/avatar.mp4", include_in_schema=False)
def avatar_video():
    ruta = BASE / "avatar.mp4"
    if not ruta.exists():
        raise HTTPException(404)
    return FileResponse(ruta, media_type="video/mp4")


@app.get("/placeholder/{pid}.svg", include_in_schema=False)
def imagen_ejemplo(pid: int):
    """Imagen de producto generada para el catálogo de ejemplo: un frasco genérico con un color distinto por producto."""
    tono = (pid * 47) % 360
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        f'<rect width="120" height="120" fill="hsl({tono} 45% 90%)"/>'
        f'<rect x="47" y="20" width="26" height="12" rx="3" fill="hsl({tono} 40% 45%)"/>'
        f'<rect x="40" y="32" width="40" height="70" rx="10" fill="#fff" stroke="hsl({tono} 40% 45%)" stroke-width="3"/>'
        f'<rect x="48" y="55" width="24" height="22" rx="3" fill="hsl({tono} 40% 45%)" opacity=".25"/></svg>'
    )
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/config")
def config(request: Request, response: Response):
    if DEMO_PASSWORD is None and request.cookies.get(COOKIE, "") not in SESIONES:
        crear_sesion(request, response)  # sin contraseña no hay pantalla de acceso: la sesión se crea sola
    return {
        "autenticado": DEMO_PASSWORD is None or request.cookies.get(COOKIE, "") in SESIONES,
        "requiere_password": DEMO_PASSWORD is not None,
        "asistente_nombre": cfg.ASISTENTE_NOMBRE,
        "farmacia_nombre": cfg.FARMACIA_NOMBRE,
        "avatar_video": (BASE / "avatar.mp4").exists(),  # si existe, el front lo usa en lugar de la imagen
        "whatsapp_url": WHATSAPP_URL,
        "limite": LIMITE_MENSAJES,
    }


@app.post("/login")
def login(datos: LoginIn, request: Request, response: Response):
    if DEMO_PASSWORD is not None and not hmac.compare_digest(datos.password.encode(), DEMO_PASSWORD.encode()):
        time.sleep(1)  # frena la fuerza bruta
        raise HTTPException(401, "Contraseña incorrecta")
    crear_sesion(request, response)
    return {"ok": True, "limite": LIMITE_MENSAJES}


@app.post("/nueva")
def nueva(request: Request):
    """Empieza una conversación en blanco (al recargar la página). El contador de mensajes se conserva."""
    ses = sesion_de(request)
    ses.nueva_conversacion()
    return {"restantes": max(LIMITE_MENSAJES - ses.mensajes, 0)}


@app.post("/chat")
def chat(datos: ChatIn, request: Request):
    ses = sesion_de(request)
    with ses.lock:
        if ses.mensajes >= LIMITE_MENSAJES:
            raise HTTPException(429, f"Has llegado al límite de {LIMITE_MENSAJES} mensajes de esta sesión. "
                                     "Para más dudas, puedes contactar con la farmacia.")
        asistente = ses.asistente
        try:
            resultado = asistente.enviar(datos.mensaje.strip())
        except anthropic.APIError:
            raise HTTPException(502, f"{cfg.ASISTENTE_NOMBRE} no está disponible en este momento. Inténtalo de nuevo en unos segundos.")
        ses.mensajes += 1  # solo cuentan los mensajes atendidos
        bloques = construir_bloques(asistente, resultado["respuesta"])
        asistente._log("respuesta_web", bloques=[b["tipo"] for b in bloques], restantes=LIMITE_MENSAJES - ses.mensajes)
    return {"bloques": bloques, "restantes": LIMITE_MENSAJES - ses.mensajes}


if __name__ == "__main__":
    import uvicorn

    # Puerto desde la variable de entorno PORT (los servicios de hosting la definen); 8000 en local
    uvicorn.run(app, host="0.0.0.0", port=cfg.env_int("PORT", 8000), proxy_headers=True, forwarded_allow_ips="*")
