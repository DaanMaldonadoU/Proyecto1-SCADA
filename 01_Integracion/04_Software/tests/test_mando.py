# -*- coding: utf-8 -*-
"""Pruebas del árbitro de mando (core.mando) y de la firma de órdenes (core.remoto)."""
from core import mando, remoto
from core.mando import Arbitro


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def web(usuario, rol):
    return {"usuario": usuario, "rol": rol, "origen": "web"}


def cmd(op, quien=None, **kw):
    c = dict(op=op, **kw)
    if quien:
        c["quien"] = quien
    return c


def arbitro(remoto_hab=True):
    r = Reloj()
    return Arbitro(remoto_habilitado=remoto_hab, reloj=r, reloj_pared=r), r


def test_local_siempre_puede_y_toma_el_mando():
    a, _ = arbitro(remoto_hab=False)
    ok, _m, quien = a.autorizar(cmd("pulso", tag="STARTV"))
    assert ok and quien["origen"] == "local"
    assert a.estado()["titular"]["usuario"] == "HMI local"


def test_usuario_solo_ve():
    a, _ = arbitro()
    ana = web("ana", "usuario")
    assert not a.orden_mando(cmd("mando", ana, accion="pedir"))[0]
    assert not a.autorizar(cmd("pulso", ana, tag="STARTV"))[0]
    assert not a.autorizar(cmd("pulso", ana, tag="STOPV"))[0]
    assert a.autorizar(cmd("ping", ana))[0]


def test_operador_necesita_mando_y_no_escribe_parametros():
    a, _ = arbitro()
    op = web("oscar", "operador")
    ok, motivo, _q = a.autorizar(cmd("pulso", op, tag="STARTV"))
    assert not ok and "pide el mando" in motivo
    assert a.orden_mando(cmd("mando", op, accion="pedir"))[0]
    assert a.autorizar(cmd("pulso", op, tag="STARTV"))[0]
    ok, motivo, _q = a.autorizar(cmd("escribir", op, tag="T_NEUM", valor=500))
    assert not ok and "ingeniero" in motivo


def test_exclusion_y_jerarquia():
    a, _ = arbitro()
    op1, op2, ing = web("oscar", "operador"), web("olga", "operador"), web("ines", "ingeniero")
    assert a.orden_mando(cmd("mando", op1, accion="pedir"))[0]
    ok, msg = a.orden_mando(cmd("mando", op2, accion="pedir"))
    assert not ok and "oscar" in msg                       # mismo nivel: espera
    assert not a.autorizar(cmd("pulso", op2, tag="STARTV"))[0]
    assert a.orden_mando(cmd("mando", ing, accion="pedir"))[0]   # nivel mayor: preferencia
    assert a.estado()["titular"]["usuario"] == "ines"
    assert not a.autorizar(cmd("pulso", op1, tag="RESETV"))[0]
    assert a.autorizar(cmd("escribir", ing, tag="T_NEUM", valor=500))[0]


def test_local_le_quita_el_mando_a_la_web_y_la_web_no_al_local():
    a, _ = arbitro()
    adm = web("daan", "admin")
    assert a.orden_mando(cmd("mando", adm, accion="pedir"))[0]
    assert a.autorizar(cmd("pulso", tag="RESETV"))[0]      # local
    assert a.estado()["titular"]["origen"] == "local"
    ok, msg = a.orden_mando(cmd("mando", adm, accion="pedir"))
    assert not ok and "HMI local" in msg


def test_stop_siempre_pasa_para_operadores():
    a, _ = arbitro(remoto_hab=False)
    op = web("oscar", "operador")
    assert a.autorizar(cmd("pulso", op, tag="STOPV"))[0]
    a.orden_mando(cmd("mando", accion="pedir"))            # local toma el mando
    assert a.autorizar(cmd("pulso", op, tag="STOPV"))[0]


def test_remoto_deshabilitado_bloquea_y_revoca():
    a, _ = arbitro()
    op = web("oscar", "operador")
    assert a.orden_mando(cmd("mando", op, accion="pedir"))[0]
    assert not a.orden_mando(cmd("mando", op, accion="remoto", habilitar=False))[0]   # solo local
    assert a.orden_mando(cmd("mando", accion="remoto", habilitar=False))[0]
    assert a.estado()["titular"] is None
    ok, motivo, _q = a.autorizar(cmd("pulso", op, tag="STARTV"))
    assert not ok and "deshabilitado" in motivo


def test_vencimiento_y_renovacion():
    a, r = arbitro()
    op = web("oscar", "operador")
    a.orden_mando(cmd("mando", op, accion="pedir"))
    r.t += mando.DURACION_S - 1
    assert a.autorizar(cmd("pulso", op, tag="STARTV"))[0]  # renueva
    r.t += mando.DURACION_S - 1
    a.tick()
    assert a.estado()["titular"]["usuario"] == "oscar"
    r.t += 2
    a.tick()
    assert a.estado()["titular"] is None
    assert any("venció" in e[0] for e in a.sacar_eventos())


def test_solo_local_para_simulacion_y_presencia():
    a, _ = arbitro()
    adm = web("daan", "admin")
    for c in (cmd("entrada", adm, tag="SC1", valor=True), cmd("fisica", adm, auto=True),
              cmd("fuente", adm, fuente="cache"), cmd("presencia", adm, conectados=[])):
        assert not a.autorizar(c)[0]
    assert a.autorizar(cmd("entrada", tag="SC1", valor=True))[0]


def test_enlace_web_y_presencia():
    a, r = arbitro()
    a.presencia({"op": "presencia", "conectados": [{"usuario": "ana", "rol": "usuario", "desde": 1}]})
    assert a.estado()["enlace_web"] and a.estado()["conectados"][0]["usuario"] == "ana"
    op = web("oscar", "operador")
    a.orden_mando(cmd("mando", op, accion="pedir"))
    r.t += mando.ENLACE_VIGENTE_S + 1
    a.tick()
    e = a.estado()
    assert not e["enlace_web"] and e["conectados"] == [] and e["titular"] is None


def test_permiso_por_rol():
    assert mando.permiso_por_rol("operador", {"op": "pulso", "tag": "STARTV"})[0]
    assert not mando.permiso_por_rol("operador", {"op": "escribir", "tag": "T_NEUM", "valor": 1})[0]
    assert mando.permiso_por_rol("ingeniero", {"op": "escribir", "tag": "T_NEUM", "valor": 1})[0]
    assert not mando.permiso_por_rol("admin", {"op": "entrada", "tag": "SC1", "valor": 1})[0]
    assert not mando.permiso_por_rol("desconocido", {"op": "pulso", "tag": "STOPV"})[0]


# ---------------------------------------------------------------------------- firma
def test_firma_valida_repetida_alterada_y_vieja():
    clave = remoto.generar_clave()
    t = [5000.0]
    v = remoto.Verificador(clave, reloj=lambda: t[0])
    o = remoto.nueva_orden(clave, {"op": "pulso", "tag": "STARTV", "ms": 300},
                           {"usuario": "oscar", "rol": "operador"}, t=5000.0)
    assert v.verificar(o) == (True, "")
    assert v.verificar(o) == (False, "orden repetida")
    o2 = remoto.nueva_orden(clave, {"op": "pulso", "tag": "STARTV", "ms": 300},
                            {"usuario": "oscar", "rol": "operador"}, t=5000.0)
    alterada = dict(o2, quien={"usuario": "oscar", "rol": "admin", "origen": "web"})
    assert v.verificar(alterada) == (False, "firma inválida")
    otra = remoto.nueva_orden(remoto.generar_clave(), {"op": "ping"}, {"usuario": "x", "rol": "admin"}, t=5000.0)
    assert v.verificar(otra) == (False, "firma inválida")
    vieja = remoto.nueva_orden(clave, {"op": "ping"}, {"usuario": "x", "rol": "admin"}, t=5000.0 - 100)
    assert not v.verificar(vieja)[0]
