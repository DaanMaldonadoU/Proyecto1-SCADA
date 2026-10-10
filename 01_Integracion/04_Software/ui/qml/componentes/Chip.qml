import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Chip conmutable (filtros del registro, selector de fuente). `tono` = color de estado del tema.
Rectangle {
    id: root
    property string texto: ""
    property bool marcado: false
    property color tono: UI.Theme.neutro
    property bool habilitado: true
    signal pulsado()
    implicitWidth: t.implicitWidth + 18; implicitHeight: 22
    radius: height / 2
    color: marcado ? Estilo.alfa(tono, 0.16) : (area.containsMouse ? UI.Theme.surface2 : "transparent")
    border.color: marcado ? tono : UI.Theme.borde
    border.width: 1
    opacity: habilitado ? 1 : 0.45
    Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }
    Text {
        id: t; anchors.centerIn: parent; text: root.texto
        color: root.marcado ? root.tono : UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.DemiBold; letterSpacing: 0.4 } Component.onCompleted: Estilo.cifrasTabulares(this)
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; enabled: root.habilitado; cursorShape: Qt.PointingHandCursor; onClicked: root.pulsado() }
}
