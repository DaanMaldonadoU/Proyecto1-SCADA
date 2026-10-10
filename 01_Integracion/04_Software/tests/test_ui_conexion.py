# -*- coding: utf-8 -*-
"""Pruebas de `ui/conexion.py` (mds/ARQUITECTURA.md §6.6).

1. Funciones puras sin bucle de eventos: argumentos de gateway/puente/gemelo, configuración de
   ida y vuelta, `interpretar_json`, candidatos de intérprete de 32 bits.
2. Ciclo real `conectar()` / `desconectar()` en modo SIM con gateway propio en puertos efímeros:
   `estado` llega a "conectado" y el subproceso del gateway muere al desconectar.

Las pruebas con Qt saltan si no hay binding (PySide6 o PyQt5). Sin pantalla: QT_QPA_PLATFORM=offscreen.
La aplicación Qt se comparte con otros módulos de prueba del mismo proceso; el bucle se avanza
con processEvents() en lazos con plazo, nunca con exec().
"""
import argparse
import json
import os
import socket
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt = pytest.importorskip("ui.qt_compat")

from core import protocolo  # noqa: E402
from ui import conexion as cx  # noqa: E402

QCoreApplication = qt.QCoreApplication


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def avanzar(cond, plazo_s, app):
    """processEvents() hasta que `cond()` sea verdad o venza el plazo. Devuelve cond()."""
    limite = time.time() + plazo_s
    while time.time() < limite:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


# ============================================================================
# Funciones puras
# ============================================================================
def test_config_defecto_y_normalizacion():
    cfg = cx.config_defecto()
    assert cfg["modo"] == "SIM" and cfg["servidor"] == "RSLinx Local OPC Server"
    assert cfg["topic"] == "PROYECTO1_TEST" and cfg["periodoMs"] == 50 and cfg["fuente"] == "cache"
    assert cfg["pub"] == protocolo.PUB_DEFECTO and cfg["cmd"] == protocolo.CMD_DEFECTO
    assert cfg["destinoWeb"] == "ninguno" and cfg["urlServidor"].startswith("wss://")
    assert cfg["mqttUrl"] == "" and cfg["extrasPuente"] == ""
    assert cfg["lanzarGateway"] is True and cfg["abrirNavegador"] is True
    assert cfg["puertoLocal"] == cx.puerto_local_defecto() > 0
    assert cx.topic_defecto("REAL") == cx.topic_defecto("EMULATE") == "PROYECTO1_TEST"
    assert cx.periodo_defecto("SIM") == 50 and cx.periodo_defecto("REAL") == 100


def test_argumentos_gateway_sim_y_opc():
    cfg = cx.config_defecto()
    a = cx.argumentos_gateway(cfg, "py64")
    assert a[:5] == ["py64", "-m", "gateway", "--modo", "SIM"]
    assert "--servidor" not in a and "--fuente" not in a and "--remoto" not in a
    assert a[a.index("--periodo") + 1] == "50"
    assert a[a.index("--pub") + 1] == protocolo.PUB_DEFECTO and a[a.index("--cmd") + 1] == protocolo.CMD_DEFECTO

    cfg.update(modo="REAL", topic="PROYECTO1_REAL", periodoMs=100, fuente="cache", remotoAlConectar=True,
               pub="tcp://127.0.0.1:6000", cmd="tcp://127.0.0.1:6001")
    a = cx.argumentos_gateway(cfg, "py32", extra=["--sin-historial"])
    assert a[a.index("--modo") + 1] == "REAL"
    assert a[a.index("--servidor") + 1] == "RSLinx Local OPC Server"
    assert a[a.index("--topic") + 1] == "PROYECTO1_REAL"
    assert a[a.index("--periodo") + 1] == "100" and a[a.index("--fuente") + 1] == "cache"
    assert a[a.index("--pub") + 1] == "tcp://127.0.0.1:6000" and a[a.index("--cmd") + 1] == "tcp://127.0.0.1:6001"
    assert "--remoto" in a and a[-1] == "--sin-historial"


def test_argumentos_puente_url_mqtt_y_extras():
    cfg = cx.config_defecto()
    a = cx.argumentos_puente(cfg, "py")
    assert a == ["py", "-m", "puente", "--url", cfg["urlServidor"], "--pub", cfg["pub"], "--cmd", cfg["cmd"]]
    assert "--mqtt" not in a

    cfg["mqttUrl"] = "mqtts://usuario:clave@broker.smartsensorslab.com:8883"
    a = cx.argumentos_puente(cfg, "py")
    assert a[a.index("--url") + 1] == cfg["urlServidor"]
    assert a[a.index("--mqtt") + 1] == cfg["mqttUrl"]

    cfg["urlServidor"] = "   "
    a = cx.argumentos_puente(cfg, "py")
    assert "--url" not in a and a[a.index("--mqtt") + 1] == cfg["mqttUrl"]

    cfg["extrasPuente"] = '--hz 5 --planta "mi planta" --prefijo scada'
    a = cx.argumentos_puente(cfg, "py")
    assert a[-6:] == ["--hz", "5", "--planta", '"mi planta"', "--prefijo", "scada"]   # tal cual (posix=False)

    assert cx.puente_configurado(cfg)
    cfg["mqttUrl"] = ""
    assert not cx.puente_configurado(cfg)


def test_argumentos_gemelo():
    cfg = cx.config_defecto()
    cfg.update(hostLocal="0.0.0.0", puertoLocal=3002, pub="tcp://127.0.0.1:7000", cmd="tcp://127.0.0.1:7001")
    a = cx.argumentos_gemelo(cfg, "py")
    assert a[:3] == ["py", "-m", "digital_twin.local"]
    assert "--gateway" not in a
    assert a[a.index("--host") + 1] == "0.0.0.0" and a[a.index("--puerto") + 1] == "3002"
    assert a[a.index("--pub") + 1] == "tcp://127.0.0.1:7000"
    assert "--publico" not in a and "--sin-navegador" not in a
    cfg.update(publicoLocal=True, abrirNavegador=False)
    a = cx.argumentos_gemelo(cfg, "py")
    assert "--publico" in a and "--sin-navegador" in a
    assert cx.url_gemelo(cfg) == "http://127.0.0.1:3002/"
    cfg["hostLocal"] = "192.168.1.20"
    assert cx.url_gemelo(cfg) == "http://192.168.1.20:3002/"


def test_config_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "sub" / "conexion.json"
    assert cx.cargar_config(ruta) == cx.config_defecto()           # no existe → defectos
    cfg = cx.config_defecto()
    cfg.update(modo="EMULATE", topic="PROYECTO1_TEST", periodoMs=120, lanzarGateway=False,
               destinoWeb="local", puertoLocal=4000, mqttUrl="mqtt://a:b@c", extrasPuente="--hz 3",
               python32=r"C:\Python312-32\python.exe", itemPrueba="I:1.0")
    assert cx.guardar_config(ruta, cfg)
    leido = cx.cargar_config(ruta)
    assert leido == cfg
    # Valores inválidos o desconocidos en el archivo: se corrigen y se ignoran
    ruta.write_text(json.dumps({"modo": "RARO", "periodoMs": "abc", "puertoLocal": 99999, "fuente": "x",
                                "destinoWeb": "nube", "desconocida": 1, "topic": ""}), encoding="utf-8")
    cfg = cx.cargar_config(ruta)
    assert cfg["modo"] == "SIM" and cfg["periodoMs"] == 50 and cfg["fuente"] == "cache"
    assert cfg["destinoWeb"] == "ninguno" and cfg["puertoLocal"] == cx.puerto_local_defecto()
    assert cfg["topic"] == "PROYECTO1_TEST" and "desconocida" not in cfg
    ruta.write_text("{ esto no es json", encoding="utf-8")
    assert cx.cargar_config(ruta) == cx.config_defecto()


def test_interpretar_json_tolera_basura():
    assert cx.interpretar_json('{"ok": true, "servidores": ["A"]}') == {"ok": True, "servidores": ["A"]}
    texto = 'pywin32 aviso {raro}\nAVISO: algo\n{"ok": true, "items": ["[T]I:1.0"]}\ntexto después {x}'
    assert cx.interpretar_json(texto) == {"ok": True, "items": ["[T]I:1.0"]}
    assert cx.interpretar_json('{"ok": false, "error": "Falta OpenOPC"}')["error"] == "Falta OpenOPC"
    r = cx.interpretar_json("Traceback…\nModuleNotFoundError: No module named x")
    assert r["ok"] is False and "No module named x" in r["error"]
    assert cx.interpretar_json("")["ok"] is False
    assert cx.interpretar_json('{"a": 1} {"ok": true}') == {"ok": True}      # se prefiere el que trae "ok"
    assert cx.interpretar_json("[1, 2]")["ok"] is False


def test_candidatos_python32(tmp_path):
    c = cx.candidatos_python32(tmp_path)
    assert c == [("py -3.12-32", ["py", "-3.12-32"])]
    venv = tmp_path / ".venv32" / "Scripts" / "python.exe"
    venv.parent.mkdir(parents=True)
    venv.write_bytes(b"")
    c = cx.candidatos_python32(tmp_path)
    assert c[0] == (".venv32", [str(venv)]) and len(c) == 2
    c = cx.candidatos_python32(tmp_path, manual=r"D:\otro\python.exe")
    assert c[0] == ("configurado", [r"D:\otro\python.exe"]) and c[1][0] == ".venv32"
    assert cx.interpretar_comprobacion_32("C:\\py32\\python.exe\nTrue\n") == ("C:\\py32\\python.exe", True)
    assert cx.interpretar_comprobacion_32("C:\\py64\\python.exe\nFalse\n") == ("C:\\py64\\python.exe", False)
    assert cx.interpretar_comprobacion_32("") == ("", False)


# ============================================================================
# Con Qt (sin ventana)
# ============================================================================
def args_hmi(**kw):
    base = dict(lanzar_gateway=None, gateway_falso=False, sin_conexion=False,
                pub=protocolo.PUB_DEFECTO, cmd=protocolo.CMD_DEFECTO)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def planta(app):
    from ui.cliente import Planta
    p = Planta()
    yield p
    p.cerrar()


def test_modelo_consola(app, planta, tmp_path):
    m = cx.ModeloConsola(maximo=5)
    for i in range(7):
        m.agregar("gateway" if i % 2 else "hmi", "línea %d" % i)
    assert m.rowCount() == 5 and m.total == 5
    assert m.data(m.index(0, 0), m.ROL_LINEA) == "línea 2"
    assert m.data(m.index(4, 0), m.ROL_LINEA) == "línea 6"
    assert m.data(m.index(4, 0), m.ROL_ORIGEN) == "hmi"
    assert len(m.data(m.index(0, 0), m.ROL_HORA)) == 8
    assert set(m.roleNames().values()) == {b"hora", b"origen", b"linea"}
    m.alternarOrigen("gateway")
    assert m.filtro == ["gateway"] and m.rowCount() == 2
    m.agregar("hmi", "oculta")
    assert m.rowCount() == 2 and m.total == 5
    m.agregar("gateway", "visible")                 # expulsa "línea 3" (gateway, visible) y entra "visible"
    assert m.rowCount() == 2 and m.data(m.index(1, 0), m.ROL_LINEA) == "visible"
    assert m.data(m.index(0, 0), m.ROL_LINEA) == "línea 5"
    m.alternarOrigen("gateway")
    assert m.filtro == [] and m.rowCount() == 5
    m.limpiar()
    assert m.rowCount() == 0 and m.total == 0


def test_propiedades_y_modo_ajusta_topic_y_periodo(app, planta, tmp_path):
    c = cx.Conexion(planta, args_hmi(pub="tcp://127.0.0.1:6100"), ruta_config=tmp_path / "c.json",
                    raiz=tmp_path, detectar_python32=False)
    assert c.estado == "desconectado" and c.autoAbrir is True and c.gatewayExterno is False
    assert c.pub == "tcp://127.0.0.1:6100" and c.cmd == protocolo.CMD_DEFECTO   # --pub manda sobre lo guardado
    assert c.gatewayEstado == c.puenteEstado == c.gemeloEstado == "parado"
    assert c.python32Disponible is False and c.consola.rowCount() >= 1
    c.modo = "REAL"
    assert c.topic == "PROYECTO1_TEST" and c.periodoMs == 100
    c.modo = "EMULATE"
    assert c.topic == "PROYECTO1_TEST" and c.periodoMs == 100
    c.topic = "MI_TOPIC"
    c.modo = "REAL"
    assert c.topic == "MI_TOPIC"                 # el usuario lo cambió: se respeta
    c.modo = "SIM"
    assert c.periodoMs == 50
    c.hostLocal = "0.0.0.0"
    c.puertoLocal = 4321
    assert c.urlGemelo == "http://127.0.0.1:4321/"
    c.guardar()
    assert "guardada" in c.mensaje
    leido = cx.cargar_config(tmp_path / "c.json")
    assert leido["topic"] == "MI_TOPIC" and leido["puertoLocal"] == 4321 and leido["pub"] == "tcp://127.0.0.1:6100"
    c2 = cx.Conexion(planta, args_hmi(lanzar_gateway="SIM", sin_conexion=True), ruta_config=tmp_path / "c.json",
                     raiz=tmp_path, detectar_python32=False)
    assert c2.autoAbrir is False and c2.gatewayExterno is True
    c.cerrar()
    c2.cerrar()


def test_conectar_opc_sin_python32_da_error(app, planta, tmp_path):
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    c.modo = "EMULATE"
    c.pub, c.cmd = "tcp://127.0.0.1:%d" % puerto_libre(), "tcp://127.0.0.1:%d" % puerto_libre()   # nadie escucha
    c.conectar()
    assert c.estado == "error" and "32 bits" in c.mensaje
    assert c.gatewayEstado == "parado"
    c.buscarServidores()
    assert c.buscando is False and "32 bits" in c.mensajeOpc
    c.cerrar()


def test_deteccion_python32_con_candidato_de_64_bits(app, planta, tmp_path):
    """El intérprete de esta máquina es de 64 bits: la detección lo prueba y lo descarta."""
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    c._candidatos = [("falso", [sys.executable]), ("inexistente", [str(tmp_path / "no_existe.exe")])]
    c._python32_buscando = True
    c._probar_siguiente_candidato()
    assert avanzar(lambda: not c.python32Buscando, 20.0, app)
    es32 = sys.maxsize <= 2 ** 32
    assert c.python32Disponible is es32
    assert (c.python32 == sys.executable) is es32
    lineas = c.consola.lineas("hmi")
    assert any("64 bits" in ln or "32 bits" in ln for ln in lineas)
    c.cerrar()


def test_ciclo_conectar_desconectar_sim(app, planta, tmp_path):
    """Gateway SIM propio en puertos efímeros: estado → conectado; al desconectar muere el subproceso."""
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=cx.RAIZ, detectar_python32=False)
    c.extra_gateway = ["--sin-historial"]
    c.modo = "SIM"
    c.lanzarGateway = True
    c.pub = "tcp://127.0.0.1:%d" % puerto_libre()
    c.cmd = "tcp://127.0.0.1:%d" % puerto_libre()
    c.destinoWeb = "ninguno"
    c.conectar()
    assert c.estado == "conectando" and c.gatewayPropio is True
    assert c.gatewayEstado in ("arrancando", "corriendo")
    assert avanzar(lambda: c.estado == "conectado", 30.0, app), (c.estado, c.mensaje, c.consola.lineas())
    assert planta.conectado and planta.modo == "SIM" and planta.gatewayVivo
    assert c.gatewayEstado == "corriendo" and c._gateway.vivo()
    assert any("publicando" in ln for ln in c.consola.lineas("gateway"))
    assert (tmp_path / "c.json").exists()                              # conectar() guarda

    c.desconectar()
    assert c.estado == "desconectado" and c.gatewayPropio is False
    assert not planta.conectado and not planta.gatewayVivo
    assert avanzar(lambda: c.gatewayEstado == "parado" and not c._gateway.vivo(), 10.0, app), c.gatewayEstado
    c.cerrar()


def test_gateway_propio_que_muere_pasa_a_error(app, planta, tmp_path):
    """Puerto CMD ocupado → el gateway sale con código 1 y la última línea de stderr va a `mensaje`.
    (Con el PUB ocupado ya no se lanza: se intenta usar lo que escucha ahí, ver la prueba siguiente.)"""
    ocupado = socket.socket()
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen(1)
    puerto = ocupado.getsockname()[1]
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=cx.RAIZ, detectar_python32=False)
    c.extra_gateway = ["--sin-historial"]
    c.modo = "SIM"
    c.pub = "tcp://127.0.0.1:%d" % puerto_libre()
    c.cmd = "tcp://127.0.0.1:%d" % puerto
    try:
        c.conectar()
        assert avanzar(lambda: c.estado == "error", 30.0, app), (c.estado, c.mensaje)
        assert c.gatewayEstado == "error" and c.gatewayPropio is False
        assert "sockets" in c.mensaje or "gateway" in c.mensaje.lower()
    finally:
        c.cerrar()
        ocupado.close()


def test_pub_ocupado_por_otro_programa(app, planta, tmp_path, monkeypatch):
    """Algo que no es un gateway ocupa el PUB: no se lanza un gateway que fallaría; error claro al vencer el plazo."""
    monkeypatch.setattr(cx, "PLAZO_SNAPSHOT_MS", 1500)
    ocupado = socket.socket()
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen(5)
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    c.pub = "tcp://127.0.0.1:%d" % ocupado.getsockname()[1]
    c.cmd = "tcp://127.0.0.1:%d" % puerto_libre()
    try:
        c.conectar()
        assert c.gatewayPropio is False and c.gatewayEstado == "parado"
        assert avanzar(lambda: c.estado == "error", 6.0, app), (c.estado, c.mensaje)
        assert "no publica" in c.mensaje
    finally:
        c.cerrar()
        ocupado.close()


# ============================================================================
# Vinculación con el servidor web (sesión 14): datos/puente.clave desde la ventana
# ============================================================================
def test_resumen_clave(tmp_path):
    assert cx.resumen_clave(tmp_path / "no_existe") == ""
    (tmp_path / "k").write_text("abcdEFGH" * 4 + "\n", encoding="utf-8")
    assert cx.resumen_clave(tmp_path / "k") == "abcd… (32 caracteres)"


def test_guardar_clave_pegada(app, planta, tmp_path):
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    assert c.claveExiste is False and c.claveResumen == ""
    c.guardarClave("corta")
    assert c.claveExiste is False and c.vinculoOk is False and "clave no guardada" in c.mensajeVinculo
    c.guardarClave("  " + "Q" * 43 + "\n")
    assert c.claveExiste is True and c.vinculoOk is True
    assert (tmp_path / "datos" / "puente.clave").read_text(encoding="utf-8").strip() == "Q" * 43
    assert c.claveResumen.startswith("QQQQ…")
    c.cerrar()


def test_vincular_servidor_en_hilo(app, planta, tmp_path, monkeypatch):
    """El slot no bloquea la GUI: la petición va en un hilo y el resultado vuelve por señal."""
    llamadas = []

    def falso(url, usuario, clave, **_kw):
        llamadas.append((url, usuario, clave))
        if clave != "buena":
            return {"ok": False, "msg": "usuario o contraseña incorrectos", "status": 401}
        return {"ok": True, "clave": "K" * 40, "url": "https://ejemplo.test"}

    monkeypatch.setattr(cx.vincular, "obtener_clave", falso)
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    assert c.usuarioServidor == cx.USUARIO_SERVIDOR_DEFECTO == "daan"
    c.vincularServidor("", "x")
    assert not llamadas and "usuario" in c.mensajeVinculo
    c.vincularServidor("admin", "mala")
    assert avanzar(lambda: not c.vinculando, 5.0, app)
    assert c.vinculoOk is False and "incorrectos" in c.mensajeVinculo and c.claveExiste is False
    c.vincularServidor("admin", "buena")
    assert avanzar(lambda: not c.vinculando, 5.0, app)
    assert c.vinculoOk is True and c.claveExiste is True and "ejemplo.test" in c.mensajeVinculo
    assert llamadas[-1] == (cx.URL_SERVIDOR_DEFECTO, "admin", "buena")
    assert c.usuarioServidor == "admin"                          # se recuerda el usuario que funcionó
    assert cx.cargar_config(tmp_path / "c.json")["usuarioServidor"] == "admin"
    assert "buena" not in (tmp_path / "c.json").read_text(encoding="utf-8")   # la contraseña nunca
    assert "K" * 40 not in " ".join(c.consola.lineas())        # la clave nunca sale en la consola
    c.cerrar()


# ============================================================================
# Gateway que ya corría (sesión 14): «Conectar» lo usa en vez de arrancar otro en los mismos puertos
# ============================================================================
@pytest.fixture
def gateway_en_marcha():
    import threading
    import zmq
    from gateway.backend_sim import BackendSim
    from gateway.servidor import Servidor
    ctx = zmq.Context()
    srv = Servidor(BackendSim(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*", periodo_ms=20, contexto=ctx)
    hilo = threading.Thread(target=srv.bucle, daemon=True)
    hilo.start()
    assert srv.listo.wait(5.0)
    yield srv
    srv.detener()
    hilo.join(5.0)
    ctx.term()


def test_endpoint_ocupado(gateway_en_marcha):
    assert cx.endpoint_ocupado(gateway_en_marcha.pub_endpoint) is True
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        libre = s.getsockname()[1]
    assert cx.endpoint_ocupado("tcp://127.0.0.1:%d" % libre) is False
    assert cx.endpoint_ocupado("tcp://192.0.2.1:5555") is False      # solo direcciones locales
    assert cx.endpoint_ocupado("basura") is False


def test_conectar_reutiliza_gateway_en_marcha(app, planta, tmp_path, gateway_en_marcha):
    """Con «Arrancar aquí» y un gateway ya escuchando en esos puertos, no se lanza otro (fallaría)."""
    srv = gateway_en_marcha
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    c.pub, c.cmd, c.modo = srv.pub_endpoint, srv.cmd_endpoint, "SIM"
    assert c.lanzarGateway is True
    c.conectar()
    assert c.gatewayPropio is False and c.gatewayEstado == "parado"
    assert avanzar(lambda: c.estado == "conectado", 8.0, app), c.mensaje
    assert any("se usa ese" in ln for ln in c.consola.lineas("hmi"))
    c.desconectar()
    assert cx.endpoint_ocupado(srv.pub_endpoint)                    # el gateway ajeno sigue vivo
    c.cerrar()


def test_conectar_ya_conectado_arranca_envio_web(app, planta, tmp_path, gateway_en_marcha, monkeypatch):
    """El HMI se conectó solo a un gateway ajeno: «Conectar» arranca el envío elegido (antes: «desconecta»)."""
    srv = gateway_en_marcha
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    c.pub, c.cmd = srv.pub_endpoint, srv.cmd_endpoint
    planta.conectar(srv.pub_endpoint, srv.cmd_endpoint)
    assert avanzar(lambda: c.estado == "conectado", 8.0, app)
    assert "Arrancar envío" in c.mensaje
    llamadas = []
    monkeypatch.setattr(c, "arrancarWeb", lambda: llamadas.append(c.destinoWeb))
    c.destinoWeb = "local"
    c.conectar()
    assert llamadas == ["local"] and "Usando el gateway en marcha" in c.mensaje
    c.modo = "REAL"
    c.conectar()
    assert llamadas == ["local"] and "no REAL" in c.mensaje          # modo distinto: se avisa, no se arranca
    c.cerrar()


def test_autoconexion_con_destino_guardado_arranca_el_envio(app, planta, tmp_path, gateway_en_marcha, monkeypatch):
    """Destino web guardado + el HMI se conecta solo a un gateway que ya corría → el envío arranca sin botones."""
    srv = gateway_en_marcha
    cx.guardar_config(tmp_path / "c.json", dict(cx.config_defecto(), destinoWeb="servidor",
                                                 pub=srv.pub_endpoint, cmd=srv.cmd_endpoint))
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=tmp_path, detectar_python32=False)
    llamadas = []
    monkeypatch.setattr(c, "arrancarWeb", lambda: llamadas.append(c.destinoWeb))
    planta.conectar(srv.pub_endpoint, srv.cmd_endpoint)
    assert avanzar(lambda: c.estado == "conectado", 8.0, app)
    assert llamadas == ["servidor"] and "enviando al servidor web" in c.mensaje
    c.cerrar()


def test_desconectar_no_deja_un_pulso_a_medias(app, planta, tmp_path, monkeypatch):
    """START y Desconectar en el mismo instante: el HMI espera a que el gateway escriba el 0 del pulso
    antes de terminarlo (en Windows muere por kill). El historial del gateway debe tener el 1 y el 0.
    PLAZO_TERMINAR_MS se acorta a 50 ms para imitar una escritura DF1 que tarda más que ese margen:
    sin la espera, el gateway muere antes de bajar el pulso (comprobado)."""
    import sqlite3
    monkeypatch.setattr(cx, "PLAZO_TERMINAR_MS", 50)
    c = cx.Conexion(planta, args_hmi(), ruta_config=tmp_path / "c.json", raiz=cx.RAIZ, detectar_python32=False)
    c.extra_gateway = ["--datos", str(tmp_path / "gw")]
    c.modo, c.lanzarGateway, c.destinoWeb = "SIM", True, "ninguno"
    c.pub = "tcp://127.0.0.1:%d" % puerto_libre()
    c.cmd = "tcp://127.0.0.1:%d" % puerto_libre()
    try:
        c.conectar()
        assert avanzar(lambda: c.estado == "conectado", 30.0, app), (c.estado, c.mensaje)
        planta.pulso("STARTV")
        c.desconectar()                       # sin esperar nada: el HMI espera por su cuenta
        assert avanzar(lambda: not c._gateway.vivo(), 10.0, app)
    finally:
        c.cerrar()
    con = sqlite3.connect(str(tmp_path / "gw" / "historial.sqlite"))
    filas = [(t, v) for t, v in con.execute("select tag, valor from escrituras where tag = 'STARTV' order by t")]
    con.close()
    assert ("STARTV", "1") in filas and ("STARTV", "0") in filas, filas
    assert filas[-1] == ("STARTV", "0")
