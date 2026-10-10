import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Conmutador de dos posiciones con texto a cada lado (p. ej. Manual | Auto).
Item {
    id: root
    property bool marcado: false
    property string textoIzq: ""
    property string textoDer: ""
    property bool habilitado: true
    property color tono: UI.Theme.aire
    signal conmutado(bool valor)
    implicitWidth: fila.implicitWidth; implicitHeight: 22
    opacity: habilitado ? 1 : 0.45
    Row {
        id: fila; spacing: 8; anchors.verticalCenter: parent.verticalCenter
        Text { text: root.textoIzq; visible: text !== ""; anchors.verticalCenter: parent.verticalCenter
               color: !root.marcado ? UI.Theme.texto : UI.Theme.textoSuave
               font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium } }
        Rectangle {
            width: 36; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter
            color: root.marcado ? Estilo.alfa(root.tono, 0.35) : UI.Theme.surface2
            border.color: root.marcado ? root.tono : UI.Theme.borde
            Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }
            Rectangle {
                width: 14; height: 14; radius: 7; y: 3
                x: root.marcado ? parent.width - width - 3 : 3
                color: root.marcado ? UI.Theme.texto : UI.Theme.textoSuave
                Behavior on x { NumberAnimation { duration: UI.Theme.animRapida; easing.type: Easing.OutQuad } }
            }
        }
        Text { text: root.textoDer; visible: text !== ""; anchors.verticalCenter: parent.verticalCenter
               color: root.marcado ? UI.Theme.texto : UI.Theme.textoSuave
               font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium } }
    }
    MouseArea { anchors.fill: parent; enabled: root.habilitado; cursorShape: Qt.PointingHandCursor
                onClicked: root.conmutado(!root.marcado) }
}
