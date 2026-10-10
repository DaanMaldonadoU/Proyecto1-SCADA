# -*- coding: utf-8 -*-
"""Pruebas de core.tags: direcciones, palabras y reglas de escritura."""
from core import tags


def test_direcciones_tabla_vigente():
    assert tags.DIRECCION["STOP_1"] == "I:1.0/0"
    assert tags.DIRECCION["START_1"] == "I:1.0/1"
    assert tags.DIRECCION["SE3"] == "I:1.0/7"
    assert tags.DIRECCION["EV_E1"] == "O:2.0/0"
    assert tags.DIRECCION["EV_C3"] == "O:2.0/5"
    assert tags.DIRECCION["STARTV"] == "B3:0/0"
    assert tags.DIRECCION["STOPV"] == "B3:0/1"
    assert tags.DIRECCION["ACTIVE"] == "B3:0/2"
    assert tags.DIRECCION["END"] == "B3:0/3"
    assert tags.DIRECCION["RESETV"] == "B3:0/4"
    assert tags.DIRECCION["X8"] == "B3:3/8"
    assert tags.DIRECCION["T5_PRE"] == "T4:5.PRE"
    assert tags.DIRECCION["T0_DN"] == "T4:0/DN"
    assert tags.DIRECCION["C_ACC"] == "C5:0.ACC"


def test_sin_direcciones_obsoletas():
    for d in tags.DIRECCION.values():
        assert not d.startswith("O:3")
        assert not d.startswith("N7")
        assert d not in ("B3:0/13", "B3:0/14", "B3:0/15")


def test_grupos_de_lectura():
    assert tags.ITEMS_RAPIDOS[:4] == ["I:1.0", "O:2.0", "B3:0", "B3:3"]
    assert len(tags.ITEMS_RAPIDOS) == 4 + 6 * 3
    assert tags.ITEMS_LENTOS == ["C5:0.ACC", "C5:0.PRE"]


def test_codificar_decodificar_palabra():
    bits = {"STOP_1": True, "SC1": True, "SE3": True}
    v = tags.codificar_palabra("I:1.0", bits)
    assert v == (1 << 0) | (1 << 2) | (1 << 7)
    dec = tags.decodificar_palabra("I:1.0", v)
    assert dec["STOP_1"] and dec["SC1"] and dec["SE3"]
    assert not dec["START_1"] and not dec["SE1"]
    # Aplicar sobre una base conserva los demás bits
    v2 = tags.codificar_palabra("I:1.0", {"SC1": False, "SE1": True}, base=v | (1 << 12))
    assert v2 == (1 << 0) | (1 << 3) | (1 << 7) | (1 << 12)
    # Palabras con signo (RSLinx) se enmascaran
    assert tags.decodificar_palabra("B3:3", -1)["X8"] is True


def test_ida_y_vuelta_todas_las_palabras():
    for palabra, tabla in tags.PALABRAS.items():
        for tag in tabla:
            v = tags.codificar_palabra(palabra, {tag: True})
            dec = tags.decodificar_palabra(palabra, v)
            assert [t for t, b in dec.items() if b] == [tag]


def test_validar_escritura_nunca_salidas():
    for modo in ("SIM", "EMULATE", "REAL"):
        ok, _ = tags.validar_escritura("EV_E1", modo, 1)
        assert not ok


def test_validar_escritura_real_bloquea_entradas():
    for tag in tags.ENTRADAS_SIMULABLES:
        assert not tags.validar_escritura(tag, "REAL", True)[0]
        assert tags.validar_escritura(tag, "EMULATE", True)[0]
        assert tags.validar_escritura(tag, "SIM", True)[0]


def test_validar_escritura_pulsos_y_parametros():
    for tag in tags.PULSOS:
        assert tags.validar_escritura(tag, "REAL", 1)[0]
    assert tags.validar_escritura("T_ESPERA", "REAL", 150)[0]
    assert not tags.validar_escritura("T_ESPERA", "REAL", None)[0]
    assert not tags.validar_escritura("T_ESPERA", "REAL", 40000)[0]
    assert not tags.validar_escritura("T_ESPERA", "REAL", -1)[0]
    assert not tags.validar_escritura("N_CICLOS", "SIM", 0)[0]
    assert not tags.validar_escritura("NO_EXISTE", "SIM", 1)[0]


def test_t_espera_cinco_direcciones():
    dirs = tags.direcciones_de_escritura("T_ESPERA")
    assert dirs == ["T4:0.PRE", "T4:1.PRE", "T4:2.PRE", "T4:3.PRE", "T4:4.PRE"]
    assert tags.direcciones_de_escritura("T_NEUM") == ["T4:5.PRE"]
    assert tags.direcciones_de_escritura("N_CICLOS") == ["C5:0.PRE"]


def test_utilidades():
    assert tags.direccion_a_palabra_bit("I:1/3") == ("I:1.0", 3)
    assert tags.direccion_a_palabra_bit("B3:0/2") == ("B3:0", 2)
    assert tags.item_opc("PROYECTO1_TEST", "I:1.0/3") == "[PROYECTO1_TEST]I:1.0/3"
    assert tags.etapa_activa({"X3": True}) == 3
    assert tags.etapa_activa({"X3": True, "X4": True}) is None
    assert tags.etapa_activa({}) is None
