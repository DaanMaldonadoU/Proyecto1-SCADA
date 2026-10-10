import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Extensión de UI.Cabecera (72 px, franja oro, escudos) con el estado de la máquina:
// título = datosInstitucion.proyecto, estado ACTIVE/END, etapa, chip de modo, LED de conexión,
// calidad, latencia y reloj. El original del sistema de diseño no se modifica.
Rectangle {
    id: root
    property string titulo: ""
    property string subtitulo: ""
    property bool compacto: false
    readonly property string modo: planta.modo === "" ? "—" : planta.modo
    readonly property bool conectado: planta.conectado
    readonly property bool enMarcha: conectado && planta.bits.ACTIVE === true
    readonly property bool fin: conectado && (planta.bits.END === true || planta.finReciente)
    signal conexionPedida()                       // botón «Conexión…» → Main.abrirConexion()

    height: 72; color: UI.Theme.surface
    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: UI.Theme.borde }
    Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: 4; color: UI.Theme.unamOro }

    Image { id: unam; source: rutaAssets + "logos/unam" + (UI.Theme.sufijoLogo || "_blanco") + ".png"; height: 52; width: 52 * 0.9
            fillMode: Image.PreserveAspectFit; mipmap: true; smooth: true
            sourceSize.height: 104
            anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter } opacity: 0.92 }
    Image { id: fi; source: rutaAssets + "logos/fi" + (UI.Theme.sufijoLogo || "_blanco") + ".png"; height: 52; width: 52
            fillMode: Image.PreserveAspectFit; mipmap: true; smooth: true
            sourceSize.height: 104
            anchors { left: unam.right; leftMargin: 10; verticalCenter: parent.verticalCenter } opacity: 0.92 }
    Rectangle { id: sep; width: 1; height: 40; color: UI.Theme.borde
                anchors { left: fi.right; leftMargin: 18; verticalCenter: parent.verticalCenter } }
    Column {
        anchors { left: sep.right; leftMargin: 18; right: estado.left; rightMargin: 24; verticalCenter: parent.verticalCenter }
        spacing: 3
        Text { width: parent.width; text: root.titulo; color: UI.Theme.texto; elide: Text.ElideRight
               font { family: UI.Theme.fuente; pixelSize: root.compacto ? 19 : UI.Theme.titulo; weight: Font.DemiBold } }
        Text { width: parent.width; text: root.subtitulo; color: UI.Theme.textoSuave; elide: Text.ElideRight
               font { family: UI.Theme.fuente; pixelSize: 12 } }
    }

    Row {
        id: estado
        anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
        spacing: root.compacto ? 14 : 22

        // --- estado de la secuencia
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            height: 30; width: filaEst.implicitWidth + 22; radius: 15
            readonly property color tono: !root.conectado ? UI.Theme.neutro : (root.fin ? UI.Theme.activo : (root.enMarcha ? UI.Theme.ok : UI.Theme.neutro))
            color: Estilo.alfa(tono, root.enMarcha || root.fin ? 0.14 : 0.08)
            border.color: Estilo.alfa(tono, 0.7)
            Row {
                id: filaEst; anchors.centerIn: parent; spacing: 8
                UI.Led { anchors.verticalCenter: parent.verticalCenter; tam: 14
                         color: root.fin ? "activo" : "ok"; encendido: root.enMarcha || root.fin }
                Text { anchors.verticalCenter: parent.verticalCenter
                       text: !root.conectado ? "SIN DATOS" : (root.fin ? "FIN DE CICLOS" : (root.enMarcha ? "EN MARCHA" : "DETENIDA"))
                       color: parent.parent.tono === UI.Theme.neutro ? UI.Theme.textoSuave : parent.parent.tono
                       font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Bold; letterSpacing: 1 } }
                Rectangle { width: 1; height: 16; color: UI.Theme.borde; anchors.verticalCenter: parent.verticalCenter }
                Text { anchors.verticalCenter: parent.verticalCenter
                       text: planta.etapa >= 0 ? "X" + planta.etapa : "X—"
                       color: planta.etapa >= 0 ? UI.Theme.activo : UI.Theme.textoSuave
                       font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Bold } Component.onCompleted: Estilo.cifrasTabulares(this) }
                Text { anchors.verticalCenter: parent.verticalCenter
                       text: planta.etapa >= 0 ? Estilo.num(planta.tEtapa, 1) + " s" : ""
                       color: UI.Theme.textoSuave; visible: text !== ""
                       font { family: UI.Theme.fuente; pixelSize: 12 } Component.onCompleted: Estilo.cifrasTabulares(this) }
            }
        }

        // --- chip de modo (REAL en rojo, EMULATE ámbar, SIM azul)
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            readonly property color tono: root.modo === "REAL" ? UI.Theme.alarma : (root.modo === "EMULATE" ? UI.Theme.activo : (root.modo === "SIM" ? UI.Theme.aire : UI.Theme.neutro))
            height: 26; width: modoT.implicitWidth + 22; radius: 13
            color: Estilo.alfa(tono, 0.16); border.color: tono
            Text { id: modoT; anchors.centerIn: parent; text: root.modo; color: parent.tono
                   font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Bold; letterSpacing: 1 } }
        }

        // --- conexión, calidad y latencia
        Column {
            anchors.verticalCenter: parent.verticalCenter; spacing: 4
            UI.Led { color: root.conectado ? "ok" : "alarma"; encendido: true; tam: 16
                     etiqueta: root.conectado ? (planta.modo === "SIM" ? "Gateway SIM · conectado" : "RSLinx OPC · conectado")
                                              : (planta.gatewayVivo ? "PLC sin lectura" : "Gateway desconectado") }
            Row {
                spacing: 6
                Text { text: planta.calidadTexto; color: planta.calidadOk ? UI.Theme.textoSuave : (root.conectado ? UI.Theme.activo : UI.Theme.textoSuave)
                       font { family: UI.Theme.fuente; pixelSize: 11 } Component.onCompleted: Estilo.cifrasTabulares(this) }
                Text { text: "·"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: 11 } }
                Text { text: root.conectado ? Estilo.num(planta.latenciaMs, 1) + " ms" : "— ms"; color: UI.Theme.textoSuave
                       font { family: UI.Theme.fuente; pixelSize: 11 } Component.onCompleted: Estilo.cifrasTabulares(this) }
            }
        }

        // --- ventana de conexión (modo, gateway, OPC DA, envío de datos)
        // Tema de pantalla: fondo gris claro (ISA-101) u oscuro; se recuerda (planta.tema).
        Chip {
            anchors.verticalCenter: parent.verticalCenter
            texto: "Fondo gris"
            tono: UI.Theme.aire
            marcado: planta.tema === "gris"
            onPulsado: planta.fijarTema(planta.tema === "gris" ? "oscuro" : "gris")
        }
        BotonMini {
            anchors.verticalCenter: parent.verticalCenter
            texto: "Conexión…"
            primario: !root.conectado
            onPulsado: root.conexionPedida()
        }

        // --- reloj
        Column {
            anchors.verticalCenter: parent.verticalCenter; spacing: 1
            visible: !root.compacto || root.width > 1340
            Text { id: reloj; anchors.right: parent.right; color: UI.Theme.texto
                   font { family: UI.Theme.fuente; pixelSize: 18; weight: Font.DemiBold } Component.onCompleted: Estilo.cifrasTabulares(this) }
            Text { id: fecha; anchors.right: parent.right; color: UI.Theme.textoSuave
                   font { family: UI.Theme.fuente; pixelSize: 11 } }
            Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true
                    onTriggered: { var d = new Date(); reloj.text = Qt.formatTime(d, "HH:mm:ss"); fecha.text = Qt.formatDate(d, "dd/MM/yyyy") } }
        }
    }
}
