# -*- coding: utf-8 -*-
r"""
gateway/diagnostico_opc.py — Diagnóstico de la conexión OPC DA (RSLinx) sin Qt ni gateway.

Qué hace:
    1. Lista los servidores OPC registrados y los topics del servidor elegido.
    2. Lee los items de la tabla vigente (core/tags.py: las 4 palabras, los 6 temporizadores
       y el contador) N veces, primero desde el dispositivo y luego desde la caché de RSLinx,
       y muestra valor, calidad y tiempos (mínimo, medio, p95, máximo) de cada variante.
    3. Con --probar-preajustes reescribe T4:0.PRE con SU MISMO VALOR y lo relee: sirve para
       comprobar que RSLinx acepta escribir preajustes de temporizador sin cambiar nada en el
       PLC. En modo REAL exige --confirmar-real.
    4. Selector de v6.1 (servidores → topics → archivos → items → lectura de prueba):
       --archivos (archivos de datos del topic, bajo <topic>.Online), --items RUTA (items de
       un archivo, p. ej. PROYECTO1_TEST.Online.I1) y --leer ITEM (una lectura síncrona).
    5. --json: un solo objeto JSON en stdout, para la ventana de conexión del HMI
       (ui/conexion.py, que corre en Python de 64 bits y no puede hablar COM). Contrato en
       mds/ARQUITECTURA.md §6.4:
           --servidores      {"ok": true, "servidores": [...]}
           --topics          {"ok": true, "topics": [...]}
           --archivos        {"ok": true, "ruta": "<topic>.Online", "archivos": [...]}
           --items RUTA      {"ok": true, "items": [...]}
           --leer ITEM       {"ok": true, "item": "[TOPIC]I:1.0", "valor": v, "calidad": "Good"}
           error             {"ok": false, "error": "..."} y código de salida 2 (también si
                             falta OpenOPC o el cliente COM no se puede crear, p. ej. en 64 bits)
       Sin --json la salida de texto es la de siempre.

Dónde se usa: en el laboratorio (SLC 5/04 por DF1, Python 3.12 de 32 bits), antes de arrancar
    el gateway. También sirve para descubrir el nombre exacto del servidor y del topic.

Uso (desde la raíz del repositorio, con el Python de 32 bits):
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --servidores
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topics
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topic PROYECTO1_TEST --archivos
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --items PROYECTO1_TEST.Online.I1
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topic PROYECTO1_TEST --leer I:1.0
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --json --servidores
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topic PROYECTO1_TEST --modo REAL --n 30
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topic PROYECTO1_TEST --probar-preajustes
    .venv32\Scripts\python.exe -m gateway.diagnostico_opc --topic PROYECTO1_TEST --modo REAL --probar-preajustes --confirmar-real

Requiere: Python 3.12+ de 32 bits en la misma máquina que RSLinx, pywin32 y OpenOPC-Python3x.
    Solo biblioteca estándar; OpenOPC se importa dentro de una función (así el módulo se
    importa y se prueba sin Windows). No escribe nunca en O:2 ni en I:1 ni en bits de mando
    (STARTV/STOPV/RESETV).
"""
import argparse
import json
import os
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from core import tags  # noqa: E402

SERVIDOR_DEFECTO = "RSLinx Local OPC Server"
TOPIC_DEFECTO = "PROYECTO1_TEST"
CODIGO_ERROR_JSON = 2


class ErrorDiagnostico(Exception):
    """Error con mensaje para el usuario (texto o JSON según el modo)."""


def _utf8_consola():
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _es_32_bits():
    return sys.maxsize <= 2 ** 32


def _cliente():
    """Cliente COM de OpenOPC. Lanza ErrorDiagnostico con un mensaje claro si no se puede."""
    try:
        import OpenOPC  # solo Windows, 32 bits, misma máquina que RSLinx
    except ImportError:
        raise ErrorDiagnostico(
            "Falta OpenOPC: instala pywin32 y OpenOPC-Python3x en este Python de 32 bits "
            "(requirements-gateway.txt)" + ("" if _es_32_bits() else
                                            ". Además este Python es de 64 bits: OPC DA de RSLinx es COM de 32 bits"))
    try:
        return OpenOPC.client()
    except Exception as e:  # pragma: no cover - depende de COM
        raise ErrorDiagnostico(
            "No se pudo crear el cliente COM de OpenOPC: %s. %s" % (
                e, "¿Está registrada gbda_aut.dll en C:\\Windows\\SysWOW64?" if _es_32_bits()
                else "Este Python es de 64 bits: OPC DA de RSLinx es COM de 32 bits (usa py -3.12-32)."))


def _estadisticas(ms):
    ms = sorted(ms)
    if not ms:
        return "sin muestras"
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    return "min %.1f · medio %.1f · p95 %.1f · máx %.1f ms (%d lecturas)" % (
        ms[0], statistics.mean(ms), p95, ms[-1], len(ms))


# ============================================================================
# Descubrimiento (reciben el cliente `opc` por parámetro: se prueban con un OpenOPC falso)
# ============================================================================
def servidores(opc):
    """Servidores OPC DA registrados en esta máquina."""
    return [str(s) for s in opc.servers()]


def topics(opc, servidor):
    """Topics del servidor (RSLinx los lista como '[TOPIC]')."""
    opc.connect(servidor)
    return [str(t).strip("[]") for t in opc.list()]


def archivos(opc, servidor, topic):
    """Archivos de datos del topic: RSLinx los expone bajo <topic>.Online (O0, I1, B3, T4, …).

    Devuelve (ruta, [archivos]). Si '<topic>.Online' no da nada se prueba con el topic a secas
    (otros servidores OPC no tienen el nivel Online).
    """
    opc.connect(servidor)
    for ruta in ("%s.Online" % topic, topic):
        try:
            r = [str(x) for x in opc.list(ruta)]
        except Exception:
            r = []
        if r:
            return ruta, r
    return "%s.Online" % topic, []


def items(opc, servidor, ruta):
    """Items (hojas) de un archivo de datos, p. ej. 'PROYECTO1_TEST.Online.I1'."""
    opc.connect(servidor)
    return [str(x) for x in opc.list(ruta, flat=True)]


def item_completo(topic, item):
    """'I:1.0' → '[TOPIC]I:1.0'; si ya trae '[…]' se respeta."""
    item = str(item).strip()
    if item.startswith("["):
        return item
    return "[%s]%s" % (topic, item)


def leer_item(opc, servidor, topic, item):
    """Una lectura síncrona del item. Devuelve (item_completo, valor, calidad)."""
    opc.connect(servidor)
    completo = item_completo(topic, item)
    _nombre, valor, calidad, _marca = opc.read([completo], sync=True)[0]
    return completo, valor, str(calidad)


# ============================================================================
# Salida de texto (igual que siempre)
# ============================================================================
def listar_servidores(opc):
    print("Servidores OPC DA registrados:")
    for s in servidores(opc):
        print("  -", s)


def listar_topics(opc, servidor):
    print("Topics de '%s':" % servidor)
    for t in topics(opc, servidor):
        print("  -", t)


def listar_archivos(opc, servidor, topic):
    ruta, lista = archivos(opc, servidor, topic)
    print("Archivos de datos en %s:" % ruta)
    for a in lista:
        print("  -", a)


def listar_items(opc, servidor, ruta):
    print("Items de %s:" % ruta)
    for it in items(opc, servidor, ruta):
        print("  -", it)


def mostrar_lectura_item(opc, servidor, topic, item):
    completo, valor, calidad = leer_item(opc, servidor, topic, item)
    print("Lectura de %s → valor=%s  calidad=%s" % (completo, valor, calidad))


def leer_items(opc, servidor, topic, n, fuente, grupo):
    items_ = [tags.item_opc(topic, d) for d in tags.ITEMS_RAPIDOS + tags.ITEMS_LENTOS]
    tiempos, ultimo = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        ultimo = opc.read(items_, group=grupo, sync=True, source=fuente, update=100)
        tiempos.append((time.perf_counter() - t0) * 1000.0)
    try:
        opc.remove(grupo)
    except Exception:
        pass
    return ultimo, tiempos


def mostrar_lectura(crudos):
    malos = 0
    for nombre, valor, calidad, marca in crudos:
        ok = calidad == "Good"
        malos += 0 if ok else 1
        direccion = nombre.split("]", 1)[-1]
        extra = ""
        if direccion in tags.PALABRAS and ok and valor is not None:
            activos = [t for t, v in tags.decodificar_palabra(direccion, valor).items() if v]
            extra = "  bits=1: " + (", ".join(activos) if activos else "ninguno")
        print("  %-12s %-8s %-8s %s%s" % (direccion, str(valor), calidad, marca, extra))
    return malos


def probar_preajustes(opc, topic):
    item = tags.item_opc(topic, "T4:0.PRE")
    nombre, valor, calidad, _ = opc.read([item], sync=True, source="device")[0]
    if calidad != "Good" or valor is None:
        print("No se pudo leer %s (calidad %s); no se prueba la escritura." % (item, calidad))
        return False
    valor = int(valor)
    print("Escribiendo %s = %d (su mismo valor actual)…" % (item, valor))
    res = opc.write([(item, valor)])
    print("  respuesta de write:", res)
    _, releido, calidad2, _ = opc.read([item], sync=True, source="device")[0]
    ok = calidad2 == "Good" and int(releido) == valor and (not res or all(r[1] == "Success" for r in res))
    print("  relectura: %s (calidad %s) → %s" % (releido, calidad2, "OK, RSLinx acepta escribir PRE" if ok else "FALLO"))
    return ok


# ============================================================================
# Salida JSON (ventana de conexión del HMI)
# ============================================================================
def _valor_json(v):
    """Valores COM (pywintypes, Decimal, bytes…) a algo serializable."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_valor_json(x) for x in v]
    return str(v)


def resultado_json(opc, a):
    """Ejecuta el subcomando elegido y devuelve el dict a imprimir (sin la clave 'ok')."""
    if a.servidores:
        return {"servidores": servidores(opc)}
    if a.topics:
        return {"topics": topics(opc, a.servidor)}
    if a.archivos:
        ruta, lista = archivos(opc, a.servidor, a.topic)
        return {"ruta": ruta, "archivos": lista}
    if a.items is not None:
        return {"items": items(opc, a.servidor, a.items)}
    if a.leer is not None:
        completo, valor, calidad = leer_item(opc, a.servidor, a.topic, a.leer)
        return {"item": completo, "valor": _valor_json(valor), "calidad": calidad}
    raise ErrorDiagnostico("--json requiere --servidores, --topics, --archivos, --items RUTA o --leer ITEM")


def _imprimir_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _main_json(a):
    try:
        opc = _cliente()
    except ErrorDiagnostico as e:
        _imprimir_json({"ok": False, "error": str(e)})
        return CODIGO_ERROR_JSON
    try:
        res = resultado_json(opc, a)
    except ErrorDiagnostico as e:
        _imprimir_json({"ok": False, "error": str(e)})
        return CODIGO_ERROR_JSON
    except Exception as e:
        _imprimir_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
        return CODIGO_ERROR_JSON
    finally:
        try:
            opc.close()
        except Exception:
            pass
    res["ok"] = True
    _imprimir_json(res)
    return 0


# ============================================================================
# Línea de órdenes
# ============================================================================
def crear_parser():
    ap = argparse.ArgumentParser(description="Diagnóstico OPC DA contra RSLinx (sin Qt, sin gateway).")
    ap.add_argument("--servidor", default=SERVIDOR_DEFECTO)
    ap.add_argument("--topic", default=TOPIC_DEFECTO)
    ap.add_argument("--modo", choices=("EMULATE", "REAL"), default="EMULATE")
    ap.add_argument("--n", type=int, default=20, help="lecturas por variante (defecto 20)")
    ap.add_argument("--servidores", action="store_true", help="solo listar servidores OPC")
    ap.add_argument("--topics", action="store_true", help="solo listar topics del servidor")
    ap.add_argument("--archivos", action="store_true", help="archivos de datos del topic (<topic>.Online)")
    ap.add_argument("--items", metavar="RUTA", default=None, help="items de un archivo, p. ej. PROYECTO1_TEST.Online.I1")
    ap.add_argument("--leer", metavar="ITEM", default=None, help="una lectura de prueba, p. ej. I:1.0 o [TOPIC]B3:0/0")
    ap.add_argument("--json", action="store_true", help="un solo objeto JSON en stdout (ventana de conexión del HMI)")
    ap.add_argument("--probar-preajustes", action="store_true",
                    help="reescribe T4:0.PRE con su valor actual y relee")
    ap.add_argument("--confirmar-real", action="store_true",
                    help="permite --probar-preajustes en modo REAL")
    return ap


def main(argv=None):
    _utf8_consola()
    a = crear_parser().parse_args(argv)

    if a.json:
        return _main_json(a)

    print("Python %s · %s bits · %s" % (sys.version.split()[0], "32" if _es_32_bits() else "64", sys.executable))
    if not _es_32_bits():
        print("AVISO: OPC DA de RSLinx es COM de 32 bits; con un Python de 64 bits la conexión fallará.")

    try:
        opc = _cliente()
    except ErrorDiagnostico as e:
        sys.exit(str(e))
    try:
        if a.servidores:
            listar_servidores(opc)
            return 0
        if a.topics:
            listar_topics(opc, a.servidor)
            return 0
        if a.archivos:
            listar_archivos(opc, a.servidor, a.topic)
            return 0
        if a.items is not None:
            listar_items(opc, a.servidor, a.items)
            return 0
        if a.leer is not None:
            mostrar_lectura_item(opc, a.servidor, a.topic, a.leer)
            return 0

        opc.connect(a.servidor)
        print("Conectado a '%s'. Topic [%s]. %d items." % (
            a.servidor, a.topic, len(tags.ITEMS_RAPIDOS) + len(tags.ITEMS_LENTOS)))

        for fuente in ("device", "cache"):
            print("\n=== Lectura desde %s (%d veces) ===" % ("el DISPOSITIVO" if fuente == "device" else "la CACHÉ de RSLinx", a.n))
            crudos, tiempos = leer_items(opc, a.servidor, a.topic, a.n, fuente, "diag_" + fuente)
            malos = mostrar_lectura(crudos)
            print("  Tiempos:", _estadisticas(tiempos))
            print("  Items sin calidad Good: %d" % malos)

        if a.probar_preajustes:
            print("\n=== Escritura de preajuste ===")
            if a.modo == "REAL" and not a.confirmar_real:
                print("Modo REAL: añade --confirmar-real para reescribir T4:0.PRE con su mismo valor.")
            else:
                probar_preajustes(opc, a.topic)
        return 0
    finally:
        try:
            opc.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
