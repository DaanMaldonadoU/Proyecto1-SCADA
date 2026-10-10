# Tabla de variables, secuencia y mapa del Ladder

Referencia técnica del PLC para el código del HMI, el gateway y el gemelo digital (Ladder del 18 de septiembre de 2026, `PROYECTO1_TEST.RSS`). La tabla de la sección 3 es la fuente de las direcciones de `core/tags.py`: si el Ladder cambia, se cambian aquí y ahí.

Autor: Daan Yael Maldonado Uriostigue.

---

## 1. Qué es el sistema

- Cinco cilindros. **1A, 2A y 3A** son de doble efecto, los manda el PLC con válvulas 5/2 biestables (dos bobinas por válvula) y cada uno tiene sensores SC (retraído) y SE (extendido).
- **4A y 5A** son de simple efecto con retorno por muelle y forman una cadena **puramente neumática** (memoria EEV3/CEV3, temporizadores neumáticos, rodillos E4A/C4A/E5A/C5A, válvula de simultaneidad). El PLC **no tiene sensores** de 4A/5A: los espera con una ventana de tiempo (`T4:5`, 5 s). Secuencia de la cadena: sale 4A, tras un retardo sale 5A, luego regresan ambos por muelle.
- La secuencia completa se repite N ciclos (por defecto 3) y termina.

## 2. Hardware y software

| Elemento | Detalle |
|---|---|
| Procesador | SLC 5/04, **1747‑L541C**, 16 K, OS401 Serie C FRN 3‑8 (no tiene ONS → se usa OSR) |
| Chasis | 1746‑A4 |
| Ranura 1 | 1746‑IB16 (16 entradas, sink, 24 VDC) |
| Ranura 2 | 1746‑OB16 (16 salidas, source) |
| Ranura 3 | 1747‑SDN registrado por error; conviene eliminarlo en I/O Configuration |
| Programación | RSLogix 500, archivo principal LAD 2 (26 escalones) |
| Emulación | RSLogix Emulate 500, estación 1, Restore Mode on Start |
| Comunicaciones | RSLinx Classic (Gateway/OEM/Single Node; **Lite no tiene OPC**) |
| Driver emulador | `EMU500‑1` (SLC 500 DH485 Emulator), nodo 01 |
| Driver PLC real | **En el laboratorio (verificado el 2026‑10‑03):** Ethernet `AB_ETH‑2` → **1761‑NET‑ENI** en 192.168.1.80 → serie DF1 → canal 0 del SLC. Alternativa sin ENI: RS‑232 DF1 directo (cable 1747‑CP3 o USB‑serial). Tiempos medidos en `mds/LATENCIA.md` |
| Referencia | Tabla equivalente del ControlLogix 1756‑L81E (mismo orden de bits) |

## 3. Tabla de variables (Ladder del 18‑sep, vigente)

Equivalencia directa: `I:1/n ≡ Local:1:I.Data.n`, `O:2/n ≡ Local:2:O.Data.n`. El HMI direcciona por **dirección física**, no por símbolo.

### Entradas (1746‑IB16, ranura 1)

| Símbolo | Dirección | ItemID OPC | Descripción |
|---|---|---|---|
| STOP_1 | I:1/0 | `I:1.0/0` | Pulsador **NC** de paro (=1 en reposo) |
| START_1 | I:1/1 | `I:1.0/1` | Pulsador NA de inicio |
| SC1 / SE1 | I:1/2, I:1/3 | `I:1.0/2`, `I:1.0/3` | 1A retraído / extendido |
| SC2 / SE2 | I:1/4, I:1/5 | `I:1.0/4`, `I:1.0/5` | 2A retraído / extendido |
| SC3 / SE3 | I:1/6, I:1/7 | `I:1.0/6`, `I:1.0/7` | 3A retraído / extendido |

### Salidas (1746‑OB16, ranura 2)

| Símbolo | Dirección | ItemID OPC | Descripción |
|---|---|---|---|
| EV_E1 / EV_C1 | O:2/0, O:2/1 | `O:2.0/0`, `O:2.0/1` | Bobina 1A+ / 1A− |
| EV_E2 / EV_C2 | O:2/2, O:2/3 | `O:2.0/2`, `O:2.0/3` | Bobina 2A+ / 2A− |
| EV_E3 / EV_C3 | O:2/4, O:2/5 | `O:2.0/4`, `O:2.0/5` | Bobina 3A+ / 3A− |

### Internas y de HMI

| Símbolo | Dirección | Acceso HMI | Descripción |
|---|---|---|---|
| First Pass | S:1/15 | — | Primer escaneo tras RUN |
| STARTV | B3:0/0 | Escritura (pulso) | Arranque desde HMI |
| STOPV | B3:0/1 | Escritura (pulso) | Paro desde HMI (en ladder va como XIO) |
| ACTIVE | B3:0/2 | Lectura | Bit de marcha enclavado |
| END | B3:0/3 | Lectura | Fin de los N ciclos |
| RESETV | B3:0/4 | Escritura (pulso) | Reset desde HMI |
| OSR_X7 | B3:2/0 | — | Almacenamiento del OSR del contador |
| X0 … X8 | B3:3/0 … B3:3/8 | Lectura | Etapas del GRAFCET (una sola activa) |
| T_ESPERA | T4:0.PRE … T4:4.PRE | Escritura | Espera por etapa, centésimas de s (100 = 1 s). El HMI escribe **los cinco** |
| T_NEUM | T4:5.PRE | Escritura | Ventana neumática 4A/5A (500 = 5 s) |
| N_CICLOS | C5:0.PRE | Escritura | Número de ciclos (3) |
| C | C5:0.ACC | Lectura | Ciclos completados |
| (monitor) | T4:n.ACC, T4:n/DN | Lectura opcional | Útil para barras de progreso de cada espera |

**Ya no se usa N7.** Versiones anteriores tenían N7:0/N7:1/N7:2 copiados a los preajustes, START/STOP/RESETV en B3:0/13‑15, ACTIVO en B3:1/0, END en B3:2/0 y salidas en O:3. Todo eso es **obsoleto**.

Límites: preajuste máximo 32767 (~327 s). Base de tiempo de todos los TON: 0.01 s.

## 4. Secuencia (GRAFCET nivel 2)

| Etapa | Acción | Transición de salida |
|---|---|---|
| X0 | Reposo; retrae 1A/2A/3A si están extendidos | X0→X1: `SC1·SC2·SC3·(START_1 + STARTV)` |
| X1 | 1A+ (EV_E1) | X1→X2: `SE1` |
| X2 | Espera `T4:0` con 1A afuera; al DN, 1A− | X2→X3: `T4:0/DN·SC1` |
| X3 | Espera `T4:1` con 1A adentro; al DN, 2A+ | X3→X4: `T4:1/DN·SE2` |
| X4 | Espera `T4:2` con 2A afuera; al DN, 2A− | X4→X5: `T4:2/DN·SC2` |
| X5 | Espera `T4:3` con 2A adentro; al DN, 3A+ | X5→X6: `T4:3/DN·SE3` |
| X6 | Espera `T4:4` con 3A afuera; al DN, 3A− | X6→X7: `T4:4/DN·SC3` |
| X7 | Ventana `T4:5` para la cadena 4A/5A; ↑X7 cuenta un ciclo | X7→X1: `T4:5/DN·SC3·(C5:0.ACC < C5:0.PRE)` / X7→X8: `T4:5/DN·(ACC ≥ PRE)` |
| X8 | END := 1 | GS fuerza X0 y reinicia el contador en el escaneo siguiente |

Todas las transiciones llevan además `ACTIVE`.

- **GM (marcha):** `ACTIVE = (START_1 + STARTV + ACTIVE) · STOP_1 · ¬STOPV · ¬END` (END suelta la marcha al terminar los N ciclos, escalón 0000).
- **GS (seguridad):** `S:1/15 + END + (START_1·STOP pulsados) + RESETV → MOV 1 → B3:3, RES C5:0`.
- Con Stop la etapa se congela; al pulsar Start continúa donde estaba. Las salidas **no** dependen de ACTIVE (paro funcional, no de emergencia) y los TON siguen contando durante el paro.
- Salidas (ejemplo 1A): `EV_E1 = X1 + X2·¬T4:0/DN`; `EV_C1 = X2·T4:0/DN + X3·¬T4:1/DN + X0·SE1 + X7·T4:5/DN·SE1`. 2A y 3A siguen la misma estructura. El bit DN garantiza que nunca se energizan las dos bobinas de una válvula.

## 5. Mapa del Ladder (LAD 2, 26 escalones)

| Escalones | Bloque |
|---|---|
| 0000 | GM: ACTIVE |
| 0001 | GS: MOV 1 → B3:3, RES C5:0 |
| 0002 – 0008 | Transiciones X0→X7 (`Xn·ACTIVE·receptividad → OTU Xn, OTL Xn+1`) |
| 0009 – 0010 | Divergencia en O (LES / GEQ) |
| 0011 – 0016 | TON T4:0 … T4:5 |
| 0017 | `X7 → OSR B3:2/0 → CTU C5:0` |
| 0018 – 0023 | Salidas EV_E1 … EV_C3 |
| 0024 | `X8 → END` |
| 0025 | Fin de archivo |
