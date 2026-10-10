import QtQuick 2.15
import QtQuick.Shapes 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Casilla de verificación con texto (ventana de conexión). Mismo trazo que Check.qml, pero
// interactiva: emite conmutado(valor) y el padre decide (p. ej. conexion.abrirNavegador = valor).
Item {
    id: root
    property string texto: ""
    property bool marcado: false
    property bool habilitado: true
    property color tono: UI.Theme.aire
    signal conmutado(bool valor)
    implicitWidth: fila.implicitWidth
    implicitHeight: 22
    opacity: habilitado ? 1 : 0.45

    Row {
        id: fila
        spacing: 7
        anchors.verticalCenter: parent.verticalCenter
        Rectangle {
            id: caja
            width: 16; height: 16; radius: 4
            anchors.verticalCenter: parent.verticalCenter
            color: root.marcado ? Estilo.alfa(root.tono, 0.2) : UI.Theme.fondo
            border.color: root.marcado ? root.tono : (area.containsMouse ? UI.Theme.textoSuave : UI.Theme.borde)
            border.width: 1
            Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }
            Shape {
                anchors.fill: parent
                visible: root.marcado
                antialiasing: true
                ShapePath {
                    strokeColor: root.tono; strokeWidth: 2; fillColor: "transparent"
                    capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                    startX: caja.width * 0.26; startY: caja.height * 0.52
                    PathLine { x: caja.width * 0.44; y: caja.height * 0.70 }
                    PathLine { x: caja.width * 0.76; y: caja.height * 0.32 }
                }
            }
        }
        Text {
            text: root.texto
            anchors.verticalCenter: parent.verticalCenter
            color: root.marcado ? UI.Theme.texto : UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium }
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.habilitado
        cursorShape: Qt.PointingHandCursor
        onClicked: root.conmutado(!root.marcado)
    }
}
