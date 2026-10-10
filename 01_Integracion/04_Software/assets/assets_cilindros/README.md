# assets_cilindros — gráficos por capas para el HMI

Dos cilindros neumáticos dibujados en SVG vectorial, vista lateral realista (aluminio anodizado, tapas negras, vástago cromado, racores push‑in, sensores magnéticos con LED). Sin logotipos ni marcas: la referencia comercial (Parker P1D‑S ø32×200 y P1A ISO 6432 ø20) va en la documentación, no en el dibujo.

```
assets_cilindros/
├── iso15552_d32/          cilindro perfilado ISO 15552 · ø32 · carrera 200 · doble efecto · magnético
│   ├── camisa.svg         cuerpo opaco (tapas, tubo perfilado con ranuras, racores, casquillo)
│   ├── camisa_corte.svg   igual, con ventana de corte en el tubo (deja ver el pistón)
│   ├── interior.svg       fondo del cilindro (interior del tubo) — sólo con camisa_corte
│   ├── vastago.svg        pistón + juntas + imán + vástago + rosca + contratuerca, en posición RETRAÍDA
│   ├── sensor_off.svg / sensor_on.svg   sensor magnético (viewBox 0 0 30 8; cuerpo centrado en x=17, y=4)
│   ├── geometria.json     coordenadas en mm (eje, caras, posiciones de sensores, carrera)
│   └── png/               las mismas capas rasterizadas a 4 px/mm (para la versión lite si el SVG pesa)
├── iso6432_d20/           minicilindro ISO 6432 · ø20 · carrera 50 · simple efecto, retorno por muelle
│   ├── camisa.svg, camisa_corte.svg, interior.svg, vastago.svg, sensor_*.svg, geometria.json, png/
│   └── muelle.svg         muelle de retorno dibujado RELAJADO (vástago retraído)
├── ui/                    sistema de diseño: tokens, botones, LEDs, iconos, componentes QML, diseno.html, DISENO.md
├── logos/                 escudos UNAM y FI (azul con fondo transparente y blanco para fondo oscuro)
├── fuentes/               Inter (OFL)
├── Cilindro.qml           componente QML de ejemplo: apila las capas y anima posición, muelle y sensores
├── preview.html           prueba en navegador con deslizador (misma superposición que QML)
├── lamina_preview.png     lámina con los dos cilindros en varias posiciones
└── herramientas/
    ├── gen_cilindros.py   generador paramétrico (cambia carrera, diámetros, colores y regenera todo)
    └── preview.py         compone las capas con cairosvg + PIL (para verificar o hacer sprite sheets)
```

## Sistema de coordenadas

- **1 unidad SVG = 1 mm.** Todas las capas de un mismo cilindro comparten el `viewBox`, así que se apilan sin transformar y se escalan con un único factor `ppm = ancho_px / viewBox_ancho`.
- El `viewBox` es lo bastante ancho para que quepa el vástago totalmente extendido (580×78 mm el grande, 215×40 el mini).
- El vástago está dibujado **retraído**. Para una posición `p ∈ [0,1]`: `x_px = p · carrera_mm · ppm`.
- El muelle está dibujado relajado y se comprime escalándolo en X alrededor de su apoyo delantero:
  `xScale = (L − p·carrera) / L`, con `L` y `x_apoyo` de `geometria.json` (`muelle.longitud`, `muelle.x_apoyo`).
- Sensores: `geometria.json` da el centro (`sensor_SC`, `sensor_SE`) en mm. El sensor se coloca en `x = cx − 17`, `y = cy − 4` con ancho `30·ppm`. SC se enciende con `p ≈ 0`, SE con `p ≈ 1` (o mejor, con los bits reales del PLC).

## Orden de capas

1. `interior.svg` (sólo si usas el corte)
2. `muelle.svg` (sólo minicilindro, sólo con corte)
3. `vastago.svg` (desplazado en X)
4. `camisa_corte.svg` **o** `camisa.svg`
5. `sensor_on/off.svg` ×2
6. Opcional, encima del interior y debajo del vástago: un `Rectangle` semitransparente azul para indicar la cámara presurizada (izquierda del pistón cuando EV_E, derecha cuando EV_C). No va en SVG porque su ancho depende de la posición.

## En QML (PyQt5 5.15 y PySide6)

`Cilindro.qml` ya hace todo lo anterior. Puntos importantes:

- `Image` con `.svg` usa **QtSvg**: pon `sourceSize.width/height` igual al tamaño en pantalla para que rasterice nítido y no re‑rasterice en cada frame.
- Los SVG están limitados a lo que QtSvg soporta (SVG Tiny): gradientes lineales y radiales, `rect`, `circle`, `path`, `text`, `transform`. **No** usan filtros, `pattern`, `mask`, `clipPath` ni CSS. No los "optimices" con herramientas que conviertan estilos a clases CSS, porque QtSvg las ignora.
- Movimiento: `Behavior on x { NumberAnimation … }` o `SpringAnimation` para el rebote al llegar al final de carrera. La velocidad real la dicta el PLC/simulador; la animación sólo alisa el muestreo de 150 ms.
- Con `renderType: Image` a tamaños grandes en la VM (Win7, sin GPU), si va lento usa las capas de `png/` en lugar de los `.svg`.

## Regenerar con otros parámetros

```bash
pip install cairosvg pillow
python herramientas/gen_cilindros.py     # edita BIG / MINI al inicio del archivo (carrera, diámetros, etc.)
python herramientas/preview.py           # lámina de comprobación en /tmp/sheet2.png
```

La carrera del mini (50 mm) es una suposición: cámbiala por la real del P1A que tengas.
