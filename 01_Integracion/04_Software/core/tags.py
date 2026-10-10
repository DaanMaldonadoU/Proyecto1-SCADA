# -*- coding: utf-8 -*-
"""
core/tags.py — Tabla de variables del PLC (docs/TABLA_DE_VARIABLES.md sección 3, ladder del 18-sep).

Única fuente de direcciones RSLinx para el gateway y el HMI. Ningún otro módulo
escribe direcciones a mano: si el ladder cambia, se cambia aquí y en docs/TABLA_DE_VARIABLES.md.

Compatibilidad: Python 3.12 a 3.13, sin dependencias externas.
Se usa en: gateway (SIM / EMULATE / REAL) y HMI.

Convenciones de nombre de tag (las claves de `bits` e `ints` en el snapshot):
    STOP_1, START_1, SC1, SE1, SC2, SE2, SC3, SE3          entradas I:1.0/n
    EV_E1, EV_C1, EV_E2, EV_C2, EV_E3, EV_C3              salidas O:2.0/n
    STARTV, STOPV, ACTIVE, END, RESETV                    bits de HMI B3:0/n
    X0 … X8                                               etapas B3:3/n
    T0_ACC … T5_ACC, T0_PRE … T5_PRE, T0_DN … T5_DN       temporizadores T4:0 … T4:5
    C_ACC, C_PRE                                          contador C5:0
Tags virtuales de escritura (no existen en el PLC):
    T_ESPERA  → escribe T4:0.PRE … T4:4.PRE (los cinco)
    T_NEUM    → T4:5.PRE
    N_CICLOS  → C5:0.PRE
"""
from collections import OrderedDict

# ----------------------------------------------------------------------------
# Palabras y bits
# ----------------------------------------------------------------------------
# Entradas físicas 1746-IB16 (ranura 1): I:1.0/n
BITS_I1 = OrderedDict([
    ("STOP_1", 0),    # pulsador NC de paro: 1 en reposo, 0 pulsado
    ("START_1", 1),   # pulsador NA de inicio
    ("SC1", 2), ("SE1", 3),   # 1A retraído / extendido
    ("SC2", 4), ("SE2", 5),   # 2A
    ("SC3", 6), ("SE3", 7),   # 3A
])
# Salidas físicas 1746-OB16 (ranura 2): O:2.0/n
BITS_O2 = OrderedDict([
    ("EV_E1", 0), ("EV_C1", 1),   # bobinas 1A+ / 1A-
    ("EV_E2", 2), ("EV_C2", 3),
    ("EV_E3", 4), ("EV_C3", 5),
])
# Bits internos de HMI: B3:0/n
BITS_B30 = OrderedDict([
    ("STARTV", 0),   # escritura (pulso) desde HMI
    ("STOPV", 1),    # escritura (pulso) desde HMI; en el ladder va como XIO
    ("ACTIVE", 2),   # lectura: marcha enclavada
    ("END", 3),      # lectura: fin de los N ciclos
    ("RESETV", 4),   # escritura (pulso) desde HMI
])
# Etapas del GRAFCET: B3:3/n (una sola activa)
BITS_B33 = OrderedDict([("X%d" % i, i) for i in range(9)])

# Palabra RSLinx -> tabla de bits. Las cuatro palabras se leen enteras en el ciclo rápido
# y se descomponen en bits localmente (menos items, menos paquetes DF1).
PALABRAS = OrderedDict([
    ("I:1.0", BITS_I1),
    ("O:2.0", BITS_O2),
    ("B3:0", BITS_B30),
    ("B3:3", BITS_B33),
])

N_TIMERS = 6            # T4:0 … T4:4 esperas por etapa, T4:5 ventana neumática 4A/5A
TIMER_NEUMATICO = 5
BASE_TIEMPO_S = 0.01    # base de tiempo de todos los TON (100 = 1 s)
LIMITE_PRE = 32767      # preajuste máximo (~327 s)


def tag_timer(n, campo):
    """Nombre de tag de un temporizador. campo: 'ACC' | 'PRE' | 'DN'."""
    return "T%d_%s" % (n, campo)


# ----------------------------------------------------------------------------
# Dirección RSLinx por tag
# ----------------------------------------------------------------------------
DIRECCION = OrderedDict()
for _palabra, _bits in PALABRAS.items():
    for _tag, _bit in _bits.items():
        DIRECCION[_tag] = "%s/%d" % (_palabra, _bit)
for _n in range(N_TIMERS):
    DIRECCION[tag_timer(_n, "ACC")] = "T4:%d.ACC" % _n
    DIRECCION[tag_timer(_n, "PRE")] = "T4:%d.PRE" % _n
    DIRECCION[tag_timer(_n, "DN")] = "T4:%d/DN" % _n
DIRECCION["C_ACC"] = "C5:0.ACC"
DIRECCION["C_PRE"] = "C5:0.PRE"

TAGS_BIT = [t for t, d in DIRECCION.items() if "/" in d]
TAGS_INT = [t for t, d in DIRECCION.items() if "/" not in d]

# ----------------------------------------------------------------------------
# Grupos de lectura
# ----------------------------------------------------------------------------
# Rápido: las 4 palabras + los 6 temporizadores (ACC, PRE, DN). RSLinx agrupa los
# items del mismo archivo en un paquete: I, O, B3, T4 = 4 transacciones DF1.
ITEMS_RAPIDOS = list(PALABRAS) + [
    DIRECCION[tag_timer(n, c)] for n in range(N_TIMERS) for c in ("ACC", "PRE", "DN")
]
# Lento: el contador. Cambia una vez por ciclo de máquina.
ITEMS_LENTOS = [DIRECCION["C_ACC"], DIRECCION["C_PRE"]]
PERIODO_LENTO_CICLOS = 10   # el grupo lento se lee 1 de cada N ciclos rápidos (y tras escribir)

# ----------------------------------------------------------------------------
# Escritura
# ----------------------------------------------------------------------------
PULSOS = OrderedDict([
    ("STARTV", DIRECCION["STARTV"]),
    ("STOPV", DIRECCION["STOPV"]),
    ("RESETV", DIRECCION["RESETV"]),
])
PULSO_MS = 300

# Tag virtual -> lista de direcciones reales que escribe
PARAMETROS = OrderedDict([
    ("T_ESPERA", ["T4:%d.PRE" % n for n in range(5)]),
    ("T_NEUM", ["T4:5.PRE"]),
    ("N_CICLOS", ["C5:0.PRE"]),
])
PRESETS_DEFECTO = {"T_ESPERA": 100, "T_NEUM": 500, "N_CICLOS": 3}
# Qué tag de lectura confirma cada parámetro (para el check verde del HMI)
CONFIRMACION_PARAMETRO = {
    "T_ESPERA": [tag_timer(n, "PRE") for n in range(5)],
    "T_NEUM": [tag_timer(5, "PRE")],
    "N_CICLOS": ["C_PRE"],
}

# Entradas que el gateway puede escribir en SIM y EMULATE (sensores simulados y pulsadores).
# En REAL cualquier escritura a I:1 se rechaza.
ENTRADAS_SIMULABLES = list(BITS_I1)
SENSORES = ["SC1", "SE1", "SC2", "SE2", "SC3", "SE3"]
PREFIJOS_PROHIBIDOS = ("O:",)   # el HMI nunca escribe salidas; el ladder manda

# ----------------------------------------------------------------------------
# GRAFCET
# ----------------------------------------------------------------------------
# (número, acción para la pantalla, temporizador asociado o None)
ETAPAS = [
    (0, "Reposo · retrae 1A/2A/3A", None),
    (1, "1A+  (EV_E1)", None),
    (2, "Espera T4:0 con 1A afuera → 1A−", 0),
    (3, "Espera T4:1 con 1A adentro → 2A+", 1),
    (4, "Espera T4:2 con 2A afuera → 2A−", 2),
    (5, "Espera T4:3 con 2A adentro → 3A+", 3),
    (6, "Espera T4:4 con 3A afuera → 3A−", 4),
    (7, "Ventana T4:5 · cadena 4A/5A · C+1", 5),
    (8, "END", None),
]
TIMER_DE_ETAPA = {n: t for n, _a, t in ETAPAS if t is not None}

# Cilindros con PLC: número -> (EV_E, EV_C, SC, SE)
CILINDROS = OrderedDict([
    (1, ("EV_E1", "EV_C1", "SC1", "SE1")),
    (2, ("EV_E2", "EV_C2", "SC2", "SE2")),
    (3, ("EV_E3", "EV_C3", "SC3", "SE3")),
])
# Cilindros puramente neumáticos (sin sensores ni bobinas en el PLC): 4A y 5A.
CILINDROS_NEUMATICOS = (4, 5)


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def decodificar_palabra(nombre, valor):
    """'I:1.0', 0x0005 -> {'STOP_1': True, 'START_1': False, 'SC1': True, ...}"""
    bits = PALABRAS[nombre]
    v = int(valor) & 0xFFFF
    return {tag: bool((v >> b) & 1) for tag, b in bits.items()}


def codificar_palabra(nombre, bits, base=0):
    """Inverso: aplica {tag: bool} sobre el valor `base` de la palabra y devuelve el entero."""
    tabla = PALABRAS[nombre]
    v = int(base) & 0xFFFF
    for tag, val in bits.items():
        b = tabla[tag]
        v = (v | (1 << b)) if val else (v & ~(1 << b) & 0xFFFF)
    return v


def direccion_a_palabra_bit(direccion):
    """'I:1.0/3' -> ('I:1.0', 3). 'I:1/3' -> ('I:1.0', 3). 'B3:0/2' -> ('B3:0', 2)."""
    palabra, bit = direccion.split("/")
    if palabra[0] in "IO" and "." not in palabra:
        palabra += ".0"
    return palabra, int(bit)


def item_opc(topic, direccion):
    """Item RSLinx completo: '[PROYECTO1_TEST]I:1.0/3'."""
    return "[%s]%s" % (topic, direccion)


def direcciones_de_escritura(tag):
    """Direcciones reales que escribe un tag de escritura (pulso, parámetro o entrada simulable)."""
    if tag in PULSOS:
        return [PULSOS[tag]]
    if tag in PARAMETROS:
        return list(PARAMETROS[tag])
    if tag in ENTRADAS_SIMULABLES:
        return [DIRECCION[tag]]
    raise KeyError("tag no escribible: %s" % tag)


def validar_escritura(tag, modo, valor=None):
    """(ok, motivo). Reglas de seguridad de mds/REGLAS.md sección 6."""
    try:
        dirs = direcciones_de_escritura(tag)
    except KeyError as e:
        return False, str(e)
    for d in dirs:
        if d.startswith(PREFIJOS_PROHIBIDOS):
            return False, "prohibido escribir salidas (%s)" % d
        if d.startswith("I:") and modo == "REAL":
            return False, "en modo REAL no se escriben entradas I:1"
    if tag in PARAMETROS:
        if valor is None:
            return False, "parámetro sin valor"
        v = int(valor)
        if not (0 <= v <= LIMITE_PRE):
            return False, "valor fuera de rango 0..%d" % LIMITE_PRE
        if tag == "N_CICLOS" and v < 1:
            return False, "N_CICLOS debe ser >= 1"
    return True, ""


def etapa_activa(bits):
    """Número de la etapa activa según los bits X0..X8, o None si no hay exactamente una."""
    activas = [i for i in range(9) if bits.get("X%d" % i)]
    return activas[0] if len(activas) == 1 else None
