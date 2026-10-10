import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "../../assets/assets_cilindros/ui/qml" as UI
import "componentes"

// Ventana de conexión (mds/ARQUITECTURA.md §6.4). Ventana aparte, no modal, mínimo 980×700.
// Columna izquierda: Modo · Gateway · Envío de datos. Columna derecha: OPC DA (solo EMULATE/REAL)
// y consola de los subprocesos. Pie: LED + estado + mensaje y botones Guardar / Conectar / Cerrar.
// Todo el estado vive en `conexion` (ui/conexion.py); aquí solo hay enlaces y llamadas a slots.
ApplicationWindow {
    id: ventana
    objectName: "ventanaConexion"
    title: "Conexión · " + (datosInstitucion.proyecto || "HMI")
    width: 1180
    height: 780
    minimumWidth: 980
    minimumHeight: 700
    color: UI.Theme.fondo
    font.family: UI.Theme.fuente
    modality: Qt.NonModal

    readonly property bool opc: conexion.modo === "EMULATE" || conexion.modo === "REAL"
    readonly property bool conectando: conexion.estado === "conectando"
    readonly property bool conectado: conexion.estado === "conectado"
    readonly property bool enCurso: conectando || conectado
    readonly property bool editable: !enCurso
    readonly property color tonoModo: tonoDeModo(conexion.modo)

    function tonoDeModo(m) {
        return m === "REAL" ? UI.Theme.alarma : (m === "EMULATE" ? UI.Theme.activo : UI.Theme.aire)
    }
    function tonoEstado(e) {
        return e === "conectado" ? UI.Theme.ok : (e === "conectando" ? UI.Theme.activo : (e === "error" ? UI.Theme.alarma : UI.Theme.neutro))
    }
    function ledEstado(e) {
        return e === "conectado" ? "ok" : (e === "conectando" ? "activo" : (e === "error" ? "alarma" : "neutro"))
    }
    function ledProceso(e) {
        return e === "corriendo" ? "ok" : (e === "arrancando" ? "activo" : (e === "error" ? "alarma" : "neutro"))
    }
    function textoProceso(e) {
        return e === "corriendo" ? "en marcha" : (e === "arrancando" ? "arrancando" : (e === "error" ? "con error" : "parado"))
    }
    function tonoOrigen(o) {
        return o === "gateway" ? UI.Theme.aire : (o === "puente" ? UI.Theme.activo : (o === "gemelo" ? UI.Theme.ok : UI.Theme.textoSuave))
    }
    function pedirConexion() {
        if (conexion.modo === "REAL" && conexion.lanzarGateway && !conexion.gatewayExterno)
            dialogoReal.open()
        else
            conexion.conectar()
    }

    Shortcut { sequence: "Escape"; onActivated: ventana.close() }

    ColumnLayout {
        anchors { fill: parent; margins: UI.Theme.espL }
        spacing: UI.Theme.espM

        // ------------------------------------------------------------ título
        RowLayout {
            Layout.fillWidth: true
            spacing: UI.Theme.espM
            Text {
                text: "CONEXIÓN"
                color: UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: UI.Theme.seccion; weight: Font.DemiBold; letterSpacing: 1.4 }
            }
            Text {
                Layout.fillWidth: true
                text: "modo · gateway · OPC DA (RSLinx) · envío de datos al gemelo"
                color: UI.Theme.textoSuave; opacity: 0.8
                elide: Text.ElideRight
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
            }
            Rectangle {
                readonly property color tono: planta.gatewayVivo ? ventana.tonoDeModo(planta.modo) : UI.Theme.neutro
                height: 24; width: tm.implicitWidth + 20; radius: 12
                color: Estilo.alfa(tono, 0.16); border.color: tono
                Text { id: tm; anchors.centerIn: parent
                       text: planta.gatewayVivo ? "GATEWAY " + planta.modo : "SIN GATEWAY"
                       color: parent.tono
                       font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Bold; letterSpacing: 1 } }
            }
        }

        // ------------------------------------------------------------ cuerpo
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: UI.Theme.espM

            // ======================= columna izquierda =======================
            ColumnLayout {
                Layout.preferredWidth: 440
                Layout.minimumWidth: 400
                Layout.maximumWidth: 470
                Layout.fillHeight: true
                spacing: UI.Theme.espM

                // --- MODO
                PanelHmi {
                    titulo: "Modo"
                    compacto: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: 124
                    // Tema de la pantalla (no es un modo del gateway): oscuro o gris ISA-101.
                    accesorios: [
                        Row {
                            spacing: 6
                            Text { text: "pantalla"; color: UI.Theme.textoSuave; anchors.verticalCenter: parent.verticalCenter
                                   font { family: UI.Theme.fuente; pixelSize: Estilo.chico } }
                            Repeater {
                                model: [ { t: "oscuro", e: "Oscuro" }, { t: "gris", e: "Gris ISA-101" } ]
                                Chip { texto: modelData.e; tono: UI.Theme.aire; marcado: planta.tema === modelData.t
                                       onPulsado: planta.fijarTema(modelData.t) }
                            }
                        }
                    ]
                    RowLayout {
                        anchors.fill: parent
                        spacing: 8
                        Repeater {
                            model: [
                                { m: "SIM", a: "Ladder y física simulados en Python. Sin RSLinx ni PLC." },
                                { m: "EMULATE", a: "RSLinx + Emulate 500. El gateway (32 bits) escribe los sensores en I:1." },
                                { m: "REAL", a: "SLC 5/04 físico por RSLinx. Nunca escribe O:2 ni I:1." }
                            ]
                            ConexionTarjetaModo {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                nombre: modelData.m
                                ayuda: modelData.a
                                tono: ventana.tonoDeModo(modelData.m)
                                marcado: conexion.modo === modelData.m
                                habilitado: ventana.editable
                                onPulsado: conexion.modo = modelData.m
                            }
                        }
                    }
                }

                // --- GATEWAY
                PanelHmi {
                    titulo: "Gateway"
                    compacto: true
                    subtitulo: "proceso aparte · ZeroMQ"
                    Layout.fillWidth: true
                    Layout.preferredHeight: ventana.opc ? 196 : 162
                    accesorios: [
                        UI.Led {
                            tam: 12
                            color: ventana.ledProceso(conexion.gatewayEstado)
                            encendido: conexion.gatewayEstado !== "parado"
                            etiqueta: conexion.gatewayPropio || conexion.gatewayEstado !== "parado"
                                      ? "propio · " + ventana.textoProceso(conexion.gatewayEstado)
                                      : (planta.gatewayVivo ? "externo · en línea" : "sin gateway")
                        }
                    ]
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Interruptor {
                                textoIzq: "Usar uno existente"
                                textoDer: "Arrancar aquí"
                                marcado: conexion.lanzarGateway
                                habilitado: ventana.editable && !conexion.gatewayExterno
                                onConmutado: conexion.lanzarGateway = valor
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: conexion.gatewayExterno
                                text: "ya lo arrancó el HMI (--lanzar-gateway)"
                                color: UI.Theme.activo; elide: Text.ElideRight
                                font { family: UI.Theme.fuente; pixelSize: Estilo.micro }
                            }
                            Item { Layout.fillWidth: true; visible: !conexion.gatewayExterno }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "PUB"; anchoEtiqueta: 30; mono: true
                                            texto: conexion.pub; habilitado: ventana.editable
                                            onEditado: conexion.pub = valor }
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "CMD"; anchoEtiqueta: 30; mono: true
                                            texto: conexion.cmd; habilitado: ventana.editable
                                            onEditado: conexion.cmd = valor }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            ConexionCampo {
                                etiqueta: "Periodo"; anchoEtiqueta: 44; anchoCampo: 58; numerico: true
                                texto: String(conexion.periodoMs)
                                habilitado: ventana.editable && conexion.lanzarGateway
                                onEditado: { var v = parseInt(valor); if (!isNaN(v) && v > 0) conexion.periodoMs = v }
                            }
                            Text { text: "ms"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: Estilo.chico } }
                            Item { width: 6 }
                            Text { visible: ventana.opc; text: "Fuente"; color: UI.Theme.textoSuave
                                   font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Medium } }
                            Chip { visible: ventana.opc; texto: "dispositivo"; tono: UI.Theme.aire
                                   marcado: conexion.fuente === "dispositivo"; habilitado: ventana.editable
                                   onPulsado: conexion.fuente = "dispositivo" }
                            Chip { visible: ventana.opc; texto: "caché"; tono: UI.Theme.aire
                                   marcado: conexion.fuente === "cache"; habilitado: ventana.editable
                                   onPulsado: conexion.fuente = "cache" }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "Intérprete"; color: UI.Theme.textoSuave
                                   font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Medium } }
                            Text {
                                Layout.fillWidth: true
                                readonly property bool falta: ventana.opc && conexion.lanzarGateway && !conexion.python32Disponible
                                text: !conexion.lanzarGateway ? "— (gateway externo)"
                                      : (!ventana.opc ? conexion.pythonHmi
                                         : (conexion.python32Disponible ? conexion.python32 + "  (32 bits)"
                                            : (conexion.python32Buscando ? "buscando Python de 32 bits…"
                                               : "sin Python de 32 bits: instala .venv32 (lab\\instalar.bat) o py -3.12-32")))
                                color: falta && !conexion.python32Buscando ? UI.Theme.alarma : UI.Theme.textoSuave
                                elide: Text.ElideMiddle
                                font { family: Estilo.mono; pixelSize: Estilo.chico; weight: falta ? Font.DemiBold : Font.Normal }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: ventana.opc
                            spacing: 8
                            ConexionCampo {
                                Layout.fillWidth: true
                                etiqueta: "Python 32"; anchoEtiqueta: 58; mono: true
                                marcador: "ruta manual (opcional): .venv32 → py -3.12-32"
                                texto: conexion.python32Manual
                                habilitado: ventana.editable
                                onEditado: conexion.python32Manual = valor
                            }
                            BotonMini { texto: "Comprobar"; habilitado: !conexion.python32Buscando; onPulsado: conexion.comprobarPython32() }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }

                // --- ENVÍO DE DATOS
                PanelHmi {
                    titulo: "Envío de datos"
                    compacto: true
                    subtitulo: "gemelo digital"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 150
                    accesorios: [
                        UI.Led {
                            tam: 12
                            visible: conexion.destinoWeb !== "ninguno"
                            readonly property string e: conexion.destinoWeb === "servidor" ? conexion.puenteEstado : conexion.gemeloEstado
                            color: ventana.ledProceso(e)
                            encendido: e !== "parado"
                            etiqueta: (conexion.destinoWeb === "servidor" ? "puente · " : "gemelo · ") + ventana.textoProceso(e)
                        }
                    ]
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: [ { d: "ninguno", t: "Ninguno" }, { d: "local", t: "Gemelo local" }, { d: "servidor", t: "Servidor web" } ]
                                Chip {
                                    texto: modelData.t
                                    tono: UI.Theme.aire
                                    marcado: conexion.destinoWeb === modelData.d
                                    onPulsado: conexion.destinoWeb = modelData.d
                                }
                            }
                            Item { Layout.fillWidth: true }
                            BotonMini {
                                visible: conexion.destinoWeb !== "ninguno" && ventana.enCurso
                                readonly property bool corre: (conexion.destinoWeb === "servidor" ? conexion.puenteEstado : conexion.gemeloEstado) !== "parado"
                                texto: corre ? "Parar envío" : "Arrancar envío"
                                onPulsado: corre ? conexion.pararWeb() : conexion.arrancarWeb()
                            }
                        }

                        // Gemelo local
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: conexion.destinoWeb === "local"
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                ConexionCampo { Layout.fillWidth: true; etiqueta: "Host"; anchoEtiqueta: 34; mono: true
                                                texto: conexion.hostLocal; marcador: "127.0.0.1 o 0.0.0.0 (toda la LAN)"
                                                onEditado: conexion.hostLocal = valor }
                                ConexionCampo { etiqueta: "Puerto"; anchoEtiqueta: 40; anchoCampo: 60; numerico: true
                                                texto: String(conexion.puertoLocal)
                                                onEditado: { var v = parseInt(valor); if (!isNaN(v) && v > 0 && v < 65536) conexion.puertoLocal = v } }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 14
                                ConexionCasilla { texto: "Abrir navegador"; marcado: conexion.abrirNavegador; onConmutado: conexion.abrirNavegador = valor }
                                ConexionCasilla { texto: "Público (sin iniciar sesión)"; marcado: conexion.publicoLocal; onConmutado: conexion.publicoLocal = valor }
                                Item { Layout.fillWidth: true }
                                BotonMini { texto: "Abrir gemelo"; habilitado: conexion.gemeloEstado === "corriendo"; onPulsado: conexion.abrirGemelo() }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: conexion.urlGemelo + "   ·   cuentas de prueba: admin / ingeniero / operador / usuario (contraseña <usuario>1234)"
                                color: UI.Theme.textoSuave; elide: Text.ElideRight
                                font { family: UI.Theme.fuente; pixelSize: Estilo.micro }
                            }
                        }

                        // Servidor web (puente)
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: conexion.destinoWeb === "servidor"
                            spacing: 4
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "WebSocket"; anchoEtiqueta: 66; mono: true
                                            marcador: "wss://…/ws/planta"
                                            texto: conexion.urlServidor; onEditado: conexion.urlServidor = valor }
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "MQTT"; anchoEtiqueta: 66; mono: true
                                            marcador: "opcional: mqtt[s]://usuario:clave@host[:puerto]"
                                            texto: conexion.mqttUrl; onEditado: conexion.mqttUrl = valor }
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "Extras"; anchoEtiqueta: 66; mono: true
                                            marcador: "argumentos extra del puente, p. ej. --hz 10 --planta estacion"
                                            texto: conexion.extrasPuente; onEditado: conexion.extrasPuente = valor }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                UI.Led { tam: 12; color: conexion.claveExiste ? "ok" : "alarma"; encendido: true
                                         etiqueta: conexion.claveExiste ? "clave encontrada · " + conexion.claveResumen : "sin clave del puente" }
                                Text { Layout.fillWidth: true; text: conexion.rutaClave; color: UI.Theme.textoSuave; elide: Text.ElideMiddle
                                       font { family: Estilo.mono; pixelSize: Estilo.micro } }
                            }
                            // Vinculación: la clave del puente se pide al servidor con una cuenta admin del
                            // gemelo (POST /api/puente/clave), o se pega a mano. La contraseña no se guarda.
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                ConexionCampo { id: campoUsuarioWeb; Layout.preferredWidth: 200; etiqueta: "Admin"; anchoEtiqueta: 66
                                                marcador: "usuario del gemelo"
                                                texto: conexion.usuarioServidor; onEditado: conexion.usuarioServidor = valor }
                                ConexionCampo { id: campoClaveWeb; Layout.fillWidth: true; secreto: true; marcador: "contraseña"
                                                onAceptado: botonVincular.pulsado() }
                                BotonMini { id: botonVincular; texto: conexion.vinculando ? "Vinculando…" : "Vincular"; primario: !conexion.claveExiste
                                            habilitado: !conexion.vinculando
                                            onPulsado: { conexion.vincularServidor(campoUsuarioWeb.textoActual(), campoClaveWeb.textoActual()); campoClaveWeb.limpiar() } }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                ConexionCampo { id: campoPegarClave; Layout.fillWidth: true; etiqueta: "o pega"; anchoEtiqueta: 66; mono: true; secreto: true
                                                marcador: "la clave que muestra el servidor (servidor_web clave)" }
                                BotonMini { texto: "Guardar clave"; onPulsado: { conexion.guardarClave(campoPegarClave.textoActual()); campoPegarClave.limpiar() } }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: conexion.mensajeVinculo !== ""
                                text: conexion.mensajeVinculo
                                color: conexion.vinculoOk ? UI.Theme.ok : (conexion.vinculando ? UI.Theme.textoSuave : UI.Theme.alarma)
                                elide: Text.ElideRight
                                font { family: UI.Theme.fuente; pixelSize: Estilo.micro }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: conexion.destinoWeb === "ninguno"
                            text: "Solo el HMI local. El gemelo web se puede arrancar después desde aquí."
                            color: UI.Theme.textoSuave; elide: Text.ElideRight
                            font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
                        }
                        Item { Layout.fillHeight: true }
                        ConexionCasilla {
                            texto: "Habilitar mando web al conectar (gateway --remoto)"
                            marcado: conexion.remotoAlConectar
                            habilitado: ventana.editable
                            onConmutado: conexion.remotoAlConectar = valor
                        }
                    }
                }
            }

            // ======================= columna derecha =======================
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: UI.Theme.espM

                // --- OPC DA (solo EMULATE / REAL)
                PanelHmi {
                    id: panelOpc
                    titulo: "OPC DA · RSLinx"
                    compacto: true
                    subtitulo: "selector de v6.1 · Python de 32 bits"
                    visible: ventana.opc
                    Layout.fillWidth: true
                    Layout.preferredHeight: 330
                    Layout.minimumHeight: 300
                    accesorios: [
                        Row {
                            spacing: 8
                            Text {
                                visible: conexion.buscando
                                anchors.verticalCenter: parent.verticalCenter
                                text: "buscando…"; color: UI.Theme.activo
                                font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.DemiBold }
                                SequentialAnimation on opacity {
                                    running: conexion.buscando; loops: Animation.Infinite
                                    NumberAnimation { to: 0.3; duration: 500 } NumberAnimation { to: 1.0; duration: 500 }
                                }
                            }
                            BotonMini { texto: "Actualizar"; habilitado: !conexion.buscando && conexion.python32Disponible
                                        onPulsado: conexion.buscarServidores() }
                        }
                    ]
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 8
                        // Las cuatro listas de v6.1 con anchos proporcionales calculados a mano (un
                        // Layout.preferredWidth relativo al ancho del propio layout acaba en 0).
                        Item {
                            id: listas
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            readonly property real hueco: 8
                            readonly property real util: Math.max(0, width - 3 * hueco)
                            ConexionLista {
                                id: lServ
                                x: 0; width: listas.util * 0.30; height: listas.height
                                titulo: "SERVIDORES OPC DA"; modelo: conexion.servidores; ocupado: conexion.buscando
                                vacio: conexion.python32Disponible ? "Pulsa «Actualizar»" : "Sin Python de 32 bits"
                                onClicado: { conexion.servidor = texto; conexion.buscarTopics() }
                            }
                            ConexionLista {
                                id: lTop
                                x: lServ.x + lServ.width + listas.hueco; width: listas.util * 0.22; height: listas.height
                                titulo: "TOPICS"; modelo: conexion.topics; ocupado: conexion.buscando
                                vacio: "Elige un servidor"
                                onClicado: { conexion.topic = texto; conexion.buscarArchivos() }
                            }
                            ConexionLista {
                                id: lArch
                                x: lTop.x + lTop.width + listas.hueco; width: listas.util * 0.18; height: listas.height
                                titulo: "ARCHIVOS"; modelo: conexion.archivos; ocupado: conexion.buscando
                                vacio: "Elige un topic"
                                onClicado: conexion.buscarItems(texto)
                            }
                            ConexionLista {
                                x: lArch.x + lArch.width + listas.hueco; width: listas.util * 0.30; height: listas.height
                                titulo: "ITEMS · doble clic = leer"; modelo: conexion.items; ocupado: conexion.buscando; mono: true
                                vacio: "Elige un archivo"
                                onDobleClic: { conexion.itemPrueba = texto; conexion.leerItem(texto) }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "Servidor"; anchoEtiqueta: 50
                                            texto: conexion.servidor; habilitado: ventana.editable
                                            onEditado: conexion.servidor = valor }
                            ConexionCampo { Layout.preferredWidth: 190; etiqueta: "Topic"; anchoEtiqueta: 34; mono: true
                                            texto: conexion.topic; habilitado: ventana.editable
                                            onEditado: conexion.topic = valor }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            ConexionCampo { Layout.fillWidth: true; etiqueta: "Item de prueba"; anchoEtiqueta: 86; mono: true
                                            marcador: "B3:0/0, I:1.0, T4:5.PRE…"
                                            texto: conexion.itemPrueba
                                            onEditado: conexion.itemPrueba = valor
                                            onAceptado: conexion.leerItem(valor) }
                            BotonMini { texto: "Probar lectura"; primario: true
                                        habilitado: !conexion.buscando && conexion.python32Disponible
                                        onPulsado: conexion.leerItem(conexion.itemPrueba) }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            readonly property var r: conexion.resultadoLectura
                            readonly property bool hayLectura: r && r.item !== undefined && r.item !== ""
                            UI.Led { tam: 12; visible: parent.hayLectura; encendido: true; color: parent.r.ok ? "ok" : "alarma" }
                            Text {
                                Layout.fillWidth: true
                                text: parent.hayLectura
                                      ? parent.r.item + "  →  valor = " + parent.r.valor + "   calidad = " + parent.r.calidad
                                      : conexion.mensajeOpc
                                color: parent.hayLectura ? (parent.r.ok ? UI.Theme.ok : UI.Theme.alarma)
                                       : (conexion.mensajeOpc.indexOf("Error") === 0 || conexion.mensajeOpc.indexOf("Sin ") === 0 ? UI.Theme.alarma : UI.Theme.textoSuave)
                                elide: Text.ElideRight
                                font { family: Estilo.mono; pixelSize: Estilo.chico; weight: parent.hayLectura ? Font.DemiBold : Font.Normal }
                            }
                        }
                    }
                }

                // --- CONSOLA
                PanelHmi {
                    titulo: "Consola"
                    compacto: true
                    subtitulo: conexion.consola.total + " líneas"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 160
                    accesorios: [
                        Row {
                            spacing: 6
                            Repeater {
                                model: conexion.origenesConsola
                                Chip {
                                    texto: modelData
                                    tono: ventana.tonoOrigen(modelData)
                                    marcado: conexion.consola.filtro.length === 0 || conexion.consola.filtro.indexOf(modelData) >= 0
                                    onPulsado: conexion.consola.alternarOrigen(modelData)
                                }
                            }
                            BotonMini { texto: "Limpiar"; onPulsado: conexion.limpiarConsola() }
                        }
                    ]
                    Rectangle {
                        anchors.fill: parent
                        color: UI.Theme.fondo
                        radius: 6
                        border.color: UI.Theme.borde
                        ListView {
                            id: consola
                            anchors { fill: parent; margins: 4 }
                            clip: true
                            model: conexion.consola
                            boundsBehavior: Flickable.StopAtBounds
                            property bool seguir: true
                            onContentYChanged: seguir = atYEnd
                            onCountChanged: if (seguir) Qt.callLater(consola.positionViewAtEnd)
                            Component.onCompleted: positionViewAtEnd()
                            ScrollBar.vertical: ScrollBar {
                                policy: ScrollBar.AsNeeded
                                contentItem: Rectangle { implicitWidth: 4; radius: 2; color: UI.Theme.borde }
                            }
                            delegate: Item {
                                width: consola.width
                                height: 19
                                Text {
                                    id: tHora
                                    x: 4; width: 62; anchors.verticalCenter: parent.verticalCenter
                                    text: hora; color: UI.Theme.textoSuave; opacity: 0.8
                                    font { family: Estilo.mono; pixelSize: Estilo.chico }
                                }
                                Text {
                                    id: tOrigen
                                    anchors { left: tHora.right; verticalCenter: parent.verticalCenter }
                                    width: 56
                                    text: origen
                                    color: ventana.tonoOrigen(origen)
                                    font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.Bold; letterSpacing: 0.5 }
                                }
                                Text {
                                    anchors { left: tOrigen.right; right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                    text: linea
                                    elide: Text.ElideRight
                                    color: origen === "hmi" ? UI.Theme.textoSuave : UI.Theme.texto
                                    font { family: Estilo.mono; pixelSize: Estilo.chico }
                                }
                            }
                            Text {
                                anchors.centerIn: parent
                                visible: consola.count === 0
                                text: "Sin líneas"
                                color: UI.Theme.textoSuave
                                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
                            }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ pie
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: UI.Theme.surface
            radius: UI.Theme.radioPanel
            border.color: UI.Theme.borde
            RowLayout {
                anchors { fill: parent; leftMargin: 14; rightMargin: 12 }
                spacing: 10
                UI.Led { tam: 18; color: ventana.ledEstado(conexion.estado); encendido: conexion.estado !== "desconectado" }
                Text {
                    text: conexion.estado.toUpperCase()
                    color: ventana.tonoEstado(conexion.estado)
                    font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Bold; letterSpacing: 1 }
                }
                Rectangle { width: 1; height: 20; color: UI.Theme.borde }
                Text {
                    Layout.fillWidth: true
                    text: conexion.mensaje
                    color: conexion.estado === "error" ? UI.Theme.alarma : UI.Theme.texto
                    elide: Text.ElideRight
                    font { family: UI.Theme.fuente; pixelSize: 12 }
                }
                BotonMini { texto: "Guardar"; onPulsado: conexion.guardar() }
                BotonMini {
                    texto: ventana.enCurso ? "Desconectar" : "Conectar"
                    primario: !ventana.enCurso
                    activo: ventana.enCurso
                    tonoActivo: ventana.conectado ? UI.Theme.ok : UI.Theme.activo
                    implicitWidth: 110
                    onPulsado: ventana.enCurso ? conexion.desconectar() : ventana.pedirConexion()
                }
                BotonMini { texto: "Cerrar"; onPulsado: ventana.close() }
            }
        }
    }

    // ------------------------------------------------------------ confirmación en REAL
    Dialog {
        id: dialogoReal
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 480
        padding: UI.Theme.espL
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: UI.Theme.surface; radius: UI.Theme.radioPanel; border.color: UI.Theme.alarma; border.width: 1 }
        header: Item {
            implicitHeight: 44
            Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: 4; color: UI.Theme.alarma
                        anchors.leftMargin: 0 }
            Text { anchors { left: parent.left; leftMargin: UI.Theme.espL; verticalCenter: parent.verticalCenter }
                   text: "CONECTAR EN MODO REAL"; color: UI.Theme.alarma
                   font { family: UI.Theme.fuente; pixelSize: UI.Theme.seccion; weight: Font.Bold; letterSpacing: 1.2 } }
        }
        contentItem: Text {
            text: "Vas a conectar con el PLC físico (SLC 5/04) por RSLinx, servidor «" + conexion.servidor
                  + "», topic [" + conexion.topic + "].\n\n"
                  + "El HMI no escribe en O:2 ni en I:1 (lo bloquea el gateway); START/STOP/RESET llegan al PLC como "
                  + "pulsos de 300 ms y los preajustes T4:n.PRE / C5:0.PRE sí se escriben. Comprueba que la planta está "
                  + "despejada antes de arrancar la secuencia.\n\n¿Conectar en modo REAL?"
            wrapMode: Text.WordWrap
            color: UI.Theme.texto
            font { family: UI.Theme.fuente; pixelSize: 13 }
            lineHeight: 1.15
        }
        footer: Item {
            implicitHeight: 52
            Row {
                anchors { right: parent.right; rightMargin: UI.Theme.espL; verticalCenter: parent.verticalCenter }
                spacing: 8
                BotonMini { texto: "Cancelar"; onPulsado: dialogoReal.reject() }
                BotonMini { texto: "Conectar en REAL"; activo: true; tonoActivo: UI.Theme.alarma; implicitWidth: 130
                            onPulsado: dialogoReal.accept() }
            }
        }
        onAccepted: conexion.conectar()
    }
}
