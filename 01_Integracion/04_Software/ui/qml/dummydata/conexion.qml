// Generado por ui/herramientas/generar_dummydata.py: no editar a mano.
// Datos de prueba para Qt Design Studio (ui/qml/HMI.qmlproject): conexion (ui/conexion.py, Conexion) con la configuración por defecto

import QtQuick 2.15

QtObject {
    property string modo: "SIM"
    property string servidor: "RSLinx Local OPC Server"
    property string topic: "PROYECTO1_TEST"
    property int periodoMs: 50
    property string fuente: "cache"
    property bool lanzarGateway: true
    property string pub: "tcp://127.0.0.1:5595"
    property string cmd: "tcp://127.0.0.1:5596"
    property string destinoWeb: "ninguno"
    property string urlServidor: "wss://digitaltwinscada.smartsensorslab.com/ws/planta"
    property string mqttUrl: ""
    property string extrasPuente: ""
    property string hostLocal: "127.0.0.1"
    property int puertoLocal: 3002
    property bool abrirNavegador: true
    property bool publicoLocal: false
    property bool remotoAlConectar: false
    property string python32Manual: ""
    property string itemPrueba: "B3:0/0"
    property string usuarioServidor: "daan"
    property string python32: ""
    property bool python32Disponible: false
    property bool python32Buscando: false
    property string estado: "conectado"
    property string mensaje: "Conectado a un gateway en marcha · modo SIM · tcp://127.0.0.1:5595 · para el gemelo elige el destino y pulsa «Arrancar envío»"
    property bool gatewayPropio: false
    property var servidores: ([])
    property var topics: ([])
    property var archivos: ([])
    property string rutaArchivos: ""
    property var items: ([])
    property bool buscando: false
    property var resultadoLectura: ({})
    property string mensajeOpc: ""
    property bool vinculando: false
    property string mensajeVinculo: ""
    property bool vinculoOk: false
    property string pythonHmi: ".venv\\Scripts\\python.exe"
    property string rutaClave: "datos\\puente.clave"
    property string rutaConfig: "datos/conexion.json"
    property var modos: (["SIM", "EMULATE", "REAL"])
    property var fuentes: (["dispositivo", "cache"])
    property var destinos: (["ninguno", "local", "servidor"])
    property var origenesConsola: (["gateway", "puente", "gemelo", "hmi"])
    property int puertoLocalDefecto: 3002
    property string urlServidorDefecto: "wss://digitaltwinscada.smartsensorslab.com/ws/planta"
    property bool autoAbrir: true
    property bool gatewayExterno: false
    property ListModel consola: ListModel {
        property var filtro: ([])
        property int total: 2
        function alternarOrigen(a0) {}
        function limpiar() {}
        ListElement { hora: "23:55:37"; origen: "hmi"; linea: "HMI en .venv\\Scripts\\python.exe (64 bits)" }
        ListElement { hora: "23:55:38"; origen: "hmi"; linea: "estado: conectado — Conectado a un gateway en marcha · modo SIM · tcp://127.0.0.1:5595 · para el gemelo elige el destino y pulsa «Arrancar envío»" }
    }
    property string gatewayEstado: "parado"
    property string puenteEstado: "parado"
    property string gemeloEstado: "parado"
    property bool claveExiste: true
    property string claveResumen: "F5HB… (43 caracteres)"
    property string urlGemelo: "http://127.0.0.1:3002/"
    function abrirGemelo() {}
    function arrancarWeb() {}
    function buscarArchivos() {}
    function buscarItems(a0) {}
    function buscarServidores() {}
    function buscarTopics() {}
    function comprobarPython32() {}
    function conectar() {}
    signal configChanged()
    function desconectar() {}
    function guardar() {}
    function guardarClave(a0) {}
    function leerItem(a0) {}
    function limpiarConsola() {}
    signal listasChanged()
    function pararWeb() {}
    function vincularServidor(a0, a1) {}
    signal vinculoChanged()
}
