import cairosvg, json, os, math
from PIL import Image
A = "/mnt/user-data/outputs/assets_cilindros"

def load(d, name, px_per_mm, extra_scale_x=None, origin_x=None):
    """rasteriza un SVG del cilindro a px_per_mm. extra_scale_x comprime en x alrededor de origin_x (muelle)."""
    svg = open(f"{A}/{d}/{name}", encoding="utf8").read()
    if extra_scale_x is not None:
        # envolver el contenido en un grupo escalado en x alrededor de origin_x
        i = svg.index("</defs>") + 7
        svg = svg[:i] + f'<g transform="translate({origin_x},0) scale({extra_scale_x},1) translate({-origin_x},0)">' + svg[i:].replace("</svg>", "</g></svg>")
    vb = [float(v) for v in svg.split('viewBox="')[1].split('"')[0].split()]
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(vb[2]*px_per_mm), output_height=int(vb[3]*px_per_mm))
    from io import BytesIO
    return Image.open(BytesIO(png)).convert("RGBA")

def sensor(d, on, px_per_mm):
    svg = open(f"{A}/{d}/sensor_{'on' if on else 'off'}.svg", encoding="utf8").read()
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(30*px_per_mm), output_height=int(8*px_per_mm))
    from io import BytesIO
    return Image.open(BytesIO(png)).convert("RGBA")

def compose(d, x_mm, cutaway, ppm, bg="#22252a"):
    g = json.load(open(f"{A}/{d}/geometria.json"))
    W, H = [int(float(v)*ppm) for v in g["viewBox"].split()[2:]]
    out = Image.new("RGBA", (W, H), bg)
    def put(im, dx_mm=0, dy_mm=0):
        out.alpha_composite(im, dest=(int(round(dx_mm*ppm)), int(round(dy_mm*ppm))))
    def put_clipped(im, dx_mm):
        dx = int(round(dx_mm*ppm))
        if dx >= im.width: return
        out.alpha_composite(im.crop((0, 0, im.width - dx, im.height)), dest=(dx, 0))
    if cutaway:
        put(load(d, "interior.svg", ppm))
        if "muelle" in g:
            L = g["muelle"]["longitud"]; k = max(0.08, (L - x_mm)/L)
            put(load(d, "muelle.svg", ppm, extra_scale_x=k, origin_x=g["muelle"]["x_apoyo"]))
    put_clipped(load(d, "vastago.svg", ppm), x_mm)
    put(load(d, "camisa_corte.svg" if cutaway else "camisa.svg", ppm))
    # sensores: el SC se enciende en x=0, el SE en x=carrera
    stroke = g["carrera_mm"]
    for key, on in (("sensor_SC", x_mm < 3), ("sensor_SE", x_mm > stroke - 3)):
        s = sensor(d, on, ppm)
        cx, cy = g[key]["x"], g[key]["y"]
        put(s, cx - 17, cy - 4)   # el cuerpo del sensor está en x 6..28 del viewBox 0 0 30 8, centro ~17
    return out

if __name__ == "__main__":
    rows = []
    for d, ppm, cases in (("iso15552_d32", 2.4, [(0, False), (0, True), (120, True), (200, True)]),
                          ("iso6432_d20", 4.5, [(0, False), (0, True), (25, True), (50, True)])):
        for x, cut in cases:
            rows.append(compose(d, x, cut, ppm))
    w = max(r.width for r in rows); h = sum(r.height for r in rows) + 12*len(rows)
    sheet = Image.new("RGBA", (w, h), "#22252a"); y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height + 12
    sheet.save("/tmp/sheet2.png"); print(sheet.size)
