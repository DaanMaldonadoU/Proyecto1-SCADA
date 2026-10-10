# -*- coding: utf-8 -*-
"""Pruebas de ui.historial.Historial (QObject del visor) sin ventana (mds/ARQUITECTURA.md 6.5 y 6.6).

Saltan si no hay binding de Qt. Comparten la QCoreApplication del proceso con los demás módulos
de prueba de ui/ (`QCoreApplication.instance() or QCoreApplication([])`). No se usa el motor QML:
se comprueba el modelo (roles), las propiedades, los slots y la exportación.
"""
import os
import re
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt = pytest.importorskip("ui.qt_compat")

from core.historial import Historial as HistorialGateway  # noqa: E402
from ui.historial import ROLES, Historial, duracion, fila_escritura  # noqa: E402

app = qt.QtCore.QCoreApplication.instance() or qt.QtCore.QCoreApplication([])

AHORA = time.time()
HORA = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")
FECHA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


@pytest.fixture
def ruta(tmp_path):
    """Base con 4 eventos (dos de la última hora, uno de hace 3 h, otro de hace 2 días), 2 alarmas y 3 escrituras."""
    r = str(tmp_path / "historial.sqlite")
    h = HistorialGateway(r)
    h.evento({"t": AHORA - 30, "nivel": "info", "msg": "Marcha (ACTIVE = 1)", "origen": "gateway"})
    h.evento({"t": AHORA - 20, "nivel": "aviso", "msg": "Escritura rechazada T_NEUM=99999", "origen": "gateway"})
    h.evento({"t": AHORA - 3 * 3600, "nivel": "info", "msg": "Gateway SIM listo", "origen": "gateway"})
    h.evento({"t": AHORA - 2 * 86400, "nivel": "alarma", "msg": "Desconectado", "origen": "gateway"})
    a1 = {"id": "calidad", "nivel": "aviso", "msg": "Items sin calidad Good", "t_ini": AHORA - 10, "activa": True}
    a2 = {"id": "etapa_excedida", "nivel": "alarma", "msg": "Etapa X2 excedida", "t_ini": AHORA - 5, "activa": True}
    h.alarma(a1, True)
    h.alarma(a2, True)
    h.alarma(dict(a1, activa=False, t_fin=AHORA - 8.5), False)
    h.escritura(AHORA - 25, "STARTV", 1, True, "[HMI local]")
    h.escritura(AHORA - 20, "T_NEUM", 99999, False, "[HMI local] fuera de rango")
    h.escritura(AHORA - 15, "T_ESPERA", 150, True, "[web:ana (operador)]")
    h.volcar()
    assert h.esperar()
    h.cerrar()
    return r


def _roles(modelo):
    return {v.data().decode("ascii"): k for k, v in modelo.roleNames().items()}


def _fila(modelo, i):
    roles = _roles(modelo)
    ix = modelo.index(i, 0)
    return {nombre: modelo.data(ix, rol) for nombre, rol in roles.items()}


def test_consultar_eventos(ruta):
    h = Historial(ruta=ruta)
    assert h.ruta == ruta and h.tabla == "eventos" and h.error == ""
    assert h.filas.rowCount() == 0 and h.total == 0
    h.consultar()
    m = h.filas
    assert set(_roles(m)) == set(ROLES)
    assert m.rowCount() == 4 and m.cuenta == 4 and h.total == 4 and h.error == ""
    f = _fila(m, 0)
    assert HORA.match(f["hora"]) and FECHA.match(f["fecha"])
    assert f["nivel"] == "aviso" and f["msg"] == "Escritura rechazada T_NEUM=99999" and f["origen"] == "gateway"
    assert abs(f["t"] - (AHORA - 20)) < 1e-3 and f["ok"] is True and f["duracion"] == "—"
    assert [_fila(m, i)["nivel"] for i in range(4)] == ["aviso", "info", "info", "alarma"]   # más reciente primero
    assert _fila(m, 1)["msg"] == "Marcha (ACTIVE = 1)"
    assert h.resumen["eventos"] == 4 and h.resumen["alarmas"] == 2 and h.resumen["escrituras"] == 3
    assert h.resumen["desdeTexto"] != "" and h.consultaMs >= 0
    assert m.fila(1)["msg"] == "Marcha (ACTIVE = 1)" and m.fila(99) == {}
    h.cerrar()


def test_cambio_de_tabla_alarmas(ruta):
    h = Historial(ruta=ruta)
    cambios = []
    h.tablaChanged.connect(lambda: cambios.append(h.tabla))
    h.tabla = "alarmas"
    h.tabla = "alarmas"                    # sin cambio: no notifica
    h.tabla = "inexistente"                # se ignora
    assert cambios == ["alarmas"] and h.tabla == "alarmas"
    h.consultar()
    m = h.filas
    assert m.rowCount() == 2 and h.total == 2
    activa, cerrada = _fila(m, 0), _fila(m, 1)
    assert activa["id"] == "etapa_excedida" and activa["tFin"] == "activa" and activa["duracion"] == "—"
    assert activa["ok"] is False and HORA.match(activa["tIni"])
    assert cerrada["id"] == "calidad" and HORA.match(cerrada["tFin"]) and cerrada["duracion"] == "1,5 s"
    assert cerrada["ok"] is True and cerrada["nivel"] == "aviso"
    h.soloActivas = True
    h.consultar()
    assert m.rowCount() == 1 and _fila(m, 0)["id"] == "etapa_excedida"
    h.soloActivas = False
    h.niveles = ["aviso"]
    h.consultar()
    assert m.rowCount() == 1 and _fila(m, 0)["id"] == "calidad"
    h.cerrar()


def test_tabla_escrituras(ruta):
    h = Historial(ruta=ruta)
    h.tabla = "escrituras"
    h.consultar()
    m = h.filas
    assert m.rowCount() == 3 and h.total == 3
    f = _fila(m, 1)
    assert f["tag"] == "T_NEUM" and f["valor"] == "99999" and f["ok"] is False
    assert f["origen"] == "HMI local" and f["msg"] == "fuera de rango" and f["nivel"] == "aviso"
    assert _fila(m, 0)["origen"] == "web:ana (operador)" and _fila(m, 0)["msg"] == ""
    h.soloFallidas = True
    h.consultar()
    assert m.rowCount() == 1 and _fila(m, 0)["tag"] == "T_NEUM"
    h.soloFallidas = False
    h.tag = "start"
    h.consultar()
    assert m.rowCount() == 1 and _fila(m, 0)["tag"] == "STARTV"
    h.cerrar()


def test_ultimas_horas(ruta):
    h = Historial(ruta=ruta)
    h.ultimas(1)
    assert abs(h.desde - (time.time() - 3600)) < 5 and h.hasta == 0
    assert h.filas.rowCount() == 2
    h.ultimas(24)
    assert h.filas.rowCount() == 3
    h.ultimas(0)
    assert h.desde == 0 and h.filas.rowCount() == 4
    h.cerrar()


def test_filtros_texto_y_niveles(ruta):
    h = Historial(ruta=ruta)
    h.niveles = ["aviso", "alarma"]
    h.consultar()
    assert h.filas.rowCount() == 2
    h.niveles = []
    h.consultar()
    assert h.filas.rowCount() == 0
    h.niveles = ["alarma", "info", "aviso", "otro"]
    assert h.niveles == ["info", "aviso", "alarma"]          # orden canónico, sin desconocidos
    h.texto = "sim listo"
    h.consultar()
    assert h.filas.rowCount() == 1 and _fila(h.filas, 0)["msg"] == "Gateway SIM listo"
    h.limite = 1
    h.texto = ""
    h.consultar()
    assert h.filas.rowCount() == 1 and h.total == 4
    h.cerrar()


def test_exportar_csv(ruta, tmp_path):
    h = Historial(ruta=ruta)
    h.consultar()
    salida = h.exportarCsv()
    assert salida and os.path.isfile(salida)
    assert os.path.dirname(salida) == str(tmp_path / "exportes")
    assert os.path.basename(salida).startswith("eventos_") and salida.endswith(".csv")
    assert h.ultimoExporte == salida and h.error == ""
    with open(salida, encoding="utf-8-sig") as f:
        lineas = f.read().splitlines()
    assert lineas[0] == "t,fecha_hora,nivel,msg,origen" and len(lineas) == 5
    h.cerrar()


def test_error_ruta_inexistente(tmp_path):
    h = Historial(ruta=str(tmp_path / "nada.sqlite"))
    assert "no existe" in h.error
    h.consultar()
    assert "no existe" in h.error and h.filas.rowCount() == 0 and h.total == 0
    assert h.exportarCsv() == "" and h.error
    assert not os.path.exists(str(tmp_path / "nada.sqlite"))
    h.cerrar()


def test_cambio_de_ruta(ruta, tmp_path):
    h = Historial(ruta=str(tmp_path / "nada.sqlite"))
    h.consultar()
    assert h.error
    h.ruta = ruta
    assert h.error == "" and h.filas.rowCount() == 0
    h.consultar()
    assert h.filas.rowCount() == 4
    h.cerrar()


def test_formatos():
    assert duracion(12.34) == "12,3 s" and duracion(0) == "0,0 s" and duracion(None) == "—"
    assert duracion(125) == "2 min 05 s" and duracion(3720) == "1 h 02 min"
    f = fila_escritura({"t": AHORA, "tag": "STARTV", "valor": "1", "ok": 1, "msg": "[gateway]"})
    assert f["origen"] == "gateway" and f["msg"] == "" and f["ok"] is True and f["nivel"] == "info"
    f = fila_escritura({"t": AHORA, "tag": "X", "valor": None, "ok": 0, "msg": "sin corchetes"})
    assert f["origen"] == "" and f["msg"] == "sin corchetes" and f["valor"] == "" and f["nivel"] == "aviso"
