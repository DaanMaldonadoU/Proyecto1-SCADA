import QtQuick 2.15
import "." as UI

// Barra superior: escudos, título, estado de conexión y modo.
Rectangle {
    id: root
    property string titulo: "Estación electroneumática · SLC 5/04"
    property string subtitulo: "Laboratorio de Control y Automatización · Facultad de Ingeniería, UNAM"
    property string modo: "SIM"                 // SIM | EMULATE | REAL
    property bool conectado: false
    property string calidad: "—"                // "Good 24/24"
    property real latenciaMs: 0
    height: 72; color: UI.Theme.surface
    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: UI.Theme.borde }
    Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: 4; color: UI.Theme.unamOro }

    Image { id: unam; source: "../../logos/unam_blanco.png"; height: 52; fillMode: Image.PreserveAspectFit; mipmap: true
            anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter } opacity: 0.92 }
    Image { id: fi; source: "../../logos/fi_blanco.png"; height: 52; fillMode: Image.PreserveAspectFit; mipmap: true
            anchors { left: unam.right; leftMargin: 10; verticalCenter: parent.verticalCenter } opacity: 0.92 }
    Column {
        anchors { left: fi.right; leftMargin: 20; verticalCenter: parent.verticalCenter } spacing: 2
        Text { text: root.titulo; color: UI.Theme.texto; font { family: UI.Theme.fuente; pixelSize: UI.Theme.titulo; weight: Font.DemiBold } }
        Text { text: root.subtitulo; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: 12 } }
    }
    Row {
        anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter } spacing: 18
        // chip de modo
        Rectangle { height: 26; width: modoT.implicitWidth + 20; radius: 13
                    color: root.modo === "REAL" ? Qt.rgba(1,0.3,0.31,0.18) : (root.modo === "EMULATE" ? Qt.rgba(1,0.69,0,0.16) : Qt.rgba(0.24,0.55,1,0.16))
                    border.color: root.modo === "REAL" ? UI.Theme.alarma : (root.modo === "EMULATE" ? UI.Theme.activo : UI.Theme.aire)
                    Text { id: modoT; anchors.centerIn: parent; text: root.modo; color: parent.border.color
                           font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Bold; letterSpacing: 1 } } }
        Column { spacing: 2; anchors.verticalCenter: parent.verticalCenter
            UI.Led { color: root.conectado ? "ok" : "alarma"; encendido: true; tam: 16
                     etiqueta: root.conectado ? "RSLinx OPC · conectado" : "desconectado" }
            Text { text: root.calidad + "   ·   " + root.latenciaMs.toFixed(0) + " ms"; color: UI.Theme.textoSuave
                   font { family: UI.Theme.fuente; pixelSize: 11 } }
        }
    }
}
