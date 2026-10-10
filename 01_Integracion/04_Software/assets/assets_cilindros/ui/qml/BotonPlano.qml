import QtQuick 2.15
import "." as UI

// Botón rectangular secundario (Aceptar, Conectar, Mapeo…).
Rectangle {
    id: root
    property string texto: "Aceptar"
    property bool habilitado: true
    property bool primario: false
    signal pulsado()
    implicitWidth: Math.max(96, t.implicitWidth + 32); implicitHeight: 38
    radius: UI.Theme.radioControl
    color: !habilitado ? UI.Theme.surface : (area.pressed ? Qt.darker(base, 1.25) : (area.containsMouse ? Qt.lighter(base, 1.08) : base))
    readonly property color base: primario ? UI.Theme.aire : UI.Theme.surface2
    border.color: primario ? Qt.lighter(UI.Theme.aire, 1.1) : UI.Theme.borde; border.width: 1
    Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }
    Text {
        id: t; anchors.centerIn: parent; text: root.texto
        color: root.habilitado ? UI.Theme.texto : UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: UI.Theme.cuerpo; weight: Font.Medium }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; enabled: root.habilitado; onClicked: root.pulsado() }
}
