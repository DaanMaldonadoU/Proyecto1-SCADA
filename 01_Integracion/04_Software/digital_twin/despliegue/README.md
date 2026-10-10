# digital_twin/despliegue — archivos para la PC servidor (Windows)

Guía paso a paso: **`../../mds/DESPLIEGUE_SERVIDOR.md`**. Aquí solo están los archivos que se copian o se ejecutan allí.

| Archivo | Para qué |
|---|---|
| `instalar_servidor.bat` | Crea `.venv-web` (Python 3.13/3.12 de 64 bits), instala `aiohttp` y `paho-mqtt`, muestra la clave del puente, guarda la URL del broker en `digital_twin\datos\mqtt.url` y crea la primera cuenta admin. |
| `servidor.bat` | Arranca el gemelo en `http://127.0.0.1:3002` (acepta los argumentos de `python -m digital_twin.servidor_web`). |
| `cuentas.bat` | Listar, crear, cambiar rol o contraseña, borrar cuentas y leer la auditoría desde la consola. |
| `Caddyfile` | Proxy inverso con HTTPS automático: `digitaltwinscada.smartsensorslab.com → 127.0.0.1:3002` y `broker.smartsensorslab.com → 127.0.0.1:9001` (MQTT sobre WebSocket). Opción A (IP pública). |
| `cloudflared-config.yml` | Lo mismo por Cloudflare Tunnel, sin abrir puertos. Opción B. |
| `mosquitto.conf`, `mosquitto_acl.conf` | Broker Mosquitto: sin anónimos, usuarios `gemelo` y `puente`, ACL por topic, listener 1883 local y 9001 WebSocket local (8883 TLS opcional). |

Los `.bat` llevan finales de línea CRLF y se ejecutan desde cualquier carpeta (hacen `cd` a la raíz del repositorio).
