# -*- coding: utf-8 -*-
"""Pruebas de core/estimador.py con secuencias sintéticas de bits y reloj simulado."""
import pytest

from core.calibracion import Calibracion
from core.estimador import EstimadorCarrera
from core.tags import TAGS_BIT

DT = 0.05   # periodo del snapshot simulado (50 ms)


def bits_base():
    """Máquina en marcha, los tres cilindros retraídos, bobinas apagadas."""
    b = {t: False for t in TAGS_BIT}
    b.update({"STOP_1": True, "ACTIVE": True, "SC1": True, "SC2": True, "SC3": True})
    return b


class Banco(object):
    """Reloj + bits + estimador. `paso()` avanza DT y aplica el snapshot."""

    def __init__(self, cal=None):
        self.cal = cal or Calibracion()
        self.est = EstimadorCarrera(self.cal)
        self.t = 100.0
        self.bits = bits_base()
        self.ultimo = self.est.actualizar(self.t, self.bits)

    def paso(self, **cambios):
        self.t += DT
        self.bits.update(cambios)
        self.ultimo = self.est.actualizar(self.t, self.bits)
        return self.ultimo

    def hasta(self, t_rel, t0, n=1):
        """Avanza hasta t0 + t_rel (s) y devuelve la lista de pos del cilindro n."""
        poses = []
        while self.t + DT <= t0 + t_rel + 1e-9:
            poses.append(self.paso()[n]["pos"])
        return poses


def extender(b, n=1, t_sensor=0.6):
    """Carrera de extensión completa de n: bobina, sale de SC, llega SE a t_sensor."""
    r = b.paso(**{"EV_E%d" % n: True})
    t0 = b.t
    assert r[n]["moviendo"] and r[n]["direccion"] == "ext" and r[n]["objetivo"] == 1.0
    b.paso(**{"SC%d" % n: False})
    b.hasta(t_sensor - DT, t0, n)
    r = b.paso(**{"SE%d" % n: True})
    b.paso(**{"EV_E%d" % n: False})
    return t0, r


def retraer(b, n=1, t_sensor=0.6):
    """Carrera de retracción completa de n: bobina, sale de SE, llega SC a t_sensor."""
    r = b.paso(**{"EV_C%d" % n: True})
    t0 = b.t
    assert r[n]["moviendo"] and r[n]["direccion"] == "ret" and r[n]["objetivo"] == 0.0
    b.paso(**{"SE%d" % n: False})
    b.hasta(t_sensor - DT, t0, n)
    r = b.paso(**{"SC%d" % n: True})
    b.paso(**{"EV_C%d" % n: False})
    return t0, r


def test_reposo_con_sensores():
    b = Banco()
    r = b.ultimo[1]
    assert r["pos"] == 0.0 and not r["moviendo"] and r["confirmado"]
    assert r["direccion"] is None and r["duracion_ms"] == 800


def test_a_sensor_antes_de_la_estimacion_salta():
    b = Banco()
    r = b.paso(EV_E1=True)
    t0 = b.t
    assert r[1]["duracion_ms"] == 800
    b.paso(SC1=False)
    poses = b.hasta(0.55, t0)
    assert poses == sorted(poses)
    assert 0.6 < poses[-1] < 0.75        # 550/800 = 0.69: aún no acaba la estimación
    r = b.paso(SE1=True)                  # sensor a 600 ms
    assert r[1]["pos"] == 1.0 and r[1]["confirmado"] and not r[1]["moviendo"]
    assert r[1]["direccion"] is None
    assert b.cal.muestras(1, "ext") == [600]
    r = b.paso(EV_E1=False)
    assert r[1]["pos"] == 1.0 and r[1]["confirmado"]


def test_b_sensor_despues_espera_en_el_extremo():
    b = Banco()
    b.paso(EV_E1=True)
    t0 = b.t
    b.paso(SC1=False)
    poses = b.hasta(0.8, t0)
    assert poses[-1] == pytest.approx(1.0)
    r = b.ultimo[1]
    assert r["moviendo"] and not r["confirmado"]
    poses = b.hasta(0.95, t0)
    assert all(p == pytest.approx(1.0) for p in poses)
    assert b.ultimo[1]["moviendo"]
    r = b.paso(SE1=True)                  # sensor a 1000 ms
    assert r[1]["confirmado"] and not r[1]["moviendo"]
    assert b.cal.muestras(1, "ext") == [1000]
    assert r[1]["duracion_ms"] == 1000


def test_c_cinco_carreras_convergen():
    b = Banco()
    for _ in range(5):
        extender(b, 1, 0.6)
        retraer(b, 1, 0.6)
    assert b.cal.duracion_ms(1, "ext") == pytest.approx(600, abs=2)
    assert b.cal.duracion_ms(1, "ret") == pytest.approx(600, abs=2)
    # la siguiente carrera ya usa la duración aprendida
    r = b.paso(EV_E1=True)
    assert r[1]["duracion_ms"] == pytest.approx(600, abs=2)


def test_d_retraccion_simetrica():
    b = Banco()
    extender(b, 1, 0.7)
    r = b.paso(EV_C1=True)
    t0 = b.t
    assert r[1]["objetivo"] == 0.0 and r[1]["pos"] == 1.0
    b.paso(SE1=False)
    poses = b.hasta(0.4, t0)
    assert poses[-1] == pytest.approx(0.5, abs=1e-6)
    assert poses == sorted(poses, reverse=True)
    b.hasta(0.9, t0)
    r = b.paso(SC1=True)
    assert r[1]["pos"] == 0.0 and r[1]["confirmado"] and not r[1]["moviendo"]
    assert b.cal.muestras(1, "ret") == [950]
    assert b.cal.muestras(1, "ext") == [700]


def test_e_paro_a_mitad_cancela_sin_registrar():
    b = Banco()
    b.paso(EV_E1=True)
    t0 = b.t
    b.paso(SC1=False)
    b.hasta(0.3, t0)
    b.paso(ACTIVE=False)                  # STOP: la válvula biestable sigue empujando
    poses = b.hasta(0.8, t0)
    assert poses[-1] == pytest.approx(1.0)   # la animación continúa
    r = b.paso(SE1=True)
    assert r[1]["pos"] == 1.0 and r[1]["confirmado"]
    assert b.cal.muestras(1, "ext") == []
    assert b.cal.duracion_ms(1, "ext") == 800


def test_e2_resetv_cancela_medicion_sin_tocar_calibracion():
    b = Banco()
    extender(b, 1, 0.6)
    retraer(b, 1, 0.6)
    antes = b.cal.como_dict()
    b.paso(EV_E1=True)
    b.paso(SC1=False)
    b.paso(RESETV=True, X0=True)
    b.paso(RESETV=False)
    b.hasta(0.6, b.t)
    b.paso(SE1=True)
    assert b.cal.muestras(1, "ext") == antes["1"]["ext"]["muestras"]
    assert b.cal.muestras(1, "ret") == antes["1"]["ret"]["muestras"]


def test_f_timeout_10s():
    b = Banco()
    b.paso(EV_E1=True)
    t0 = b.t
    b.paso(SC1=False)
    b.hasta(9.9, t0)
    assert b.ultimo[1]["moviendo"]
    vistos = []
    for _ in range(10):
        vistos.append(b.paso())
    con_timeout = [r[1] for r in vistos if r[1].get("timeout")]
    assert len(con_timeout) == 1
    assert not con_timeout[0]["moviendo"] and not con_timeout[0]["confirmado"]
    assert con_timeout[0]["pos"] == pytest.approx(1.0)
    r = vistos[-1][1]
    assert "timeout" not in r and not r["moviendo"] and r["pos"] == pytest.approx(1.0)
    # si el sensor aparece después, se confirma sin registrar
    r = b.paso(SE1=True)
    assert r[1]["confirmado"] and b.cal.muestras(1, "ext") == []


def test_g_tres_cilindros_no_se_mezclan():
    b = Banco()
    b.paso(EV_E1=True, EV_E2=True)
    t0 = b.t
    b.paso(SC1=False, SC2=False)
    b.hasta(0.3, t0)
    b.paso(EV_E3=True)                    # 3A arranca 350 ms después
    t3 = b.t
    b.paso(SC3=False)
    b.hasta(0.5, t0)
    r = b.paso(SE1=True)                  # 1A llega a 550 ms
    assert r[1]["confirmado"] and r[2]["moviendo"] and r[3]["moviendo"]
    b.hasta(0.9, t0)
    r = b.paso(SE2=True)                  # 2A llega a 950 ms
    assert r[2]["confirmado"] and r[3]["moviendo"]
    b.hasta(t3 - t0 + 1.15, t0)
    r = b.paso(SE3=True)                  # 3A llega a 1200 ms de su bobina
    assert r[3]["confirmado"]
    assert b.cal.muestras(1, "ext") == [550]
    assert b.cal.muestras(2, "ext") == [950]
    assert b.cal.muestras(3, "ext") == [1200]
    for n in (1, 2, 3):
        assert b.cal.muestras(n, "ret") == []


def test_bobina_contraria_a_mitad_cancela_y_arranca_nueva():
    b = Banco()
    b.paso(EV_E1=True)
    t0 = b.t
    b.paso(SC1=False)
    b.hasta(0.4, t0)                      # pos = 0.5
    r = b.paso(EV_E1=False, EV_C1=True)
    assert r[1]["direccion"] == "ret" and r[1]["moviendo"]
    assert 0.4 < r[1]["pos"] < 0.6
    b.hasta(0.8, t0)
    r = b.paso(SC1=True)
    assert r[1]["pos"] == 0.0 and r[1]["confirmado"]
    # ni la extensión interrumpida ni la retracción parcial se registran
    assert b.cal.muestras(1, "ext") == []
    assert b.cal.muestras(1, "ret") == []


def test_flanco_con_sensor_de_destino_ya_activo_no_mueve():
    b = Banco()
    r = b.paso(EV_C1=True)                # ya está retraído
    assert not r[1]["moviendo"] and r[1]["pos"] == 0.0
    assert b.cal.muestras(1, "ret") == []


def test_persistencia_desde_estimador(tmp_path):
    ruta = str(tmp_path / "datos" / "calibracion.json")
    b = Banco(Calibracion(ruta))
    extender(b, 2, 0.75)
    assert Calibracion(ruta).muestras(2, "ext") == [750]
