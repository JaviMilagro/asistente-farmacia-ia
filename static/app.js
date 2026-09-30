"use strict";

const AVATAR = "/static/avatar.svg";
// Los nombres (asistente y farmacia) los da el servidor en /config; aquí solo se construyen los textos fijos.
let CFG = { asistente_nombre: "Lía", farmacia_nombre: "Farmacia Ejemplo" };
const bienvenida = () => `¡Hola! 👋🏻 Soy ${CFG.asistente_nombre}, la asistente virtual de ${CFG.farmacia_nombre}. ¿Cómo puedo ayudarte?`;
const descargo = () =>
  "La información que ofrece este asistente de inteligencia artificial tiene fines exclusivamente informativos y no " +
  `constituye consejo médico ni farmacéutico. ${CFG.farmacia_nombre} no se hace responsable del uso que se haga de esta ` +
  "información sin la supervisión de un profesional sanitario.";
const SUGERENCIAS = ["Protección solar", "Cuidado del bebé", "Boca seca"];
const ICONO_SIN_FOTO =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#1E9E5A" d="M9 2h6v2h-1v2.1c1.7.5 3 2 3 3.9v10a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V10c0-1.9 1.3-3.4 3-3.9V4H9V2zm-.5 9v3h7v-3h-7z"/></svg>';

const $ = (s) => document.querySelector(s);
const chat = $("#chat");
const chatIn = $("#chatIn");
const form = $("#form");
const texto = $("#texto");
const botonEnviar = $("#enviar");
const avatarWrap = $("#avatarCabecera");

let enviando = false;
let bloqueado = false;

function el(etiqueta, clase, contenido) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (contenido !== undefined) nodo.textContent = contenido;
  return nodo;
}

/* ---------------------------------------------------------------- render de texto (sin innerHTML: todo se escapa) */
function inline(padre, cadena) {
  const re = /(\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  let ultimo = 0;
  let m;
  while ((m = re.exec(cadena))) {
    if (m.index > ultimo) padre.append(cadena.slice(ultimo, m.index));
    const t = m[0];
    if (t.startsWith("**")) {
      padre.append(el("strong", null, t.slice(2, -2)));
    } else {
      const partes = /^\[([^\]]+)\]\((.+)\)$/.exec(t);
      const a = el("a", null, partes[1]);
      a.href = partes[2];
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      padre.append(a);
    }
    ultimo = m.index + t.length;
  }
  if (ultimo < cadena.length) padre.append(cadena.slice(ultimo));
}

function renderTexto(contenedor, cadena) {
  let ul = null;
  let p = null;
  for (const linea of cadena.split("\n")) {
    const vineta = /^\s*[-*•]\s+(.*)$/.exec(linea);
    if (vineta) {
      p = null;
      if (!ul) { ul = el("ul"); contenedor.append(ul); }
      const li = el("li");
      inline(li, vineta[1]);
      ul.append(li);
    } else if (!linea.trim()) {
      p = null;
      ul = null;
    } else {
      ul = null;
      if (!p) { p = el("p"); contenedor.append(p); } else { p.append(document.createElement("br")); }
      inline(p, linea.trim());
    }
  }
}

/* ---------------------------------------------------------------- filas del chat */
function bajar() {
  chat.scrollTop = chat.scrollHeight;
}

function filaAsistente() {
  const fila = el("div", "fila asistente");
  const mini = el("img", "mini-avatar");
  mini.src = AVATAR;
  mini.alt = "";
  const columna = el("div", "columna");
  fila.append(mini, columna);
  return { fila, columna };
}

function burbujaUsuario(cadena) {
  const fila = el("div", "fila usuario");
  fila.append(el("div", "burbuja usuario", cadena));
  chatIn.append(fila);
  bajar();
}

function burbujaAsistente(cadena, clase) {
  const { fila, columna } = filaAsistente();
  const b = el("div", "burbuja asistente" + (clase ? " " + clase : ""));
  renderTexto(b, cadena);
  columna.append(b);
  chatIn.append(fila);
  bajar();
}

function tarjeta(bloque) {
  const p = bloque.producto;
  const art = el("article", "tarjeta");
  const fila = el("div", "tarjeta-fila");

  const foto = el("div", "foto");
  const sinFoto = () => { foto.innerHTML = ICONO_SIN_FOTO; };
  if (p.imagen) {
    const img = el("img");
    img.src = p.imagen;
    img.alt = "";
    img.loading = "lazy";
    img.onerror = sinFoto;
    foto.append(img);
  } else {
    sinFoto();
  }

  const info = el("div", "info");
  if (p.marca) info.append(el("div", "marca", p.marca));
  info.append(el("div", "nombre", p.nombre));
  const precio = el("div", "precio-fila");
  precio.append(el("span", "precio", p.precio_texto));
  if (!p.en_stock) precio.append(el("span", "sin-stock", "Sin stock"));
  info.append(precio);
  fila.append(foto, info);
  art.append(fila);

  if (bloque.frase) art.append(el("p", "frase", bloque.frase));
  const enlace = el("a", "btn-tienda", "Ver en la tienda");
  enlace.href = p.url_producto;
  enlace.target = "_blank";
  enlace.rel = "noopener noreferrer";
  art.append(enlace);
  return art;
}

function renderRespuesta(bloques) {
  const { fila, columna } = filaAsistente();
  for (const b of bloques) {
    if (b.tipo === "producto") {
      columna.append(tarjeta(b));
    } else {
      const burbuja = el("div", "burbuja asistente");
      renderTexto(burbuja, b.texto);
      columna.append(burbuja);
    }
  }
  chatIn.append(fila);
  // Al ser una respuesta larga, se alinea su inicio con la parte superior de la vista
  fila.scrollIntoView({ block: "start" });
  if (chat.scrollHeight - chat.scrollTop - chat.clientHeight < 4) bajar();
}

/* ---------------------------------------------------------------- escribiendo… + rebote del avatar (sincronizados) */
let filaEscribiendo = null;

function mostrarEscribiendo() {
  const { fila, columna } = filaAsistente();
  const b = el("div", "burbuja asistente");
  const puntos = el("div", "puntos");
  puntos.append(el("span"), el("span"), el("span"));
  b.append(puntos);
  columna.append(b);
  chatIn.append(fila);
  filaEscribiendo = fila;
  bajar();
  // Los puntos empiezan a animarse al insertarse; el rebote arranca en el mismo fotograma
  avatarWrap.classList.remove("rebote");
  void avatarWrap.offsetWidth;
  avatarWrap.classList.add("rebote");
}

function ocultarEscribiendo() {
  if (filaEscribiendo) filaEscribiendo.remove();
  filaEscribiendo = null;
}

avatarWrap.addEventListener("animationend", (e) => {
  if (e.animationName === "rebote") avatarWrap.classList.remove("rebote");
});

/* ---------------------------------------------------------------- envío */
function actualizarBoton() {
  botonEnviar.disabled = enviando || bloqueado || !texto.value.trim();
}

function ajustarAltura() {
  texto.style.height = "auto";
  texto.style.height = Math.min(texto.scrollHeight, 120) + "px";
}

let sugerenciasEl = null;

async function enviar(cadena) {
  cadena = cadena.trim();
  if (!cadena || enviando || bloqueado) return;
  enviando = true;
  if (sugerenciasEl) { sugerenciasEl.remove(); sugerenciasEl = null; }
  burbujaUsuario(cadena);
  texto.value = "";
  ajustarAltura();
  actualizarBoton();
  mostrarEscribiendo();

  try {
    const r = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje: cadena }),
    });
    ocultarEscribiendo();
    if (r.status === 401) { mostrarAcceso(); return; }
    if (r.status === 429) {
      const d = await r.json().catch(() => ({}));
      burbujaAsistente(d.detail || "Has llegado al límite de mensajes de esta sesión.", "error");
      bloqueado = true;
      texto.disabled = true;
      texto.placeholder = "Límite de mensajes alcanzado";
      return;
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      burbujaAsistente(d.detail || "Ha habido un problema. Inténtalo de nuevo.", "error");
      return;
    }
    const datos = await r.json();
    renderRespuesta(datos.bloques);
  } catch (e) {
    ocultarEscribiendo();
    burbujaAsistente("No he podido conectar. Comprueba tu conexión e inténtalo de nuevo.", "error");
  } finally {
    enviando = false;
    actualizarBoton();
    if (!bloqueado) texto.focus({ preventScroll: true });
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  enviar(texto.value);
});
texto.addEventListener("input", () => { ajustarAltura(); actualizarBoton(); });
texto.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    enviar(texto.value);
  }
});

/* ---------------------------------------------------------------- bienvenida (fija, no la genera el modelo) */
function mostrarBienvenida() {
  chatIn.replaceChildren();
  const { fila, columna } = filaAsistente();
  const b = el("div", "burbuja asistente");
  b.append(el("p", null, bienvenida()), el("p", "descargo", descargo()));
  columna.append(b);
  chatIn.append(fila);

  sugerenciasEl = el("div", "sugerencias");
  for (const s of SUGERENCIAS) {
    const boton = el("button", "sugerencia", s);
    boton.type = "button";
    boton.addEventListener("click", () => enviar(s));
    sugerenciasEl.append(boton);
  }
  chatIn.append(sugerenciasEl);
}

/* ---------------------------------------------------------------- acceso */
const acceso = $("#acceso");
function mostrarAcceso() {
  acceso.hidden = false;
  $("#password").focus();
}

$("#formAcceso").addEventListener("submit", async (e) => {
  e.preventDefault();
  const error = $("#errorAcceso");
  error.textContent = "";
  const r = await fetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("#password").value }),
  });
  if (!r.ok) {
    error.textContent = "Contraseña incorrecta";
    return;
  }
  acceso.hidden = true;
  $("#password").value = "";
  mostrarBienvenida();
  bloqueado = false;
  texto.disabled = false;
  texto.focus();
});

/* ---------------------------------------------------------------- avatar en vídeo (opcional) y WhatsApp */
function usarVideoSiExiste(hayVideo) {
  const reducido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!hayVideo || reducido) return; // con animaciones reducidas el avatar queda fijo
  const img = $("#avatarImg");
  const v = document.createElement("video");
  v.className = "avatar";
  v.poster = AVATAR;
  v.autoplay = true;
  v.muted = true;
  v.loop = true;
  v.playsInline = true;
  v.setAttribute("playsinline", "");
  v.src = "/avatar.mp4";
  v.addEventListener("error", () => v.replaceWith(img));
  img.replaceWith(v);
}

function ajustarPie() {
  const pie = $("#pie");
  const poner = () => document.documentElement.style.setProperty("--alto-pie", pie.offsetHeight + "px");
  new ResizeObserver(poner).observe(pie);
  poner();
}

async function iniciar() {
  ajustarPie();
  const cfg = await (await fetch("/config")).json();
  CFG = cfg;
  document.title = `${cfg.asistente_nombre} · ${cfg.farmacia_nombre}`;
  $("#titulo").textContent = `${cfg.asistente_nombre} · ${cfg.farmacia_nombre}`;
  $("#accesoTitulo").textContent = `Hola, soy ${cfg.asistente_nombre}`;
  $("#accesoTexto").textContent = `Demo de pruebas de ${cfg.farmacia_nombre}. Introduce la contraseña de acceso.`;
  usarVideoSiExiste(cfg.avatar_video);
  if (cfg.whatsapp_url) {
    const w = $("#whatsapp");
    w.href = cfg.whatsapp_url;
    w.hidden = false;
  }
  if (!cfg.autenticado) {
    mostrarAcceso();
  } else {
    await fetch("/nueva", { method: "POST" }); // al recargar empieza una conversación en blanco
    mostrarBienvenida();
    texto.focus({ preventScroll: true });
  }
}

iniciar();
