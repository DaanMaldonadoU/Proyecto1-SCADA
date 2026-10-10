"""
hmi_estacion.py  (v4) — HMI en Python (Tkinter + OPC DA / RSLinx Classic)
Estación electroneumática · GRAFCET / Ladder RSLogix 500 · SLC 5/04 (1747-L541C)
Maldonado Uriostigue Daan Yael

MODOS:
  SIM      → lógica del ladder + física en Python (ladder_sim.py). Sin RSLinx.  Usa TAGS_HTML.
  EMULATE  → RSLogix Emulate 500 vía RSLinx OPC Server. El HMI hace la física y
             escribe los sensores SC/SE en I:1 del emulador.                    Usa TAGS_PLC.
  REAL     → SLC 5/04 físico vía RSLinx (DF1 / DH+). Nunca escribe I:1.         Usa TAGS_PLC.

Al pulsar Conectar en EMULATE/REAL se abre el selector: servidores OPC registrados,
topics del servidor, archivos de datos (O0, I1, B3…) y sus ItemIDs reales.

Requisitos (Windows 32 bits, misma PC que RSLinx):  pip install pywin32 OpenOPC-Python3x
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from ladder_sim import Ladder, Fisica

# ============================================================================
#  CONFIGURACIÓN
# ============================================================================
OPC_SERVER = "RSLinx Local OPC Server"   # o "RSLinx OPC Server"; se puede elegir en el selector
OPC_GATEWAY_HOST = ""                    # "" = COM local. IP si usas OpenOPC Gateway Service
TOPIC_DEFAULT = "PROYECTO1_TEST"         # topic DDE/OPC configurado en RSLinx
POLL_MS = 150                            # periodo de lectura / paso de la física
MONITOR_WORDS = ["I:1.0", "O:3.0", "O:3.1"]   # palabras que se muestran bit a bit en el monitor de E/S
TAGS_JSON = "tags_plc.json"              # si existe, sobreescribe TAGS_PLC (lo genera el botón "Mapeo…")
HIST_S = 45                              # segundos visibles en el cronograma
STOP_NC_HTML = True                      # en el informe Stop es NC (1 en reposo)
STOP_NC_PLC = False                      # en PROYECTO1_TEST el escalón 0000 usa STOP como NA físico

# --- Tabla del informe (Hoja 2 del HTML). La usa el modo SIM. ---------------
TAGS_HTML = {
    "Stop": "I:1/0", "Start": "I:1/1",
    "SC1": "I:1/2", "SE1": "I:1/3", "SC2": "I:1/4", "SE2": "I:1/5", "SC3": "I:1/6", "SE3": "I:1/7",
    "EV_E1": "O:3/0", "EV_C1": "O:3/1", "EV_E2": "O:3/2", "EV_C2": "O:3/3", "EV_E3": "O:3/4", "EV_C3": "O:3/5",
    "STARTV": "B3:0/13", "STOPV": "B3:0/14", "RESETV": "B3:0/15",
    "ACTIVO": "B3:1/0", "END": "B3:2/0",
    **{"X%d" % i: "B3:3/%d" % i for i in range(9)},
    "T_ESPERA": "N7:0", "N_CICLOS": "N7:1", "T_NEUM": "N7:2",
    "C_ACC": "C5:0.ACC", "C_PRE": "C5:0.PRE", "T7_ACC": "T4:5.ACC",
}

# --- Tabla del programa real PROYECTO1_TEST.RSS (modos EMULATE / REAL) ------
# Lo que ya se ve en el escalón 0000 está puesto; lo demás en None → la GUI NO lo lee.
# Rellena con el navegador del selector (archivo → ItemID) o con Cross Reference de RSLogix.
# Sintaxis RSLinx: bits  I:1.0/0  O:2.0/0  B3:0/13   enteros N7:0   timer T4:5.ACC   contador C5:0.ACC
TAGS_PLC = {
    # --- confirmado en los escalones 0000 / 0001 de PROYECTO1_TEST ---
    "Start":  "I:1.0/0",    # NA físico
    "Stop":   "I:1.0/1",    # NA físico  → STOP_NC_PLC = False
    "STARTV": "B3:0/0",
    "STOPV":  "B3:0/1",
    "ACTIVO": "B3:0/2",     # ACTIVE
    "END":    "B3:0/3",     # FIN 3 CICLOS
    "RESETV": "B3:0/4",
    **{"X%d" % i: "B3:3/%d" % i for i in range(9)},   # MOV 1 → B3:3 (etapas en la palabra B3:3)
    "C_ACC": "C5:0.ACC", "C_PRE": "C5:0.PRE",           # RES C5:0
    # --- sensores en 1746-IB16 slot 1 (SE1 = I:1/3 confirmado); EV en el 1747-SDN slot 3 (EV_E1 = O:3/0 confirmado) ---
    "SC1": "I:1.0/2", "SE1": "I:1.0/3", "SC2": "I:1.0/4", "SE2": "I:1.0/5", "SC3": "I:1.0/6", "SE3": "I:1.0/7",
    "EV_E1": "O:3.0/0", "EV_C1": "O:3.0/1", "EV_E2": "O:3.0/2", "EV_C2": "O:3.0/3", "EV_E3": "O:3.0/4", "EV_C3": "O:3.0/5",
    "T_ESPERA": "N7:0", "N_CICLOS": "N7:1", "T_NEUM": "N7:2",   # escalón 0002 "carga de parámetros"
    "T7_ACC": "T4:5.ACC",
}

import json, os, collections
if os.path.exists(TAGS_JSON):
    try:
        with open(TAGS_JSON, encoding="utf-8") as _f:
            TAGS_PLC.update({k: (v or None) for k, v in json.load(_f).items() if k in TAGS_PLC})
    except Exception as _e:
        print("No se pudo leer", TAGS_JSON, _e)

INT_TAGS = {"T_ESPERA", "N_CICLOS", "T_NEUM", "C_ACC", "C_PRE", "T7_ACC"}
SENSOR_TAGS = ["SC1", "SE1", "SC2", "SE2", "SC3", "SE3"]
EV_TAGS = ["EV_E1", "EV_C1", "EV_E2", "EV_C2", "EV_E3", "EV_C3"]

MODES = {
    #                 tags            Stop NC              escritura I:1   física en el HMI
    "SIM":     dict(tags=TAGS_HTML, stop_nc=STOP_NC_HTML, entradas=True,  fisica=False),
    "EMULATE": dict(tags=TAGS_PLC,  stop_nc=STOP_NC_PLC,  entradas=True,  fisica=True),
    "REAL":    dict(tags=TAGS_PLC,  stop_nc=STOP_NC_PLC,  entradas=False, fisica=False),
}

# Paleta tomada del HTML
C_BG, C_TXT = "#f1f3f6", "#161616"
C_IO, C_INT, C_HMI, C_SYS, C_REC = "#0b3fa8", "#1E7B4B", "#7c3aed", "#b45309", "#b0161b"
C_ON, C_OFF, C_LINE = "#dff3df", "#ffffff", "#9aa3ad"
FONT = ("Consolas", 10)


# ============================================================================
#  OpenOPC helpers
# ============================================================================
def new_opc_client():
    import OpenOPC                                       # sólo Windows (pywin32 + gbda_aut.dll 32 bits)
    return OpenOPC.open_client(OPC_GATEWAY_HOST) if OPC_GATEWAY_HOST else OpenOPC.client()


def _with_client(fn):
    opc = new_opc_client()
    try:
        return fn(opc)
    finally:
        try:
            opc.close()
        except Exception:
            pass


def discover_servers():
    return _with_client(lambda opc: [str(s) for s in opc.servers()])


def discover_topics(server):
    def f(opc):
        opc.connect(server)
        return [str(t).strip("[]") for t in opc.list()]
    return _with_client(f)


def discover_files(server, topic):
    """Archivos de datos del topic: RSLinx los expone bajo <topic>.Online (O0, I1, B3, …)."""
    def f(opc):
        opc.connect(server)
        for path in ("%s.Online" % topic, topic):
            try:
                r = [str(x) for x in opc.list(path)]
                if r:
                    return path, r
            except Exception:
                pass
        return topic, []
    return _with_client(f)


def discover_items(server, path):
    def f(opc):
        opc.connect(server)
        return [str(x) for x in opc.list(path, flat=True)]
    return _with_client(f)


def test_item(server, item):
    def f(opc):
        opc.connect(server)
        name, val, quality, ts = opc.read([item], sync=True)[0]   # lista → tuplas de 4
        return val, quality
    return _with_client(f)


def word_of(addr):
    """'I:1/2' → ('I:1.0', 2)   'I:1.0/2' → ('I:1.0', 2)   'B3:0/13' → ('B3:0', 13)"""
    word, bit = addr.split("/")
    if word[0] in "IO" and "." not in word:
        word += ".0"
    return word, int(bit)


# ============================================================================
#  Backends: misma interfaz  connect / read_all / write / close
#  read_all() → {tag: valor} (+ "_pos": [p1,p2,p3] para la animación)
# ============================================================================
class SimBackend:
    def __init__(self, log):
        self.log, self.lad, self.lock, self.run = log, Ladder(), threading.Lock(), False
        self.tags = TAGS_HTML

    def connect(self):
        self.run = True
        threading.Thread(target=self._scan, daemon=True).start()
        self.log("SIM: ladder interno en marcha (ladder_sim.py, tabla del informe)")

    def _scan(self):
        t = time.monotonic()
        while self.run:
            time.sleep(0.02)
            now = time.monotonic()
            with self.lock:
                self.lad.scan(now - t)
            t = now

    def read_all(self):
        with self.lock:
            d = {tag: (self.lad.n[a] if tag in INT_TAGS else self.lad.b[a]) for tag, a in self.tags.items()}
            d["_pos"] = list(self.lad.fis.pos)
        return d

    def write(self, tag, value):
        a = self.tags[tag]
        with self.lock:
            if tag in INT_TAGS:
                self.lad.n[a] = int(value)
            else:
                self.lad.b[a] = bool(value)

    def close(self):
        self.run = False


class DaBackend:
    """OPC DA clásico contra RSLinx vía OpenOPC. Lecturas SÍNCRONAS (sin callbacks COM)."""

    def __init__(self, server, topic, tags, stop_nc, fisica, log):
        self.server, self.topic, self.log = server, topic, log
        self.stop_nc, self.fisica_on = stop_nc, fisica
        self.faltan = [t for t, a in tags.items() if not a]
        self.tags = {t: a for t, a in tags.items() if a}          # sólo los definidos
        self.items = {t: "[%s]%s" % (topic, a) for t, a in self.tags.items()}
        self.opc = None
        self.lock = threading.Lock()
        self.fis = Fisica()
        self.last_sens = [None] * 6
        self.last_bad = None
        self.input_mode = None        # None → probar bit; luego 'bit' | 'word' | 'fail'
        self.t_prev = None
        self.fisica_fuente = "EV"     # "EV" = según salidas del PLC · "ETAPA" = guiada por el GRAFCET
        self.step_prev, self.t_step = None, time.monotonic()
        self.mon_items = ["[%s]%s" % (topic, w) for w in MONITOR_WORDS]

    def connect(self):
        self.opc = new_opc_client()
        self.opc.connect(self.server)
        self.log("OPC DA conectado a '%s', topic [%s], %d items" % (self.server, self.topic, len(self.items)))
        if self.faltan:
            self.log("Tags sin dirección (no se leen): %s" % ", ".join(self.faltan))
        if self.fisica_on:
            if all(t in self.tags for t in SENSOR_TAGS) and (
                    self.fisica_fuente == "ETAPA" or all(t in self.tags for t in EV_TAGS)):
                sens = self.fis.step(0.0, [(0, 0)] * 3)
                self.last_sens = [v for pair in sens for v in pair]
                ini = list(zip(SENSOR_TAGS, self.last_sens))
                if self.stop_nc and "Stop" in self.tags:
                    ini.insert(0, ("Stop", True))
                self._write_inputs(ini)
                self.log("EMULATE: física del HMI activa, fuente %s (sensores → I:1 del emulador)" % self.fisica_fuente)
            else:
                self.fisica_on = False
                self.log("Física desactivada: faltan direcciones de SC/SE (o de EV_* en fuente EV) en TAGS_PLC")

    def read_all(self):
        tags = list(self.items)
        with self.lock:
            raw = self.opc.read([self.items[t] for t in tags] + self.mon_items, group="hmi", sync=True)
        d, bad = {}, []
        d["_mon"] = {w: (int(v) & 0xFFFF if q == "Good" and v is not None else None)
                     for w, (n, v, q, ts) in zip(MONITOR_WORDS, raw[len(tags):])}
        for tag, (name, val, quality, ts) in zip(tags, raw[:len(tags)]):
            if quality != "Good" or val is None:
                bad.append("%s (%s)" % (name, quality))
                d[tag] = 0 if tag in INT_TAGS else False
            else:
                d[tag] = int(val) if tag in INT_TAGS else bool(val)
        if tags and len(bad) == len(tags):
            raise RuntimeError("ningún item legible; ej. %s" % bad[0])
        if bad != self.last_bad:
            self.last_bad = bad
            self.log("Items sin calidad Good (%d): %s" % (len(bad), ", ".join(bad[:6]) + (" …" if len(bad) > 6 else ""))
                     if bad else "Todos los items con calidad Good")
        if self.fisica_on:
            now = time.monotonic()
            dt = 0.0 if self.t_prev is None else now - self.t_prev
            self.t_prev = now
            ev_bad = any(any(self.items[t] in b for t in EV_TAGS if t in self.items) for b in bad)
            if self.fisica_fuente == "EV" and ev_bad and not getattr(self, "_aviso_ev", False):
                self._aviso_ev = True
                self.log("Las EV no se leen con calidad Good → física guiada por etapa mientras corriges el mapeo (botón Mapeo…)")
            if self.fisica_fuente == "ETAPA" or ev_bad:
                ev = self._ev_por_etapa(d)
                d["_ev_cmd"] = ev
            else:
                ev = [(d["EV_E1"], d["EV_C1"]), (d["EV_E2"], d["EV_C2"]), (d["EV_E3"], d["EV_C3"])]
            sens = self.fis.step(dt, ev)
            flat = [v for pair in sens for v in pair]
            cambios = [(t, bool(v)) for t, v, prev in zip(SENSOR_TAGS, flat, self.last_sens) if v != prev]
            if cambios:
                self.last_sens = flat
                self._write_inputs(cambios)
            d["_pos"] = list(self.fis.pos)
        return d

    def _ev_por_etapa(self, d):
        """Física guiada por el GRAFCET del informe (para cuando las salidas EV no están mapeadas).
        Devuelve [(E1,C1),(E2,C2),(E3,C3)] según la etapa activa y el tiempo en ella."""
        step = next((i for i in range(9) if d.get("X%d" % i)), None)
        now = time.monotonic()
        if step != self.step_prev:
            self.step_prev, self.t_step = step, now
        el = now - self.t_step
        T = (d.get("T_ESPERA") or 100) / 100.0          # 1 s por defecto
        T7 = (d.get("T_NEUM") or 500) / 100.0           # 5 s por defecto
        ext = lambda i: self.fis.pos[i] > 0.02
        cmd = [(0, 0), (0, 0), (0, 0)]
        if step in (0, 8):
            cmd = [(0, 1) if ext(i) else (0, 0) for i in range(3)]      # EV_C# := SE#
        elif step == 1:
            cmd[0] = (1, 0)
        elif step == 2:
            cmd[0] = (1, 0) if el < T else (0, 1)
        elif step == 3:
            cmd[0] = (0, 1) if el < T else (0, 0)
            cmd[1] = (0, 0) if el < T else (1, 0)
        elif step == 4:
            cmd[1] = (1, 0) if el < T else (0, 1)
        elif step == 5:
            cmd[1] = (0, 1) if el < T else (0, 0)
            cmd[2] = (0, 0) if el < T else (1, 0)
        elif step == 6:
            cmd[2] = (1, 0) if el < T else (0, 1)
        elif step == 7:
            cmd[2] = (0, 1) if el < T7 else (0, 0)
            if el >= T7:
                cmd = [(0, 1) if ext(i) else (0, 0) for i in range(3)]
        return cmd

    def _write_inputs(self, cambios):
        """Bits de I:1. 1º bit a bit; si RSLinx lo rechaza, 2º palabra completa (lee-modifica-escribe)."""
        cambios = [(t, v) for t, v in cambios if t in self.items]
        if not cambios:
            return
        if self.input_mode != "word":
            with self.lock:
                res = self.opc.write([(self.items[t], v) for t, v in cambios])
            if not res or all(r[1] == "Success" for r in res):
                self.input_mode = "bit"
                return
            if self.input_mode is None:
                self.log("RSLinx rechazó escribir bits de I:1 (%s); probando por palabra…" % res[0][1])
        try:
            por_palabra = {}
            for t, v in cambios:
                w, b = word_of(self.tags[t])
                por_palabra.setdefault(w, []).append((b, v))
            with self.lock:
                for w, bits in por_palabra.items():
                    item = "[%s]%s" % (self.topic, w)
                    name, val, quality, ts = self.opc.read([item], sync=True)[0]
                    if quality != "Good":
                        raise RuntimeError("lectura %s calidad %s" % (item, quality))
                    word = int(val) & 0xFFFF
                    for b, v in bits:
                        word = (word | (1 << b)) if v else (word & ~(1 << b))
                    res = self.opc.write([(item, word)])
                    if res and res[0][1] != "Success":
                        raise RuntimeError("%s → %s" % (item, res[0][1]))
            if self.input_mode != "word":
                self.input_mode = "word"
                self.log("OK: entradas escritas por palabra I:1.0")
        except Exception as e:
            if self.input_mode != "fail":
                self.input_mode = "fail"
                self.log("El emulador no acepta escrituras en I:1 (%s). Alternativas: Forces en RSLogix, "
                         "o usar bits B3 como sensores mientras se emula." % e)

    def write(self, tag, value):
        if tag not in self.items:
            raise RuntimeError("tag %s sin dirección en la tabla" % tag)
        if self.tags[tag].startswith("I:"):
            self._write_inputs([(tag, bool(value))])
            return
        v = int(value) if tag in INT_TAGS else bool(value)
        with self.lock:
            res = self.opc.write([(self.items[tag], v)])
        if res and res[0][1] != "Success":
            raise RuntimeError("%s → %s" % (self.items[tag], res[0][1]))

    def close(self):
        try:
            if self.opc:
                self.opc.remove("hmi")
                self.opc.close()
        except Exception:
            pass


# ============================================================================
#  Selector: servidor → topic → archivo → items
# ============================================================================
class OpcPicker(tk.Toplevel):
    def __init__(self, master, server, topic, on_ok):
        super().__init__(master)
        self.title("Conexión OPC DA — seleccionar servidor, topic e items")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self.on_ok = on_ok
        self.transient(master)
        self.grab_set()
        self.q = queue.Queue()
        self.online_path = None

        heads = ["Servidores OPC DA", "Topics", "Archivos de datos", "Items (doble clic → prueba)"]
        widths = [30, 18, 14, 30]
        self.lbs = []
        for c, (h, w) in enumerate(zip(heads, widths)):
            ttk.Label(self, text=h, foreground=C_INT).grid(row=0, column=c, padx=6, pady=(8, 2), sticky="w")
            lb = tk.Listbox(self, width=w, height=10, font=FONT, exportselection=False)
            lb.grid(row=1, column=c, padx=6, sticky="nsew")
            self.lbs.append(lb)
        self.lb_srv, self.lb_top, self.lb_file, self.lb_item = self.lbs
        self.lb_srv.bind("<<ListboxSelect>>", self._on_srv)
        self.lb_top.bind("<<ListboxSelect>>", self._on_top)
        self.lb_file.bind("<<ListboxSelect>>", self._on_file)
        self.lb_item.bind("<Double-Button-1>", self._on_item)

        f = ttk.Frame(self, padding=(6, 6))
        f.grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(f, text="Servidor").grid(row=0, column=0, sticky="w")
        self.v_srv = tk.StringVar(master=self, value=server)
        ttk.Entry(f, textvariable=self.v_srv, width=30, font=FONT).grid(row=0, column=1, padx=4, sticky="w")
        ttk.Label(f, text="Topic").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.v_top = tk.StringVar(master=self, value=topic)
        ttk.Entry(f, textvariable=self.v_top, width=18, font=FONT).grid(row=0, column=3, padx=4, sticky="w")
        ttk.Label(f, text="Item de prueba").grid(row=1, column=0, sticky="w")
        self.v_item = tk.StringVar(master=self, value="B3:0/0")
        ttk.Entry(f, textvariable=self.v_item, width=30, font=FONT).grid(row=1, column=1, padx=4, sticky="w")
        ttk.Button(f, text="Probar lectura", command=self._probar).grid(row=1, column=2, padx=4, sticky="w")

        b = ttk.Frame(self, padding=(6, 0, 6, 6))
        b.grid(row=3, column=0, columnspan=4, sticky="ew")
        ttk.Button(b, text="Actualizar", command=self._buscar).pack(side="left")
        ttk.Button(b, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Conectar con esta selección", command=self._ok).pack(side="right", padx=6)
        self.status = ttk.Label(self, text="", foreground=C_LINE)
        self.status.grid(row=4, column=0, columnspan=4, padx=6, pady=(0, 8), sticky="w")

        self.after(100, self._poll)
        self._buscar()

    def _run(self, fn, tag, *args):
        def job():
            try:
                self.q.put((tag, fn(*args)))
            except Exception as e:
                self.q.put(("error", "%s: %s" % (tag, e)))
        threading.Thread(target=job, daemon=True).start()

    def _st(self, txt, color=C_LINE):
        self.status.configure(text=txt, foreground=color)

    def _buscar(self):
        for lb in self.lbs:
            lb.delete(0, "end")
        self._st("Buscando servidores OPC DA registrados…")
        self._run(discover_servers, "servers")

    def _on_srv(self, *_):
        sel = self.lb_srv.curselection()
        if not sel:
            return
        self.v_srv.set(self.lb_srv.get(sel[0]))
        for lb in self.lbs[1:]:
            lb.delete(0, "end")
        self._st("Leyendo topics de '%s'…" % self.v_srv.get())
        self._run(discover_topics, "topics", self.v_srv.get())

    def _on_top(self, *_):
        sel = self.lb_top.curselection()
        if not sel:
            return
        self.v_top.set(self.lb_top.get(sel[0]))
        for lb in self.lbs[2:]:
            lb.delete(0, "end")
        self._st("Leyendo archivos de [%s]…" % self.v_top.get())
        self._run(discover_files, "files", self.v_srv.get(), self.v_top.get())

    def _on_file(self, *_):
        sel = self.lb_file.curselection()
        if not sel or not self.online_path:
            return
        path = "%s.%s" % (self.online_path, self.lb_file.get(sel[0]))
        self.lb_item.delete(0, "end")
        self._st("Leyendo items de %s…" % path)
        self._run(discover_items, "items", self.v_srv.get(), path)

    def _on_item(self, *_):
        sel = self.lb_item.curselection()
        if sel:
            it = self.lb_item.get(sel[0])
            if it.startswith("["):                       # ItemID completo → quitar [topic]
                it = it.split("]", 1)[1]
            self.v_item.set(it)
            self._probar()

    def _probar(self):
        item = "[%s]%s" % (self.v_top.get(), self.v_item.get())
        self._st("Leyendo %s…" % item)
        self._run(test_item, "test", self.v_srv.get(), item)

    def _poll(self):
        try:
            while True:
                tag, payload = self.q.get_nowait()
                if tag == "servers":
                    for s in payload:
                        self.lb_srv.insert("end", s)
                    self._st("%d servidor(es). Selecciona uno." % len(payload))
                    if self.v_srv.get() in payload:
                        self.lb_srv.selection_set(payload.index(self.v_srv.get()))
                        self._on_srv()
                elif tag == "topics":
                    for t in payload:
                        self.lb_top.insert("end", t)
                    self._st("%d topic(s)." % len(payload) if payload else
                             "Sin topics: RSLinx → DDE/OPC → Topic Configuration.", C_LINE if payload else C_REC)
                    if self.v_top.get() in payload:
                        self.lb_top.selection_set(payload.index(self.v_top.get()))
                        self._on_top()
                elif tag == "files":
                    self.online_path, files = payload
                    for f in files:
                        self.lb_file.insert("end", f)
                    self._st("%d archivo(s) en %s." % (len(files), self.online_path))
                elif tag == "items":
                    for it in payload:
                        self.lb_item.insert("end", it)
                    self._st("%d item(s). Doble clic para probar." % len(payload))
                elif tag == "test":
                    val, quality = payload
                    self._st("Lectura → valor=%s  calidad=%s" % (val, quality), C_INT if quality == "Good" else C_REC)
                else:
                    self._st(payload, C_REC)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _ok(self):
        srv, top = self.v_srv.get().strip(), self.v_top.get().strip()
        if not srv or not top:
            messagebox.showwarning("Conexión OPC", "Indica servidor y topic.", parent=self)
            return
        self.destroy()
        self.on_ok(srv, top)


# ============================================================================
#  GUI
# ============================================================================
class HMI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HMI v6.1 — Estación electroneumática · SLC 5/04 · OPC DA (RSLinx) · selector + navegador")
        self.configure(bg=C_BG)
        self.be = None
        self.q = queue.Queue()
        self.cmd_q = queue.Queue()     # escrituras pendientes (las ejecuta el hilo OPC)
        self.running = False
        self.alive = True
        self.data = {}
        self._build()
        self.after(POLL_MS, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ---------- construcción ----------
    def _build(self):
        s = ttk.Style(self)
        s.configure("TFrame", background=C_BG)
        s.configure("TLabel", background=C_BG, foreground=C_TXT, font=FONT)
        s.configure("TCheckbutton", background=C_BG, font=FONT)
        s.configure("TLabelframe", background=C_BG)
        s.configure("TLabelframe.Label", background=C_BG, foreground=C_INT, font=("Consolas", 10, "bold"))
        s.configure("TButton", font=FONT)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(top, text="Modo").pack(side="left")
        self.mode = tk.StringVar(value="SIM")
        cb = ttk.Combobox(top, textvariable=self.mode, values=list(MODES), width=9, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", self._on_mode)
        ttk.Label(top, text="Servidor").pack(side="left", padx=(10, 0))
        self.server = tk.StringVar(value=OPC_SERVER)
        ttk.Entry(top, textvariable=self.server, width=26, font=FONT).pack(side="left", padx=4)
        ttk.Label(top, text="Topic").pack(side="left", padx=(6, 0))
        self.topic = tk.StringVar(value=TOPIC_DEFAULT)
        ttk.Entry(top, textvariable=self.topic, width=16, font=FONT).pack(side="left", padx=4)
        self.btn_conn = ttk.Button(top, text="Conectar", command=self._toggle)
        self.btn_conn.pack(side="left", padx=6)
        self.led = tk.Canvas(top, width=18, height=18, bg=C_BG, highlightthickness=0)
        self.led.pack(side="left")
        self.led_id = self.led.create_oval(2, 2, 16, 16, fill=C_REC, outline="")
        self.lbl_state = ttk.Label(top, text="Desconectado")
        self.lbl_state.pack(side="left", padx=4)
        ttk.Button(top, text="Mapeo…", command=self._open_mapeo).pack(side="right")

        fg = ttk.LabelFrame(self, text=" GRAFCET (B3:3) ", padding=6)
        fg.grid(row=1, column=0, sticky="ns", padx=8, pady=4)
        self.cv_g = tk.Canvas(fg, width=250, height=470, bg="white", highlightthickness=0)
        self.cv_g.pack()
        self._draw_grafcet()

        fs = ttk.LabelFrame(self, text=" Cilindros 1A · 2A · 3A ", padding=6)
        fs.grid(row=1, column=1, sticky="n", padx=4, pady=4)
        self.cv_s = tk.Canvas(fs, width=380, height=300, bg="white", highlightthickness=0)
        self.cv_s.pack()
        self._draw_cylinders()

        self.fr_in = ttk.LabelFrame(fs, text=" Entradas simuladas I:1 (sólo emulador) ", padding=4)
        self.fr_in.pack(fill="x", pady=(6, 0))
        tk.Button(self.fr_in, text="Start físico", font=FONT, bg=C_IO, fg="white",
                  command=lambda: self._pulse("Start", True)).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        self.btn_stop_fis = tk.Button(self.fr_in, text="Stop físico", font=FONT, bg=C_IO, fg="white",
                                      command=self._stop_fisico)
        self.btn_stop_fis.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        self.fisica_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.fr_in, text="Física automática (sensores desde la animación)",
                        variable=self.fisica_auto, command=self._on_fisica).grid(row=1, column=0, columnspan=2, sticky="w")
        self.fisica_fuente = tk.StringVar(value="EV")
        ff = ttk.Frame(self.fr_in)
        ff.grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(ff, text="Mueve los cilindros según:").pack(side="left")
        ttk.Radiobutton(ff, text="salidas EV del PLC", variable=self.fisica_fuente, value="EV",
                        command=self._on_fisica).pack(side="left", padx=4)
        ttk.Radiobutton(ff, text="etapa X (guiado)", variable=self.fisica_fuente, value="ETAPA",
                        command=self._on_fisica).pack(side="left")
        self.sens_vars, self.sens_cb = {}, []
        for i, tag in enumerate(SENSOR_TAGS):
            v = tk.BooleanVar()
            self.sens_vars[tag] = v
            c = ttk.Checkbutton(self.fr_in, text=tag, variable=v,
                                command=lambda t=tag, v=v: self._write(t, v.get()))
            c.grid(row=2 + i // 2, column=i % 2, sticky="w", padx=4)
            self.sens_cb.append(c)

        fc = ttk.LabelFrame(self, text=" Mandos HMI vía OPC ", padding=6)
        fc.grid(row=1, column=2, sticky="n", padx=8, pady=4)
        self.btn_hmi = {}
        for r, (txt, tag, col) in enumerate([("START", "STARTV", C_INT), ("STOP", "STOPV", C_REC), ("RESET", "RESETV", C_SYS)]):
            b = tk.Button(fc, text=txt, font=("Consolas", 11, "bold"), bg=col, fg="white", width=18,
                          command=lambda t=tag: self._pulse(t, True))
            b.grid(row=r, column=0, columnspan=3, pady=3)
            self.btn_hmi[tag] = b

        ttk.Label(fc, text="Parámetros (0.01 s)", foreground=C_HMI).grid(row=3, column=0, columnspan=3, pady=(8, 2))
        self.par_vars, self.par_lbl = {}, {}
        for r, tag in enumerate(["T_ESPERA", "N_CICLOS", "T_NEUM"], start=4):
            l = ttk.Label(fc, text=tag)
            l.grid(row=r, column=0, sticky="w")
            self.par_lbl[tag] = l
            v = tk.StringVar()
            self.par_vars[tag] = v
            ttk.Entry(fc, textvariable=v, width=7, font=FONT, justify="right").grid(row=r, column=1, padx=3)
            ttk.Button(fc, text="Escribir", width=8, command=lambda t=tag: self._write_param(t)).grid(row=r, column=2)

        ttk.Label(fc, text="Estado", foreground=C_INT).grid(row=7, column=0, columnspan=3, pady=(8, 2))
        self.ind, self.ind_lbl = {}, {}
        for r, tag in enumerate(["ACTIVO", "END", "Start", "Stop"], start=8):
            l = ttk.Label(fc, text=tag)
            l.grid(row=r, column=0, sticky="w")
            self.ind_lbl[tag] = l
            v = tk.Label(fc, text="0", width=5, bg=C_OFF, relief="solid", bd=1, font=FONT)
            v.grid(row=r, column=1, columnspan=2, sticky="w", padx=3)
            self.ind[tag] = v
        self.lbl_cnt = ttk.Label(fc, text="Contador  ACC - / PRE -")
        self.lbl_cnt.grid(row=12, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.lbl_t7 = ttk.Label(fc, text="T ventana ACC - / PRE -")
        self.lbl_t7.grid(row=13, column=0, columnspan=3, sticky="w")

        fm = ttk.LabelFrame(fc, text=" Monitor E/S (bit 15 … 0) ", padding=4)
        fm.grid(row=14, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.mon = {}
        for r, w in enumerate(MONITOR_WORDS):
            ttk.Label(fm, text="%-6s" % w).grid(row=r, column=0, sticky="w")
            cv = tk.Canvas(fm, width=16 * 13 + 2, height=14, bg=C_BG, highlightthickness=0)
            cv.grid(row=r, column=1, padx=2)
            leds = [cv.create_rectangle(2 + i * 13, 1, 12 + i * 13, 13, fill=C_OFF, outline=C_LINE) for i in range(16)]
            self.mon[w] = (cv, leds)

        fh = ttk.LabelFrame(self, text=" Cronograma — posición de 1A · 2A · 3A y etapa activa (últimos %d s) " % HIST_S, padding=4)
        fh.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 4))
        self.cv_h = tk.Canvas(fh, width=1040, height=150, bg="white", highlightthickness=0)
        self.cv_h.pack(fill="x")
        self.hist = collections.deque(maxlen=int(HIST_S * 1000 / POLL_MS) + 20)   # (t, pos1, pos2, pos3, step)

        self.txt = tk.Text(self, height=6, font=("Consolas", 9), bg="white", fg=C_TXT)
        self.txt.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        self.log("HMI listo. Elige modo y pulsa Conectar.")
        self._on_mode()

    def _draw_grafcet(self):
        c = self.cv_g
        self.g_steps = {}
        acts = ["EV_C# := SE#", "EV_E1", "1s → EV_C1", "1s → EV_E2", "1s → EV_C2",
                "1s → EV_E3", "1s → EV_C3", "5s · C:=C+1", "END"]
        for i in range(9):
            y = 20 + i * 50
            r = c.create_rectangle(20, y, 60, y + 30, outline=C_INT, width=2 if i == 0 else 1, fill=C_OFF)
            if i == 0:
                c.create_rectangle(23, y + 3, 57, y + 27, outline=C_INT)
            c.create_text(40, y + 15, text="X%d" % i, font=("Consolas", 10, "bold"))
            c.create_rectangle(70, y + 5, 230, y + 25, outline=C_LINE)
            c.create_text(150, y + 15, text=acts[i], font=("Consolas", 8))
            if i < 8:
                c.create_line(40, y + 30, 40, y + 50, fill=C_TXT)
                c.create_line(30, y + 40, 50, y + 40, fill=C_REC, width=2)
            self.g_steps[i] = r
        c.create_text(120, 462, text="X7 → X1 si C<N   ·   X7 → X8 si C≥N", font=("Consolas", 8), fill=C_REC)

    def _draw_cylinders(self):
        c = self.cv_s
        self.cyl = {}
        for i in range(3):
            y = 20 + i * 90
            c.create_text(14, y + 20, text="%dA" % (i + 1), font=("Consolas", 10, "bold"))
            c.create_rectangle(40, y, 200, y + 40, outline=C_TXT, width=2)
            pist = c.create_rectangle(45, y + 8, 85, y + 32, fill=C_IO, outline="")
            rod = c.create_rectangle(85, y + 16, 200, y + 24, fill=C_LINE, outline="")
            sc = c.create_oval(44, y + 46, 56, y + 58, fill=C_OFF, outline=C_IO)
            se = c.create_oval(184, y + 46, 196, y + 58, fill=C_OFF, outline=C_IO)
            tsc = c.create_text(50, y + 68, text="SC%d" % (i + 1), font=("Consolas", 7))
            tse = c.create_text(190, y + 68, text="SE%d" % (i + 1), font=("Consolas", 7))
            eve = c.create_rectangle(240, y, 300, y + 18, fill=C_OFF, outline=C_IO)
            evc = c.create_rectangle(240, y + 22, 300, y + 40, fill=C_OFF, outline=C_IO)
            c.create_text(270, y + 9, text="EV_E%d" % (i + 1), font=("Consolas", 8))
            c.create_text(270, y + 31, text="EV_C%d" % (i + 1), font=("Consolas", 8))
            teve = c.create_text(340, y + 9, text="", font=("Consolas", 7), fill=C_IO)
            tevc = c.create_text(340, y + 31, text="", font=("Consolas", 7), fill=C_IO)
            self.cyl[i] = dict(pist=pist, rod=rod, sc=sc, se=se, eve=eve, evc=evc, y=y,
                               tsc=tsc, tse=tse, teve=teve, tevc=tevc)

    def _apply_addresses(self):
        """Muestra en pantalla las direcciones de la tabla activa ('?' si falta)."""
        tags = MODES[self.mode.get()]["tags"]
        a = lambda t: tags.get(t) or "?"
        for i, k in self.cyl.items():
            n = i + 1
            self.cv_s.itemconfigure(k["tsc"], text="SC%d %s" % (n, a("SC%d" % n)))
            self.cv_s.itemconfigure(k["tse"], text="SE%d %s" % (n, a("SE%d" % n)))
            self.cv_s.itemconfigure(k["teve"], text=a("EV_E%d" % n))
            self.cv_s.itemconfigure(k["tevc"], text=a("EV_C%d" % n))
        for tag, b in self.btn_hmi.items():
            b.configure(text="%-6s %s" % (tag[:-1], a(tag)))
        for tag, l in self.par_lbl.items():
            l.configure(text="%-9s %s" % (tag, a(tag)))
        for tag, l in self.ind_lbl.items():
            l.configure(text="%-7s %s" % (tag, a(tag)))
        for c, tag in zip(self.sens_cb, SENSOR_TAGS):
            c.configure(text="%s %s" % (tag, a(tag)))

    # ---------- acciones ----------
    def _on_mode(self, *_):
        m = self.mode.get()
        state = "normal" if MODES[m]["entradas"] else "disabled"
        def set_state(widget):
            for w in widget.winfo_children():
                if isinstance(w, (ttk.Frame, tk.Frame)):
                    set_state(w)
                else:
                    try:
                        w.configure(state=state)
                    except tk.TclError:
                        pass
        set_state(self.fr_in)
        self._on_fisica()
        self._apply_addresses()
        self.log("Modo %s%s" % (m, "" if m == "SIM" else "  → %s [%s]" % (self.server.get(), self.topic.get())))

    def _on_fisica(self):
        manual = MODES[self.mode.get()]["entradas"] and not self.fisica_auto.get() and self.mode.get() != "SIM"
        for c in self.sens_cb:
            c.configure(state="normal" if manual else "disabled")
        if isinstance(self.be, DaBackend):
            self.be.fisica_on = MODES[self.mode.get()]["fisica"] and self.fisica_auto.get()
            self.be.fisica_fuente = self.fisica_fuente.get()
            self.be.t_prev = None

    def _toggle(self):
        if self.running:
            self.running = False
            return
        log = lambda msg: self.q.put(("log", msg))
        if self.mode.get() == "SIM":
            self._start_backend(SimBackend(log))
        else:
            OpcPicker(self, self.server.get(), self.topic.get(), self._on_picked)

    def _on_picked(self, server, topic):
        self.server.set(server)
        self.topic.set(topic)
        m = MODES[self.mode.get()]
        be = DaBackend(server, topic, m["tags"], m["stop_nc"], m["fisica"] and self.fisica_auto.get(),
                       lambda msg: self.q.put(("log", msg)))
        be.fisica_fuente = self.fisica_fuente.get()
        self._start_backend(be)

    def _start_backend(self, backend):
        self.be = backend
        while not self.cmd_q.empty():
            self.cmd_q.get_nowait()
        self.btn_conn.configure(state="disabled")
        self.lbl_state.configure(text="Conectando…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            self.be.connect()
            self.running = True
            self.q.put(("state", "Conectado"))
            fallos = 0
            while self.running:
                # 1) escrituras pendientes (mismo hilo que creó el objeto COM)
                try:
                    while True:
                        tag, value, addr = self.cmd_q.get_nowait()
                        try:
                            self.be.write(tag, value)
                            self.q.put(("log", "→ %s (%s) = %s" % (tag, addr, value)))
                        except Exception as e:
                            self.q.put(("log", "Error escribiendo %s: %s" % (tag, e)))
                except queue.Empty:
                    pass
                # 2) lectura + física
                try:
                    self.q.put(("data", self.be.read_all()))
                    fallos = 0
                except Exception as e:
                    fallos += 1
                    self.q.put(("error", "Lectura (%d/5): %s" % (fallos, e)))
                    if fallos >= 5:
                        self.running = False
                time.sleep(POLL_MS / 1000)
        except Exception as e:
            self.q.put(("error", "Conexión: %s" % e))
        finally:
            self.be.close()
            self.q.put(("state", "Desconectado"))

    def _write(self, tag, value):
        if not self.running:
            return
        tags = MODES[self.mode.get()]["tags"]
        if not tags.get(tag):
            self.log("'%s' no tiene dirección en la tabla de tags; complétala en TAGS_PLC" % tag)
            return
        if tags[tag].startswith("I:") and not MODES[self.mode.get()]["entradas"]:
            self.log("Bloqueado: en modo REAL no se escriben entradas I:1")
            return
        self.cmd_q.put((tag, value, tags[tag]))     # la ejecuta el hilo OPC en su siguiente vuelta

    def _pulse(self, tag, active):
        """Pulso de 300 ms."""
        self._write(tag, active)
        self.after(300, lambda: self._write(tag, not active))

    def _stop_fisico(self):
        """Stop NC: pulso a 0. Stop NA: pulso a 1."""
        self._pulse("Stop", not MODES[self.mode.get()]["stop_nc"])

    def _write_param(self, tag):
        try:
            v = int(self.par_vars[tag].get())
        except ValueError:
            messagebox.showwarning("Parámetro", "Valor entero.")
            return
        self._write(tag, v)

    # ---------- refresco ----------
    def _tick(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "data":
                    self.data = payload
                    self._refresh()
                elif kind == "state":
                    on = payload == "Conectado"
                    self.lbl_state.configure(text=payload)
                    self.led.itemconfigure(self.led_id, fill=C_INT if on else C_REC)
                    self.btn_conn.configure(text="Desconectar" if on else "Conectar", state="normal")
                    self.log(payload)
                else:
                    self.log(payload)
        except queue.Empty:
            pass
        if self.alive:
            self.after(POLL_MS, self._tick)

    def _refresh(self):
        d = self.data
        g = lambda t: bool(d.get(t, False))
        pos = d.get("_pos")
        for i in range(9):
            on = g("X%d" % i)
            self.cv_g.itemconfigure(self.g_steps[i], fill=C_ON if on else C_OFF, outline=C_INT if on else C_LINE)
        for i in range(3):
            k = self.cyl[i]
            sc, se = g("SC%d" % (i + 1)), g("SE%d" % (i + 1))
            x0 = 45 + 100 * pos[i] if pos is not None else (145 if se else (45 if sc else 95))
            y = k["y"]
            self.cv_s.coords(k["pist"], x0, y + 8, x0 + 40, y + 32)
            self.cv_s.coords(k["rod"], x0 + 40, y + 16, x0 + 160, y + 24)
            self.cv_s.itemconfigure(k["sc"], fill=C_IO if sc else C_OFF)
            self.cv_s.itemconfigure(k["se"], fill=C_IO if se else C_OFF)
            cmd = d.get("_ev_cmd")
            e_on, c_on = g("EV_E%d" % (i + 1)), g("EV_C%d" % (i + 1))
            fe = C_ON if e_on else ("#fde9c8" if cmd and cmd[i][0] else C_OFF)   # ámbar = comandada por la GUI
            fcl = C_ON if c_on else ("#fde9c8" if cmd and cmd[i][1] else C_OFF)
            self.cv_s.itemconfigure(k["eve"], fill=fe)
            self.cv_s.itemconfigure(k["evc"], fill=fcl)
            self.sens_vars["SC%d" % (i + 1)].set(sc)
            self.sens_vars["SE%d" % (i + 1)].set(se)
        for tag, l in self.ind.items():
            v = g(tag)
            l.configure(text="1" if v else "0", bg=C_ON if v else C_OFF)
        self.lbl_cnt.configure(text="Contador  ACC %s / PRE %s" % (d.get("C_ACC", "-"), d.get("C_PRE", "-")))
        self.lbl_t7.configure(text="T ventana ACC %s / PRE %s" % (d.get("T7_ACC", "-"), d.get("T_NEUM", "-")))
        for tag in ("T_ESPERA", "N_CICLOS", "T_NEUM"):
            if not self.par_vars[tag].get() and tag in d:
                self.par_vars[tag].set(str(d[tag]))
        # monitor de palabras
        for w, (cv, leds) in self.mon.items():
            val = (d.get("_mon") or {}).get(w)
            for i, led in enumerate(leds):
                bit = 15 - i
                cv.itemconfigure(led, fill=(C_LINE if val is None else (C_IO if (val >> bit) & 1 else C_OFF)))
        # cronograma
        step = next((i for i in range(9) if g("X%d" % i)), None)
        if pos is not None:
            self.hist.append((time.monotonic(), pos[0], pos[1], pos[2], step))
        else:
            est = lambda n: 1.0 if g("SE%d" % n) else (0.0 if g("SC%d" % n) else 0.5)
            self.hist.append((time.monotonic(), est(1), est(2), est(3), step))
        self._draw_hist()

    def _draw_hist(self):
        c = self.cv_h
        c.delete("all")
        W, H = int(c.winfo_width() or 1040), 150
        x0, x1, top, lane_h = 40, W - 10, 22, 36
        now = time.monotonic()
        xs = lambda t: x1 - (now - t) * (x1 - x0) / HIST_S
        cols = [C_IO, C_INT, C_HMI]
        for i in range(3):
            yb = top + (i + 1) * lane_h
            c.create_line(x0, yb, x1, yb, fill=C_LINE)
            c.create_line(x0, yb - lane_h + 6, x1, yb - lane_h + 6, fill="#e6e8ec", dash=(2, 4))
            c.create_text(20, yb - lane_h / 2 + 3, text="%dA" % (i + 1), font=("Consolas", 9, "bold"), fill=cols[i])
        for sec in range(0, HIST_S + 1, 5):
            x = x1 - sec * (x1 - x0) / HIST_S
            c.create_line(x, top, x, top + 3 * lane_h, fill="#eef0f3")
            c.create_text(x, top + 3 * lane_h + 9, text="-%ds" % sec if sec else "ahora", font=("Consolas", 7), fill=C_LINE)
        pts = [h for h in self.hist if now - h[0] <= HIST_S]
        if len(pts) < 2:
            return
        for i in range(3):
            yb = top + (i + 1) * lane_h
            line = []
            for h in pts:
                line += [xs(h[0]), yb - h[1 + i] * (lane_h - 8)]
            c.create_line(*line, fill=cols[i], width=2)
        # etapas: barra superior con cambios
        prev_step, x_start = pts[0][4], xs(pts[0][0])
        for h in pts[1:] + [(now, 0, 0, 0, None)]:
            if h[4] != prev_step:
                xe = xs(h[0])
                if prev_step is not None:
                    c.create_rectangle(x_start, 4, xe, 18, fill=C_ON, outline=C_INT)
                    if xe - x_start > 18:
                        c.create_text((x_start + xe) / 2, 11, text="X%d" % prev_step, font=("Consolas", 8))
                    c.create_line(xe, 4, xe, top + 3 * lane_h, fill=C_REC, dash=(1, 3))
                prev_step, x_start = h[4], xe

    def _open_mapeo(self):
        """Editor de TAGS_PLC: una fila por señal, valor en vivo, guarda en tags_plc.json."""
        win = tk.Toplevel(self)
        win.title("Mapeo de señales del PLC (TAGS_PLC) — se guarda en %s" % TAGS_JSON)
        win.configure(bg=C_BG)
        win.transient(self)
        ttk.Label(win, text="Señal", foreground=C_INT).grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Label(win, text="Dirección RSLinx (vacío = no leer)", foreground=C_INT).grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(win, text="Valor actual", foreground=C_INT).grid(row=0, column=2, padx=6, sticky="w")
        ttk.Label(win, text="Señal", foreground=C_INT).grid(row=0, column=3, padx=6, sticky="w")
        ttk.Label(win, text="Dirección RSLinx", foreground=C_INT).grid(row=0, column=4, padx=6, sticky="w")
        ttk.Label(win, text="Valor actual", foreground=C_INT).grid(row=0, column=5, padx=6, sticky="w")
        vars_, lbls = {}, {}
        keys = list(TAGS_PLC)
        half = (len(keys) + 1) // 2
        for n, k in enumerate(keys):
            r, cbase = (n % half) + 1, 0 if n < half else 3
            ttk.Label(win, text=k).grid(row=r, column=cbase, padx=6, sticky="w")
            v = tk.StringVar(value=TAGS_PLC.get(k) or "")
            vars_[k] = v
            ttk.Entry(win, textvariable=v, width=14, font=FONT).grid(row=r, column=cbase + 1, padx=6, pady=1)
            l = ttk.Label(win, text="-", width=8)
            l.grid(row=r, column=cbase + 2, padx=6, sticky="w")
            lbls[k] = l

        def refresh():
            if not win.winfo_exists():
                return
            for k, l in lbls.items():
                v = self.data.get(k)
                l.configure(text="-" if v is None else ("1" if v is True else ("0" if v is False else str(v))))
            win.after(300, refresh)
        refresh()

        def guardar():
            for k, v in vars_.items():
                TAGS_PLC[k] = v.get().strip() or None
            try:
                with open(TAGS_JSON, "w", encoding="utf-8") as f:
                    json.dump({k: (v or "") for k, v in TAGS_PLC.items()}, f, indent=2, ensure_ascii=False)
                self.log("Mapeo guardado en %s. Reconecta para aplicarlo." % TAGS_JSON)
            except Exception as e:
                self.log("No se pudo guardar %s: %s" % (TAGS_JSON, e))
            self._apply_addresses()
            win.destroy()
        fb = ttk.Frame(win, padding=6)
        fb.grid(row=half + 1, column=0, columnspan=6, sticky="e")
        ttk.Label(fb, text="Tip: con el monitor de E/S ve qué bit de O:x se enciende en X1 → es EV_E1.",
                  foreground=C_LINE).pack(side="left", padx=(0, 20))
        ttk.Button(fb, text="Guardar", command=guardar).pack(side="right")
        ttk.Button(fb, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    def log(self, msg):
        self.txt.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
        self.txt.see("end")

    def _quit(self):
        self.running = False
        self.alive = False
        self.after(300, self.destroy)


if __name__ == "__main__":
    HMI().mainloop()