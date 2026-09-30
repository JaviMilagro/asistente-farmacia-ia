#!/usr/bin/env bash
# Arranca el asistente en local y la publica temporalmente con un túnel rápido de Cloudflare (cloudflared).
#
# Uso:   ./arrancar_demo.sh                  (puerto 8000)
#        PUERTO=8010 ./arrancar_demo.sh
#
# Necesita en el entorno (o en un fichero .env local, que NO se sube al repositorio):
#   ANTHROPIC_API_KEY   clave de la API de Anthropic
#   DEMO_PASSWORD       contraseña de acceso a la demo
# Opcional:
#   WHATSAPP_NUMERO     vacío por defecto: sin él no se muestra el botón de WhatsApp
#
# Requiere el entorno .venv312 (Python 3.12 + requirements.txt). Ctrl+C detiene el servidor y el túnel.
# La URL pública cambia en cada ejecución.
set -euo pipefail
cd "$(dirname "$0")"

PUERTO="${PUERTO:-8000}"

if [ -f .env ]; then  # variables locales opcionales (no se suben: ver .gitignore)
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
export WHATSAPP_NUMERO="${WHATSAPP_NUMERO:-}"  # vacío por defecto

falta() { echo "ERROR: $1" >&2; exit 1; }

command -v cloudflared >/dev/null 2>&1 || falta "cloudflared no está instalado. En macOS con Homebrew: brew install cloudflared
       (sin Homebrew: descarga el binario desde https://github.com/cloudflare/cloudflared/releases y ponlo en tu PATH)."
[ -n "${ANTHROPIC_API_KEY:-}" ] || falta "falta ANTHROPIC_API_KEY (expórtala o ponla en un .env local)."
[ -n "${DEMO_PASSWORD:-}" ] || falta "falta DEMO_PASSWORD: sin contraseña no se publica nada en Internet."

PY=.venv312/bin/python
if [ ! -x "$PY" ]; then
  falta "no existe .venv312 (el entorno con Python 3.12 y las dependencias). Créalo así:
         uv venv --python 3.12 --seed .venv312
         .venv312/bin/pip install -r requirements.txt
       (si no tienes uv: https://docs.astral.sh/uv/getting-started/installation/)"
fi

# Antes de arrancar nada: el modelo tiene que poder importarse. Si no, ni se abre el servidor ni el túnel.
echo "Comprobando que sentence_transformers se puede importar..."
if ! error_import="$("$PY" -c 'import sentence_transformers' 2>&1)"; then
  echo "ERROR: no se puede importar sentence_transformers con $PY. Última línea del error:" >&2
  printf '%s\n' "$error_import" | tail -n 1 >&2
  exit 1
fi

# Puerto ocupado si algo acepta conexiones en él (bash puro: no depende de lsof)
if (exec 3<>"/dev/tcp/127.0.0.1/$PUERTO") 2>/dev/null; then
  falta "el puerto $PUERTO ya está en uso. Prueba con: PUERTO=8010 ./arrancar_demo.sh"
fi

# Resumen de un log cuando se detiene un proceso: sus últimas 5 líneas y la línea del error
# (la que empieza por ImportError, ...Error o ...Exception), sin el medio del traceback.
mostrar_fallo() {  # $1 = nombre del proceso, $2 = fichero de log
  echo "El $1 se ha detenido. Últimas 5 líneas del log:" >&2
  tail -n 5 "$2" >&2 || true
  linea_error="$(grep -E '^[A-Za-z_.]*(Error|Exception)([: ]|$)' "$2" | tail -n 1 || true)"
  if [ -n "$linea_error" ]; then
    echo "Línea del error:" >&2
    echo "$linea_error" >&2
  fi
}

TMP="$(mktemp -d)"
SERVIDOR_PID=""
TUNEL_PID=""
limpiar() {
  trap - EXIT
  [ -n "$TUNEL_PID" ] && kill "$TUNEL_PID" 2>/dev/null || true
  if [ -n "$SERVIDOR_PID" ]; then
    kill "$SERVIDOR_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do  # espera al apagado ordenado (hasta 5 s) y, si no llega, lo fuerza
      kill -0 "$SERVIDOR_PID" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$SERVIDOR_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
  echo; echo "Demo detenida."
}
trap limpiar EXIT
trap 'exit 130' INT   # Ctrl+C: sale (y el trap de EXIT limpia)
trap 'exit 143' TERM

echo "Arrancando el servidor en http://localhost:$PUERTO (usa $PY)..."
PORT="$PUERTO" "$PY" servidor.py >"$TMP/servidor.log" 2>&1 &
SERVIDOR_PID=$!

listo=""
for _ in $(seq 1 120); do
  if ! kill -0 "$SERVIDOR_PID" 2>/dev/null; then
    mostrar_fallo "servidor" "$TMP/servidor.log"
    exit 1
  fi
  if curl -fsS -m 2 "http://localhost:$PUERTO/salud" >/dev/null 2>&1; then listo=1; break; fi
  sleep 1
done
[ -n "$listo" ] || falta "el servidor no respondió en 2 minutos. Log: $(tail -n 5 "$TMP/servidor.log")"
echo "Servidor listo."

echo "Abriendo el túnel de Cloudflare..."
cloudflared tunnel --url "http://localhost:$PUERTO" >"$TMP/tunel.log" 2>&1 &
TUNEL_PID=$!

URL=""
for _ in $(seq 1 45); do
  if ! kill -0 "$TUNEL_PID" 2>/dev/null; then
    echo "ERROR: cloudflared se ha detenido. Últimas líneas del log:" >&2
    tail -n 15 "$TMP/tunel.log" >&2
    exit 1
  fi
  URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$TMP/tunel.log" | head -n 1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "ERROR: no apareció la URL del túnel en 45 s. Log:" >&2; tail -n 15 "$TMP/tunel.log" >&2; exit 1; }

echo
echo "============================================================"
echo "  URL pública (temporal):  $URL"
echo "  Acceso: la contraseña de DEMO_PASSWORD."
if [ -z "$WHATSAPP_NUMERO" ]; then echo "  WhatsApp: desactivado (WHATSAPP_NUMERO vacío)."; else echo "  WhatsApp: activado."; fi
echo "  Ctrl+C para detener el servidor y el túnel."
echo "============================================================"
echo "Ojo: cualquiera con la URL llega a la pantalla de acceso, y cada conversación consume tu API de Anthropic."

# macOS trae bash 3.2 (sin 'wait -n'): se vigila con un bucle
while kill -0 "$SERVIDOR_PID" 2>/dev/null && kill -0 "$TUNEL_PID" 2>/dev/null; do sleep 2; done
if ! kill -0 "$SERVIDOR_PID" 2>/dev/null; then
  mostrar_fallo "servidor" "$TMP/servidor.log"
else
  echo "El túnel de Cloudflare se ha detenido. Últimas 5 líneas de su log:" >&2
  tail -n 5 "$TMP/tunel.log" >&2 || true
fi
exit 1
