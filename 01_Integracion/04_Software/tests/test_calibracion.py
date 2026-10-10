# -*- coding: utf-8 -*-
"""Pruebas de core/calibracion.py: mediana móvil, persistencia, JSON corrupto, descartes."""
import json
import os

from core.calibracion import Calibracion


def test_sin_muestras_da_defecto():
    c = Calibracion()
    assert c.duracion_ms(1, "ext") == Calibracion.DEFECTO_MS == 800
    assert c.muestras(3, "ret") == []


def test_mediana_1_3_5_7_muestras():
    c = Calibracion()
    c.registrar(1, "ext", 700)
    assert c.duracion_ms(1, "ext") == 700
    c.registrar(1, "ext", 900)
    c.registrar(1, "ext", 500)
    assert c.duracion_ms(1, "ext") == 700            # mediana de [700, 900, 500]
    c.registrar(1, "ext", 1000)
    c.registrar(1, "ext", 650)
    assert c.duracion_ms(1, "ext") == 700            # [700, 900, 500, 1000, 650]
    c.registrar(1, "ext", 2000)
    c.registrar(1, "ext", 2100)
    # ventana 5: quedan [500, 1000, 650, 2000, 2100]
    assert c.muestras(1, "ext") == [500, 1000, 650, 2000, 2100]
    assert c.duracion_ms(1, "ext") == 1000
    # las otras claves no se tocan
    assert c.duracion_ms(1, "ret") == 800
    assert c.duracion_ms(2, "ext") == 800


def test_mediana_entera():
    c = Calibracion()
    c.registrar(2, "ret", 600.4)
    assert c.muestras(2, "ret") == [600]
    assert isinstance(c.duracion_ms(2, "ret"), int)


def test_descartadas_fuera_de_rango():
    c = Calibracion()
    assert c.registrar(1, "ext", 50) is None
    assert c.registrar(1, "ext", 10001) is None
    assert c.registrar(1, "ext", float("nan")) is None
    assert c.registrar(1, "ext", "abc") is None
    assert c.descartadas == 4
    assert c.muestras(1, "ext") == []
    c.registrar(1, "ext", 100)
    c.registrar(1, "ext", 10000)
    assert c.muestras(1, "ext") == [100, 10000]
    assert c.descartadas == 4


def test_persistencia_ida_y_vuelta(tmp_path):
    ruta = str(tmp_path / "sub" / "calibracion.json")   # la carpeta no existe aún
    c = Calibracion(ruta)
    for ms in (610, 590, 600):
        c.registrar(1, "ext", ms)
    c.registrar(3, "ret", 1234)
    assert os.path.exists(ruta)
    assert not os.path.exists(ruta + ".tmp")

    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    assert datos["1"]["ext"] == {"ms": 600, "muestras": [610, 590, 600]}
    assert datos["3"]["ret"]["ms"] == 1234
    assert datos["_meta"]["version"] == 1
    assert datos["_meta"]["actualizado"]
    assert datos == c.como_dict()

    c2 = Calibracion(ruta)
    assert c2.duracion_ms(1, "ext") == 600
    assert c2.muestras(1, "ext") == [610, 590, 600]
    assert c2.duracion_ms(3, "ret") == 1234
    assert c2.duracion_ms(2, "ext") == 800


def test_json_corrupto_arranca_vacio(tmp_path):
    ruta = tmp_path / "calibracion.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    c = Calibracion(str(ruta))
    assert c.duracion_ms(1, "ext") == 800
    assert c.ultimo_error
    c.registrar(1, "ext", 700)                        # sobrescribe con un JSON válido
    assert Calibracion(str(ruta)).duracion_ms(1, "ext") == 700


def test_json_con_formato_raro(tmp_path):
    ruta = tmp_path / "calibracion.json"
    ruta.write_text(json.dumps({"1": {"ext": {"muestras": [700, "x", 5, True, 900]}},
                                "2": "basura"}), encoding="utf-8")
    c = Calibracion(str(ruta))
    assert c.muestras(1, "ext") == [700, 900]
    assert c.duracion_ms(1, "ext") == 800   # mediana de 700 y 900


def test_reiniciar(tmp_path):
    ruta = str(tmp_path / "calibracion.json")
    c = Calibracion(ruta)
    c.registrar(2, "ext", 500)
    c.registrar(2, "ext", 50)                         # descartada
    c.reiniciar()
    assert c.duracion_ms(2, "ext") == 800
    assert c.muestras(2, "ext") == []
    assert c.descartadas == 0
    assert Calibracion(ruta).muestras(2, "ext") == []


def test_sin_ruta_no_escribe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = Calibracion()
    c.registrar(1, "ext", 700)
    c.guardar()
    assert os.listdir(str(tmp_path)) == []
