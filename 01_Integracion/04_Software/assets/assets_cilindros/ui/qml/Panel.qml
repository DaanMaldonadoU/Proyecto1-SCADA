import QtQuick 2.15
import "." as UI

// Contenedor con título de sección. Pon el contenido dentro de `contenido`.
Rectangle {
    id: root
    property string titulo: ""
    property string icono: ""            // nombre de ui/iconos, p. ej. "grafcet"
    default property alias contenido: cuerpo.data
    property alias padding: cuerpo.anchors.margins

    color: UI.Theme.surface
    radius: UI.Theme.radioPanel
    border.color: UI.Theme.borde
    border.width: 1

    Row {
        id: cab
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: UI.Theme.espL }
        spacing: UI.Theme.espS
        height: root.titulo === "" ? 0 : 20
        visible: root.titulo !== ""
        Image {
            visible: root.icono !== ""
            source: root.icono !== "" ? UI.Theme.rutaUi + "iconos/" + root.icono + "_claro.svg" : ""
            sourceSize: Qt.size(18, 18); width: 18; height: 18
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.titulo.toUpperCase()
            color: UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: UI.Theme.seccion; weight: Font.DemiBold; letterSpacing: 1.1 }
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    Item {
        id: cuerpo
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; top: cab.bottom; margins: UI.Theme.espL }
        anchors.topMargin: root.titulo === "" ? UI.Theme.espL : UI.Theme.espM
    }
}
