# -*- coding: utf-8 -*-
"""Pruebas de core.alarmas (cada regla se activa y se limpia), core.latencia y core.historial."""
import sqlite3

from core.alarmas import Alarmas
from core.historial import Historial
from core.latencia import EstadisticasLatencia, percentil


def _snap(**kw):
    s = {
        "conectado": True,
        "calidad": {"good": 24, "total": 24},
        "bits": {"STOP_1": True, "ACTIVE": True, "SC1": True, "SC2": True, "SC3": True},
        "ints": {"T0_PRE": 100, "T1_PRE": 100, "T2_PRE": 100, "T3_PRE": 100, "T4_PRE": 100, "T5_PRE": 500},
        "etapa": 0, "t_etapa": 0.0,
        "lat": {"p95_ms": 5.0},
    }
    s.update(kw)
    return s


def _ids(lista):
    return {a["id"] for a in lista}


def test_sin_alarmas_en_reposo():
    a = Alarmas(50)
    lista, ev = a.evaluar(_snap(), 1.0)
    assert lista == [] and ev == []


def test_desconexion():
    a = Alarmas(50)
    lista, ev = a.evaluar(_snap(conectado=False), 1.0)
    assert _ids(lista) == {"desconexion"}
    assert len(ev) == 1 and ev[0]["nivel"] == "alarma"
    al = lista[0]
    assert set(al) == {"id", "nivel", "msg", "t_ini", "activa"} and al["activa"] and al["t_ini"] == 1.0
    lista, ev = a.evaluar(_snap(conectado=False), 2.0)
    assert ev == [] and lista[0]["t_ini"] == 1.0          # no se repite
    lista, ev = a.evaluar(_snap(), 3.0)
    assert lista == [] and len(ev) == 1 and ev[0]["nivel"] == "info"
    assert a.ultimos_cambios[0][1] is False


def test_calidad():
    a = Alarmas(50)
    lista, ev = a.evaluar(_snap(calidad={"good": 20, "total": 24}), 1.0)
    assert _ids(lista) == {"calidad"} and ev[0]["nivel"] == "aviso"
    lista, ev = a.evaluar(_snap(), 2.0)
    assert lista == [] and len(ev) == 1


def test_stop_fisico():
    a = Alarmas(50)
    bits = {"STOP_1": False, "ACTIVE": False, "SC1": True, "SC2": True, "SC3": True}
    lista, _ = a.evaluar(_snap(bits=bits), 1.0)
    assert _ids(lista) == {"stop_fisico"}
    lista, _ = a.evaluar(_snap(), 2.0)
    assert lista == []


def test_etapa_excedida_con_ton():
    a = Alarmas(50)
    # X2 con T4:0.PRE = 100 → límite 1,5·1 + 1 = 2,5 s
    lista, _ = a.evaluar(_snap(etapa=2, t_etapa=2.4), 1.0)
    assert lista == []
    lista, ev = a.evaluar(_snap(etapa=2, t_etapa=2.6), 2.0)
    assert _ids(lista) == {"etapa_excedida"} and ev[0]["nivel"] == "alarma"
    lista, ev = a.evaluar(_snap(etapa=3, t_etapa=0.0), 3.0)       # cambia la etapa
    assert lista == [] and len(ev) == 1
    # X7 con T4:5.PRE = 500 → 8,5 s
    lista, _ = a.evaluar(_snap(etapa=7, t_etapa=8.0), 4.0)
    assert lista == []
    lista, _ = a.evaluar(_snap(etapa=7, t_etapa=9.0), 5.0)
    assert _ids(lista) == {"etapa_excedida"}


def test_etapa_excedida_espera_sensor():
    a = Alarmas(50)
    lista, _ = a.evaluar(_snap(etapa=1, t_etapa=4.9), 1.0)
    assert lista == []
    lista, _ = a.evaluar(_snap(etapa=1, t_etapa=5.1), 2.0)
    assert _ids(lista) == {"etapa_excedida"}
    lista, _ = a.evaluar(_snap(etapa=2, t_etapa=0.1), 3.0)
    assert lista == []
    # X0 con ACTIVE esperando que retraiga 2A
    bits = {"STOP_1": True, "ACTIVE": True, "SC1": True, "SC2": False, "SC3": True}
    lista, _ = a.evaluar(_snap(etapa=0, t_etapa=6.0, bits=bits), 4.0)
    assert _ids(lista) == {"etapa_excedida"}
    # X0 con todo retraído (p. ej. tras END esperando START) no es alarma
    lista, _ = a.evaluar(_snap(etapa=0, t_etapa=60.0), 5.0)
    assert lista == []


def test_etapa_excedida_no_en_paro():
    a = Alarmas(50)
    bits = {"STOP_1": True, "ACTIVE": False, "SC1": True, "SC2": True, "SC3": True}
    lista, _ = a.evaluar(_snap(etapa=2, t_etapa=100.0, bits=bits), 1.0)
    assert lista == []


def test_latencia_diez_ciclos():
    a = Alarmas(50)
    alto = {"p95_ms": 150.0}
    for k in range(9):
        lista, _ = a.evaluar(_snap(lat=alto), float(k))
        assert lista == []
    lista, ev = a.evaluar(_snap(lat=alto), 9.0)
    assert _ids(lista) == {"latencia"} and ev[0]["nivel"] == "aviso"
    lista, ev = a.evaluar(_snap(lat={"p95_ms": 60.0}), 10.0)
    assert lista == [] and len(ev) == 1


def test_estadisticas_latencia():
    e = EstadisticasLatencia(ventana=10)
    assert e.resumen("sim")["p95_ms"] == 0.0
    for k in range(20):
        e.registrar(float(k), 1.0, 50.0)
    r = e.resumen("cache")
    assert set(r) == {"lectura_ms", "lectura_max_ms", "ciclo_ms", "periodo_ms", "p95_ms", "fuente"}
    assert r["fuente"] == "cache"
    assert r["lectura_ms"] == 19.0 and r["lectura_max_ms"] == 19.0
    assert r["periodo_ms"] == 50.0
    assert 18.0 <= r["p95_ms"] <= 19.0
    h = e.historial(5)
    assert len(h) == 5 and h[-1][1] == 19.0
    assert percentil([1, 2, 3, 4], 50) == 2.5


def test_historial_sqlite(tmp_path):
    ruta = tmp_path / "sub" / "historial.sqlite"
    h = Historial(str(ruta))
    h.evento({"t": 1.0, "nivel": "info", "msg": "hola", "origen": "prueba"})
    al = {"id": "calidad", "nivel": "aviso", "msg": "m", "t_ini": 2.0, "activa": True}
    h.alarma(al, True)
    h.escritura(3.0, "T_ESPERA", 150, True, "")
    h.volcar()
    al2 = dict(al, activa=False, t_fin=4.0)
    h.alarma(al2, False)
    h.volcar()
    assert h.esperar()
    h.cerrar()
    con = sqlite3.connect(str(ruta))
    assert con.execute("SELECT msg FROM eventos").fetchall() == [("hola",)]
    assert con.execute("SELECT id, t_ini, t_fin FROM alarmas").fetchall() == [("calidad", 2.0, 4.0)]
    assert con.execute("SELECT tag, valor, ok FROM escrituras").fetchall() == [("T_ESPERA", "150", 1)]
    con.close()


def test_etapa_excedida_con_margen_del_enlace():
    """Lecturas del PLC por OPC (o sin pos): +MARGEN_ENLACE_S, porque la etapa se ve cambiar tarde."""
    from core.alarmas import MARGEN_ENLACE_S
    a = Alarmas(100)
    # X3 real (T4:1 = 1 s + salida de 2A ≈ 0,9 s) vista 1,5 s tarde: 3,4 s > 2,5 s, pero no es una falla
    lista, _ = a.evaluar(_snap(etapa=3, t_etapa=3.4, fuente="cache", pos=None), 1.0)
    assert lista == []
    lista, _ = a.evaluar(_snap(etapa=3, t_etapa=2.5 + MARGEN_ENLACE_S + 0.1, fuente="cache", pos=None), 2.0)
    assert _ids(lista) == {"etapa_excedida"}                 # atascada de verdad: se sigue detectando
    a = Alarmas(50)
    lista, _ = a.evaluar(_snap(etapa=1, t_etapa=5.0 + MARGEN_ENLACE_S - 0.1, fuente="sim", pos=None), 1.0)
    assert lista == []                                       # SIM --simular-enlace (sin pos): mismo margen
    lista, _ = a.evaluar(_snap(etapa=3, t_etapa=2.6, fuente="sim", pos=[0.0, 1.0, 0.0]), 2.0)
    assert _ids(lista) == {"etapa_excedida"}                 # SIM normal: sin margen, como siempre
    assert Alarmas.margen_enlace({"fuente": "dispositivo"}) == MARGEN_ENLACE_S
    assert Alarmas.margen_enlace({"fuente": "sim", "pos": [0, 0, 0]}) == 0.0
