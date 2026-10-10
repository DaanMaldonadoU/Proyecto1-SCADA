import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Tarjeta de modo (SIM azul / EMULATE ámbar / REAL rojo) con texto de ayuda. ISA-101: solo la
// tarjeta elegida toma color.
Rectangle {
    id: root
    property string nombre: ""
    property string ayuda: ""
    property color tono: UI.Theme.aire
    property bool marcado: false
    property bool habilitado: true
    signal pulsado()
    implicitHeight: 78
    radius: 8
    color: marcado ? Estilo.alfa(tono, 0.14) : (area.containsMouse && habilitado ? UI.Theme.surface2 : UI.Theme.fondo)
    border.color: marcado ? tono : UI.Theme.borde
    border.width: marcado ? 1.5 : 1
    opacity: habilitado ? 1 : 0.5
    Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }

    Column {
        anchors { fill: parent; margins: 10 }
        spacing: 4
        Row {
            spacing: 6
            Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                        color: root.marcado ? root.tono : UI.Theme.neutro }
            Text {
                text: root.nombre
                anchors.verticalCenter: parent.verticalCenter
                color: root.marcado ? root.tono : UI.Theme.texto
                font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Bold; letterSpacing: 1 }
            }
        }
        Text {
            width: parent.width
            text: root.ayuda
            wrapMode: Text.WordWrap
            maximumLineCount: 3
            elide: Text.ElideRight
            color: UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: Estilo.micro }
            lineHeight: 1.1
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.habilitado
        cursorShape: Qt.PointingHandCursor
        onClicked: root.pulsado()
    }
}
