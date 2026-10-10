# Sistema de diseño del HMI

Tema oscuro industrial, criterio ISA‑101: en reposo todo es gris, el color aparece sólo para indicar estado.
Tokens en `tokens.json` y en `qml/Theme.qml` (son el mismo contenido; si cambias uno, cambia el otro).

## Carpetas
- `botones/` — botón redondo industrial `start | stop | reset | power` × `normal | hover | pressed | disabled` (viewBox 100×100) y botón plano `plano_*` (160×44) para acciones secundarias.
- `leds/` — LED con bisel `ok | activo | alarma | aire | neutro` × `on | off` (40×40).
- `iconos/` — iconos de línea 24×24 en tres colores: `_claro` (sobre fondo oscuro), `_oscuro`, `_acento` (azul).
- `qml/` — componentes listos: `Theme` (singleton), `Panel`, `BotonIndustrial`, `BotonPlano`, `Led`, `EtapaGrafcet`, `AnilloProgreso`, `Cabecera`, con `qmldir`.
- `diseno.html` — muestra de todo lo anterior y la distribución de pantalla propuesta.
- `../logos/` — escudos UNAM y FI en azul (fondo transparente) y en blanco (para la cabecera oscura). Son los archivos del repositorio público `unamfi/Tesis`; para la versión oficial en vector pide los archivos a Comunicación Social de la FI / identidad institucional UNAM.
- `../fuentes/` — Inter Regular/Medium/SemiBold/Bold (licencia OFL incluida). Cárgala en Python con `QFontDatabase.addApplicationFont(ruta)` antes de crear el motor QML; el fallback es Segoe UI (Win7 lo tiene).

## Significado del color
| Color | Uso |
|---|---|
| Ámbar `#FFB000` | etapa activa, bobina energizada, sensor activo, advertencia |
| Verde `#2ECC71` | en marcha (ACTIVE), calidad Good, escritura confirmada |
| Rojo `#FF4D4F` | STOP, alarma, desconectado, modo REAL (chip) |
| Azul `#3D8BFF` | aire presurizado en las cámaras, acciones del sistema (Conectar) |
| Gris `#7B8794` | inactivo, deshabilitado, sin dato |
| Oro UNAM `#C9A227` | sólo la franja de la cabecera |

## Distribución de la pantalla (1920×1080, rejilla de 12 columnas, huecos de 16 px)
```
┌──────────────────────── Cabecera 72 px: escudos · título · chip de modo · conexión/latencia ────────────────────────┐
│ SINÓPTICO (8 col)                                                           │ GRAFCET (4 col)                        │
│  1A ═══════╗   2A ═══════╗   3A ═══════╗        [zona PLC]                  │  X0 Reposo                             │
│  EV_E1 EV_C1 SC1 SE1  …                                                     │  X1 1A+                                │
│  4A ═════╗ 5A ═════╗  [cadena neumática · cuenta regresiva T4:5]            │  X2 ▮▮▮▮▯▯ espera 1A afuera (activa)   │
│                                                                             │  …  X8 END                             │
├─────────────────────────┬─────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ MANDOS (3)              │ PARÁMETROS (3)          │ CRONOGRAMA (6): Gantt en vivo + anillo C5:0.ACC / PRE            │
│ ● START ● STOP ● RESET  │ T_ESPERA ──●── 1.00 s ✓ │                                                                  │
├────────────────────┬────┴─────────────────────────┴────────────────┬────────────────────────────────────────────────┤
│ MONITOR E/S (4)    │ REGISTRO DE EVENTOS (5)                        │ LATENCIA OPC (3)                               │
└────────────────────┴────────────────────────────────────────────────┴────────────────────────────────────────────────┘
```

## Comportamiento
- Botón industrial: al pulsar escribe el bit virtual con pulso de 300 ms; el anillo de confirmación se enciende cuando el PLC devuelve ACTIVE (START), lo apaga (STOP) o vuelve a X0 (RESET).
- Parámetros: deslizador + campo; el check verde aparece cuando la relectura de `T4:n.PRE` / `C5:0.PRE` coincide con lo escrito.
- Cámaras del cilindro: rectángulo azul al 28 % de opacidad entre la tapa y el pistón, en la cámara que corresponde a la bobina energizada (EV_E → cámara trasera, EV_C → delantera). Se dibuja en QML sobre `interior.svg` y bajo `vastago.svg`.
- Vástago: `Behavior on x` de 150 ms; `SpringAnimation` (spring 3, damping 0.3) sólo al llegar al final de carrera.
- Modo REAL: el chip de la cabecera pasa a rojo y se bloquea el panel "Simular sensores".
- Alarmas: desconexión, items sin calidad Good, tiempo de etapa excedido (ACC > PRE·1.5 sin transición), Stop físico pulsado. Se listan en el registro y la cabecera parpadea en rojo sólo mientras haya una activa.
