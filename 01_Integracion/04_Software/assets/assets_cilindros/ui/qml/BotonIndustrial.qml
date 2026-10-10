import QtQuick 2.15
import "." as UI

// Botón redondo industrial: tipo start | stop | reset | power. Cambia de SVG según el estado.
// `confirmado` enciende un anillo cuando el PLC devuelve el bit (STARTV → ACTIVE, etc.).
Item {
    id: root
    property string tipo: "start"
    property string etiqueta: ""
    property bool   confirmado: false
    property bool   habilitado: true
    signal pulsado()

    implicitWidth: 96; implicitHeight: 96 + (etiqueta !== "" ? 22 : 0)

    readonly property string estado: !habilitado ? "disabled" : (area.pressed ? "pressed" : (area.containsMouse ? "hover" : "normal"))

    // anillo de confirmación
    Rectangle {
        anchors.centerIn: img; width: img.width * 0.96; height: width; radius: width / 2
        color: "transparent"; border.width: 3
        border.color: root.tipo === "stop" ? UI.Theme.alarma : (root.tipo === "reset" ? UI.Theme.activo : UI.Theme.ok)
        opacity: root.confirmado ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: UI.Theme.animNormal } }
    }
    Image {
        id: img
        width: 96; height: 96
        anchors.horizontalCenter: parent.horizontalCenter
        source: UI.Theme.rutaUi + "botones/" + root.tipo + "_" + root.estado + ".svg"
        sourceSize: Qt.size(width, height)
        scale: area.pressed ? 0.97 : 1.0
        Behavior on scale { NumberAnimation { duration: UI.Theme.animRapida } }
    }
    Text {
        anchors { top: img.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        text: root.etiqueta; color: root.habilitado ? UI.Theme.texto : UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: UI.Theme.etiqueta; weight: Font.Medium; letterSpacing: 0.8 }
    }
    MouseArea {
        id: area; anchors.fill: img; hoverEnabled: true; enabled: root.habilitado
        onClicked: root.pulsado()
    }
}
