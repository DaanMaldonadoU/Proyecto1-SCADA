# -*- coding: utf-8 -*-
r"""
puente/vincular.py — Obtiene la clave del puente del servidor web del gemelo con una cuenta admin.

El puente (python -m puente) se autentica ante el servidor con la clave compartida
`datos/puente.clave`. En vez de copiar ese archivo a mano desde la PC servidor, basta con el
usuario y la contraseña de una cuenta **admin** del gemelo: este módulo los manda una vez a
`POST /api/puente/clave` (por HTTPS), recibe la clave y la guarda en `datos/puente.clave`.

Uso por consola (la contraseña se pide sin mostrarla):

    .venv\Scripts\python.exe -m puente.vincular --usuario admin
    .venv\Scripts\python.exe -m puente.vincular --url wss://digitaltwinscada.smartsensorslab.com/ws/planta --usuario admin
    .venv\Scripts\python.exe -m puente.vincular --url ws://127.0.0.1:3002/ws/planta --usuario admin --clave-archivo datos\puente.clave

Uso desde el HMI (en un hilo aparte, nunca en el de Qt: la petición puede tardar hasta `timeout`):

    from puente.vincular import obtener_clave, guardar_clave
    r = obtener_clave("wss://digitaltwinscada.smartsensorslab.com/ws/planta", usuario, contrasena)
    if r["ok"]:
        guardar_clave(ruta, r["clave"])
    else:
        mostrar(r["msg"])           # texto en español listo para la pantalla

`obtener_clave` nunca lanza excepciones: siempre devuelve un dict con "ok". No sigue
redirecciones (las credenciales no deben reenviarse a otra dirección sin que lo sepa el usuario).

Comprobar una clave sin cuenta admin (sirve con cualquier versión del servidor):

    .venv\Scripts\python.exe -m puente.vincular --probar                 # la de datos/puente.clave
    .venv\Scripts\python.exe -m puente.vincular --guardar <CLAVE>        # la guarda y la prueba
    lab\clave_puente.bat <CLAVE>                                         # lo mismo, con doble clic

`probar_clave(url, clave)` hace el saludo WebSocket de /ws/planta con la clave: 101 = el servidor la
acepta, 401 = no es la suya. Si la acepta, esa conexión es «la planta» un instante (y desplaza al
puente que estuviera conectado, que vuelve solo en 1–15 s).

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
import argparse
import base64
import getpass
import http.client
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

URL_DEFECTO = "wss://digitaltwinscada.smartsensorslab.com/ws/planta"
RUTA_API = "/api/puente/clave"
MIN_CLAVE = 16                  # el mismo mínimo que core.remoto.leer_clave
MAX_RESPUESTA = 64 * 1024       # la respuesta real ocupa unos 200 bytes
TIMEOUT_DEFECTO_S = 10.0

_ESQUEMAS = {"wss": "https", "ws": "http", "https": "https", "http": "http"}
_HOSTS_LOCALES = ("localhost", "127.0.0.1", "::1")


def url_https(url):
    """Base HTTP(S) del servidor a partir de lo que el usuario tenga a mano.

    wss://host[:p]/ws/planta -> https://host[:p]      ws://… -> http://…
    https://host[:p]/lo/que/sea -> https://host[:p]   host (sin esquema) -> https://host
    Vacía, con un esquema que no sea ws/wss/http/https o sin host -> ValueError."""
    texto = url.strip() if isinstance(url, str) else ""
    if not texto:
        raise ValueError("falta la dirección del servidor del gemelo")
    if any(c.isspace() for c in texto):
        raise ValueError("la dirección del servidor no puede tener espacios: %r" % texto)
    if "://" not in texto:
        texto = "https://" + texto
    partes = urllib.parse.urlsplit(texto)
    esquema = _ESQUEMAS.get(partes.scheme.lower())
    if esquema is None:
        raise ValueError("dirección no válida %r: debe empezar por wss://, ws://, https:// o http://" % url.strip())
    host = partes.hostname
    if not host:
        raise ValueError("dirección no válida %r: falta el nombre del servidor" % url.strip())
    try:
        puerto = partes.port
    except ValueError:
        raise ValueError("dirección no válida %r: el puerto no es un número válido" % url.strip()) from None
    if ":" in host:                 # IPv6 literal
        host = "[%s]" % host
    return "%s://%s%s" % (esquema, host, "" if puerto is None else ":%d" % puerto)


def _es_local(base):
    host = urllib.parse.urlsplit(base).hostname or ""
    return host in _HOSTS_LOCALES or host.startswith("127.")


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    """Convierte cualquier redirección en HTTPError: las credenciales no se reenvían a ciegas."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abridor(base, contexto_ssl):
    manejadores = [_SinRedireccion()]
    if contexto_ssl is not None:
        manejadores.append(urllib.request.HTTPSHandler(context=contexto_ssl))
    if _es_local(base):
        manejadores.append(urllib.request.ProxyHandler({}))     # nunca pasar 127.0.0.1 por un proxy
    return urllib.request.build_opener(*manejadores)


def _motivo(error):
    """Texto corto del motivo de un fallo de conexión."""
    if isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError):
        error = error.reason
    if isinstance(error, ssl.SSLCertVerificationError):
        return "el certificado HTTPS no es válido (%s)" % (error.verify_message or error)
    if isinstance(error, ssl.SSLError):
        return "fallo de TLS/HTTPS (%s)" % error
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "no respondió a tiempo"
    if isinstance(error, ConnectionRefusedError):
        return "conexión rechazada (¿servidor apagado o puerto equivocado?)"
    if isinstance(error, socket.gaierror):
        return "no se encontró el nombre del servidor (¿sin internet o dirección mal escrita?)"
    if isinstance(error, (ConnectionResetError, http.client.RemoteDisconnected)):
        return "el servidor cerró la conexión"
    return str(error) or error.__class__.__name__


def _json_de(crudo):
    try:
        datos = json.loads(crudo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _fallo(msg, status=None):
    return {"ok": False, "msg": msg, "status": status}


def _mensaje_http(base, status, datos, motivo, cabeceras):
    msg_srv = datos.get("msg") if isinstance(datos, dict) and isinstance(datos.get("msg"), str) else ""
    if status == 401:
        return "usuario o contraseña incorrectos"
    if status == 403:
        return msg_srv or "solo una cuenta admin puede vincular el puente"
    if status == 404:
        return ("el servidor no tiene %s: actualízalo (git pull) y reinícialo, o pega la clave a mano"
                % RUTA_API)
    if status == 429:
        return msg_srv or "demasiados intentos; espera unos minutos"
    if 300 <= status < 400:
        destino = (cabeceras.get("Location") if cabeceras is not None else None) or "otra dirección"
        return ("%s redirige a %s (%d): escribe directamente la dirección https:// del servidor"
                % (base, destino, status))
    if status >= 500:
        return ("el servidor respondió %d%s: ¿están encendidos el servidor del gemelo y el túnel?"
                % (status, " (%s)" % (msg_srv or motivo) if (msg_srv or motivo) else ""))
    return "el servidor respondió %d%s" % (status, ": %s" % (msg_srv or motivo) if (msg_srv or motivo) else "")


def obtener_clave(url, usuario, clave, timeout=TIMEOUT_DEFECTO_S, contexto_ssl=None):
    """Pide la clave del puente al servidor con una cuenta admin. Nunca lanza.

    url: la del puente (wss://…/ws/planta), la del sitio (https://…) o solo el host.
    usuario, clave: cuenta del gemelo con rol admin.
    contexto_ssl: ssl.SSLContext propio (p. ej. con una CA local); None = verificación normal.

    Éxito: {"ok": True, "clave": str, "url": base, "planta_en_linea": bool, "via": str|None,
            "mqtt": None|bool}
    Fallo: {"ok": False, "msg": texto en español, "status": código HTTP o None si no hubo respuesta}"""
    try:
        base = url_https(url)
    except ValueError as e:
        return _fallo(str(e))
    if not isinstance(usuario, str) or not usuario.strip():
        return _fallo("escribe el usuario de una cuenta admin del gemelo")
    if not isinstance(clave, str) or not clave:
        return _fallo("escribe la contraseña de la cuenta")
    cuerpo = json.dumps({"usuario": usuario.strip(), "clave": clave}).encode("utf-8")
    pedido = urllib.request.Request(base + RUTA_API, data=cuerpo, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8", "Accept": "application/json",
        "User-Agent": "scada-hmi-vincular/1"})
    try:
        with _abridor(base, contexto_ssl).open(pedido, timeout=timeout) as r:
            status = r.status
            crudo = r.read(MAX_RESPUESTA)
    except urllib.error.HTTPError as e:
        try:
            datos = _json_de(e.read(MAX_RESPUESTA))
        except (OSError, http.client.HTTPException):
            datos = None
        finally:
            e.close()
        return _fallo(_mensaje_http(base, e.code, datos, e.reason, e.headers), e.code)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        return _fallo("no se pudo conectar con %s: %s" % (base, _motivo(e)))
    except ValueError as e:         # dirección que urllib no acepta aunque url_https la diera por buena
        return _fallo("dirección no válida %s: %s" % (base, e))
    datos = _json_de(crudo)
    if datos is None:
        return _fallo("%s respondió algo que no es JSON: ¿es la dirección del servidor del gemelo?" % base, status)
    if datos.get("ok") is not True:
        return _fallo(datos.get("msg") if isinstance(datos.get("msg"), str) else
                      "el servidor rechazó la petición", status)
    recibida = datos.get("clave")
    recibida = recibida.strip() if isinstance(recibida, str) else ""
    if len(recibida) < MIN_CLAVE or any(c.isspace() for c in recibida):
        return _fallo("el servidor devolvió una clave del puente inválida (vacía o demasiado corta)", status)
    return {"ok": True, "clave": recibida, "url": base, "planta_en_linea": bool(datos.get("planta_en_linea")),
            "via": datos.get("via"), "mqtt": datos.get("mqtt")}


def guardar_clave(ruta, clave):
    """Escribe la clave (sin espacios alrededor y con salto de línea final) en `ruta`, en UTF-8,
    creando la carpeta. La escritura es atómica: o queda la clave nueva entera o la anterior.
    Clave corta o con espacios internos -> ValueError. Devuelve la ruta absoluta (str)."""
    if not isinstance(clave, str):
        raise ValueError("la clave del puente debe ser texto")
    limpia = clave.strip()
    if len(limpia) < MIN_CLAVE:
        raise ValueError("la clave del puente es demasiado corta (%d caracteres; mínimo %d)"
                         % (len(limpia), MIN_CLAVE))
    if any(c.isspace() for c in limpia):
        raise ValueError("la clave del puente no puede tener espacios ni saltos de línea en medio")
    ruta = os.path.abspath(os.fspath(ruta))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8", newline="\n") as f:
        f.write(limpia + "\n")
    os.replace(temporal, ruta)
    return ruta


def probar_clave(url, clave, timeout=TIMEOUT_DEFECTO_S, contexto_ssl=None, planta="prueba-de-clave"):
    """Saludo WebSocket a /ws/planta con `clave`. Nunca lanza. Devuelve
    {"ok": True, "status": 101, "msg"} si el servidor la acepta, {"ok": False, "status": 401, "msg"} si la
    rechaza, o {"ok": False, "status": None|n, "msg"} si no se pudo comprobar (sin conexión, proxy, 404…)."""
    try:
        base = url_https(url)
    except ValueError as e:
        return _fallo(str(e))
    partes = urllib.parse.urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    ruta = partes.path if partes.path.rstrip("/").endswith("/ws/planta") else "/ws/planta"
    b = urllib.parse.urlsplit(base)
    cabeceras = {"Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
                 "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode("ascii"),
                 "Authorization": "Bearer %s" % str(clave).strip(), "X-Planta": planta}
    try:
        if b.scheme == "https":
            conn = http.client.HTTPSConnection(b.hostname, b.port or 443, timeout=timeout,
                                               context=contexto_ssl or ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(b.hostname, b.port or 80, timeout=timeout)
        try:
            conn.request("GET", ruta, headers=cabeceras)
            resp = conn.getresponse()
            status = resp.status
            cuerpo = b"" if status == 101 else resp.read(300)
        finally:
            conn.close()
    except Exception as e:  # nunca lanzar: es un diagnóstico
        return _fallo("no se pudo conectar con %s: %s" % (base, _motivo(e)))
    if status == 101:
        return {"ok": True, "status": 101, "msg": "el servidor %s acepta la clave" % base}
    if status == 401:
        return _fallo("el servidor %s RECHAZA la clave (401 clave inválida): no es la que está usando" % base, 401)
    texto = cuerpo.decode("utf-8", "replace").strip()[:120]
    return _fallo("respuesta inesperada de %s%s: %d %s" % (base, ruta, status, texto), status)


def _resumen(clave):
    """Nunca se imprime la clave completa: solo sus 4 primeros caracteres."""
    return clave[:4] + "…"


def _argumentos(argv=None):
    p = argparse.ArgumentParser(prog="python -m puente.vincular",
                                description="Obtiene datos/puente.clave del servidor del gemelo con una cuenta admin.")
    p.add_argument("--url", default=URL_DEFECTO,
                   help="dirección del servidor: la del puente (wss://…/ws/planta) o la del sitio (defecto %s)"
                        % URL_DEFECTO)
    p.add_argument("--usuario", default=None, help="cuenta admin del gemelo (si falta, se pregunta)")
    p.add_argument("--clave-archivo", default=os.path.join(RAIZ, "datos", "puente.clave"),
                   help="dónde guardar la clave (defecto datos/puente.clave)")
    p.add_argument("--contrasena-stdin", action="store_true",
                   help="lee la contraseña de una línea de la entrada estándar en vez de pedirla")
    p.add_argument("--timeout", type=float, default=TIMEOUT_DEFECTO_S,
                   help="segundos de espera de la respuesta (defecto %.0f)" % TIMEOUT_DEFECTO_S)
    p.add_argument("--probar", action="store_true",
                   help="no pide cuenta: comprueba si el servidor acepta la clave guardada en --clave-archivo")
    p.add_argument("--guardar", metavar="CLAVE", default=None,
                   help="no pide cuenta: guarda esta clave (la que da el servidor) en --clave-archivo y la prueba")
    return p.parse_args(argv)


def _probar_y_contar(url, ruta, timeout):
    """--probar / --guardar: imprime el resultado del saludo y devuelve el código de salida."""
    try:
        with open(ruta, "r", encoding="utf-8-sig") as f:
            clave = f.read().strip()
    except OSError:
        print("[vincular] no existe %s: guárdala primero con --guardar <CLAVE>" % ruta)
        return 1
    print("[vincular] probando la clave %s (%d caracteres) contra %s…" % (_resumen(clave), len(clave), url))
    r = probar_clave(url, clave, timeout=timeout)
    print("[vincular] %s %s" % ("OK:" if r["ok"] else "ERROR:", r["msg"]))
    if r.get("status") == 401:
        print("[vincular] Pide en la PC del servidor la clave correcta: digital_twin\\despliegue\\clave_puente.bat")
    return 0 if r["ok"] else 1


def main(argv=None):
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no imprime "…"
        except (AttributeError, ValueError):
            pass
    a = _argumentos(argv)
    try:
        base = url_https(a.url)
    except ValueError as e:
        print("[vincular] ERROR: %s" % e)
        return 1
    if a.guardar is not None:
        try:
            ruta = guardar_clave(a.clave_archivo, a.guardar)
        except (OSError, ValueError) as e:
            print("[vincular] ERROR: %s" % e)
            return 1
        print("[vincular] clave guardada en %s" % ruta)
        return _probar_y_contar(a.url, ruta, a.timeout)
    if a.probar:
        return _probar_y_contar(a.url, os.path.abspath(a.clave_archivo), a.timeout)
    try:
        usuario = a.usuario
        if not usuario:
            if a.contrasena_stdin:
                usuario = sys.stdin.readline().strip()
            else:
                usuario = input("Usuario (cuenta admin del gemelo): ").strip()
        if a.contrasena_stdin:
            contrasena = sys.stdin.readline().rstrip("\r\n")
        else:
            contrasena = getpass.getpass("Contraseña de %s: " % usuario)
    except (EOFError, KeyboardInterrupt):
        print("\n[vincular] cancelado")
        return 1
    if base.startswith("http://") and not _es_local(base):
        print("[vincular] AVISO: %s no va cifrado; la contraseña y la clave viajarían en claro. Usa https:// o wss://."
              % base)
    print("[vincular] pidiendo la clave del puente a %s como «%s»…" % (base, usuario))
    r = obtener_clave(a.url, usuario, contrasena, timeout=a.timeout)
    if not r["ok"]:
        print("[vincular] ERROR: %s" % r["msg"])
        return 1
    ruta = os.path.abspath(a.clave_archivo)
    anterior = None
    try:
        with open(ruta, "r", encoding="utf-8-sig") as f:
            anterior = f.read().strip()
    except OSError:
        pass
    try:
        ruta = guardar_clave(ruta, r["clave"])
    except (OSError, ValueError) as e:
        print("[vincular] ERROR: se recibió la clave pero no se pudo guardar en %s: %s" % (ruta, e))
        return 1
    if anterior and anterior != r["clave"]:
        print("[vincular] se reemplazó la clave anterior de %s" % ruta)
    print("[vincular] clave recibida (%s) y guardada en %s" % (_resumen(r["clave"]), ruta))
    if r["planta_en_linea"]:
        print("[vincular] el servidor ya tiene un puente conectado (vía %s)" % (r.get("via") or "?"))
    else:
        print("[vincular] la planta está fuera de línea: arranca el puente con --url %s/ws/planta"
              % base.replace("https://", "wss://", 1).replace("http://", "ws://", 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
