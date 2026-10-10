import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Lista de una columna con título (selector OPC de v6.1: servidores → topics → archivos → items).
// Delegados de una línea, selección resaltada; clicado(texto) al pulsar, dobleClic(texto) al doble clic.
Rectangle {
    id: root
    property string titulo: ""
    property var modelo: []                    // lista de cadenas (conexion.servidores, …)
    property int seleccion: -1
    property string vacio: "—"                 // texto cuando no hay elementos
    property bool ocupado: false               // búsqueda en curso
    property bool mono: false
    signal clicado(string texto)
    signal dobleClic(string texto)
    color: UI.Theme.fondo
    radius: 6
    border.color: UI.Theme.borde
    border.width: 1
    onModeloChanged: seleccion = -1

    Text {
        id: cab
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 6 }
        text: root.titulo + (root.modelo.length > 0 ? "  ·  " + root.modelo.length : "")
        color: UI.Theme.textoSuave
        elide: Text.ElideRight
        font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.DemiBold; letterSpacing: 0.8 }
        Component.onCompleted: Estilo.cifrasTabulares(this)
    }
    Rectangle { anchors { left: parent.left; right: parent.right; top: cab.bottom; topMargin: 4; margins: 1 } height: 1; color: UI.Theme.borde }

    ListView {
        id: lista
        anchors { left: parent.left; right: parent.right; top: cab.bottom; bottom: parent.bottom; topMargin: 6; leftMargin: 2; rightMargin: 2; bottomMargin: 2 }
        clip: true
        model: root.modelo
        boundsBehavior: Flickable.StopAtBounds
        currentIndex: root.seleccion
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle { implicitWidth: 4; radius: 2; color: UI.Theme.borde }
        }
        delegate: Rectangle {
            width: lista.width
            height: 22
            radius: 3
            readonly property bool elegido: index === root.seleccion
            color: elegido ? Estilo.alfa(UI.Theme.aire, 0.2) : (area.containsMouse ? UI.Theme.surface2 : "transparent")
            Rectangle { width: 2; height: parent.height - 6; radius: 1; x: 1; anchors.verticalCenter: parent.verticalCenter
                        color: UI.Theme.aire; visible: parent.elegido }
            Text {
                anchors { left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 6; verticalCenter: parent.verticalCenter }
                text: modelData
                elide: Text.ElideMiddle
                color: parent.elegido ? UI.Theme.texto : UI.Theme.textoSuave
                font { family: root.mono ? Estilo.mono : UI.Theme.fuente; pixelSize: 12; weight: parent.elegido ? Font.DemiBold : Font.Normal }
            }
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { root.seleccion = index; root.clicado(modelData) }
                onDoubleClicked: { root.seleccion = index; root.dobleClic(modelData) }
            }
        }
        Text {
            anchors.centerIn: parent
            width: parent.width - 16
            visible: lista.count === 0
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.ocupado ? "Buscando…" : root.vacio
            color: UI.Theme.textoSuave
            opacity: 0.8
            font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
        }
    }
}
