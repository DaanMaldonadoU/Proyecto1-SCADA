# -*- coding: utf-8 -*-
r"""
digital_twin/servidor_web/diagnostico_clave.py — ¿Por qué el puente no entra? Diagnóstico de la clave en la PC servidor.

El puente del laboratorio entra en /ws/planta con la clave compartida. El servidor la lee **al arrancar**
de <datos>/puente.clave (defecto digital_twin\datos\ de la carpeta desde la que corre). Si el archivo
que uno mira no es el que leyó el servidor en marcha (otra carpeta, otro --datos, o se creó o cambió
después de arrancar), el puente recibe «401 clave inválida» aunque la clave «sea la del servidor».

Uso en la PC servidor (doble clic o consola, desde la carpeta del repositorio):

    digital_twin\despliegue\clave_puente.bat                 # diagnóstico
    digital_twin\despliegue\clave_puente.bat fijar <CLAVE>   # el servidor usará esta clave (la del HMI)
    .venv-web\Scripts\python.exe -m digital_twin.servidor_web clave-diagnostico
    .venv-web\Scripts\python.exe -m digital_twin.servidor_web clave-fijar <CLAVE>

Qué hace el diagnóstico:
    1. Muestra el archivo de clave de ESTA carpeta (sus 4 primeros caracteres y su largo).
    2. Busca qué proceso escucha en el puerto del servidor (3002) y desde qué carpeta corre; avisa si
       es otra carpeta o si arrancó con otro --datos.
    3. Si ya hay un puente conectado por WebSocket (GET /api/salud), no prueba nada: la clave funciona y
       probarla desplazaría a ese puente.
    4. Prueba la clave en el propio servidor (ws://127.0.0.1:3002/ws/planta) y por Internet
       (wss://digitaltwinscada.smartsensorslab.com/ws/planta), y dice qué hacer en cada caso.
    5. Si la clave vale, la imprime completa para copiarla al laboratorio (datos\puente.clave del HMI,
       o «o pega» → Guardar clave en la ventana de conexión).

`fijar` guarda la clave dada (la copia anterior queda como puente.clave.anterior-AAAAMMDD-HHMMSS) y
recuerda reiniciar el servidor, que solo la lee al arrancar.

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar (usa puente/vincular.py).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from puente.vincular import MIN_CLAVE, guardar_clave, probar_clave  # noqa: E402

URL_PUBLICA_DEFECTO = "wss://digitaltwinscada.smartsensorslab.com/ws/planta"


def resumen(clave):
    return "%s… (%d caracteres)" % (clave[:4], len(clave))


def leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return None


def proceso_en_puerto(puerto):
    """{"pid", "orden", "carpeta", "datos"} del proceso que escucha en 127.0.0.1:<puerto> (solo Windows;
    None si no hay o no se pudo averiguar). `carpeta` = la del repositorio (la que contiene .venv-web)."""
    if sys.platform != "win32":
        return None
    try:
        salida = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                                errors="replace", timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = None
    for linea in salida.splitlines():
        p = linea.split()
        if len(p) >= 5 and p[1].endswith(":%d" % puerto) and p[3].upper() in ("LISTENING", "ESCUCHANDO"):
            pid = p[4]
            break
    if pid is None:
        return {}
    info = {"pid": pid, "orden": "", "carpeta": None, "datos": None}
    try:
        orden = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-CimInstance Win32_Process -Filter 'ProcessId=%s').CommandLine" % pid],
                               capture_output=True, text=True, errors="replace", timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        orden = ""
    info["orden"] = orden
    m = re.search(r'"?([A-Za-z]:\\[^"]*?)\\\.venv[^\\"]*\\Scripts\\python', orden)
    if m:
        info["carpeta"] = m.group(1)
    m = re.search(r'--datos\s+("([^"]+)"|(\S+))', orden)
    if m:
        info["datos"] = m.group(2) or m.group(3)
    return info


def salud(puerto, timeout=5.0):
    try:
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with abridor.open("http://127.0.0.1:%d/api/salud" % puerto, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def diagnosticar(datos, puerto=3002, url_publica=URL_PUBLICA_DEFECTO, probar_publica=True, log=print):
    """Imprime el diagnóstico y devuelve un código: "ok" | "sin_archivo" | "sin_servidor" | "rechazada" |
    "proxy" | "sin_internet" | "puente_conectado"."""
    ruta = os.path.abspath(os.path.join(datos, "puente.clave"))
    log("== Clave del puente: diagnóstico (%s) ==" % time.strftime("%Y-%m-%d %H:%M:%S"))
    log("Carpeta de esta herramienta : %s" % RAIZ)
    clave = leer(ruta)
    if clave is None:
        log("Archivo de clave            : %s  (NO EXISTE)" % ruta)
        log("-> El servidor lo crea la primera vez que arranca. Arranca digital_twin\\despliegue\\servidor.bat")
        log("   desde ESTA carpeta y vuelve a ejecutar este diagnóstico.")
        return "sin_archivo"
    log("Archivo de clave            : %s  (%s)" % (ruta, resumen(clave)))

    proc = proceso_en_puerto(puerto)
    if proc == {}:
        log("Servidor en el puerto       : NINGUNO escucha en el %d. Arranca digital_twin\\despliegue\\servidor.bat." % puerto)
        return "sin_servidor"
    if proc:
        log("Servidor en el puerto       : %d, proceso %s" % (puerto, proc["pid"]))
        if proc["orden"]:
            log("  orden                     : %s" % proc["orden"])
        if proc["carpeta"] and os.path.normcase(os.path.abspath(proc["carpeta"])) != os.path.normcase(RAIZ):
            log("  AVISO: el servidor corre desde OTRA carpeta: %s" % proc["carpeta"])
            log("         Su clave es la de %s" % os.path.join(proc["carpeta"], "digital_twin", "datos", "puente.clave"))
            log("         Ejecuta este diagnóstico desde esa carpeta.")
        if proc["datos"]:
            log("  AVISO: el servidor arrancó con --datos %s: su clave es la de esa carpeta." % proc["datos"])

    s = salud(puerto)
    if s is None:
        log("GET /api/salud              : sin respuesta en http://127.0.0.1:%d (¿es otro programa?)" % puerto)
    else:
        log("GET /api/salud              : planta_en_linea=%s via=%s" % (s.get("planta_en_linea"), s.get("via")))
        if s.get("planta_en_linea") and s.get("via") == "ws":
            log("-> Ya hay un puente conectado por WebSocket: la clave que usa el laboratorio funciona.")
            log("   No se prueba nada para no desconectarlo.")
            return "puente_conectado"

    local = probar_clave("ws://127.0.0.1:%d/ws/planta" % puerto, clave, planta="diagnostico-clave (servidor)")
    log("Prueba en el propio servidor: %s" % local["msg"])
    if not local["ok"]:
        if local.get("status") == 401:
            log("")
            log("-> El servidor EN MARCHA no usa esta clave. Lo más probable: el archivo se creó o cambió después")
            log("   de arrancarlo, o el servidor corre desde otra carpeta (ver arriba). Arreglo:")
            log("     1. Cierra la consola de servidor.bat (o: nssm restart GemeloDigital) y vuelve a arrancarlo")
            log("        desde ESTA carpeta: así lee %s" % ruta)
            log("     2. Vuelve a ejecutar este diagnóstico: debe decir que acepta la clave.")
            log("   O, para usar la clave que ya tiene el HMI:  clave_puente.bat fijar <CLAVE_DEL_HMI>  y reiniciar.")
            return "rechazada"
        log("-> No se pudo probar en el propio servidor; revisa que servidor.bat esté en marcha en el puerto %d." % puerto)
        return "sin_servidor"

    resultado = "ok"
    if probar_publica:
        publica = probar_clave(url_publica, clave, planta="diagnostico-clave (internet)")
        log("Prueba por Internet         : %s" % publica["msg"])
        if not publica["ok"]:
            if publica.get("status") == 401:
                log("-> Dentro acepta y por Internet no: el proxy (Caddy/cloudflared) quita la cabecera Authorization")
                log("   o apunta a otro servidor. Revisa su configuración (mds/DESPLIEGUE_SERVIDOR.md §3).")
                resultado = "proxy"
            else:
                log("-> Dentro funciona, pero no se llega por Internet: revisa el túnel o el proxy y el DNS.")
                resultado = "sin_internet"
    log("")
    log("== La clave del servidor es correcta. Cópiala TAL CUAL a la PC del laboratorio: ==")
    log(clave)
    log("En el laboratorio: datos\\puente.clave (o lab\\clave_puente.bat <CLAVE>, o en el HMI: Conexión… → Servidor web")
    log("→ «o pega» → Guardar clave). Luego Envío de datos = Servidor web → Conectar.")
    log("(Cada prueba aceptada aparece en la auditoría como «puente conectado / desconectado».)")
    return resultado


def fijar(datos, clave, log=print):
    """Hace que el servidor use `clave` (la del HMI): la guarda en <datos>/puente.clave y conserva la anterior."""
    clave = str(clave).strip()
    if len(clave) < MIN_CLAVE:
        raise ValueError("la clave es demasiado corta (%d caracteres; mínimo %d)" % (len(clave), MIN_CLAVE))
    ruta = os.path.abspath(os.path.join(datos, "puente.clave"))
    anterior = leer(ruta)
    if anterior == clave:
        log("La clave de %s ya es esa (%s)." % (ruta, resumen(clave)))
    else:
        if anterior is not None:
            copia = ruta + ".anterior-" + time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(ruta, copia)          # copia, no mover: el archivo nunca falta
            log("Clave anterior (%s) guardada en %s" % (resumen(anterior), copia))
        guardar_clave(ruta, clave)
        log("Clave nueva (%s) guardada en %s" % (resumen(clave), ruta))
    log("")
    log("AHORA REINICIA EL SERVIDOR (cierra servidor.bat y ábrelo otra vez, o: nssm restart GemeloDigital):")
    log("solo lee la clave al arrancar. Después ejecuta clave_puente.bat para comprobarlo.")
    return ruta
