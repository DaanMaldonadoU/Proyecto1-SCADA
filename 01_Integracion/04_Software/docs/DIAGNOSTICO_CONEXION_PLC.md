# Diagnóstico de la conexión HMI ⇄ PLC real (SLC 5/04)

Fecha: 2026-10-03 · Topic RSLinx: `PROYECTO1_TEST` · Servidor OPC: `RSLinx Local OPC Server` / `RSLinx OPC Server`

> **Procedencia.** Informe escrito en la PC del laboratorio sobre la copia del proyecto que **sí se conectó al SLC 5/04**. Se trajo al repositorio en la sesión 10 (2026-10-09, `bitacora/2026-10-09_sesion-10.md`) junto con los cambios de código de la sección 10. Se conserva tal cual como registro de ese día; lo que cambió después: `lab\gateway.bat` y la ventana de conexión ya usan `PROYECTO1_TEST` por defecto (§8), el puente web espera 2 s como el HMI, y hay pruebas sin COM en `tests/test_backend_opc.py`. Resumen para el contexto técnico: `mds/LATENCIA.md`. (En la sesión 10 se añadieron a `gateway/backend_opc.py` el rechazo de escrituras por elemento y una segunda lectura de validación; en la sesión 14 se **retiraron** a pedido del autor, porque nunca se probaron con el PLC: el archivo vuelve a ser el de este informe.)

## 1. Síntomas reportados

- Al pulsar **START** en el HMI, el bit no cambiaba en RSLogix 500 (no se podía escribir en el PLC).
- La versión `old/hmi_estacion.py` se comportaba algo mejor.
- Latencia alta en la pantalla del HMI.

## 2. Ruta de comunicación real

Leída del registro de RSLinx (`Project\Default\PROYECTO1_TEST`) y de la página web del equipo en 192.168.1.80:

```
HMI (64 bits) ──ZeroMQ──► gateway (Python 32 bits, OpenOPC) ──COM──► RSLinx Classic
   ──Ethernet (driver AB_ETH-2)──► 1761-NET-ENI (192.168.1.80) ──serie DF1──► canal 0 del SLC 5/04
```

| Ajuste del topic | Valor | Comentario |
|---|---|---|
| `Target` | `AB_ETH-2` → 192.168.1.80 | Es un 1761-NET-ENI, no Ethernet nativo |
| `Poll` (Polled Messages) | **1000 ms** | Sondeo por defecto del topic |
| `OptimizePokes` | 0 | Correcto (escrituras sin agrupar) |
| `UpdateAfterPoke` | 1 | Correcto |
| `Timeout` | 5 s | |

El PLC se comunica por un **enlace serie DF1** (máximo 19200 baudios en el canal 0 del SLC 5/04) a través del ENI. Todo lo que habla con el PLC (gateway, RSLogix online) comparte ese enlace.

## 3. Problema 1 — Direcciones inexistentes que dejaban B3:0 sin leer

### Medición

`gateway.diagnostico_opc --topic PROYECTO1_TEST --modo REAL` con el programa que tenía el PLC en ese momento:

| Item | Lectura en grupo | Lectura individual |
|---|---|---|
| `I:1.0`, `O:2.0`, `C5:0.*` | Good | Good |
| `B3:0` | **Bad** | Good (valor 8) |
| `B3:3` | Bad | **Bad** (no existe: B3 tenía 1 palabra) |
| `T4:0`…`T4:3` | **Bad** | Good |
| `T4:4`, `T4:5` | Bad | **Bad** (no existen: T4 tenía 4 temporizadores) |

Resultado con el gateway sin corregir: **4 de 24 items en Good**, B3:0 nunca se leía (ni ACTIVE, ni END, ni la confirmación de STARTV).

### Causa

RSLinx agrupa en **un solo paquete DF1 los items del mismo archivo** (B3, T4…). Si un elemento del paquete no existe en el PLC, el paquete entero vuelve con calidad Bad, también los elementos que sí existen. Además:

- La contaminación afecta a **todos los clientes de RSLinx**, no solo al gateway (se comprobó: un grupo con `B3:3` hizo fallar la lectura de `B3:0` desde otro programa).
- Si el gateway se cierra a la fuerza (`kill`), sus grupos siguen vivos en RSLinx unos **6 minutos** (hasta que DCOM los libera), y la contaminación dura ese tiempo. Se midió: B3:0 volvió a leerse Good ~7 min después de matar el gateway.

### Cambio

`gateway/backend_opc.py`:

- Al conectar, `_validar_direcciones()` lee toda la tabla una vez desde el PLC. Lo que no sale Good se prueba **elemento por elemento** (cada uno en su propia lectura, después de eliminar el grupo de validación para que no contamine) y lo que sigue Bad se **quita del sondeo** (`faltantes`).
- Si **ningún** item sale Good, la conexión falla con un mensaje claro (PLC sin comunicación o topic mal configurado) y el servidor reintenta.
- Las escrituras a direcciones inexistentes se rechazan con «X no existe en el PLC (revisa el programa descargado)».

`gateway/servidor.py`: al conectar, si faltan elementos, publica una **alarma** en el HMI: «El PLC no tiene B3:3, T4:4, T4:5…».

### Resultado

Con el gateway corregido: **17 de 17 items en Good**, B3:0 se lee y la escritura se ve de vuelta en el snapshot.

## 4. Problema 2 — Órdenes que el HMI daba por perdidas

### Medición

Con lectura desde el dispositivo, cada ciclo del gateway tardaba ~1,2 s (lectura de 1221 ms) y la orden de pulso **no respondía en 500 ms**: el HMI mostraba «sin respuesta del gateway», aunque el PLC recibía la orden más tarde.

Tiempos de escritura OPC medidos (`opc.write` de un bit):

| Situación | Tiempo de escritura |
|---|---|
| Sin grupos de lectura activos | 73–98 ms (un caso de 959 ms) |
| Con grupo de caché a 100 ms | 165–1177 ms |
| Con grupo de caché a 250 ms | 182–1177 ms |

### Cambio

`core/protocolo.py`: `TIMEOUT_CMD_MS` pasa de **500 a 2000 ms**. La orden puede esperar a que termine la lectura en curso, y una escritura por DF1 tarda de 100 a 1200 ms. El hilo de órdenes del HMI es independiente, así que el timeout más largo no congela la pantalla.

### Resultado

Pulso respondido con `ok: True` en 929 ms y bit visible en el snapshot a los 1043 ms.

## 5. Problema 3 — Lectura lenta desde el dispositivo

### Medición

Grupo de 15 items válidos, 10 lecturas:

| Fuente | Tiempo por lectura |
|---|---|
| `dispositivo` (`source="device"`) | 200–2238 ms (valores: 1221, 202, 1215, 1217, 202, 1220, 1232, 2238, 205, 200) |
| `cache` (`source="cache"`) | **6–8 ms** |

### Cambio

La fuente **caché** pasa a ser la opción por defecto: RSLinx sondea el PLC por su cuenta y el gateway no se bloquea esperando al enlace serie.

- `gateway/backend_opc.py` y `gateway/__main__.py`: `fuente="cache"` por defecto.
- `ui/conexion.py`: valor por defecto y de respaldo `"cache"`.
- `datos/conexion.json`: `"fuente": "cache"`.
- `tests/test_ui_conexion.py`: actualizado al nuevo valor por defecto.

### Resultado

Gateway: lectura de ~6 ms, ~9 snapshots/s (124 en 14 s), frente a 19 en 16 s antes del cambio.

## 6. Problema 4 — La latencia restante está en el enlace serie ENI ↔ SLC

Con el código ya corregido, el gateway lee la caché en 6 ms, pero **la caché de RSLinx solo se actualiza cuando el PLC contesta**. Se midió cada cuánto cambia `S:4` (reloj libre del SLC, cuenta cada 10 ms) en la caché.

### Refresco real de la caché

| Update pedido | Mediana | p90 | Máximo |
|---|---|---|---|
| 100 ms | 329–335 ms | 1305–1357 ms | 1357 ms |
| 50 ms | 294–403 ms | 1240–1833 ms | 1833 ms |
| 20 ms | 1212–1367 ms | 1265–2359 ms | 2359 ms |

Pedir más rápido **empeora** el refresco: el enlace se satura.

### Según cuántos archivos se leen (update 100 ms)

| Grupo | Mediana (medición 1) | Mediana (medición 2, RSLogix offline) |
|---|---|---|
| S, I, O, B3, T4 (5 archivos) | 379 ms | 311 ms |
| S, I, O, B3 (4 archivos) | 330 ms | 1286 ms |
| Solo S (1 archivo) | 342 ms | 896 ms |

Leer menos archivos **no mejora** el refresco: el cuello de botella no es la cantidad de datos.

### Lectura individual desde el dispositivo

```
417, 2416, 411, 1426, 404, 1422, 1214, 409, 2441, 2430 ms
```

Red hasta el ENI: ping de **1 ms**.

### Interpretación

- Los tiempos salen en **escalones de ~1 s exacto** (≈410 → ≈1420 → ≈2430 ms). Eso corresponde a **reintentos DF1**: un paquete se pierde o llega mal y se repite al vencer el *ACK timeout*, que por defecto es 1 s (50 × 20 ms).
- La base de ~400 ms por transacción es varias veces lo esperable para un paquete pequeño a 19200 baudios (~30–50 ms). Puede deberse a una velocidad más baja o a errores en el enlace.
- Poner RSLogix offline no cambió el resultado, y solo RSLinx tiene conexión TCP con el ENI desde esta PC.

**Conclusión:** la latencia que queda viene del **enlace serie entre el 1761-NET-ENI y el canal 0 del SLC**, no del HMI ni del gateway. Si se eliminan los reintentos, el refresco debería bajar a ~100–150 ms sin tocar más código.

## 7. Recomendaciones pendientes (en orden)

1. **RSLogix 500 → Channel Status (canal 0)**, online: si suben los contadores de *ACK timeouts*, *NAKs* o *retries*, el diagnóstico queda confirmado.
2. **RSLogix 500 → Channel Configuration → Chan. 0 – System**: DF1 Full Duplex, **19200**, Error Detection **CRC**, Embedded Responses Auto/Enabled, Duplicate Packet Detect activado. Descargar si se cambia algo.
3. **Configuración del ENI** (utilidad ENI/ENIW): velocidad serie igual a la del canal 0 o en automático. Apagar y encender el ENI después de cambiar la velocidad del canal 0.
4. **Cable ENI ↔ canal 0** (1761-CBL-AM00 / HM02) bien asentado y en buen estado.
5. **Que no haya otra computadora** conectada al mismo ENI (192.168.1.80) con RSLinx: todas comparten el enlace serie.
6. **Topic en RSLinx → Data Collection → Polled Messages**: está en 1000 ms; probar con 100 ms.

Mejoras de código y ladder, que conviene hacer **después** de resolver los reintentos (con el enlace saturado se midió poca ganancia):

- **Una sola transacción de lectura:** en el ladder, `MOV I:1.0 B3:4` y `MOV O:2.0 B3:5`. El gateway leería entradas, salidas, bits del HMI y etapas en un solo bloque B3:0…B3:5.
- **Temporizadores en el grupo lento**, con el avance de `T4:n.ACC` calculado entre lecturas para que las barras de progreso sigan suaves.
- **Botones de una sola escritura:** que el ladder borre STARTV/STOPV/RESETV (OTU) después de usarlos, en lugar de que el HMI escriba 1 y luego 0.
- **Cierre ordenado del gateway:** escribir el 0 de los pulsos pendientes al cerrarse, para que un bit no se quede en 1. En Windows el HMI termina el gateway con `kill`, lo que además deja sus grupos en RSLinx ~6 min.

## 8. Otras observaciones

- **El programa que tenía el PLC al empezar no coincidía con la tabla de `docs/TABLA_DE_VARIABLES.md`:** B3 con 1 palabra, T4 con 4 temporizadores y preajustes en 0 (`T4:3.PRE = 3`). Durante la prueba, un pulso en **B3:0/1** (STOPV según la tabla) **hizo avanzar los bits 4 a 9 de B3:0** y luego el PLC volvió al reposo (B3:0 = 9). En ese programa, ese bit tenía otra función. Las salidas O:2.0 marcaban 10752 antes y después, pero no se vigilaron durante la secuencia.
- **Escrituras hechas en el PLC durante el diagnóstico:** solo en B3:0/1. Unas 20 escrituras de 0 sobre un bit que ya valía 0, y tres pulsos 1 → 0 de ~300 ms (≈12:57, ≈12:59 y 13:05:29).
- **B3:0/0 (STARTV) estaba en 1 fijo** cuando se revisó; no lo puso el diagnóstico.
- Después de estos cambios, el HMI funciona contra el PLC (confirmado en el laboratorio).
- `datos/conexion.json` tenía el modo guardado en **SIM**: en SIM los botones no llegan al PLC. Hay que elegir REAL en la ventana de conexión.
- `lab\gateway.bat` usa por defecto el topic `PROYECTO1_REAL`, que no existe en este RSLinx; el que existe es `PROYECTO1_TEST`.

## 9. Pruebas

- Suite completa: `.venv\Scripts\python.exe -m pytest -q` → **154 passed, 1 skipped**.
- Gateway corregido contra el PLC real (modo REAL, fuente caché, cliente ZeroMQ de prueba): 17/17 items Good, lectura ~6 ms, pulso respondido `ok` en 929 ms, bit visible en 1043 ms, cierre limpio del gateway.
- Todas las mediciones de la sección 6 fueron **de solo lectura**.

## 10. Archivos modificados

| Archivo | Cambio |
|---|---|
| `gateway/backend_opc.py` | Validación de direcciones al conectar (`_validar_direcciones`, `faltantes`, `elementos_faltantes`), lectura y escritura sin las direcciones inexistentes, fuente `cache` por defecto, grupo lento vacío tolerado |
| `gateway/servidor.py` | Alarma al HMI con los elementos que faltan en el PLC |
| `gateway/__main__.py` | `--fuente` por defecto `cache` |
| `core/protocolo.py` | `TIMEOUT_CMD_MS` de 500 a 2000 ms |
| `ui/conexion.py` | Fuente por defecto `cache` |
| `datos/conexion.json` | `"fuente": "cache"` |
| `tests/test_ui_conexion.py` | Valor por defecto esperado `cache` |
