#!/usr/bin/env python3
"""Genera los SVG del sistema de diseño del HMI: botones industriales, LEDs e iconos.
Compatibles con QtSvg (sin filtros, patterns, masks ni CSS)."""
import os, json

D = "/mnt/user-data/outputs/assets_cilindros/ui"
TOK = json.load(open("/mnt/user-data/outputs/assets_cilindros/ui/tokens.json"))
C = TOK["color"]

def stops(lst):
    return "".join(f'<stop offset="{o}" stop-color="{c}"{"" if a is None else f" stop-opacity=\"{a}\""}/>' for o, c, a in [(x + (None,))[:3] for x in lst])
def lin(i, s, x1=0, y1=0, x2=0, y2=1): return f'<linearGradient id="{i}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stops(s)}</linearGradient>'
def rad(i, s, cx=0.5, cy=0.5, r=0.5, fx=None, fy=None):
    f = f' fx="{fx}" fy="{fy}"' if fx is not None else ""
    return f'<radialGradient id="{i}" cx="{cx}" cy="{cy}" r="{r}"{f}>{stops(s)}</radialGradient>'
def svg(vb, defs, body): return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><defs>{defs}</defs>{body}</svg>'
def save(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf8").write(s)

# ----------------------------------------------------------------- utilidades de color
def hex2rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
def rgb2hex(r): return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in r)
def mix(a, b, t): A, B = hex2rgb(a), hex2rgb(b); return rgb2hex([A[i] + (B[i] - A[i]) * t for i in range(3)])
def light(h, t): return mix(h, "#ffffff", t)
def dark(h, t): return mix(h, "#000000", t)

# ----------------------------------------------------------------- botones industriales
SYMBOLS = {
    "start": '<path d="M43,34 L67,50 L43,66 Z" fill="{c}"/>',
    "stop":  '<rect x="38" y="38" width="24" height="24" rx="2.5" fill="{c}"/>',
    "reset": '<path d="M62,38 A17,17 0 1 0 66,53" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
             '<path d="M64,30 L64,42 L52,42 Z" fill="{c}"/>',
    "power": '<path d="M50,32 L50,49" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
             '<path d="M40,38 A16,16 0 1 0 60,38" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round"/>',
}
KINDS = {"start": C["ok"], "stop": C["alarma"], "reset": C["activo"], "power": C["aire"]}

def button(kind, state):
    base = KINDS[kind]
    disabled = state == "disabled"
    cap = "#5b6472" if disabled else base
    if state == "hover": cap = light(base, 0.12)
    if state == "pressed": cap = dark(base, 0.18)
    sym = "#2a2f36" if disabled else ("#0e1116" if kind == "reset" else "#ffffff")
    defs = (
        rad("bezel", [(0, "#f2f4f6"), (0.35, "#c3c8cf"), (0.7, "#6f7680"), (1, "#3a4048")], cx=0.35, cy=0.3, r=0.8) +
        lin("ring", [(0, "#e9ecf0"), (0.5, "#7c848e"), (1, "#2c3138")]) +
        rad("cap", [(0, light(cap, 0.35 if state != "pressed" else 0.1)), (0.55, cap), (1, dark(cap, 0.45))], cx=0.4, cy=0.3, r=0.75) +
        rad("gloss", [(0, "#ffffff", 0.55), (1, "#ffffff", 0.0)], cx=0.5, cy=0.0, r=0.55) +
        rad("halo", [(0, base, 0.55), (0.7, base, 0.12), (1, base, 0.0)])
    )
    o = []
    if state in ("hover", "pressed") and not disabled:
        o.append('<circle cx="50" cy="50" r="49" fill="url(#halo)"/>')
    # bisel metálico
    o.append('<circle cx="50" cy="50" r="42" fill="url(#bezel)"/>')
    o.append('<circle cx="50" cy="50" r="42" fill="none" stroke="#14171b" stroke-width="1.2"/>')
    o.append('<circle cx="50" cy="50" r="36.5" fill="url(#ring)"/>')
    o.append('<circle cx="50" cy="50" r="33.5" fill="#101317"/>')
    # capuchón
    r_cap = 30 if state != "pressed" else 28.5
    dy = 0 if state != "pressed" else 1.5
    o.append(f'<circle cx="50" cy="{50+dy}" r="{r_cap}" fill="url(#cap)"/>')
    if state != "pressed":
        o.append('<ellipse cx="50" cy="36" rx="22" ry="12" fill="url(#gloss)"/>')
    o.append(f'<circle cx="50" cy="{50+dy}" r="{r_cap}" fill="none" stroke="#000000" stroke-opacity="0.35" stroke-width="1"/>')
    o.append(f'<g transform="translate(0,{dy})">' + SYMBOLS[kind].format(c=sym) + "</g>")
    return svg("0 0 100 100", defs, "".join(o))

for k in KINDS:
    for st in ("normal", "hover", "pressed", "disabled"):
        save(f"{D}/botones/{k}_{st}.svg", button(k, st))

# ----------------------------------------------------------------- botón rectangular (secundario) — fondos
def flat_button(state):
    fill = {"normal": C["surface2"], "hover": light(C["surface2"], 0.08), "pressed": dark(C["surface2"], 0.25), "disabled": C["surface"]}[state]
    stroke = C["borde"] if state != "hover" else light(C["borde"], 0.25)
    return svg("0 0 160 44", "",
               f'<rect x="1" y="1" width="158" height="42" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
               f'<rect x="2" y="2" width="156" height="1.5" rx="1" fill="#ffffff" fill-opacity="{0.08 if state != "pressed" else 0.02}"/>')
for st in ("normal", "hover", "pressed", "disabled"):
    save(f"{D}/botones/plano_{st}.svg", flat_button(st))

# ----------------------------------------------------------------- LEDs
def led(color, on):
    c = C[color]
    defs = (rad("bz", [(0, "#d9dde2"), (0.6, "#7a828c"), (1, "#30363d")], cx=0.35, cy=0.3, r=0.8) +
            rad("lens", [(0, light(c, 0.75 if on else 0.05)), (0.45, c if on else dark(c, 0.55)), (1, dark(c, 0.35 if on else 0.75))], cx=0.4, cy=0.35, r=0.7) +
            rad("gl", [(0, c, 0.6), (0.6, c, 0.15), (1, c, 0)]) +
            rad("sp", [(0, "#ffffff", 0.7), (1, "#ffffff", 0)], cx=0.5, cy=0.0, r=0.6))
    o = []
    if on: o.append('<circle cx="20" cy="20" r="20" fill="url(#gl)"/>')
    o.append('<circle cx="20" cy="20" r="13" fill="url(#bz)"/>')
    o.append('<circle cx="20" cy="20" r="13" fill="none" stroke="#111417" stroke-width="0.8"/>')
    o.append('<circle cx="20" cy="20" r="10" fill="url(#lens)"/>')
    o.append('<ellipse cx="20" cy="15" rx="7" ry="4" fill="url(#sp)"/>')
    return svg("0 0 40 40", defs, "".join(o))
for col in ("ok", "activo", "alarma", "aire", "neutro"):
    for on in (True, False):
        save(f"{D}/leds/{col}_{'on' if on else 'off'}.svg", led(col, on))

# ----------------------------------------------------------------- iconos (línea, 24x24)
S = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
ICONS = {
    "conexion":  '<path d="M9 7V4M15 7V4M6 7h12v4a6 6 0 0 1-12 0V7zM12 17v4"/>',
    "desconectado": '<path d="M9 7V4M15 7V4M6 7h12v4a6 6 0 0 1-12 0V7zM12 17v4M3 3l18 18"/>',
    "alarma":    '<path d="M6 17V11a6 6 0 0 1 12 0v6l2 2H4l2-2zM10 21h4"/>',
    "ajustes":   '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "reloj":     '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "contador":  '<path d="M4 19V9M10 19V5M16 19v-8M22 19H2"/>',
    "io":        '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "registro":  '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "plc":       '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h4M7 12h4M7 16h4M15 8h2M15 12h2M15 16h2"/>',
    "aire":      '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h8a3 3 0 1 1-3 3"/>',
    "latencia":  '<path d="M2 12h4l3-7 4 14 3-7h6"/>',
    "grafcet":   '<rect x="8" y="3" width="8" height="6" rx="1"/><rect x="8" y="15" width="8" height="6" rx="1"/><path d="M12 9v6M9 12h6"/>',
    "cilindro":  '<rect x="2" y="8" width="13" height="8" rx="1"/><path d="M15 12h7M4 8V6M13 8V6"/>',
    "cerrar":    '<path d="M6 6l12 12M18 6L6 18"/>',
    "check":     '<path d="M4 12l5 5L20 7"/>',
    "expandir":  '<path d="M4 9V4h5M20 15v5h-5M20 4l-6 6M4 20l6-6"/>',
    "camara":    '<rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 7l1.5-2h5L16 7"/>',
    "vm":        '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4M7 9h4M7 12h6"/>',
}
for name, body in ICONS.items():
    for cname, col in (("claro", C["texto"]), ("oscuro", C["fondo"]), ("acento", C["aire"])):
        save(f"{D}/iconos/{name}_{cname}.svg", svg("0 0 24 24", "", f"<g {S.format(c=col)}>{body}</g>"))
print("ui ok")
