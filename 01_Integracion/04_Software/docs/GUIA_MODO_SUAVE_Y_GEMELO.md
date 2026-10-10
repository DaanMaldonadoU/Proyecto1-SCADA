# Modo suave, envío al gemelo y vinculación con el servidor

Guía de la sesión 14 (2026-10-09). Explica tres cosas nuevas del HMI, para quien lo opera en el laboratorio:

1. **Modo suave**: un botón que hace que los pistones y los gráficos se muevan de forma continua aunque las lecturas del PLC lleguen tarde y a saltos.
2. **Envío al gemelo más fluido**: el gemelo digital (local o en el servidor) recibe la misma animación prevista y la sigue entre mensajes.
3. **Vincular el HMI con el servidor del gemelo**: cómo dar la «credencial» que pide el envío de datos al servidor, una sola vez, desde la ventana de conexión.

Contrato técnico (para quien programe): `mds/ARQUITECTURA.md` §6.1 y §6.4, `mds/ENLACE_WEB.md` §3 y §5.3, `mds/LATENCIA.md` (Modo suave).

---

## 1. Modo suave

### 1.1 Qué problema resuelve

En el laboratorio, el enlace serie entre el 1761-NET-ENI y el SLC refresca los datos cada 0,3 s en el caso típico y a veces tarda 1 o 2 s (reintentos DF1; ver `docs/DIAGNOSTICO_CONEXION_PLC.md`). Además, RSLinx refresca cada archivo del PLC por separado (`I:1`, `O:2`, `B3`, `T4`), así que una lectura puede traer la etapa de hace un segundo y las bobinas de ahora. El resultado en pantalla:

- Una carrera de 0,8 s puede **no verse nunca**: la bobina y el sensor de llegada aparecen en la misma lectura y el vástago «salta» de un extremo al otro.
- Las barras de los temporizadores avanzan a tirones y la etapa cambia tarde.
- El cronograma y el gemelo heredan los mismos saltos.

### 1.2 Cómo se activa

En el panel **Sinóptico**, arriba a la derecha, el botón **Suave**. Al pulsarlo:

- El subtítulo del panel cambia a «modo suave · animación prevista».
- El HMI lo recuerda para la próxima vez (`datos\preferencias_hmi.json`).
- Se vuelve a pulsar para apagarlo: la pantalla muestra otra vez lo leído tal cual.

No escribe nada en el PLC ni cambia el gateway: solo cambia cómo se dibuja.

### 1.3 Qué hace

| Situación | Sin modo suave | Con modo suave |
|---|---|---|
| Se lee `EV_E1 = 1` | El vástago empieza a moverse con la duración calibrada | Igual, pero sin saltos al llegar |
| El sensor `SE1` llega antes de que termine la animación | Salta al extremo | Acelera y llega en ≤ 0,25 s |
| Una carrera completa ocurrió entre dos lecturas | No se ve | Se **repone** con una carrera corta (0,35 s) para que se vea que ocurrió |
| Etapa X2 esperando `T4:0` | La barra avanza cuando llega cada lectura | La barra avanza continua; al cumplirse el tiempo, 1A empieza a regresar aunque la lectura aún no lo diga (el PLC enciende `EV_C1` por tiempo, con o sin STOP) |
| La etapa (B3:3) llega más vieja que las bobinas (O:2) | La pantalla muestra estados mezclados | Manda la evidencia más reciente: si `EV_E2` está encendida, el ciclo ya está en X3 con `T4:1` hecho |
| El programa del PLC no tiene `B3:3` (como el del 03-oct) | — | Anima por bobinas y sensores; el subtítulo dice «sin etapa (B3:3): por bobinas» |
| Un cilindro no se mueve (sin aire, atascado) | — | Si el sensor contrario sigue activo más de 3 s + la carrera, manda el sensor y aparece «sin confirmación» junto al cilindro |

Lo que **no** cambia: el monitor de E/S (bits y palabras), el registro de eventos, las alarmas y los parámetros siguen mostrando lo que se leyó del PLC. La etapa resaltada del GRAFCET es la más reciente que se sabe, nunca una transición que no se haya leído: solo se adelanta el DN del temporizador de la etapa en curso, que el PLC activa por tiempo.

### 1.4 Probarlo sin el PLC

El gateway SIM tiene una opción que imita el enlace lento del laboratorio (cada archivo del PLC se refresca cada 0,15–2,4 s, sin posición del vástago, como en REAL):

```bat
.venv\Scripts\python.exe -m gateway --modo SIM --simular-enlace
.venv\Scripts\python.exe ui\app.py
```

En la ventana de conexión: **Usar uno existente** (el gateway ya corre) → Conectar → START. Con el botón **Suave** apagado se ven los saltos; encendido, el movimiento continuo. Con `T_ESPERA = 0,20 s` la diferencia es mayor: sin modo suave se pierden carreras enteras.

Medido en las pruebas (`tests/test_suavizado.py`, planta simulada a través del enlace lento, 3 ciclos):

| | Estimador clásico | Modo suave |
|---|---|---|
| Salto máximo del vástago en un cuadro de 15 ms | 1,00 (extremo a extremo) | 0,06 |
| Carreras vistas con `T_ESPERA = 1 s` | 3 de 3 | 3 de 3 |
| Carreras vistas con `T_ESPERA = 0,2 s` (6 semillas) | 0 a 3 de 3 | 3 de 3 siempre (3–5 repuestas por corrida) |
| Retraso al llegar afuera respecto a la planta | — | −0,1 a 1,1 s |
| Con lecturas al día (sin enlace lento) | — | error medio ≤ 0,005 de carrera |

---

## 2. Envío al gemelo más fluido

El puente que manda los datos al gemelo (`python -m puente`, y el que va dentro de `digital_twin.local`) aplica el mismo modo suave **automáticamente cuando el gateway no da la posición** (modo REAL o `--simular-enlace`). Cada snapshot sale con la posición animada y un bloque `suave` con la velocidad y el destino de cada vástago. El navegador ya no espera al snapshot siguiente: sigue moviendo el vástago con esa velocidad y absorbe las correcciones en ~60 ms. Antes iba 1,5 periodos (≈ 150–300 ms) por detrás para poder interpolar.

- En la página, la pastilla de latencia termina en **«· suave»** cuando está activo, y la etapa, la barra del temporizador y el tiempo de etapa son los previstos (los mismos que en el HMI).
- Para forzarlo o quitarlo: `--suave si` o `--suave no` en el puente (en la ventana de conexión, campo **Extras** del servidor web) o en `digital_twin.local`.
- **Gemelo local** (misma PC): el tramo puente → servidor → navegador tarda ~1 ms; lo que se ve es el PLC más la animación. Es la forma de verlo mejor en el laboratorio.
- **Servidor en internet**: se añade la red (típicamente 50–150 ms). El cuello de botella sigue siendo el enlace serie del PLC; el modo suave hace que no se note a saltos.

---

## 3. Vincular el HMI con el servidor del gemelo («la credencial»)

### 3.1 Qué credencial es

El puente se identifica ante el servidor `https://digitaltwinscada.smartsensorslab.com` con una **clave compartida**: el archivo `datos\puente.clave`. El servidor la genera la primera vez que arranca (en su carpeta `digital_twin\datos\puente.clave`). Sin ese archivo en la PC del HMI, el puente termina con «copia aquí el archivo datos/puente.clave…» y no se envía nada: eso es lo que pasó en la prueba.

No es la contraseña de una cuenta de la web. La clave permite hablar «como planta»: por eso se guarda como una contraseña y nunca se sube al repositorio (`datos/` está en `.gitignore`).

El 2026-10-09 el servidor respondía `{"ok": true, "planta_en_linea": false, "mqtt": null}` en `/api/salud`: está arriba y **sin MQTT**, así que el envío va por WebSocket (`wss://…/ws/planta`, lo que ya trae la ventana por defecto). El campo **MQTT** se deja vacío.

### 3.2 Una sola vez: actualizar el servidor

La vinculación desde el HMI usa una ruta nueva del servidor (`POST /api/puente/clave`). En la PC servidor:

```bat
cd C:\ruta\HMI
git pull
REM reiniciar el servidor del gemelo: cerrar la consola de servidor.bat y volver a abrirla
REM (o, si está como servicio: nssm restart GemeloDigital)
digital_twin\despliegue\servidor.bat
```

Hasta que se actualice, «Vincular» responde «el servidor no tiene /api/puente/clave: actualízalo…»; mientras tanto vale la opción de pegar la clave (§3.4). Comprobado el 2026-10-09: el servidor publicado todavía responde 404 en esa ruta.

**Cuenta admin del servidor: `daan`** (rol admin; confirmado por el autor el 2026-10-09). La cuenta `admin` **no existe** en el servidor: solo existe en el gemelo local (§3.5). La contraseña de `daan` la conoce el autor; no se escribe en el repositorio.

### 3.3 Vincular desde el HMI (recomendado)

1. HMI → **Conexión…** → sección **Envío de datos** → **Servidor web**.
2. **WebSocket**: `wss://digitaltwinscada.smartsensorslab.com/ws/planta` (ya viene puesto). **MQTT**: vacío.
3. **Admin**: ya viene puesto `daan` (la cuenta admin del servidor); al lado, su contraseña. Pulsar **Vincular** (o Enter). El usuario se recuerda en `datos\conexion.json`; la contraseña no.
4. Debe aparecer en verde «vinculado con https://digitaltwinscada.smartsensorslab.com · clave guardada en …» y el LED pasa a **«clave encontrada · abcd… (43 caracteres)»**.
5. **Conectar** (o, si ya estaba conectado, el puente se reinicia solo con la clave nueva). El LED dice «puente · en marcha» y, en la web, «Planta en línea · REAL · WS».

La contraseña no se guarda en ningún sitio: solo se usa para pedir la clave. La clave queda en `datos\puente.clave` y las siguientes veces basta con **Conectar**.

Para que la web pueda **mandar** (START/RESET, parámetros), además hay que habilitar el mando remoto: interruptor **Web** de la franja de mando del HMI, o la casilla «Habilitar mando web al conectar». STOP desde la web pasa siempre.

### 3.4 Alternativas

- **Pegar la clave**: en la PC servidor, `.venv-web\Scripts\python.exe -m digital_twin.servidor_web clave` la muestra; se copia y en el HMI se pega en **o pega** → **Guardar clave**. Funciona también con un servidor sin actualizar.
- **Por consola** en la PC del HMI: `.venv\Scripts\python.exe -m puente.vincular --usuario <admin>` (pide la contraseña sin mostrarla).
- **Copiar el archivo** `digital_twin\datos\puente.clave` del servidor a `datos\puente.clave` del HMI (USB), como antes.

**Si el servidor rechaza la clave (401) aunque «sea la del servidor»** (pasó el 2026-10-09): el servidor la lee **al arrancar** y de **su** carpeta. Herramientas (sesión 14):

- **En la PC servidor:** doble clic en `digital_twin\despliegue\clave_puente.bat`. Dice qué proceso atiende el puerto 3002 y desde qué carpeta, prueba la clave dentro del servidor y por Internet, y explica qué hacer. Si la clave vale, la muestra **completa** para copiarla. Para que el servidor use la clave que ya tiene el HMI: `clave_puente.bat fijar <CLAVE>` y **reiniciar** `servidor.bat`.
- **En la PC del laboratorio:** `lab\clave_puente.bat <CLAVE>` la guarda en `datos\puente.clave` y comprueba que el servidor la acepta (`OK: … acepta la clave`). Sin argumento, prueba la que ya está guardada.

### 3.5 Gemelo local: cuentas

El gemelo local (Envío de datos → **Gemelo local**) no necesita clave ni internet. Tiene sus propias cuentas de prueba, distintas de las del servidor: `admin / admin1234`, `ingeniero / ingeniero1234`, `operador / operador1234`, `usuario / usuario1234`. Con la casilla **Público** se ve sin iniciar sesión (sin mandar). Al revés que en el servidor: allí la cuenta admin es `daan` y `admin` no existe. Por eso en la prueba del laboratorio el intento de entrar como `daan` en el gemelo **local** falló.

### 3.6 Problemas típicos

| Mensaje | Causa y arreglo |
|---|---|
| «usuario o contraseña incorrectos» | Cuenta o contraseña del **servidor** (`daan`, no las del gemelo local). Tras 5 fallos en 5 min el servidor pide esperar. |
| «solo una cuenta admin puede vincular el puente» | La cuenta existe pero no es admin. Usar una admin o cambiarle el rol (`cuentas.bat rol <usuario> admin`). |
| «el servidor no tiene /api/puente/clave…» | El servidor no está actualizado (§3.2). Mientras, pegar la clave (§3.4). |
| «no se pudo conectar con https://…» | Sin internet o el servidor apagado: `https://digitaltwinscada.smartsensorslab.com/api/salud` en un navegador debe responder `{"ok": true…}`. |
| En la consola del puente: «el servidor rechazó la conexión (401): ¿clave correcta?» | La clave guardada no es la del servidor (p. ej. se regeneró). Volver a **Vincular**. |
| La web dice «Planta fuera de línea» | El puente no corre: mirar la consola de la ventana de conexión (filtro «puente»). |
| El HMI dice «Conectado a un gateway en marcha» y el gemelo no arranca | El HMI encontró un gateway ya corriendo (`lab\gateway.bat`, otra ventana). Elige el destino en Envío de datos y pulsa **Arrancar envío**. Desde la sesión 14, **Conectar** también sirve: usa ese gateway (no intenta abrir otro en los mismos puertos) y arranca el envío. |

---

## 4. Fondo gris (ISA-101)

La guía ISA-101 para HMI recomienda una pantalla gris en reposo, con el color reservado para el estado (marcha, alarma, bobina activa) y sin fondos oscuros ni saturados. El HMI tiene ahora dos temas:

- **Oscuro**: el del sistema de diseño, igual que siempre.
- **Gris ISA-101**: fondo gris claro, paneles grises más claros, texto oscuro, escudos azules e iconos oscuros. Los colores de estado son los mismos, solo más oscuros para que contrasten.

Se cambia con el chip **Fondo gris** de la cabecera (junto a «Conexión…») o, en la ventana de conexión, en **Modo → pantalla: Oscuro | Gris ISA-101**. Se recuerda en `datos\preferencias_hmi.json`. Solo cambia la pantalla: no toca el gateway ni el PLC.

## 5. Otros arreglos de esta sesión

- **La simulación se quedaba en X0 tras un RESET** con un cilindro a media carrera. La física del simulador paraba el vástago al apagarse la bobina y X0 → X1 exige SC1·SC2·SC3. Una válvula 5/2 biestable real conserva el carrete y el cilindro termina su carrera: ahora el simulador hace lo mismo. Solo afecta a SIM y EMULATE.
- **El envío al gemelo arranca solo** si el HMI se conecta a un gateway que ya estaba corriendo y hay un destino guardado (Gemelo local o Servidor web). Ya no hace falta «Arrancar envío».
- **Pegar la clave en el HMI:** Conexión… → Envío de datos → **Servidor web** → **o pega** → **Guardar clave**. O, con la contraseña de `daan`, **Vincular**: el servidor la entrega exacta, sin copiarla a mano.

## 6. Archivos nuevos o tocados

| Archivo | Qué |
|---|---|
| `core/suavizado.py` | El modo suave (Python puro; lo usan el HMI y el puente) |
| `ui/cliente.py`, `ui/qml/componentes/Sinoptico.qml`, `Cilindro.qml` | Botón **Suave** y animación en el HMI |
| `gateway/backend_sim.py`, `gateway/__main__.py` | `--simular-enlace` |
| `puente/enlace.py`, `puente/__main__.py`, `digital_twin/local.py` | `--suave auto|si|no` y bloque `suave` |
| `digital_twin/index.html` | Seguimiento predictivo en el navegador |
| `digital_twin/servidor_web/app.py` | `POST /api/puente/clave` (solo admin) |
| `puente/vincular.py` | Pedir y guardar la clave (lo usan la ventana y la consola) |
| `ui/conexion.py`, `ui/qml/VentanaConexion.qml`, `componentes/ConexionCampo.qml` | Vincular / pegar clave en la ventana de conexión |
| `tests/test_suavizado.py`, `tests/test_vincular.py`, `tests/test_ui_planta.py`, `tests/test_ui_conexion.py` | Pruebas |
