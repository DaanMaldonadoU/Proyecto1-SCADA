# -*- coding: utf-8 -*-
"""
tests/test_clave_servidor.py — Diagnóstico de la clave del puente en la PC servidor
(digital_twin/servidor_web/diagnostico_clave.py) y prueba de clave del laboratorio (puente.vincular).

Contra un ServidorGemelo real en un hilo (127.0.0.1, puerto efímero), sin Internet: la prueba por Internet
se desactiva. Python 3.12+, aiohttp.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("aiohttp")

from core import remoto  # noqa: E402
from digital_twin.servidor_web import diagnostico_clave as dc  # noqa: E402
from puente import vincular  # noqa: E402
from tests.test_vincular import ServidorEnHilo, _puerto_libre  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def servidor(tmp_path):
    """Servidor del gemelo con su clave en tmp_path/srv/puente.clave (como lo deja servidor.bat)."""
    from digital_twin.servidor_web.app import ServidorGemelo
    datos = tmp_path / "srv"
    clave = remoto.leer_clave(str(datos / "puente.clave"), crear=True)

    def fabrica():
        srv = ServidorGemelo(str(datos), clave, log=lambda *_: None)
        return srv, srv.aplicacion()

    s = ServidorEnHilo(fabrica).arrancar()
    s.datos, s.clave, s.puerto = str(datos), clave, int(s.base.rsplit(":", 1)[1])
    yield s
    s.parar()


def _diagnostico(datos, puerto, monkeypatch, proceso=None):
    monkeypatch.setattr(dc, "proceso_en_puerto", lambda _p: proceso)   # sin netstat en las pruebas
    lineas = []
    r = dc.diagnosticar(datos, puerto=puerto, probar_publica=False, log=lineas.append)
    return r, "\n".join(lineas)


def test_probar_clave(servidor):
    url = "ws://127.0.0.1:%d/ws/planta" % servidor.puerto
    assert vincular.probar_clave(url, servidor.clave)["status"] == 101
    r = vincular.probar_clave(url, "otra-clave-que-no-es-la-del-servidor")
    assert r["ok"] is False and r["status"] == 401 and "RECHAZA" in r["msg"]
    r = vincular.probar_clave("ws://127.0.0.1:%d/ws/planta" % _puerto_libre(), servidor.clave, timeout=3)
    assert r["ok"] is False and r["status"] is None and "no se pudo conectar" in r["msg"]


def test_diagnostico_clave_correcta(servidor, monkeypatch):
    r, texto = _diagnostico(servidor.datos, servidor.puerto, monkeypatch)
    assert r == "ok"
    assert "acepta la clave" in texto and servidor.clave in texto       # se muestra para copiarla al laboratorio


def test_diagnostico_otra_carpeta_rechazada(servidor, tmp_path, monkeypatch):
    """El archivo que se mira no es el que leyó el servidor en marcha: 401 y la receta de reiniciar."""
    otra = tmp_path / "otra"
    remoto.leer_clave(str(otra / "puente.clave"), crear=True)
    r, texto = _diagnostico(str(otra), servidor.puerto, monkeypatch)
    assert r == "rechazada"
    assert "REINICIA" not in texto and "vuelve a arrancarlo" in texto and "fijar" in texto
    leida = remoto.leer_clave(str(otra / "puente.clave"))
    assert leida not in texto                                          # una clave que no vale no se imprime


def test_diagnostico_sin_archivo_y_sin_servidor(tmp_path, monkeypatch):
    r, texto = _diagnostico(str(tmp_path / "vacia"), _puerto_libre(), monkeypatch)
    assert r == "sin_archivo" and "NO EXISTE" in texto
    remoto.leer_clave(str(tmp_path / "con" / "puente.clave"), crear=True)
    r, texto = _diagnostico(str(tmp_path / "con"), _puerto_libre(), monkeypatch, proceso={})
    assert r == "sin_servidor" and "NINGUNO" in texto


def test_diagnostico_avisa_otra_carpeta_del_proceso(servidor, monkeypatch):
    proceso = {"pid": "123", "orden": r'"E:\otro\HMI\.venv-web\Scripts\python.exe" -m digital_twin.servidor_web',
               "carpeta": r"E:\otro\HMI", "datos": None}
    r, texto = _diagnostico(servidor.datos, servidor.puerto, monkeypatch, proceso=proceso)
    assert "OTRA carpeta" in texto and r"E:\otro\HMI" in texto


def test_proceso_en_puerto_lee_carpeta_y_datos(monkeypatch):
    """La orden del proceso (netstat + Win32_Process) se interpreta: carpeta del repo y --datos."""
    class R:
        def __init__(self, stdout):
            self.stdout = stdout

    def falso(orden, **_kw):
        if orden[0] == "netstat":
            return R("  TCP    127.0.0.1:3002         0.0.0.0:0              LISTENING       4242\n")
        return R('"C:\\Gemelo\\HMI\\.venv-web\\Scripts\\python.exe" -m digital_twin.servidor_web --host 127.0.0.1 '
                 '--port 3002 --datos "D:\\datos gemelo"\n')

    monkeypatch.setattr(dc.sys, "platform", "win32")
    monkeypatch.setattr(dc.subprocess, "run", falso)
    p = dc.proceso_en_puerto(3002)
    assert p["pid"] == "4242" and p["carpeta"] == r"C:\Gemelo\HMI" and p["datos"] == r"D:\datos gemelo"
    assert dc.proceso_en_puerto(3999) == {}


def test_fijar_conserva_la_anterior(tmp_path):
    datos = tmp_path / "srv"
    vieja = remoto.leer_clave(str(datos / "puente.clave"), crear=True)
    nueva = "F" * 43
    lineas = []
    dc.fijar(str(datos), nueva, log=lineas.append)
    assert remoto.leer_clave(str(datos / "puente.clave")) == nueva
    copias = [f for f in os.listdir(datos) if f.startswith("puente.clave.anterior-")]
    assert len(copias) == 1 and (datos / copias[0]).read_text(encoding="utf-8").strip() == vieja
    assert any("REINICIA" in ln for ln in lineas)
    dc.fijar(str(datos), nueva, log=lineas.append)                     # misma clave: no crea otra copia
    assert len([f for f in os.listdir(datos) if f.startswith("puente.clave.anterior-")]) == 1
    with pytest.raises(ValueError):
        dc.fijar(str(datos), "corta")


def test_cli_laboratorio_guardar_y_probar(servidor, tmp_path):
    """lab\\clave_puente.bat CLAVE = python -m puente.vincular --guardar CLAVE (guarda y prueba)."""
    ruta = tmp_path / "hmi" / "puente.clave"
    url = "ws://127.0.0.1:%d/ws/planta" % servidor.puerto
    base = [sys.executable, "-m", "puente.vincular", "--url", url, "--clave-archivo", str(ruta)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(base + ["--guardar", servidor.clave], cwd=RAIZ, capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "acepta la clave" in r.stdout and servidor.clave not in r.stdout
    assert remoto.leer_clave(str(ruta)) == servidor.clave
    ruta.write_text("una-clave-que-el-servidor-no-conoce\n", encoding="utf-8")
    r = subprocess.run(base + ["--probar"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                       env=env, timeout=60)
    assert r.returncode == 1 and "RECHAZA" in r.stdout and "clave_puente.bat" in r.stdout
