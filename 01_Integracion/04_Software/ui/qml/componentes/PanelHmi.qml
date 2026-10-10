import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Extensión de UI.Panel (el original no se toca): mismo aspecto, más
//  · `accesorios`: controles alineados a la derecha en la línea del título (filtros, leyendas);
//  · `compacto`: márgenes de 10 px para 1366×768;
//  · `atenuado`: sin conexión el contenido pasa a gris (ISA-101: sin dato = gris).
Rectangle {
    id: root
    property string titulo: ""
    property string icono: ""                 // nombre en ui/iconos (sin sufijo)
    property bool compacto: false
    property bool atenuado: false
    property string subtitulo: ""             // texto discreto junto al título
    default property alias contenido: cuerpo.data
    property alias accesorios: acc.data
    readonly property int margen: compacto ? 10 : UI.Theme.espL

    color: UI.Theme.surface
    radius: UI.Theme.radioPanel
    border.color: UI.Theme.borde
    border.width: 1

    Item {
        id: cab
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: root.margen }
        height: root.titulo === "" ? 0 : 20
        visible: root.titulo !== ""
        Row {
            id: tit
            anchors.verticalCenter: parent.verticalCenter
            spacing: UI.Theme.espS
            Image {
                visible: root.icono !== ""
                source: root.icono !== "" ? rutaAssets + "ui/iconos/" + root.icono + (UI.Theme.sufijoIcono || "_claro") + ".svg" : ""
                sourceSize: Qt.size(18, 18); width: 18; height: 18
                anchors.verticalCenter: parent.verticalCenter
                opacity: 0.85
            }
            Text {
                text: root.titulo.toUpperCase()
                color: UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: root.compacto ? 13 : UI.Theme.seccion; weight: Font.DemiBold; letterSpacing: 1.1 }
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: root.subtitulo !== ""
                text: root.subtitulo
                color: UI.Theme.textoSuave; opacity: 0.75
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Row {
            id: acc
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            spacing: UI.Theme.espS
        }
    }
    Item {
        id: cuerpo
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; top: cab.bottom; margins: root.margen }
        anchors.topMargin: root.titulo === "" ? root.margen : (root.compacto ? 8 : UI.Theme.espM)
        opacity: root.atenuado ? 0.55 : 1.0
        Behavior on opacity { NumberAnimation { duration: UI.Theme.animNormal } }
    }
}
