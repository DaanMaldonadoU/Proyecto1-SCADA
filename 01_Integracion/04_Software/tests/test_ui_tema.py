# -*- coding: utf-8 -*-
"""
tests/test_ui_tema.py — Tema de pantalla oscuro | gris ISA-101 (sesión 14).

* `Planta.tema` / `fijarTema` se guardan en datos/preferencias_hmi.json (aquí en tmp_path).
* El interceptor de ui/app.py hace que `UI.Theme` sea ui/qml/tema/Theme.qml: se carga el HMI completo
  sin ventana en un subproceso (necesita un QGuiApplication propio) y se comprueba que el fondo de la
  ventana cambia al pasar a gris y vuelve al color exacto del sistema de diseño en oscuro.

Saltan sin binding de Qt. Python 3.12+.
"""
import os
import re
import subprocess
import sys
import textwrap

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("ui.qt_compat")

from ui import cliente  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tema_se_guarda_y_valida(tmp_path, monkeypatch):
    from ui.qt_compat import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(cliente, "RUTA_PREFERENCIAS", tmp_path / "pref.json")
    monkeypatch.setattr(cliente, "RUTA_CALIBRACION", tmp_path / "cal.json")
    p = cliente.Planta()
    assert p.tema == "oscuro" and p.temas == ["oscuro", "gris"]
    p.fijarTema("verde")                       # desconocido: se ignora
    assert p.tema == "oscuro"
    p.fijarTema("gris")
    assert p.tema == "gris" and '"tema": "gris"' in (tmp_path / "pref.json").read_text(encoding="utf-8")
    assert cliente.Planta().tema == "gris"     # se recuerda
    p.cerrar()


def test_interceptor_cambia_los_colores_del_qml(tmp_path):
    original = open(os.path.join(RAIZ, "assets", "assets_cilindros", "ui", "qml", "Theme.qml"), encoding="utf-8").read()
    fondo_original = re.search(r'fondo:\s*"(#[0-9A-Fa-f]{6})"', original).group(1).lower()
    guion = textwrap.dedent(r"""
        import os, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, sys.argv[1])
        from ui import app as appmod, cliente, conexion
        cliente.RUTA_PREFERENCIAS = os.path.join(sys.argv[2], "pref.json")
        cliente.RUTA_CALIBRACION = os.path.join(sys.argv[2], "cal.json")
        conexion.RUTA_CONFIG = os.path.join(sys.argv[2], "conexion.json")
        qapp = appmod.preparar_qt()
        hmi = appmod.Aplicacion(appmod.crear_parser().parse_args(
            ["--sin-conexion", "--pub", "tcp://127.0.0.1:1", "--cmd", "tcp://127.0.0.1:2"]))
        v = hmi.ventana()
        def color():
            qapp.processEvents()
            return v.property("color").name()
        print("OSCURO", color())
        hmi.planta.fijarTema("gris")
        print("GRIS", color())
        hmi.planta.fijarTema("oscuro")
        print("OTRA_VEZ", color())
        hmi.cerrar()
    """)
    r = subprocess.run([sys.executable, "-c", guion, RAIZ, str(tmp_path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120, cwd=RAIZ)
    salida = dict(l.split(" ", 1) for l in r.stdout.splitlines() if l.split(" ", 1)[0] in ("OSCURO", "GRIS", "OTRA_VEZ"))
    assert set(salida) == {"OSCURO", "GRIS", "OTRA_VEZ"}, r.stdout + r.stderr
    assert salida["OSCURO"] == fondo_original == salida["OTRA_VEZ"]
    assert salida["GRIS"] == "#bfc4ca"
    assert "[ERROR]" not in r.stderr, r.stderr
