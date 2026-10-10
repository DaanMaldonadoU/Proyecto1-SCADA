# -*- coding: utf-8 -*-
"""Pruebas de core.historial.LectorHistorial: lee lo que escribe Historial (mds/ARQUITECTURA.md 6.5).

Se escribe con `Historial` (el escritor del gateway, con su hilo propio), se espera a que vacíe la
cola y se consulta con `LectorHistorial`: orden, filtros, límite, resumen, CSV, archivo inexistente
o roto sin excepciones y lectura concurrente mientras otro hilo sigue escribiendo.
"""
import csv
import os
import sqlite3
import threading
import time

import pytest

from core.historial import Historial, LectorHistorial, hora_legible

T0 = 1700000000.0      # epoch fijo (nov-2023) para no depender del reloj


def _poblar(ruta):
    """Base pequeña y conocida: 5 eventos, 2 alarmas (una cerrada, una activa), 4 escrituras."""
    h = Historial(ruta)
    h.evento({"t": T0 + 0, "nivel": "info", "msg": "Gateway SIM listo", "origen": "gateway"})
    h.evento({"t": T0 + 1, "nivel": "info", "msg": "Pulso STARTV (300 ms)", "origen": "HMI local"})
    h.evento({"t": T0 + 2, "nivel": "aviso", "msg": "Escritura rechazada T_NEUM=99999: fuera de rango", "origen": "gateway"})
    h.evento({"t": T0 + 3, "nivel": "alarma", "msg": "Alarma: etapa X2 excedida al 100% del PRE", "origen": "gateway"})
    h.evento({"t": T0 + 4, "nivel": "info", "msg": "Fin de N ciclos (END)", "origen": "gateway"})
    a1 = {"id": "calidad", "nivel": "aviso", "msg": "Items sin calidad Good", "t_ini": T0 + 1.5, "activa": True}
    a2 = {"id": "etapa_excedida", "nivel": "alarma", "msg": "Etapa X2 excedida", "t_ini": T0 + 3.5, "activa": True}
    h.alarma(a1, True)
    h.alarma(a2, True)
    h.alarma(dict(a1, activa=False, t_fin=T0 + 2.5), False)
    h.escritura(T0 + 1.0, "STARTV", 1, True, "[HMI local]")
    h.escritura(T0 + 1.3, "STARTV", 0, True, "[gateway]")
    h.escritura(T0 + 2.0, "T_NEUM", 99999, False, "[HMI local] fuera de rango")
    h.escritura(T0 + 4.5, "T_ESPERA", 150, True, "[web:ana (operador)]")
    h.volcar()
    assert h.esperar()
    h.cerrar()


@pytest.fixture
def base(tmp_path):
    ruta = str(tmp_path / "carpeta con espacios" / "historial.sqlite")   # la URI file: debe escapar espacios
    _poblar(ruta)
    lector = LectorHistorial(ruta)
    yield lector
    lector.cerrar()


# ---------------------------------------------------------------- orden, claves, límite
def test_eventos_orden_y_claves(base):
    filas = base.eventos()
    assert base.ultimo_error is None
    assert [f["t"] for f in filas] == [T0 + 4, T0 + 3, T0 + 2, T0 + 1, T0 + 0]      # lo más reciente primero
    assert set(filas[0]) == {"t", "nivel", "msg", "origen"}
    assert filas[0]["msg"] == "Fin de N ciclos (END)" and filas[0]["origen"] == "gateway"


def test_eventos_limite(base):
    filas = base.eventos(limite=2)
    assert [f["t"] for f in filas] == [T0 + 4, T0 + 3]
    assert len(base.eventos(limite=None)) == 5
    assert base.eventos(limite=0) == []


def test_solo_lectura(base):
    assert base.eventos()                         # la conexión está abierta
    with pytest.raises(sqlite3.OperationalError):
        base._con.execute("INSERT INTO eventos VALUES (1, 'info', 'no', 'x')")


# ---------------------------------------------------------------- filtros de eventos
def test_eventos_rango(base):
    assert [f["t"] for f in base.eventos(desde=T0 + 2)] == [T0 + 4, T0 + 3, T0 + 2]
    assert [f["t"] for f in base.eventos(hasta=T0 + 1)] == [T0 + 1, T0 + 0]
    assert [f["t"] for f in base.eventos(desde=T0 + 1, hasta=T0 + 3)] == [T0 + 3, T0 + 2, T0 + 1]


def test_eventos_niveles(base):
    assert [f["nivel"] for f in base.eventos(niveles=["aviso", "alarma"])] == ["alarma", "aviso"]
    assert len(base.eventos(niveles=["info"])) == 3
    assert base.eventos(niveles=[]) == []          # lista vacía = ningún nivel
    assert len(base.eventos(niveles=None)) == 5    # None = todos


def test_eventos_texto(base):
    assert [f["t"] for f in base.eventos(texto="startv")] == [T0 + 1]       # sin distinguir mayúsculas
    assert [f["t"] for f in base.eventos(texto="100%")] == [T0 + 3]         # el % se escapa, no es comodín
    assert len(base.eventos(texto="_")) == 1                                # el _ también (T_NEUM)
    assert base.eventos(texto="no existe") == []


def test_eventos_origen(base):
    assert [f["t"] for f in base.eventos(origen="HMI local")] == [T0 + 1]
    assert len(base.eventos(origen="gateway")) == 4
    assert base.eventos(origen="hmi") == []        # coincidencia exacta


# ---------------------------------------------------------------- alarmas
def test_alarmas(base):
    filas = base.alarmas()
    assert set(filas[0]) == {"id", "nivel", "msg", "t_ini", "t_fin"}
    assert [f["id"] for f in filas] == ["etapa_excedida", "calidad"]
    assert filas[0]["t_fin"] is None and filas[1]["t_fin"] == T0 + 2.5
    activas = base.alarmas(solo_activas=True)
    assert [f["id"] for f in activas] == ["etapa_excedida"]
    # Rango: cuenta si estuvo activa en algún momento del rango
    assert [f["id"] for f in base.alarmas(desde=T0 + 3)] == ["etapa_excedida"]       # calidad terminó en 2,5
    assert [f["id"] for f in base.alarmas(desde=T0 + 2)] == ["etapa_excedida", "calidad"]
    assert [f["id"] for f in base.alarmas(hasta=T0 + 2)] == ["calidad"]              # etapa empezó en 3,5
    assert [f["id"] for f in base.alarmas(desde=T0 + 10)] == ["etapa_excedida"]      # sigue activa
    # Extras del visor
    assert [f["id"] for f in base.alarmas(niveles=["aviso"])] == ["calidad"]
    assert [f["id"] for f in base.alarmas(texto="x2")] == ["etapa_excedida"]
    assert [f["id"] for f in base.alarmas(texto="calid")] == ["calidad"]             # busca también en id
    assert len(base.alarmas(limite=1)) == 1


# ---------------------------------------------------------------- escrituras
def test_escrituras(base):
    filas = base.escrituras()
    assert set(filas[0]) == {"t", "tag", "valor", "ok", "msg"}
    assert [f["tag"] for f in filas] == ["T_ESPERA", "T_NEUM", "STARTV", "STARTV"]
    assert filas[0]["ok"] is True and filas[1]["ok"] is False
    assert filas[0]["valor"] == "150"               # Historial guarda el valor como texto
    assert [f["t"] for f in base.escrituras(tag="startv")] == [T0 + 1.3, T0 + 1.0]
    assert [f["tag"] for f in base.escrituras(tag="T_")] == ["T_ESPERA", "T_NEUM"]   # subcadena, _ escapado
    fallidas = base.escrituras(solo_fallidas=True)
    assert len(fallidas) == 1 and fallidas[0]["tag"] == "T_NEUM" and fallidas[0]["ok"] is False
    assert base.escrituras(tag="STARTV", solo_fallidas=True) == []
    assert [f["tag"] for f in base.escrituras(texto="rango")] == ["T_NEUM"]
    assert [f["tag"] for f in base.escrituras(desde=T0 + 1.2, hasta=T0 + 3)] == ["T_NEUM", "STARTV"]


# ---------------------------------------------------------------- resumen
def test_resumen(base):
    r = base.resumen()
    assert set(r) == {"eventos", "alarmas", "escrituras", "t_min", "t_max", "ruta"}
    assert (r["eventos"], r["alarmas"], r["escrituras"]) == (5, 2, 4)
    assert r["t_min"] == T0 and r["t_max"] == T0 + 4.5
    assert r["ruta"] == base.ruta


# ---------------------------------------------------------------- CSV
def _leer_csv(ruta):
    with open(ruta, "rb") as f:
        crudo = f.read()
    assert crudo.startswith(b"\xef\xbb\xbf")        # BOM: Excel lo abre como UTF-8
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_exportar_csv_eventos(base, tmp_path):
    ruta = str(tmp_path / "nueva" / "carpeta" / "eventos.csv")    # la carpeta se crea
    assert base.exportar_csv("eventos", ruta) == 5
    filas = _leer_csv(ruta)
    assert filas[0] == ["t", "fecha_hora", "nivel", "msg", "origen"]
    assert len(filas) == 6
    assert float(filas[1][0]) == T0 and float(filas[5][0]) == T0 + 4      # cronológico
    assert filas[1][1] == hora_legible(T0) and len(filas[1][1]) == 23       # 'AAAA-MM-DD HH:MM:SS.mmm'
    assert filas[4][3] == "Alarma: etapa X2 excedida al 100% del PRE"
    # Con filtros (los mismos del método eventos)
    assert base.exportar_csv("eventos", ruta, niveles=["aviso"], texto="rango") == 1
    assert len(_leer_csv(ruta)) == 2


def test_exportar_csv_alarmas_y_escrituras(base, tmp_path):
    ruta_a = str(tmp_path / "alarmas.csv")
    assert base.exportar_csv("alarmas", ruta_a) == 2
    filas = _leer_csv(ruta_a)
    assert filas[0] == ["id", "nivel", "msg", "t_ini", "inicio", "t_fin", "fin", "duracion_s"]
    assert filas[1][0] == "calidad" and filas[1][7] == "1.000"
    assert filas[2][0] == "etapa_excedida" and filas[2][5] == "" and filas[2][6] == "activa"
    ruta_e = str(tmp_path / "escrituras.csv")
    assert base.exportar_csv("escrituras", ruta_e, solo_fallidas=True) == 1
    filas = _leer_csv(ruta_e)
    assert filas[0] == ["t", "fecha_hora", "tag", "valor", "ok", "msg"]
    assert filas[1][2:] == ["T_NEUM", "99999", "0", "[HMI local] fuera de rango"]
    with pytest.raises(ValueError):
        base.exportar_csv("otra", str(tmp_path / "x.csv"))


# ---------------------------------------------------------------- sin base, base rota
def test_archivo_inexistente_no_lanza(tmp_path):
    ruta = str(tmp_path / "no_existe.sqlite")
    lector = LectorHistorial(ruta)
    assert "no existe" in lector.ultimo_error
    assert lector.eventos() == [] and lector.alarmas() == [] and lector.escrituras() == []
    r = lector.resumen()
    assert (r["eventos"], r["alarmas"], r["escrituras"], r["t_min"], r["t_max"], r["ruta"]) == (0, 0, 0, None, None, ruta)
    salida = str(tmp_path / "x.csv")
    assert lector.exportar_csv("eventos", salida) is None and not os.path.exists(salida)
    assert not os.path.exists(ruta)                 # el lector nunca crea la base
    # El gateway crea la base más tarde: el lector se engancha en la siguiente consulta
    _poblar(ruta)
    assert len(lector.eventos()) == 5 and lector.ultimo_error is None
    lector.cerrar()


def test_archivo_roto_no_lanza(tmp_path):
    ruta = tmp_path / "roto.sqlite"
    ruta.write_bytes(b"esto no es una base sqlite " * 100)
    lector = LectorHistorial(str(ruta))
    assert lector.eventos() == [] and lector.ultimo_error
    assert lector.resumen()["eventos"] == 0
    assert lector.exportar_csv("eventos", str(tmp_path / "x.csv")) is None
    lector.cerrar()


# ---------------------------------------------------------------- lectura concurrente
def test_lectura_concurrente_con_escritor(tmp_path):
    """Un hilo escribe con Historial (WAL) mientras el hilo principal consulta sin parar."""
    ruta = str(tmp_path / "vivo.sqlite")
    h = Historial(ruta)
    N = 300

    def escritor():
        for i in range(N):
            h.evento({"t": T0 + i, "nivel": "info", "msg": "evento %d" % i, "origen": "prueba"})
            h.volcar()
            if i % 50 == 0:
                time.sleep(0.005)

    hilo = threading.Thread(target=escritor, name="escritor-prueba")
    hilo.start()
    lector = LectorHistorial(ruta)
    vistos, lecturas = 0, 0
    while hilo.is_alive() or lecturas < 3:
        n = lector.resumen()["eventos"]
        assert lector.ultimo_error is None
        assert n >= vistos                           # nunca va hacia atrás
        vistos = n
        lecturas += 1
    hilo.join(5.0)
    assert h.esperar()
    assert lector.resumen()["eventos"] == N
    ultimos = lector.eventos(limite=3)
    assert [f["msg"] for f in ultimos] == ["evento 299", "evento 298", "evento 297"]
    h.cerrar()
    lector.cerrar()
