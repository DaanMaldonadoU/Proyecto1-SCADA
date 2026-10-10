# -*- coding: utf-8 -*-
"""Pruebas de `gateway/diagnostico_opc.py --json` con un módulo OpenOPC falso (mds/ARQUITECTURA.md §6.6).

El OpenOPC real solo existe en Windows de 32 bits con RSLinx; aquí se inyecta un sustituto en
sys.modules["OpenOPC"] que imita `client()`, `servers()`, `connect()`, `list()`, `read()` y
`close()`, y se ejecuta `main(argv)` capturando stdout. Sin OpenOPC el módulo debe responder
{"ok": false, "error": …} y salir con código 2.
"""
import io
import json
import sys
import types
from contextlib import redirect_stdout

import pytest

from gateway import diagnostico_opc as diag


class ClienteFalso:
    """Imita lo que el gateway usa de OpenOPC.client()."""

    ARBOL = {
        "PROYECTO1_TEST.Online": ["O0", "I1", "S2", "B3", "T4", "C5"],
        "PROYECTO1_TEST.Online.I1": ["[PROYECTO1_TEST]I:1.0", "[PROYECTO1_TEST]I:1.0/0", "[PROYECTO1_TEST]I:1.0/1"],
        "OTRO.Online": [],
        "OTRO": ["N7"],
    }
    VALORES = {"[PROYECTO1_TEST]I:1.0": (1, "Good"), "[PROYECTO1_TEST]B3:0/0": (False, "Good"),
               "[PROYECTO1_TEST]N7:0": (None, "Bad")}
    instancias = []

    def __init__(self):
        self.servidor = None
        self.cerrado = False
        ClienteFalso.instancias.append(self)

    def servers(self):
        return ["RSLinx Local OPC Server", "RSLinx Remote OPC Server"]

    def connect(self, servidor):
        if servidor != "RSLinx Local OPC Server":
            raise RuntimeError("Servidor desconocido: %s" % servidor)
        self.servidor = servidor

    def list(self, ruta=None, flat=False):
        if ruta is None:
            return ["[PROYECTO1_TEST]", "[OTRO]"]
        if ruta in self.ARBOL:
            return list(self.ARBOL[ruta])
        raise RuntimeError("ruta desconocida: %s" % ruta)

    def read(self, items, **kw):
        res = []
        for it in items:
            v, q = self.VALORES.get(it, (None, "Bad"))
            res.append((it, v, q, "2026-10-02 10:00:00"))
        return res

    def close(self):
        self.cerrado = True


@pytest.fixture
def openopc_falso(monkeypatch):
    mod = types.ModuleType("OpenOPC")
    mod.client = ClienteFalso
    monkeypatch.setitem(sys.modules, "OpenOPC", mod)
    ClienteFalso.instancias = []
    return mod


@pytest.fixture
def sin_openopc(monkeypatch):
    monkeypatch.setitem(sys.modules, "OpenOPC", None)   # import OpenOPC → ImportError


def ejecutar(argv):
    """main(argv) con stdout capturado → (código, objeto JSON, texto)."""
    salida = io.StringIO()
    with redirect_stdout(salida):
        codigo = diag.main(argv)
    texto = salida.getvalue()
    lineas = [ln for ln in texto.splitlines() if ln.strip()]
    assert len(lineas) == 1, "con --json debe salir un solo objeto: %r" % texto
    return codigo, json.loads(lineas[0]), texto


def test_servidores_json(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--servidores"])
    assert codigo == 0
    assert res == {"ok": True, "servidores": ["RSLinx Local OPC Server", "RSLinx Remote OPC Server"]}
    assert ClienteFalso.instancias[-1].cerrado


def test_topics_json(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--topics", "--servidor", "RSLinx Local OPC Server"])
    assert codigo == 0
    assert res == {"ok": True, "topics": ["PROYECTO1_TEST", "OTRO"]}


def test_archivos_json(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--archivos", "--topic", "PROYECTO1_TEST"])
    assert codigo == 0
    assert res == {"ok": True, "ruta": "PROYECTO1_TEST.Online", "archivos": ["O0", "I1", "S2", "B3", "T4", "C5"]}
    # Sin nivel Online se prueba con el topic a secas
    codigo, res, _ = ejecutar(["--json", "--archivos", "--topic", "OTRO"])
    assert codigo == 0 and res["ok"] and res["ruta"] == "OTRO" and res["archivos"] == ["N7"]


def test_items_json(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--items", "PROYECTO1_TEST.Online.I1"])
    assert codigo == 0
    assert res["ok"] and res["items"][0] == "[PROYECTO1_TEST]I:1.0" and len(res["items"]) == 3


def test_leer_json_con_y_sin_topic(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--leer", "I:1.0", "--topic", "PROYECTO1_TEST"])
    assert codigo == 0
    assert res == {"ok": True, "item": "[PROYECTO1_TEST]I:1.0", "valor": 1, "calidad": "Good"}
    codigo, res, _ = ejecutar(["--json", "--leer", "[PROYECTO1_TEST]B3:0/0"])
    assert codigo == 0 and res["valor"] is False and res["calidad"] == "Good"
    codigo, res, _ = ejecutar(["--json", "--leer", "N7:0", "--topic", "PROYECTO1_TEST"])
    assert codigo == 0 and res["ok"] and res["calidad"] == "Bad" and res["valor"] is None


def test_error_del_servidor_en_json(openopc_falso):
    codigo, res, _ = ejecutar(["--json", "--topics", "--servidor", "No existe"])
    assert codigo == 2
    assert res["ok"] is False and "No existe" in res["error"]
    codigo, res, _ = ejecutar(["--json", "--items", "RUTA.INVENTADA"])
    assert codigo == 2 and res["ok"] is False and "RUTA.INVENTADA" in res["error"]


def test_json_sin_subcomando_es_error(openopc_falso):
    codigo, res, _ = ejecutar(["--json"])
    assert codigo == 2 and res["ok"] is False


def test_sin_openopc_json_devuelve_error_y_codigo_2(sin_openopc):
    codigo, res, _ = ejecutar(["--json", "--servidores"])
    assert codigo == 2
    assert res["ok"] is False and "OpenOPC" in res["error"]
    if sys.maxsize > 2 ** 32:
        assert "64 bits" in res["error"]


def test_cliente_com_que_falla_en_64_bits(monkeypatch):
    mod = types.ModuleType("OpenOPC")

    def client():
        raise OSError("Class not registered")
    mod.client = client
    monkeypatch.setitem(sys.modules, "OpenOPC", mod)
    codigo, res, _ = ejecutar(["--json", "--servidores"])
    assert codigo == 2 and res["ok"] is False and "Class not registered" in res["error"]
    if sys.maxsize > 2 ** 32:
        assert "64 bits" in res["error"]


def test_sin_openopc_modo_texto_sale_con_mensaje(sin_openopc):
    with redirect_stdout(io.StringIO()):
        with pytest.raises(SystemExit) as e:
            diag.main(["--servidores"])
    assert "OpenOPC" in str(e.value)


def test_modo_texto_no_cambia(openopc_falso):
    salida = io.StringIO()
    with redirect_stdout(salida):
        codigo = diag.main(["--servidores"])
    texto = salida.getvalue()
    assert codigo == 0
    assert texto.startswith("Python ")
    assert "Servidores OPC DA registrados:" in texto and "  - RSLinx Local OPC Server" in texto


def test_funciones_de_descubrimiento_reciben_el_cliente():
    opc = ClienteFalso()
    assert diag.servidores(opc) == ["RSLinx Local OPC Server", "RSLinx Remote OPC Server"]
    assert diag.topics(opc, "RSLinx Local OPC Server") == ["PROYECTO1_TEST", "OTRO"]
    assert diag.archivos(opc, "RSLinx Local OPC Server", "PROYECTO1_TEST")[0] == "PROYECTO1_TEST.Online"
    assert diag.item_completo("PROYECTO1_TEST", "I:1.0") == "[PROYECTO1_TEST]I:1.0"
    assert diag.item_completo("X", "[Y]I:1.0") == "[Y]I:1.0"
    assert diag.leer_item(opc, "RSLinx Local OPC Server", "PROYECTO1_TEST", "I:1.0") == ("[PROYECTO1_TEST]I:1.0", 1, "Good")
