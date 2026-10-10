# -*- coding: utf-8 -*-
"""
tests/test_dummydata.py — Los datos de prueba de Qt Design Studio siguen al día con ui/.

Qué prueba: ui/qml/dummydata/ (lo genera ui/herramientas/generar_dummydata.py) imita a los
objetos que ui/app.py pone en el contexto del motor QML. Si `Planta`, `Conexion` o `Historial`
ganan una propiedad, un slot o una señal y nadie regenera los archivos, Design Studio mostraría
la pantalla con huecos o errores. Aquí se comparan los nombres declarados en cada clase
(metaobjeto estático de Qt, sin instanciar nada) con los que aparecen en el QML.

También comprueba que `rutaAssets.qml` declara `toString(): string`: sin el tipo de retorno el
motor recibe un QVariant vacío y ninguna imagen carga.

Si falla: .venv\\Scripts\\python.exe ui\\herramientas\\generar_dummydata.py
Salta si no hay binding de Qt. Requiere: Python 3.12+ con PySide6 o PyQt5.
"""
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("ui.qt_compat")

from ui.cliente import Planta  # noqa: E402
from ui.conexion import Conexion  # noqa: E402
from ui.historial import Historial  # noqa: E402

DUMMYDATA = Path(__file__).resolve().parent.parent / "ui" / "qml" / "dummydata"


def _texto(x):
    return x if isinstance(x, str) else bytes(x).decode()


def nombres(cls):
    """(propiedades, slots, señales) declarados por la clase, sin los de sus bases de Qt."""
    mo = cls.staticMetaObject
    props = {_texto(mo.property(i).name()) for i in range(mo.propertyOffset(), mo.propertyCount())}
    slots, senales = set(), set()
    for i in range(mo.methodOffset(), mo.methodCount()):
        m = mo.method(i)
        nombre = _texto(m.name())
        if nombre.startswith("_"):
            continue
        tipo = int(getattr(m.methodType(), "value", m.methodType()))
        if tipo == 2:
            slots.add(nombre)
        elif tipo == 1 and not (nombre.endswith("Changed") and nombre[:-len("Changed")] in props):
            senales.add(nombre)
    return props, slots, senales


def declarados(archivo):
    texto = (DUMMYDATA / archivo).read_text(encoding="utf-8")
    props = set(re.findall(r"\bproperty\s+\w+\s+(\w+)\s*:", texto))
    funciones = set(re.findall(r"\bfunction\s+(\w+)\s*\(", texto))
    senales = set(re.findall(r"\bsignal\s+(\w+)\s*\(", texto))
    return props, funciones, senales


@pytest.mark.parametrize("archivo, cls", [("planta.qml", Planta), ("conexion.qml", Conexion),
                                          ("historial.qml", Historial)])
def test_dummydata_tiene_todo_lo_de_la_clase(archivo, cls):
    props, slots, senales = nombres(cls)
    q_props, q_funciones, q_senales = declarados(archivo)
    assert props, "la clase %s no expone propiedades (¿metaobjeto equivocado?)" % cls.__name__
    assert not props - q_props, "faltan propiedades en %s: %s" % (archivo, sorted(props - q_props))
    assert not slots - q_funciones, "faltan funciones en %s: %s" % (archivo, sorted(slots - q_funciones))
    assert not senales - q_senales, "faltan señales en %s: %s" % (archivo, sorted(senales - q_senales))


def test_dummydata_archivos_de_contexto():
    # Los mismos nombres que ui/app.py pasa a setContextProperty.
    esperados = {"planta", "conexion", "historial", "datosInstitucion", "rutaAssets", "configVentana"}
    assert {p.stem for p in DUMMYDATA.glob("*.qml")} == esperados


def test_ruta_assets_devuelve_cadena():
    texto = (DUMMYDATA / "rutaAssets.qml").read_text(encoding="utf-8")
    assert "function toString(): string" in texto
    assert "../../../assets/assets_cilindros/" in texto
