# -*- coding: utf-8 -*-
"""Pruebas del ladder simulado, la física y la cadena neumática (sin tiempo real)."""
import pytest

from core import tags
from gateway.backend_sim import BackendSim
from gateway.fisica import CadenaNeumatica, Fisica
from gateway.ladder_sim import Ladder

DT = 0.005


def _planta(t_espera=10, t_neum=20, n_ciclos=3):
    b = BackendSim()
    b.conectar()
    b.escribir([(d, t_espera) for d in tags.PARAMETROS["T_ESPERA"]])
    b.escribir([(tags.PARAMETROS["T_NEUM"][0], t_neum), (tags.PARAMETROS["N_CICLOS"][0], n_ciclos)])
    return b


def _pulso(b, tag, s=0.3, vigilar=None):
    b.escribir([(tags.PULSOS[tag], 1)])
    _correr(b, s, vigilar)
    b.escribir([(tags.PULSOS[tag], 0)])


def _correr(b, segundos, vigilar=None):
    for _ in range(int(round(segundos / DT))):
        b.avanzar(DT)
        if vigilar:
            vigilar(b)


def _sin_conflicto(b):
    for e, c, _sc, _se in tags.CILINDROS.values():
        assert not (b.ladder.bits[e] and b.ladder.bits[c]), "EV_E y EV_C a la vez en %s/%s" % (e, c)


def test_arranque_en_x0():
    lad = Ladder()
    lad.scan(0.0)
    assert lad.etapa() == 0
    assert lad.bits["STOP_1"] is True
    assert not lad.bits["ACTIVE"]
    assert lad.ints["T0_PRE"] == 100 and lad.ints["T5_PRE"] == 500 and lad.ints["C_PRE"] == 3


def test_secuencia_completa_hasta_end():
    b = _planta()
    assert b.ladder.etapa() == 0
    visitadas = [0]

    def vigilar(p):
        _sin_conflicto(p)
        e = p.ladder.etapa()
        assert e is not None, "debe haber exactamente una etapa activa"
        if not visitadas or visitadas[-1] != e:
            visitadas.append(e)
        # END se ve un barrido y en el siguiente GS vuelve a X0
        if p.ladder.bits["END"]:
            vigilar.end_visto = True

    vigilar.end_visto = False
    _pulso(b, "STARTV", vigilar=vigilar)
    _correr(b, 25.0, vigilar)
    assert vigilar.end_visto
    # Tres ciclos X1..X7 y luego X8 → X0
    ciclo = [1, 2, 3, 4, 5, 6, 7]
    assert visitadas == [0] + ciclo * 3 + [8, 0]
    assert b.ladder.etapa() == 0
    assert b.ladder.ints["C_ACC"] == 0          # GS lo reinicia tras END
    assert b.ladder.bits["ACTIVE"]              # la marcha sigue enclavada


def test_contador_cuenta_por_flanco_de_x7():
    b = _planta(n_ciclos=5)
    max_c = [0]

    def vigilar(p):
        max_c[0] = max(max_c[0], p.ladder.ints["C_ACC"])

    _pulso(b, "STARTV", vigilar=vigilar)
    _correr(b, 12.0, vigilar)
    assert 1 <= max_c[0] <= 5


def test_stop_congela_etapa_y_start_continua():
    b = _planta(t_espera=100)
    _pulso(b, "STARTV")
    # Esperar a estar en X2 (1A afuera, contando T4:0)
    for _ in range(2000):
        b.avanzar(DT)
        if b.ladder.etapa() == 2:
            break
    assert b.ladder.etapa() == 2
    _pulso(b, "STOPV", s=0.3)
    assert not b.ladder.bits["ACTIVE"]
    _correr(b, 2.0, _sin_conflicto)
    # Congelada en X2, pero el TON siguió contando (DN) y las salidas no dependen de ACTIVE
    assert b.ladder.etapa() == 2
    assert b.ladder.bits["T0_DN"]
    assert b.ladder.ints["T0_ACC"] == b.ladder.ints["T0_PRE"]
    assert b.ladder.bits["EV_C1"] and not b.ladder.bits["EV_E1"]
    _pulso(b, "STARTV")
    _correr(b, 1.0)
    assert b.ladder.bits["ACTIVE"]
    assert b.ladder.etapa() in (3, 4)


def test_stop_fisico_nc():
    b = _planta()
    _pulso(b, "STARTV")
    assert b.ladder.bits["ACTIVE"]
    b.escribir([(tags.DIRECCION["STOP_1"], 0)])
    _correr(b, 0.05)
    assert not b.ladder.bits["ACTIVE"]
    b.escribir([(tags.DIRECCION["STOP_1"], 1)])
    _correr(b, 0.05)
    assert not b.ladder.bits["ACTIVE"]         # hace falta START de nuevo


def test_reset_vuelve_a_x0():
    b = _planta(t_espera=100)
    _pulso(b, "STARTV")
    _correr(b, 3.0)
    assert b.ladder.etapa() not in (0, None)
    _pulso(b, "RESETV")
    assert b.ladder.etapa() == 0
    assert b.ladder.ints["C_ACC"] == 0
    # En X0 retrae lo que quedó extendido y no se vuelve a arrancar sin START... salvo que
    # ACTIVE siga enclavado y los sensores estén en SC: en ese caso espera START.
    _correr(b, 3.0, _sin_conflicto)
    assert b.ladder.etapa() == 0
    assert all(b.ladder.bits[s] for s in ("SC1", "SC2", "SC3"))


def test_start_y_stop_fisicos_juntos_hacen_gs():
    b = _planta(t_espera=100)
    _pulso(b, "STARTV")
    _correr(b, 2.0)
    assert b.ladder.etapa() != 0
    b.escribir([(tags.DIRECCION["START_1"], 1), (tags.DIRECCION["STOP_1"], 0)])
    _correr(b, 0.05)
    assert b.ladder.etapa() == 0
    assert not b.ladder.bits["ACTIVE"]


def test_ton_con_dt_pequeno_no_se_congela():
    lad = Ladder()
    lad.scan(0.0)
    lad.bits["X0"] = False
    lad.bits["X2"] = True
    lad.ints["T0_PRE"] = 10                 # 0,1 s
    for _ in range(100):                    # 100 × 1 ms = 0,1 s
        lad.scan(0.001)
    assert lad.bits["T0_DN"]
    assert lad.ints["T0_ACC"] == 10


def test_ton_acc_acotado_y_reset_al_salir():
    lad = Ladder()
    lad.scan(0.0)
    lad.bits["X0"] = False
    lad.bits["X2"] = True
    lad.ints["T0_PRE"] = 5
    lad.scan(1.0)
    assert lad.ints["T0_ACC"] == 5 and lad.bits["T0_DN"]
    lad.bits["X2"] = False
    lad.bits["X3"] = True
    lad.scan(0.001)
    assert lad.ints["T0_ACC"] == 0 and not lad.bits["T0_DN"]


def test_escribir_por_direccion():
    lad = Ladder()
    lad.escribir("T4:3.PRE", 250)
    assert lad.ints["T3_PRE"] == 250
    lad.escribir("C5:0.PRE", 7)
    assert lad.ints["C_PRE"] == 7
    lad.escribir("B3:0/0", 1)
    assert lad.bits["STARTV"]
    lad.escribir("I:1/3", 1)                # forma corta
    assert lad.bits["SE1"]
    lad.escribir("I:1.0", tags.codificar_palabra("I:1.0", {"STOP_1": True, "SC2": True}))
    assert lad.bits["SC2"] and not lad.bits["SE1"]
    with pytest.raises(ValueError):
        lad.escribir("O:2.0/0", 1)
    with pytest.raises(KeyError):
        lad.escribir("N7:0", 1)


def test_palabras():
    lad = Ladder()
    lad.scan(0.0)
    p = lad.palabras()
    assert set(p) == {"I:1.0", "O:2.0", "B3:0", "B3:3"}
    assert p["B3:3"] == 1                   # X0
    assert p["I:1.0"] & 1 == 1              # STOP_1 NC


def test_fisica_carreras_y_sensores():
    f = Fisica()
    assert f.sensores() == [(True, False)] * 3
    # 1A extiende en 0,80 s
    for _ in range(77):
        f.step(0.01, [(1, 0), (0, 0), (0, 0)])
    assert f.sensores()[0] == (False, False)
    f.step(0.03, [(1, 0), (0, 0), (0, 0)])
    assert f.sensores()[0] == (False, True)
    # Con ambas bobinas el carrete no cambia (válvula biestable): sigue en extender, hasta el tope
    p = f.pos[0]
    f.step(0.1, [(1, 1), (0, 0), (0, 0)])
    assert p <= f.pos[0] <= 1.0 and f.sensores()[0] == (False, True)
    f2 = Fisica({2: (0.5, 0.5)})
    assert f2.carreras[1] == (0.5, 0.5)


def test_fisica_valvula_biestable_termina_la_carrera():
    """Sin bobina, el carrete conserva la última orden: el vástago termina su carrera."""
    f = Fisica()
    for _ in range(40):                       # medio camino hacia afuera
        f.step(0.01, [(1, 0), (0, 0), (0, 0)])
    assert f.sensores()[0] == (False, False)
    for _ in range(60):                       # se apaga la bobina (p. ej. RESET): sigue saliendo
        f.step(0.01, [(0, 0), (0, 0), (0, 0)])
    assert f.sensores()[0] == (False, True)
    f.step(0.2, [(0, 1), (0, 0), (0, 0)])     # retraer y apagar a medias: sigue entrando
    for _ in range(100):
        f.step(0.01, [(0, 0), (0, 0), (0, 0)])
    assert f.sensores()[0] == (True, False)


def test_reset_a_media_carrera_no_deja_la_secuencia_en_x0():
    """Caso del autor (sesión 14): RESET desde la web con 3A a media carrera. Antes la física lo dejaba
    a medias, sin SC3, y X0 → X1 (que exige SC1·SC2·SC3) no volvía a ocurrir."""
    from gateway.backend_sim import BackendSim
    be = BackendSim()
    be.conectar()
    for tag, v in (("T_ESPERA", 20), ("T_NEUM", 50), ("N_CICLOS", 3)):
        for d in tags.direcciones_de_escritura(tag):
            be.ladder.escribir(d, v)

    def pulso(tag):
        be.ladder.escribir(tags.DIRECCION[tag], 1)
        be.avanzar(0.3)
        be.ladder.escribir(tags.DIRECCION[tag], 0)

    pulso("STARTV")
    t = 0.0
    while not (be.ladder.bits["EV_E3"] and 0.2 < be.fis.pos[2] < 0.8) and t < 20:
        be.avanzar(0.01)
        t += 0.01
    assert 0.2 < be.fis.pos[2] < 0.8, "3A no llegó a media carrera"
    pulso("RESETV")
    be.avanzar(3.0)
    assert be.ladder.X(0)
    assert be.ladder.bits["SC1"] and be.ladder.bits["SC2"] and be.ladder.bits["SC3"]
    pulso("STARTV")
    be.avanzar(0.5)
    assert be.ladder.X(1) or be.ladder.X(2), "la secuencia no salió de X0 tras el RESET"


def test_cadena_neumatica():
    c = CadenaNeumatica()
    assert c.posiciones(1.0, False) == [0.0, 0.0]
    assert c.posiciones(0.0, True) == [0.0, 0.0]
    assert c.posiciones(0.3, True) == [0.5, 0.0]
    assert c.posiciones(1.5, True) == [1.0, 0.5]
    assert c.posiciones(2.5, True) == [1.0, 1.0]
    p = c.posiciones(3.15, True)
    assert p[0] == pytest.approx(0.5) and p[1] == pytest.approx(0.5)
    assert c.posiciones(4.0, True) == [0.0, 0.0]


def test_manual_sensores_por_entrada():
    b = _planta()
    b.cambiar_fisica(False)
    res = b.escribir([(tags.DIRECCION["SC1"], 0)])
    assert res[0][1] is True
    b.avanzar(0.01)
    assert not b.ladder.bits["SC1"]
    b.cambiar_fisica(True)
    assert b.ladder.bits["SC1"]
    res = b.escribir([(tags.DIRECCION["SC1"], 0)])
    assert res[0][1] is False                # en automático la física manda
