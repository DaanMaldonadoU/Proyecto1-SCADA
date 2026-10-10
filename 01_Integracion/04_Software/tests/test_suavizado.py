# -*- coding: utf-8 -*-
"""
tests/test_suavizado.py — Modo suave (core/suavizado.py) contra la planta simulada.

La planta es el ladder del 18-sep + la física de gateway/ (BackendSim sin reloj real); las
lecturas pasan por gateway.backend_sim.EnlaceLento con semilla fija, que imita el enlace
ENI ↔ SLC del laboratorio (cada archivo del PLC se refresca cada 0,15–2,4 s). Se compara la
animación del suavizador (muestreada cada 15 ms, como el HMI) con la posición verdadera.

Sin Qt ni COM. Python 3.12+.
"""
import pytest

from core import tags
from core.estimador import EstimadorCarrera
from core.calibracion import Calibracion
from core.suavizado import ALCANCE_S, REPOSICION_MS, Suavizador
from gateway.backend_sim import BackendSim, EnlaceLento
from gateway.fisica import CadenaNeumatica

PERIODO_GW = 0.1        # periodo del gateway en OPC
CUADRO = 0.015          # tick de la GUI


def _snapshot(valores, t_etapa, sin_etapa=False):
    """Lo mismo que gateway/servidor.py::_construir_snapshot con los valores leídos."""
    bits, ints = {}, {}
    for palabra in tags.PALABRAS:
        if palabra in valores and not (sin_etapa and palabra == tags.DIRECCION["X0"].split("/")[0]):
            bits.update(tags.decodificar_palabra(palabra, valores[palabra]))
    for tag in tags.TAGS_BIT:
        d = tags.DIRECCION[tag]
        if d in valores and tag not in bits:
            bits[tag] = bool(valores[d])
    for tag in tags.TAGS_INT:
        d = tags.DIRECCION[tag]
        if d in valores:
            ints[tag] = int(valores[d])
    etapa = None if sin_etapa else tags.etapa_activa(bits)
    return {"conectado": True, "modo": "REAL", "bits": bits, "ints": ints, "etapa": etapa,
            "t_etapa": t_etapa, "pos": None, "pos_neum": None}


class _Corrida:
    """Planta simulada + enlace (opcional) + suavizador (+ estimador clásico para comparar)."""

    def __init__(self, lento=True, semilla=7, sin_etapa=False, presets=None, ciclos=2):
        self.be = BackendSim()
        self.be.conectar()
        p = dict(tags.PRESETS_DEFECTO)
        p.update(presets or {})
        p["N_CICLOS"] = ciclos
        for tag, valor in p.items():
            for d in tags.direcciones_de_escritura(tag):
                self.be.ladder.escribir(d, valor)
        self.enlace = EnlaceLento(semilla) if lento else None
        self.sin_etapa = sin_etapa
        self.cal = Calibracion()
        self.suave = Suavizador(self.cal, cadena=CadenaNeumatica())
        self.clasico = EstimadorCarrera(Calibracion())
        self.t = 0.0
        self._t_gw = 0.0
        self._etapa_gw = None
        self._t_etapa0 = 0.0
        self.muestras = []          # (t, pos verdadera [3], pos suave [3], pos clásica [3], salida)
        self.snaps = []

    def pulso_start(self):
        self.be.ladder.escribir(tags.DIRECCION["STARTV"], 1)
        self.correr(0.3)
        self.be.ladder.escribir(tags.DIRECCION["STARTV"], 0)

    def leer(self, tag):
        return self.be.ladder.leer(tags.DIRECCION[tag])

    def escribir(self, tag, valor):
        self.be.ladder.escribir(tags.DIRECCION[tag], valor)

    def correr(self, segundos):
        fin = self.t + segundos
        clasico = [0.0, 0.0, 0.0]
        while self.t < fin - 1e-9:
            self.be.avanzar(CUADRO)
            self.t += CUADRO
            if self.t - self._t_gw >= PERIODO_GW - 1e-9:
                self._t_gw = self.t
                valores, _q, _ms = self.be._leer(tags.ITEMS_RAPIDOS + tags.ITEMS_LENTOS)
                if self.enlace is not None:
                    valores = self.enlace.filtrar(valores, self.t)
                snap = _snapshot(valores, 0.0, self.sin_etapa)
                if snap["etapa"] != self._etapa_gw:
                    self._etapa_gw, self._t_etapa0 = snap["etapa"], self.t
                snap["t_etapa"] = round(self.t - self._t_etapa0, 3)
                self.snaps.append((self.t, snap))
                self.suave.actualizar(self.t, snap)
                est = self.clasico.actualizar(self.t, snap["bits"])
                clasico = [est[n]["pos"] for n in (1, 2, 3)]
            salida = self.suave.muestrear(self.t)
            self.muestras.append((self.t, list(self.be.fis.pos), salida["pos"], clasico, salida))


def _extensiones(serie):
    """Veces que la serie cruza 0,98 hacia arriba."""
    n, afuera = 0, serie[0] >= 0.98
    for p in serie[1:]:
        if not afuera and p >= 0.98:
            n += 1
            afuera = True
        elif afuera and p <= 0.5:
            afuera = False
    return n


def _max_salto(serie):
    return max(abs(b - a) for a, b in zip(serie, serie[1:]))


@pytest.fixture(scope="module")
def corrida_lenta():
    c = _Corrida(lento=True, semilla=11, ciclos=3)
    c.correr(1.0)
    c.pulso_start()
    c.correr(45.0)
    return c


def test_planta_simulada_termina(corrida_lenta):
    assert corrida_lenta.leer("C_ACC") == 0 or corrida_lenta.be.ladder.X(0)


def test_sin_saltos_con_enlace_lento(corrida_lenta):
    """El clásico salta de extremo a extremo; el suave nunca más de lo que permite ALCANCE_S."""
    tope = CUADRO / min(ALCANCE_S, REPOSICION_MS / 1000.0) + 1e-6
    for k in range(3):
        suave = [m[2][k] for m in corrida_lenta.muestras]
        assert _max_salto(suave) <= tope, "cilindro %dA" % (k + 1)
    saltos_clasico = max(_max_salto([m[3][k] for m in corrida_lenta.muestras]) for k in range(3))
    assert saltos_clasico > 0.5     # el problema que el modo suave resuelve


def test_todas_las_carreras_se_ven(corrida_lenta):
    """Cada salida real aparece en la animación (repuesta si las lecturas la perdieron)."""
    for k in range(3):
        reales = _extensiones([m[1][k] for m in corrida_lenta.muestras])
        vistas = _extensiones([m[2][k] for m in corrida_lenta.muestras])
        assert reales == 3, "la planta simulada debía hacer 3 ciclos"
        assert vistas == reales, "cilindro %dA: %d vistas de %d" % (k + 1, vistas, reales)


def test_esperas_cortas_repone_carreras_perdidas():
    """Con T_ESPERA = 0,2 s el enlace lento se come carreras enteras: el estimador clásico no las
    muestra; el suave las repone (todas se ven) y sigue sin saltos."""
    c = _Corrida(lento=True, semilla=5, ciclos=3, presets={"T_ESPERA": 20, "T_NEUM": 200})
    c.correr(1.0)
    c.pulso_start()
    c.correr(30.0)
    assert c.suave.repuestas >= 1
    perdidas_clasico = 0
    for k in range(3):
        reales = _extensiones([m[1][k] for m in c.muestras])
        assert reales == 3
        assert _extensiones([m[2][k] for m in c.muestras]) == reales, "cilindro %dA" % (k + 1)
        perdidas_clasico += reales - _extensiones([m[3][k] for m in c.muestras])
        assert _max_salto([m[2][k] for m in c.muestras]) <= CUADRO / min(ALCANCE_S, REPOSICION_MS / 1000.0) + 1e-6
    assert perdidas_clasico >= 1


def test_retraso_acotado(corrida_lenta):
    """La animación va detrás de la planta, pero no más de lo que tarda el enlace."""
    for k in range(3):
        t_real = [m[0] for m, a in zip(corrida_lenta.muestras[1:], corrida_lenta.muestras)
                  if a[1][k] < 0.98 <= m[1][k]]
        t_vista = [m[0] for m, a in zip(corrida_lenta.muestras[1:], corrida_lenta.muestras)
                   if a[2][k] < 0.98 <= m[2][k]]
        assert len(t_real) == len(t_vista)
        retrasos = [v - r for r, v in zip(t_real, t_vista)]
        assert all(-0.2 <= d <= 3.5 for d in retrasos), retrasos


def test_acc_previsto_monotono_y_acotado(corrida_lenta):
    """Dentro de una etapa el ACC previsto nunca retrocede y nunca pasa del PRE."""
    previo = {}
    for _t, _real, _s, _c, salida in corrida_lenta.muestras:
        etapa = salida["etapa"]
        if etapa is None:
            continue
        timer = tags.TIMER_DE_ETAPA.get(etapa)
        if timer is None:
            previo = {}
            continue
        acc = salida["acc"][timer]
        pre = tags.PRESETS_DEFECTO["T_NEUM" if timer == tags.TIMER_NEUMATICO else "T_ESPERA"]
        assert 0 <= acc <= pre
        clave = (etapa, salida["indice"] >= 0)
        if previo.get("etapa") == etapa:
            assert acc >= previo["acc"]
        previo = {"etapa": etapa, "acc": acc}
        del clave


def test_sin_enlace_sigue_de_cerca():
    """Con lecturas al día, la animación casi coincide con la planta (solo el periodo del gateway)."""
    c = _Corrida(lento=False, ciclos=1)
    c.correr(0.5)
    c.pulso_start()
    c.correr(16.0)
    for k in range(3):
        errores = [abs(m[1][k] - m[2][k]) for m in c.muestras]
        assert sum(errores) / len(errores) < 0.06, "cilindro %dA" % (k + 1)
        assert _extensiones([m[2][k] for m in c.muestras]) == 1


def test_sin_etapa_anima_por_bobinas():
    """Programa sin B3:3 (como el del 03-oct): sin cursor, pero sigue sin saltos."""
    c = _Corrida(lento=True, semilla=3, sin_etapa=True, ciclos=1)
    c.correr(0.5)
    c.pulso_start()
    c.correr(16.0)
    assert c.muestras[-1][4]["sin_etapa"] is True
    tope = CUADRO / ALCANCE_S + 1e-6
    for k in range(3):
        assert _max_salto([m[2][k] for m in c.muestras]) <= tope
        assert max(m[2][k] for m in c.muestras) >= 0.98     # se vio salir


def _snap_manual(etapa, bits=None, ints=None, t_etapa=0.0):
    b = {"SC1": True, "SC2": True, "SC3": True, "STOP_1": True}
    b.update(bits or {})
    if etapa is not None:
        b["X%d" % etapa] = True
    i = {tags.tag_timer(n, "PRE"): 100 for n in range(5)}
    i[tags.tag_timer(5, "PRE")] = 500
    i.update(ints or {})
    return {"conectado": True, "bits": b, "ints": i, "etapa": etapa, "t_etapa": t_etapa}


def test_dn_previsto_adelanta_el_regreso():
    """En X2 el regreso de 1A arranca al cumplirse T4:0 aunque ninguna lectura lo diga aún."""
    s = Suavizador()
    s.actualizar(0.0, _snap_manual(1, {"EV_E1": True, "SC1": False}))
    s.actualizar(1.0, _snap_manual(2, {"EV_E1": True, "SC1": False, "SE1": True}, {"T0_ACC": 0}))
    t = 1.0
    while t < 2.2:
        t += CUADRO
        m = s.muestrear(t)
    # T4:0 = 1 s desde la entrada en X2 → a los 2,2 s ya va de regreso (índice 5) sin leerlo.
    assert m["indice"] == 5
    assert m["objetivo"][0] == 0.0 and m["pos"][0] < 1.0
    assert m["acc"][0] == 100


def test_reset_cancela_reposiciones():
    s = Suavizador()
    s.actualizar(0.0, _snap_manual(1, {"EV_E1": True}))
    s.actualizar(0.1, _snap_manual(5, {"SC1": True}))     # salto X1 → X5: 1A repuesta y 2A también
    assert s.repuestas >= 1
    s.actualizar(0.2, _snap_manual(0))                     # RESET (GS) a mitad de ciclo
    m = s.muestrear(0.3)
    assert m["indice"] == 0 and m["objetivo"] == [0.0, 0.0, 0.0]


def test_ciclo_nuevo_repone_lo_que_falto():
    """X7 → X3 (se perdieron X1 y X2 del ciclo nuevo): 1A sale y regresa en la animación."""
    s = Suavizador()
    s.actualizar(0.0, _snap_manual(7))
    s.muestrear(0.0)
    s.actualizar(0.1, _snap_manual(3, {}, {"T1_ACC": 10}))
    t, maximo = 0.1, 0.0
    while t < 1.5:
        t += CUADRO
        maximo = max(maximo, s.muestrear(t)["pos"][0])
    assert maximo >= 0.98
    assert s.muestrear(t)["pos"][0] == 0.0


def test_discrepancia_manda_el_sensor():
    """Bobina de salida encendida pero SC sigue activo mucho tiempo (sin aire): vuelve al sensor."""
    s = Suavizador()
    snap = _snap_manual(None, {"EV_E1": True})
    s.actualizar(0.0, snap)
    t, maximo = 0.0, 0.0
    while t < 6.0:
        t += CUADRO
        s.actualizar(t, snap) if int(t * 10) % 3 == 0 else None
        m = s.muestrear(t)
        maximo = max(maximo, m["pos"][0])
    assert maximo >= 0.98                 # primero creyó a la bobina
    assert m["discrepancia"][0] is True
    assert m["pos"][0] == 0.0             # y luego al sensor


def test_desconexion_congela():
    s = Suavizador()
    s.actualizar(0.0, _snap_manual(1, {"EV_E1": True}))
    s.muestrear(0.0)
    p = s.muestrear(0.3)["pos"][0]
    s.actualizar(0.31, {"conectado": False})
    assert s.muestrear(1.0)["pos"][0] == p


# ============================================================================
# Puente: el mismo suavizado hacia el gemelo (puente/enlace.py, --suave auto|si|no)
# ============================================================================
def _puente(suave):
    from puente.enlace import Puente
    return Puente("ws://127.0.0.1:1/ws/planta", "x" * 32, suave=suave, log=lambda _m: None)


def _snap_gateway(pos):
    s = _snap_manual(1, {"EV_E1": True})
    s.update({"modo": "REAL" if pos is None else "SIM", "pos": pos, "pos_neum": None, "seq": 1})
    return s


def test_puente_auto_suaviza_solo_sin_pos():
    p = _puente("auto")
    real = p._completar(_snap_gateway(None))
    enviado = p.preparar_envio(real, t=10.0)
    assert enviado is not real and "suave" not in real          # no toca el snapshot guardado
    assert enviado["pos_estimada"] is True
    assert set(enviado["suave"]) >= {"v", "obj", "etapa", "t_etapa", "acc", "repuestas"}
    assert enviado["suave"]["obj"][0] == 1.0 and enviado["suave"]["etapa"] == 1
    sim = p._completar(_snap_gateway([0.3, 0.0, 0.0]))
    assert p.preparar_envio(sim) is sim and "suave" not in sim  # SIM: la posición del gateway tal cual


def test_puente_si_y_no():
    p = _puente("si")
    assert "suave" in p.preparar_envio(p._completar(_snap_gateway([0.3, 0.0, 0.0])))
    p = _puente("no")
    s = p._completar(_snap_gateway(None))
    assert p.preparar_envio(s) is s and "suave" not in s
