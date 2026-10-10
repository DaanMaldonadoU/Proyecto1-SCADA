import QtQuick 2.15
import "." as UI

// LED con bisel: color ok | activo | alarma | aire | neutro.
Row {
    id: root
    property string color: "activo"
    property bool encendido: false
    property string etiqueta: ""
    property int tam: 22
    spacing: 6
    Image {
        width: root.tam; height: root.tam
        source: UI.Theme.rutaUi + "leds/" + root.color + "_" + (root.encendido ? "on" : "off") + ".svg"
        sourceSize: Qt.size(width, height)
        anchors.verticalCenter: parent.verticalCenter
    }
    Text {
        visible: root.etiqueta !== ""; text: root.etiqueta
        color: root.encendido ? UI.Theme.texto : UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: UI.Theme.etiqueta; weight: Font.Medium }
        anchors.verticalCenter: parent.verticalCenter
    }
}
