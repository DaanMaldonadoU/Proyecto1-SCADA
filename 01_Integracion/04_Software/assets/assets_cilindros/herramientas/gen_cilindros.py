#!/usr/bin/env python3
"""
Genera los SVG por capas de dos cilindros neumáticos para el HMI:

  iso15552_d32/   cilindro perfilado ISO 15552, ø32, carrera 200 (tipo P1D-S, doble efecto, magnético)
  iso6432_d20/    minicilindro ISO 6432, ø20, simple efecto con retorno por muelle (tipo P1A)

Unidades: 1 unidad SVG = 1 mm. Todos los archivos de un cilindro comparten el mismo viewBox,
así que en QML se apilan Image sobre Image sin transformar. El vástago se dibuja en la posición
RETRAÍDA; para animarlo se desplaza en +x por (carrera_mm * escala).

Compatibilidad QtSvg (SVG Tiny): sin filtros, sin patterns, sin masks, sin CSS. Sólo gradientes,
clipPath y atributos de presentación.
"""
import os, math

# ----------------------------------------------------------------------------- parámetros
BIG = dict(name="iso15552_d32", bore=32, stroke=200, rod=12, thread_d=10, thread_len=20,
           wh=26, cap_len=26, prof=46, port_len=12)
MINI = dict(name="iso6432_d20", bore=20, stroke=50, rod=8, thread_d=8, thread_len=12,
            wh=20, cap_len=16, tube_d=22, cap_d=24)

OUT = "/mnt/user-data/outputs/assets_cilindros"

# ----------------------------------------------------------------------------- utilidades
def grad(id_, stops, x1=0, y1=0, x2=0, y2=1):
    s = "".join(f'<stop offset="{o}" stop-color="{c}"{"" if a is None else f" stop-opacity=\"{a}\""}/>'
                for o, c, a in [(st + (None,))[:3] for st in stops])
    return f'<linearGradient id="{id_}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{s}</linearGradient>'

def ugrad(id_, base, y1, y2):
    """variante de un gradiente vertical en coordenadas absolutas (para tubos dibujados en tiras)"""
    g = DEFS[base]
    g = g.replace(f'id="{base}"', f'id="{id_}" gradientUnits="userSpaceOnUse"')
    g = g.replace('x1="0" y1="0" x2="0" y2="1"', f'x1="0" y1="{y1:.2f}" x2="0" y2="{y2:.2f}"')
    return g

def rgrad(id_, stops, cx=0.5, cy=0.5, r=0.5):
    s = "".join(f'<stop offset="{o}" stop-color="{c}"{"" if a is None else f" stop-opacity=\"{a}\""}/>'
                for o, c, a in [(st + (None,))[:3] for st in stops])
    return f'<radialGradient id="{id_}" cx="{cx}" cy="{cy}" r="{r}">{s}</radialGradient>'

DEFS = {
 # aluminio anodizado natural (perfil)
 "alu": grad("alu", [(0,"#f4f5f7"),(0.08,"#e3e5e8"),(0.22,"#f7f8f9"),(0.45,"#c4c8ce"),(0.7,"#9a9fa6"),(0.9,"#aeb3b9"),(1,"#7f848a")]),
 # anodizado negro (tapas)
 "blk": grad("blk", [(0,"#6b6e73"),(0.1,"#4a4d51"),(0.3,"#2e3033"),(0.6,"#1b1c1e"),(0.85,"#26282b"),(1,"#0e0f10")]),
 # cromo (vástago)
 "chrome": grad("chrome", [(0,"#9aa0a7"),(0.12,"#ffffff"),(0.3,"#f2f4f6"),(0.5,"#c9ced4"),(0.72,"#6e747b"),(0.9,"#8d939a"),(1,"#4c5157")]),
 # rosca (más oscura)
 "thread": grad("thread", [(0,"#7d838a"),(0.2,"#d9dde1"),(0.5,"#9ca2a8"),(0.8,"#565b61"),(1,"#3d4146")]),
 # inox (minicilindro)
 "inox": grad("inox", [(0,"#f2f3f4"),(0.1,"#dfe2e5"),(0.28,"#fbfbfc"),(0.5,"#b7bcc2"),(0.75,"#7a8087"),(0.92,"#9ea3a9"),(1,"#5f646a")]),
 # latón (racores)
 "brass": grad("brass", [(0,"#f3e3a6"),(0.3,"#d8b85c"),(0.6,"#a9852f"),(1,"#6e5314")]),
 # plástico gris (cuerpo de racor push-in)
 "plast": grad("plast", [(0,"#6f7378"),(0.4,"#3c3f43"),(1,"#1f2124")]),
 # interior del tubo (fondo del corte)
 "bore": grad("bore", [(0,"#1c1e21"),(0.3,"#2e3136"),(0.5,"#3b3f45"),(0.8,"#24272b"),(1,"#131416")]),
 # zona de aire presurizado (para tinte opcional)
 "goma": grad("goma", [(0,"#3a3d42"),(0.5,"#1d1f22"),(1,"#0d0e10")]),
 "led_off": rgrad("led_off", [(0,"#5a2a2a"),(1,"#2a1414")]),
 "led_on": rgrad("led_on", [(0,"#fff4d6"),(0.35,"#ffb000"),(1,"#c74a00")]),
 "shadow": rgrad("shadow", [(0,"#000000",0.45),(0.6,"#000000",0.18),(1,"#000000",0.0)], cy=0.5, r=0.5),
 "cable": grad("cable", [(0,"#4a4d52"),(0.5,"#2b2d31"),(1,"#151618")]),
 "spring": grad("spring", [(0,"#9ea4ab"),(0.3,"#e4e7ea"),(0.6,"#8a9097"),(1,"#4f545a")]),
 "glass": grad("glass", [(0,"#ffffff",0.28),(0.5,"#ffffff",0.05),(1,"#ffffff",0.16)]),
}

def svg(vb, body, defs, ids=None, title=""):
    d = "".join(DEFS[k] for k in defs)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="{vb}" width="{vb.split()[2]}mm" height="{vb.split()[3]}mm">'
            f'<title>{title}</title><defs>{d}</defs>{body}</svg>')

def rect(x, y, w, h, fill, rx=0, extra=""):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" fill="{fill}" {extra}/>'

def line(x1, y1, x2, y2, stroke, w=0.3, op=1):
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" stroke-width="{w}" stroke-opacity="{op}" stroke-linecap="round"/>'

def hilite(x, y, w, h):
    """brillo superior + sombra inferior sobre una superficie cilíndrica horizontal"""
    return (rect(x, y + h*0.14, w, h*0.06, "#ffffff", extra='opacity="0.55"') +
            rect(x, y + h*0.84, w, h*0.05, "#000000", extra='opacity="0.35"'))

def edge(x, y, w, h, rx=0):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" fill="none" stroke="#0b0c0d" stroke-width="0.35" stroke-opacity="0.85"/>'

def threads(x, y, w, h, pitch=1.25):
    """rosca: líneas oblicuas finas sobre el gradiente"""
    out = [rect(x, y, w, h, "url(#thread)")]
    n = int(w / pitch)
    for i in range(n + 1):
        xx = x + i * pitch
        out.append(f'<line x1="{xx:.2f}" y1="{y:.2f}" x2="{xx+0.4:.2f}" y2="{y+h:.2f}" stroke="#2b2f34" stroke-width="0.35" stroke-opacity="0.8"/>')
        out.append(f'<line x1="{xx+0.55:.2f}" y1="{y:.2f}" x2="{xx+0.95:.2f}" y2="{y+h:.2f}" stroke="#ffffff" stroke-width="0.25" stroke-opacity="0.45"/>')
    out.append(edge(x, y, w, h))
    return "".join(out)

def hexnut(x, cy, w, af, fill="url(#chrome)"):
    """tuerca vista de lado (tres caras)"""
    h = af
    y = cy - h/2
    parts = [rect(x, y, w, h, fill),
             rect(x, y + h*0.33, w, h*0.34, "#ffffff", extra='opacity="0.18"'),
             line(x, y + h*0.33, x + w, y + h*0.33, "#0b0c0d", 0.3, 0.7),
             line(x, y + h*0.67, x + w, y + h*0.67, "#0b0c0d", 0.3, 0.7),
             edge(x, y, w, h)]
    return "".join(parts)

def shadow(cx, cy, rx, ry):
    return f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" fill="url(#shadow)"/>'

def pushin_fitting(x, y_top_of_cap, k=1.0):
    """racor push-in recto de latón/plástico montado sobre la tapa, tubo hacia arriba. k = escala"""
    o = [f'<g transform="translate({x:.2f},{y_top_of_cap:.2f}) scale({k}) translate({-x:.2f},{-y_top_of_cap:.2f})">']
    # cuerpo hexagonal de latón sobre la tapa
    o.append(hexnut(x - 4.5, y_top_of_cap - 3, 9, 6, "url(#brass)"))
    # cuerpo plástico
    o.append(rect(x - 3.2, y_top_of_cap - 11, 6.4, 5.5, "url(#plast)", rx=0.6))
    o.append(rect(x - 3.2, y_top_of_cap - 9.8, 6.4, 0.8, "#ffffff", extra='opacity="0.25"'))
    # anillo de liberación
    o.append(rect(x - 3.6, y_top_of_cap - 12.6, 7.2, 2.0, "#3f7fd6", rx=0.5))
    o.append(rect(x - 3.6, y_top_of_cap - 12.2, 7.2, 0.6, "#ffffff", extra='opacity="0.35"'))
    # tubo de poliuretano
    o.append(rect(x - 2.0, y_top_of_cap - 24, 4.0, 11.6, "#4b8ff0", rx=0.4))
    o.append(rect(x - 1.2, y_top_of_cap - 24, 1.0, 11.6, "#ffffff", extra='opacity="0.45"'))
    o.append(edge(x - 2.0, y_top_of_cap - 24, 4.0, 11.6, rx=0.4))
    o.append('</g>')
    return "".join(o)

def sensor_svg(on, L=22, D=5, cable_left=True):
    """sensor magnético cilíndrico con LED. viewBox 0 0 30 8, cuerpo centrado."""
    x0 = 6 if cable_left else 2
    o = []
    # cable
    if cable_left:
        o.append(rect(0, 3.0, 7, 2.0, "url(#cable)", rx=1))
    else:
        o.append(rect(x0 + L - 1, 3.0, 7, 2.0, "url(#cable)", rx=1))
    # cuerpo
    o.append(rect(x0, 1.5, L, D, "url(#alu)", rx=1.2))
    o.append(hilite(x0, 1.5, L, D))
    # tornillo de fijación
    o.append(rect(x0 + 3, 1.0, 3.2, 1.2, "url(#chrome)", rx=0.3))
    # LED
    o.append(f'<ellipse cx="{x0+L-5:.2f}" cy="4.0" rx="1.6" ry="1.4" fill="url(#{"led_on" if on else "led_off"})"/>')
    if on:
        o.append(f'<ellipse cx="{x0+L-5:.2f}" cy="4.0" rx="3.2" ry="2.6" fill="#ffb000" opacity="0.25"/>')
    o.append(edge(x0, 1.5, L, D, rx=1.2))
    return svg("0 0 30 8", "".join(o), ["alu","chrome","cable","led_on","led_off"], title=f"sensor {'on' if on else 'off'}")

# ============================================================================ ISO 15552 ø32
def build_big(p):
    W, H = 580, 78            # viewBox (cabe el vástago totalmente extendido)
    ax = 40                   # eje del cilindro (y)
    prof = p["prof"]; hp = prof/2
    x0 = 8                    # cara trasera
    cap = p["cap_len"]
    tube_len = p["stroke"] + 42
    x_tube = x0 + cap
    x_fcap = x_tube + tube_len
    x_front = x_fcap + cap     # cara delantera (salida del vástago)
    ytop, ybot = ax - hp, ax + hp
    bore = p["bore"]; hb = bore/2
    rod = p["rod"]; hr = rod/2

    # ---------------- camisa (fondo común de tapas y tubo)
    def caps_and_tube(cutaway):
        o = []
        o.append(shadow((x0 + x_front)/2, ybot + 5.5, (x_front - x0)/2 + 4, 4.5))
        # tapa trasera
        o.append(rect(x0, ytop, cap, prof, "url(#blk)", rx=2.2))
        o.append(hilite(x0, ytop, cap, prof))
        # tornillo de regulación de amortiguación (trasera)
        o.append(f'<circle cx="{x0+8:.1f}" cy="{ytop+8:.1f}" r="2.6" fill="url(#chrome)"/>')
        o.append(line(x0+6.4, ytop+8, x0+9.6, ytop+8, "#0b0c0d", 0.6))
        o.append(f'<circle cx="{x0+8:.1f}" cy="{ytop+8:.1f}" r="2.6" fill="none" stroke="#0b0c0d" stroke-width="0.35"/>')
        # tirantes (cabezas de tornillo en las 4 esquinas de las tapas)
        for cx_ in (x0 + 5.5, x_front - 5.5):
            for cy_ in (ybot - 5.5,):
                o.append(f'<circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="2.4" fill="url(#chrome)"/>')
                o.append(f'<circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="1.2" fill="#2b2d30"/>')
                o.append(f'<circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="2.4" fill="none" stroke="#0b0c0d" stroke-width="0.35"/>')
        # tubo perfilado
        ty, th = ytop + 0.8, prof - 1.6
        if not cutaway:
            o.append(rect(x_tube, ty, tube_len, th, "url(#alu)"))
            o.append(hilite(x_tube, ty, tube_len, th))
        else:
            wx, wy, ww, wh = x_tube + 6, ax - hb, tube_len - 12, bore
            for (sx, sy, sw, sh) in ((x_tube, ty, tube_len, wy - ty), (x_tube, wy + wh, tube_len, ty + th - wy - wh),
                                     (x_tube, wy, wx - x_tube, wh), (wx + ww, wy, x_tube + tube_len - wx - ww, wh)):
                o.append(rect(sx, sy, sw, sh, "url(#alu_u)"))
            o.append(rect(x_tube, ty + 1.6, tube_len, 1.6, "#ffffff", extra='opacity="0.55"'))
            o.append(rect(x_tube, wy + wh + 1.8, tube_len, 1.4, "#000000", extra='opacity="0.35"'))
        # ranuras del perfil (T-slot) en la cara visible: superior e inferior
        for yy in (ax - 19.3, ax + 19.3):
            o.append(rect(x_tube, yy - 1.4, tube_len, 2.8, "#5f6469"))
            o.append(rect(x_tube, yy - 1.4, tube_len, 0.6, "#2c2f33"))
            o.append(rect(x_tube, yy + 0.8, tube_len, 0.6, "#e6e8eb", extra='opacity="0.7"'))
        # líneas de arista del perfil
        o.append(line(x_tube, ytop + 0.8, x_tube + tube_len, ytop + 0.8, "#0b0c0d", 0.35, 0.8))
        o.append(line(x_tube, ybot - 0.8, x_tube + tube_len, ybot - 0.8, "#0b0c0d", 0.35, 0.8))
        # ventana de corte
        if cutaway:
            wx, wy, ww, wh = x_tube + 6, ax - hb, tube_len - 12, bore
            # borde del corte (canto del metal seccionado)
            o.append(f'<rect x="{wx-0.6:.2f}" y="{wy-0.6:.2f}" width="{ww+1.2:.2f}" height="{wh+1.2:.2f}" fill="none" stroke="#eef0f2" stroke-width="1.2"/>')
            o.append(f'<rect x="{wx:.2f}" y="{wy:.2f}" width="{ww:.2f}" height="{wh:.2f}" fill="none" stroke="#1a1c1f" stroke-width="0.5"/>')
        # tapa delantera
        o.append(rect(x_fcap, ytop, cap, prof, "url(#blk)", rx=2.2))
        o.append(hilite(x_fcap, ytop, cap, prof))
        o.append(f'<circle cx="{x_front-8:.1f}" cy="{ytop+8:.1f}" r="2.6" fill="url(#chrome)"/>')
        o.append(line(x_front-9.6, ytop+8, x_front-6.4, ytop+8, "#0b0c0d", 0.6))
        o.append(f'<circle cx="{x_front-8:.1f}" cy="{ytop+8:.1f}" r="2.6" fill="none" stroke="#0b0c0d" stroke-width="0.35"/>')
        # casquillo guía del vástago (saliente en la cara delantera)
        o.append(rect(x_front, ax - hr - 3.5, 4, rod + 7, "url(#alu)", rx=0.8))
        o.append(hilite(x_front, ax - hr - 3.5, 4, rod + 7))
        o.append(edge(x_front, ax - hr - 3.5, 4, rod + 7, rx=0.8))
        # contornos de las tapas
        o.append(edge(x0, ytop, cap, prof, rx=2.2))
        o.append(edge(x_fcap, ytop, cap, prof, rx=2.2))
        # racores sobre las tapas
        o.append(pushin_fitting(x0 + cap/2 + 1, ytop))
        o.append(pushin_fitting(x_fcap + cap/2 - 1, ytop))
        # etiqueta discreta en el tubo
        o.append(rect(x_tube + 12, ax - 6, 38, 12, "#ffffff", rx=1, extra='opacity="0.85"') if not cutaway else "")
        if not cutaway:
            o.append(f'<text x="{x_tube+31:.1f}" y="{ax-1:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="4.2" font-weight="bold" fill="#1b1c1e" text-anchor="middle">ISO 15552</text>')
            o.append(f'<text x="{x_tube+31:.1f}" y="{ax+4.2:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="3.4" fill="#1b1c1e" text-anchor="middle">Ø{bore} · {p["stroke"]} mm</text>')
        return "".join(o)

    # ---------------- interior del tubo (sólo para el corte)
    def interior():
        wx, wy, ww, wh = x_tube + 6, ax - hb, tube_len - 12, bore
        o = [rect(wx, wy, ww, wh, "url(#bore)")]
        o.append(rect(wx, wy + 1.5, ww, 1.2, "#ffffff", extra='opacity="0.08"'))
        return "".join(o)

    # ---------------- vástago + pistón (posición retraída)
    def rod_group():
        o = []
        px = x_tube + 5            # cara trasera del pistón (retraído)
        pw = 22
        # pistón
        o.append(rect(px, ax - hb + 0.6, pw, bore - 1.2, "url(#alu)", rx=1.5))
        o.append(hilite(px, ax - hb + 0.6, pw, bore - 1.2))
        # juntas (dos) y banda de imán
        for jx in (px + 2.5, px + pw - 4.5):
            o.append(rect(jx, ax - hb + 0.3, 2.0, bore - 0.6, "url(#goma)", rx=0.5))
        o.append(rect(px + 8.5, ax - hb + 2, 5, bore - 4, "#8a2c2c", rx=0.6))
        o.append(rect(px + 8.5, ax - hb + 3, 5, 1.2, "#ffffff", extra='opacity="0.3"'))
        o.append(edge(px, ax - hb + 0.6, pw, bore - 1.2, rx=1.5))
        # amortiguador (buje) delantero del pistón
        o.append(rect(px + pw, ax - hr - 2.5, 6, rod + 5, "url(#alu)", rx=1))
        o.append(edge(px + pw, ax - hr - 2.5, 6, rod + 5, rx=1))
        # vástago desde el pistón hasta el saliente
        rx0 = px + pw + 6
        rlen = (x_front + 4 + p["wh"]) - rx0
        o.append(rect(rx0, ax - hr, rlen, rod, "url(#chrome)"))
        o.append(rect(rx0, ax - hr + rod*0.16, rlen, rod*0.10, "#ffffff", extra='opacity="0.85"'))
        o.append(rect(rx0, ax - hr + rod*0.80, rlen, rod*0.07, "#000000", extra='opacity="0.35"'))
        o.append(edge(rx0, ax - hr, rlen, rod))
        # llave (plano) y rosca
        xe = rx0 + rlen
        o.append(hexnut(xe - 6, ax, 6, rod - 1))
        o.append(threads(xe, ax - p["thread_d"]/2, p["thread_len"], p["thread_d"], 1.25))
        # contratuerca
        o.append(hexnut(xe + 2, ax, 5, p["thread_d"] + 6))
        return "".join(o)

    vb = f"0 0 {W} {H}"
    DEFS["alu_u"] = ugrad("alu_u", "alu", ytop + 0.8, ybot - 0.8)
    defs_all = ["alu","alu_u","blk","chrome","thread","brass","plast","bore","goma","shadow","glass"]
    files = {
        "camisa.svg":       svg(vb, caps_and_tube(False), defs_all, title="camisa ISO 15552 ø32 (opaca)"),
        "camisa_corte.svg": svg(vb, caps_and_tube(True), defs_all, title="camisa ISO 15552 ø32 (con ventana de corte)"),
        "interior.svg":     svg(vb, interior(), ["bore"], title="interior del tubo"),
        "vastago.svg":      svg(vb, rod_group(), ["alu","chrome","thread","goma"], title="vástago + pistón (retraído)"),
        "sensor_off.svg":   sensor_svg(False),
        "sensor_on.svg":    sensor_svg(True),
    }
    meta = dict(viewBox=vb, eje_y=ax, cara_trasera_x=x0, cara_delantera_x=x_front, carrera_mm=p["stroke"],
                tubo_x=[x_tube, x_tube + tube_len], ranura_sensores_y=[ax - 19.3, ax + 19.3],
                sensor_SC=dict(x=x_tube + 5 + 11, y=ax + 19.3), sensor_SE=dict(x=x_tube + 5 + 11 + p["stroke"], y=ax + 19.3),
                piston_retraido_x=x_tube + 5, extremo_vastago_retraido_x=x_front + 4 + p["wh"] + p["thread_len"] + 2)
    return files, meta

# ============================================================================ ISO 6432 ø20
def build_mini(p):
    W, H = 215, 40
    ax = 20
    td = p["tube_d"]; ht = td/2
    cd = p["cap_d"]; hc = cd/2
    x0 = 6
    cap = p["cap_len"]
    tube_len = p["stroke"] + 28
    x_tube = x0 + cap
    x_fcap = x_tube + tube_len
    x_front = x_fcap + cap
    bore = p["bore"]; hb = bore/2
    rod = p["rod"]; hr = rod/2

    def body(cutaway):
        o = [shadow((x0 + x_front)/2, ax + hc + 4, (x_front - x0)/2 + 2, 3)]
        # tapa trasera (redonda, rebordeada)
        o.append(rect(x0, ax - hc, cap, cd, "url(#inox)", rx=3))
        o.append(hilite(x0, ax - hc, cap, cd))
        # rebordeado (línea de rodillado)
        o.append(line(x0 + cap - 2.5, ax - hc + 0.5, x0 + cap - 2.5, ax + hc - 0.5, "#0b0c0d", 0.35, 0.6))
        # racor push-in M5 trasero (arriba)
        o.append(pushin_fitting(x0 + cap/2, ax - hc + 1, k=0.72))
        # tubo
        if not cutaway:
            o.append(rect(x_tube, ax - ht, tube_len, td, "url(#inox)"))
            o.append(hilite(x_tube, ax - ht, tube_len, td))
        else:
            wx, wy, ww, wh = x_tube + 4, ax - hb, tube_len - 8, bore
            for (sx, sy, sw, sh) in ((x_tube, ax - ht, tube_len, wy - (ax - ht)), (x_tube, wy + wh, tube_len, ax + ht - wy - wh),
                                     (x_tube, wy, wx - x_tube, wh), (wx + ww, wy, x_tube + tube_len - wx - ww, wh)):
                o.append(rect(sx, sy, sw, sh, "url(#inox_u)"))
            o.append(rect(x_tube, ax - ht + 0.4, tube_len, 0.6, "#ffffff", extra='opacity="0.55"'))
        o.append(line(x_tube, ax - ht, x_fcap, ax - ht, "#0b0c0d", 0.35, 0.8))
        o.append(line(x_tube, ax + ht, x_fcap, ax + ht, "#0b0c0d", 0.35, 0.8))
        if cutaway:
            wx, wy, ww, wh = x_tube + 4, ax - hb, tube_len - 8, bore
            o.append(f'<rect x="{wx-0.5:.2f}" y="{wy-0.5:.2f}" width="{ww+1:.2f}" height="{wh+1:.2f}" fill="none" stroke="#eef0f2" stroke-width="1.0"/>')
            o.append(f'<rect x="{wx:.2f}" y="{wy:.2f}" width="{ww:.2f}" height="{wh:.2f}" fill="none" stroke="#1a1c1f" stroke-width="0.45"/>')
        # abrazaderas de los sensores (banda alrededor del tubo)
        for sx in (x_tube + 3 + 5, x_tube + 3 + 5 + p["stroke"]):
            if cutaway:
                o.append(rect(sx - 2.2, ax - ht - 0.6, 4.4, ht - hb + 0.6, "url(#blk)"))
                o.append(rect(sx - 2.2, ax + hb, 4.4, ht - hb + 0.6, "url(#blk)"))
                o.append(rect(sx - 2.2, ax - ht + 0.4, 4.4, 0.7, "#ffffff", extra='opacity="0.25"'))
            else:
                o.append(rect(sx - 2.2, ax - ht - 0.6, 4.4, td + 1.2, "url(#blk)", rx=0.6))
                o.append(rect(sx - 2.2, ax - ht + 2.5, 4.4, 1.2, "#ffffff", extra='opacity="0.25"'))
                o.append(edge(sx - 2.2, ax - ht - 0.6, 4.4, td + 1.2, rx=0.6))
        # tapa delantera con respiradero
        o.append(rect(x_fcap, ax - hc, cap, cd, "url(#inox)", rx=3))
        o.append(hilite(x_fcap, ax - hc, cap, cd))
        o.append(line(x_fcap + 2.5, ax - hc + 0.5, x_fcap + 2.5, ax + hc - 0.5, "#0b0c0d", 0.35, 0.6))
        # respiradero (agujero pequeño con malla) en la tapa delantera
        o.append(f'<circle cx="{x_fcap+cap/2:.1f}" cy="{ax-6.5:.1f}" r="1.6" fill="#1a1c1f"/>')
        o.append(f'<circle cx="{x_fcap+cap/2:.1f}" cy="{ax-6.5:.1f}" r="1.6" fill="none" stroke="#e6e8eb" stroke-width="0.35" stroke-opacity="0.7"/>')
        # cuello roscado M22x1.5 + tuerca de fijación
        o.append(threads(x_front, ax - 5.5, 9, 11, 1.5))
        o.append(hexnut(x_front + 2, ax, 5, 14))
        o.append(edge(x0, ax - hc, cap, cd, rx=3))
        o.append(edge(x_fcap, ax - hc, cap, cd, rx=3))
        if not cutaway:
            o.append(f'<text x="{x_tube+tube_len/2:.1f}" y="{ax+1.4:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="2.6" fill="#1b1c1e" fill-opacity="0.75" text-anchor="middle">ISO 6432 · Ø{bore}</text>')
        return "".join(o)

    def interior():
        wx, wy, ww, wh = x_tube + 4, ax - hb, tube_len - 8, bore
        return rect(wx, wy, ww, wh, "url(#bore)") + rect(wx, wy + 1, ww, 0.9, "#ffffff", extra='opacity="0.08"')

    def rod_group():
        o = []
        px = x_tube + 3; pw = 10
        o.append(rect(px, ax - hb + 0.4, pw, bore - 0.8, "url(#alu)", rx=1))
        o.append(hilite(px, ax - hb + 0.4, pw, bore - 0.8))
        o.append(rect(px + 1.5, ax - hb + 0.2, 1.6, bore - 0.4, "url(#goma)", rx=0.4))
        o.append(rect(px + pw - 3.1, ax - hb + 0.2, 1.6, bore - 0.4, "url(#goma)", rx=0.4))
        o.append(rect(px + 4.2, ax - hb + 1.5, 2.2, bore - 3, "#8a2c2c", rx=0.4))
        o.append(edge(px, ax - hb + 0.4, pw, bore - 0.8, rx=1))
        rx0 = px + pw
        rlen = (x_front + 9 + p["wh"]) - rx0
        o.append(rect(rx0, ax - hr, rlen, rod, "url(#chrome)"))
        o.append(rect(rx0, ax - hr + rod*0.16, rlen, rod*0.10, "#ffffff", extra='opacity="0.85"'))
        o.append(rect(rx0, ax - hr + rod*0.80, rlen, rod*0.07, "#000000", extra='opacity="0.35"'))
        o.append(edge(rx0, ax - hr, rlen, rod))
        xe = rx0 + rlen
        o.append(hexnut(xe - 4, ax, 4, rod - 1))
        o.append(threads(xe, ax - p["thread_d"]/2, p["thread_len"], p["thread_d"], 1.0))
        return "".join(o)

    def spring():
        """muelle de retorno en la cámara delantera, dibujado con el vástago RETRAÍDO (muelle relajado).
        Origen de la escala en x = xs_end (extremo apoyado en la tapa delantera). Para comprimirlo en QML:
        transform: [ Scale { origin.x: xs_end; xScale: (L - x)/L } ]"""
        px = x_tube + 3 + 10       # cara delantera del pistón retraído
        xs0 = px + 0.5
        xs1 = x_fcap - 4.5         # apoyo en la tapa delantera (borde de la ventana)
        L = xs1 - xs0
        n = 8                      # espiras
        r = hb - 2.2
        steps = 48
        segs_front, segs_back = [], []
        cur, curkind = "", None
        for i in range(n * steps + 1):
            t = i / (n * steps)
            xx = xs0 + t * L
            ph = 2 * math.pi * n * t
            yy = ax + r * math.sin(ph)
            kind = "f" if math.cos(ph) >= 0 else "b"     # cos>0: la hebra viene hacia el observador
            if kind != curkind:
                if cur: (segs_front if curkind == "f" else segs_back).append(cur)
                cur, curkind = f"M{xx:.2f},{yy:.2f} ", kind
            else:
                cur += f"L{xx:.2f},{yy:.2f} "
        (segs_front if curkind == "f" else segs_back).append(cur)
        o = []
        for dpath in segs_back:
            o.append(f'<path d="{dpath}" fill="none" stroke="#2a2d31" stroke-width="1.4" stroke-linecap="round"/>')
            o.append(f'<path d="{dpath}" fill="none" stroke="#6d737a" stroke-width="0.8" stroke-linecap="round"/>')
        for dpath in segs_front:
            o.append(f'<path d="{dpath}" fill="none" stroke="#2a2d31" stroke-width="2.4" stroke-linecap="round"/>')
            o.append(f'<path d="{dpath}" fill="none" stroke="url(#spring)" stroke-width="1.7" stroke-linecap="round"/>')
            o.append(f'<path d="{dpath}" fill="none" stroke="#ffffff" stroke-width="0.45" stroke-opacity="0.55" stroke-linecap="round"/>')
        return "".join(o), xs0, xs1

    vb = f"0 0 {W} {H}"
    DEFS["inox_u"] = ugrad("inox_u", "inox", ax - ht, ax + ht)
    sp, xs0, xs1 = spring()
    files = {
        "camisa.svg":       svg(vb, body(False), ["inox","inox_u","chrome","thread","brass","plast","shadow","alu","blk"], title="camisa ISO 6432 ø20 (opaca)"),
        "camisa_corte.svg": svg(vb, body(True), ["inox","inox_u","chrome","thread","brass","plast","shadow","alu","blk"], title="camisa ISO 6432 ø20 (con ventana de corte)"),
        "interior.svg":     svg(vb, interior(), ["bore"], title="interior del tubo"),
        "vastago.svg":      svg(vb, rod_group(), ["alu","chrome","thread","goma"], title="vástago + pistón (retraído)"),
        "muelle.svg":       svg(vb, sp, ["spring"], title="muelle de retorno (relajado, vástago retraído)"),
        "sensor_off.svg":   sensor_svg(False, L=16),
        "sensor_on.svg":    sensor_svg(True, L=16),
    }
    meta = dict(viewBox=vb, eje_y=ax, cara_trasera_x=x0, cara_delantera_x=x_front, carrera_mm=p["stroke"],
                tubo_x=[x_tube, x_fcap], muelle=dict(x_inicio=xs0, x_apoyo=xs1, longitud=xs1 - xs0),
                sensor_SC=dict(x=x_tube + 3 + 5, y=ax + ht - 0.5), sensor_SE=dict(x=x_tube + 3 + 5 + p["stroke"], y=ax + ht - 0.5),
                piston_retraido_x=x_tube + 3)
    return files, meta

# ============================================================================ salida
def write(files, meta, d):
    os.makedirs(d, exist_ok=True)
    for n, s in files.items():
        with open(os.path.join(d, n), "w", encoding="utf-8") as f:
            f.write(s)
    import json
    with open(os.path.join(d, "geometria.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    f1, m1 = build_big(BIG);  write(f1, m1, os.path.join(OUT, BIG["name"]))
    f2, m2 = build_mini(MINI); write(f2, m2, os.path.join(OUT, MINI["name"]))
    print("ok", m1["extremo_vastago_retraido_x"], m2)
