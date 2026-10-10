"""
ladder_sim.py — Lógica del ladder (Hoja 2) y física de los cilindros.

* Ladder : traducción del ladder RSLogix 500 (etapas B3:3, TON T4, CTU C5:0, N7).
           Se usa en el modo SIM del HMI (sin RSLinx, sin PLC).
* Fisica : mueve los émbolos 1A/2A/3A según las electroválvulas y genera los
           sensores SC/SE. La usa el modo SIM y también el modo EMULATE, donde
           el HMI escribe esos sensores en la tabla I:1 del Emulate 500.
"""

CARRERA_S = 0.8   # segundos que tarda un cilindro en extender/retraer

BITS = (
    ["I:1/%d" % i for i in range(8)] +          # Stop(NC), Start, SC1, SE1, SC2, SE2, SC3, SE3
    ["O:3/%d" % i for i in range(6)] +          # EV_E1, EV_C1, EV_E2, EV_C2, EV_E3, EV_C3
    ["B3:0/13", "B3:0/14", "B3:0/15"] +         # STARTV, STOPV, RESETV
    ["B3:1/0", "B3:2/0", "B3:2/1"] +            # ACTIVO, END, OS_X7
    ["B3:3/%d" % i for i in range(9)] +         # X0..X8
    ["T4:%d/DN" % i for i in range(6)] +
    ["S:1/15"]
)
INTS = {"N7:0": 100, "N7:1": 3, "N7:2": 500,    # defaults del informe
        "C5:0.ACC": 0, "C5:0.PRE": 3}
INTS.update({"T4:%d.ACC" % i: 0 for i in range(6)})
INTS.update({"T4:%d.PRE" % i: 100 for i in range(6)})


class Fisica:
    """Tres cilindros con válvulas 5/2 biestables. pos[i] ∈ [0,1]."""

    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]

    def step(self, dt, ev):
        """ev = [(EV_E1, EV_C1), (EV_E2, EV_C2), (EV_E3, EV_C3)] → [(SC1,SE1),(SC2,SE2),(SC3,SE3)]"""
        sens = []
        for i, (e, c) in enumerate(ev):
            if e and not c:
                self.pos[i] = min(1.0, self.pos[i] + dt / CARRERA_S)
            elif c and not e:
                self.pos[i] = max(0.0, self.pos[i] - dt / CARRERA_S)
            sens.append((self.pos[i] <= 0.02, self.pos[i] >= 0.98))
        return sens


class Ladder:
    """Lógica etapa/transición traducida del ladder (rungs 0000…)."""

    def __init__(self):
        self.b = {k: False for k in BITS}
        self.n = dict(INTS)
        self.b["I:1/0"] = True        # Stop es NC: 1 en reposo
        self.fis = Fisica()
        self.first_pass = True
        self.prev_x7 = False

    def X(self, i): return self.b["B3:3/%d" % i]
    def setX(self, i, v): self.b["B3:3/%d" % i] = v
    def DN(self, k): return self.b["T4:%d/DN" % k]

    def scan(self, dt):
        b, n = self.b, self.n
        stop_ok = b["I:1/0"]                 # 1 = no pulsado
        start = b["I:1/1"] or b["B3:0/13"]
        SC = [b["I:1/2"], b["I:1/4"], b["I:1/6"]]
        SE = [b["I:1/3"], b["I:1/5"], b["I:1/7"]]

        # 0000: ACTIVO (marcha enclavada)
        if start and stop_ok and not b["B3:0/14"]:
            b["B3:1/0"] = True
        if (not stop_ok) or b["B3:0/14"]:
            b["B3:1/0"] = False
        act = b["B3:1/0"]

        # 0001: inicialización / RESET → MOV 1 → B3:3, RES C5:0
        reset_fis = b["I:1/1"] and not stop_ok            # Start · /Stop
        b["S:1/15"] = self.first_pass
        if self.first_pass or b["B3:2/0"] or reset_fis or b["B3:0/15"]:
            for i in range(9):
                self.setX(i, i == 0)
            n["C5:0.ACC"] = 0
            b["B3:2/0"] = False
            for k in range(6):
                n["T4:%d.ACC" % k] = 0
                b["T4:%d/DN" % k] = False
        self.first_pass = False

        # presets desde N7
        for k in range(5):
            n["T4:%d.PRE" % k] = n["N7:0"]
        n["T4:5.PRE"] = n["N7:2"]
        n["C5:0.PRE"] = n["N7:1"]

        # TON T4:0..4 (X2..X6) y T4:5 (X7), base 0.01 s
        for k in range(6):
            en = self.X(k + 2) if k < 5 else self.X(7)
            if en:
                n["T4:%d.ACC" % k] = min(n["T4:%d.PRE" % k], n["T4:%d.ACC" % k] + int(round(dt * 100)))
                b["T4:%d/DN" % k] = n["T4:%d.ACC" % k] >= n["T4:%d.PRE" % k]
            else:
                n["T4:%d.ACC" % k] = 0
                b["T4:%d/DN" % k] = False

        # CTU C5:0 por flanco de X7 (ONS)
        if self.X(7) and not self.prev_x7:
            n["C5:0.ACC"] += 1
        self.prev_x7 = self.X(7)
        b["B3:2/1"] = self.X(7)

        # transiciones (OTU origen + OTL destino)
        C_lt = n["C5:0.ACC"] < n["C5:0.PRE"]
        trans = [
            (0, 1, act and SC[0] and SC[1] and SC[2] and start),
            (1, 2, act and SE[0]),
            (2, 3, act and self.DN(0) and SC[0]),
            (3, 4, act and self.DN(1) and SE[1]),
            (4, 5, act and self.DN(2) and SC[1]),
            (5, 6, act and self.DN(3) and SE[2]),
            (6, 7, act and self.DN(4) and SC[2]),
            (7, 1, act and self.DN(5) and SC[2] and C_lt),
            (7, 8, act and self.DN(5) and not C_lt),
        ]
        for src, dst, cond in trans:
            if self.X(src) and cond:
                self.setX(src, False)
                self.setX(dst, True)
                break

        if self.X(8):
            b["B3:2/0"] = True            # END

        # salidas (rungs de EV con rama de retención)
        X, DN = self.X, self.DN
        b["O:3/0"] = X(1) or (X(2) and not DN(0))
        b["O:3/1"] = (X(2) and DN(0)) or (X(3) and not DN(1)) or (X(0) and SE[0]) or (X(7) and DN(5) and SE[0])
        b["O:3/2"] = (X(3) and DN(1)) or (X(4) and not DN(2))
        b["O:3/3"] = (X(4) and DN(2)) or (X(5) and not DN(3)) or (X(0) and SE[1]) or (X(7) and DN(5) and SE[1])
        b["O:3/4"] = (X(5) and DN(3)) or (X(6) and not DN(4))
        b["O:3/5"] = (X(6) and DN(4)) or (X(7) and not DN(5)) or (X(7) and DN(5) and SE[2]) or (X(0) and SE[2])

        # física simulada → sensores
        sens = self.fis.step(dt, [(b["O:3/0"], b["O:3/1"]), (b["O:3/2"], b["O:3/3"]), (b["O:3/4"], b["O:3/5"])])
        for i, (sc, se) in enumerate(sens):
            b["I:1/%d" % (2 + 2 * i)] = sc
            b["I:1/%d" % (3 + 2 * i)] = se
