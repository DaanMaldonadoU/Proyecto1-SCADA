# -*- coding: utf-8 -*-
"""
ui/herramientas/captura.py — Capturas del HMI sin pantalla para revisar el diseño.

Qué hace:
    Arranca el publicador (gateway falso por defecto, o el gateway real en SIM) como subproceso
    en puertos propios, levanta el HMI sin ventana visible (offscreen en Qt 6; en Qt 5, ventana
    nativa fuera del escritorio), espera `--espera` s, hace grabWindow() a 1920×1080 y a 1366×768
    y guarda los PNG en datos/capturas/

Uso (desde la raíz del repositorio):
    .venv\\Scripts\\python.exe ui\\herramientas\\captura.py [--espera 3] [--gateway falso|sim|ninguno]
        [--modo SIM|EMULATE|REAL] [--alarma] [--arrancar] [--sufijo _x] [--tamanos 1920x1080,1366x768]

Con PyQt5 (Qt 5.15) los archivos llevan el prefijo "qt5_" (qt5_hmi_1920x1080.png) para poder
compararlos con los de PySide6 (Qt 6); --prefijo lo cambia.

Requiere: Python 3.12+ de 64 bits con PySide6 6.x, o Python 3.12+ con PyQt5 5.15; pyzmq, msgpack.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from ui.qt_compat import BINDING, QTimer  # noqa: E402

# Qt 6: plataforma offscreen (sin ventana). Qt 5.15 en Windows: la plataforma offscreen no tiene
# OpenGL ni expone la ventana al grafo de escena y grabWindow() devuelve una imagen 0×0 (también con
# QT_QUICK_BACKEND=software). Con PyQt5 se usa la plataforma nativa y la ventana se coloca fuera
# del escritorio: no se ve, pero se renderiza y se puede capturar.
FUERA_DE_PANTALLA = False
if "QT_QPA_PLATFORM" not in os.environ:
    if BINDING == "PyQt5" and sys.platform == "win32":
        FUERA_DE_PANTALLA = True
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

from ui.app import MENSAJES, Aplicacion, ProcesoHijo, RUTA_GATEWAY_FALSO, crear_parser, preparar_qt  # noqa: E402
from ui import conexion  # noqa: E402

CARPETA = RAIZ / "datos" / "capturas"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Capturas PNG del HMI (sin ventana visible).")
    ap.add_argument("--espera", type=float, default=3.0, help="segundos antes de la primera captura")
    ap.add_argument("--gateway", choices=("falso", "sim", "ninguno"), default="falso")
    ap.add_argument("--modo", choices=("SIM", "EMULATE", "REAL"), default="SIM", help="modo del gateway falso")
    ap.add_argument("--alarma", action="store_true", help="gateway falso con una alarma fija activa")
    ap.add_argument("--sufijo", default="", help="sufijo del nombre de archivo")
    ap.add_argument("--prefijo", default="qt5_" if BINDING == "PyQt5" else "",
                    help="prefijo del nombre de archivo (por defecto 'qt5_' con PyQt5, nada con PySide6)")
    ap.add_argument("--arrancar", action="store_true", help="pulso STARTV a los 0,5 s (el gateway real no arranca solo)")
    ap.add_argument("--tamanos", default="1920x1080,1366x768")
    ap.add_argument("--pub", default="tcp://127.0.0.1:5585")
    ap.add_argument("--cmd", default="tcp://127.0.0.1:5586")
    a = ap.parse_args(argv)
    tamanos = [tuple(int(x) for x in t.lower().split("x")) for t in a.tamanos.split(",") if t]
    CARPETA.mkdir(parents=True, exist_ok=True)

    hijo = None
    if a.gateway == "falso":
        extra = ["--modo", a.modo] + (["--alarma-fija"] if a.alarma else [])
        hijo = ProcesoHijo("gateway falso", [sys.executable, str(RUTA_GATEWAY_FALSO), "--pub", a.pub, "--cmd", a.cmd] + extra)
    elif a.gateway == "sim":
        hijo = ProcesoHijo("gateway", [sys.executable, "-m", "gateway", "--modo", "SIM", "--pub", a.pub, "--cmd", a.cmd])

    app = preparar_qt()
    if hijo is not None:
        hijo.arrancar()
    guardadas = []
    try:
        # Configuración de conexión vacía y temporal: con la de datos/conexion.json el HMI arrancaría
        # solo el envío web guardado (p. ej. al servidor publicado) con los datos de la captura.
        conexion.RUTA_CONFIG = Path(tempfile.mkdtemp(prefix="captura_")) / "conexion.json"
        args_hmi = crear_parser().parse_args(["--pub", a.pub, "--cmd", a.cmd,
                                              "--ancho", str(tamanos[0][0]), "--alto", str(tamanos[0][1])])
        hmi = Aplicacion(args_hmi)
        ventana = hmi.ventana()
        if ventana is None:
            print("captura: no se pudo cargar el QML", file=sys.stderr)
            return 1

        if FUERA_DE_PANTALLA:
            ventana.setProperty("x", -20000)
            ventana.setProperty("y", -20000)
        pendientes = list(tamanos)

        def capturar():
            ancho, alto = pendientes.pop(0)
            img = ventana.grabWindow()
            ruta = CARPETA / ("%shmi_%dx%d%s.png" % (a.prefijo, ancho, alto, a.sufijo))
            img.save(str(ruta))
            guardadas.append((ruta, img.width(), img.height()))
            if pendientes:
                siguiente()
            else:
                app.quit()

        def siguiente():
            ancho, alto = pendientes[0]
            ventana.setProperty("width", ancho)
            ventana.setProperty("height", alto)
            QTimer.singleShot(1200, capturar)   # deja que el layout y los Canvas se repinten

        if a.arrancar:
            QTimer.singleShot(500, lambda: hmi.planta.pulso("STARTV"))
        QTimer.singleShot(int(a.espera * 1000), capturar)
        QTimer.singleShot(int((a.espera + 5 + 2 * len(tamanos)) * 1000), app.quit)   # salvavidas
        app.exec()
        print("captura: seq %d, etapa X%s, modo %s; %d avisos y %d errores de Qt/QML"
              % (hmi.planta.seq, hmi.planta.etapa, hmi.planta.modo, MENSAJES["avisos"], MENSAJES["errores"]))
        hmi.cerrar()
    finally:
        if hijo is not None:
            hijo.terminar()
    for ruta, w, h in guardadas:
        print("captura: %s (%d×%d)" % (ruta, w, h))
    return 0 if len(guardadas) == len(tamanos) else 1


if __name__ == "__main__":
    sys.exit(main())
