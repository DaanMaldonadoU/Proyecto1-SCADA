import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Banda bajo la cabecera: visible SOLO mientras haya alarmas activas (ISA-101).
// Roja si alguna es de nivel "alarma", ámbar si solo hay avisos. Parpadeo suave del fondo.
// "Ver" despliega la lista de alarmas activas.
Item {
    id: root
    readonly property var activas: planta.alarmas.filter(function (a) { return a.activa })
    readonly property bool hay: activas.length > 0
    readonly property bool grave: activas.some(function (a) { return a.nivel === "alarma" })
    readonly property color tono: grave ? UI.Theme.alarma : UI.Theme.activo
    implicitHeight: hay ? 30 : 0
    clip: true
    Behavior on implicitHeight { NumberAnimation { duration: UI.Theme.animNormal; easing.type: Easing.OutQuad } }

    function hora(t) { var d = new Date(t * 1000); return Qt.formatTime(d, "HH:mm:ss") }

    Rectangle {
        id: fondo
        anchors.fill: parent
        color: Estilo.alfa(root.tono, 0.16)
        Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: 4; color: root.tono }
        Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Estilo.alfa(root.tono, 0.6) }
        SequentialAnimation on opacity {
            running: root.hay; loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 0.45; duration: 900; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.45; to: 1.0; duration: 900; easing.type: Easing.InOutSine }
        }
    }
    Row {
        anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter }
        spacing: 10
        Image { source: rutaAssets + "ui/iconos/alarma_claro.svg"; sourceSize: Qt.size(16, 16); width: 16; height: 16
                anchors.verticalCenter: parent.verticalCenter }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.activas.length === 1 ? "1 ALARMA ACTIVA" : root.activas.length + " ALARMAS ACTIVAS"
            color: root.tono
            font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Bold; letterSpacing: 1 }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.hay ? root.activas[root.activas.length - 1].msg + "  ·  desde " + root.hora(root.activas[root.activas.length - 1].t_ini) : ""
            color: UI.Theme.texto
            font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Medium }
        }
    }
    BotonMini {
        anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
        height: 22
        texto: lista.opened ? "Ocultar ▴" : "Ver todas ▾"
        onPulsado: lista.opened ? lista.close() : lista.open()
    }

    Popup {
        id: lista
        parent: Overlay.overlay
        x: parent ? parent.width - width - 20 : 0
        y: 72 + 30 + 4
        width: 520
        padding: 12
        background: Rectangle { color: UI.Theme.surface; radius: UI.Theme.radioPanel; border.color: UI.Theme.borde }
        contentItem: Column {
            spacing: 6
            Text { text: "ALARMAS ACTIVAS"; color: UI.Theme.textoSuave
                   font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.DemiBold; letterSpacing: 1.1 } }
            Repeater {
                model: root.activas
                Rectangle {
                    width: 496; height: 40; radius: 6
                    readonly property color tono: modelData.nivel === "alarma" ? UI.Theme.alarma : UI.Theme.activo
                    color: Estilo.alfa(tono, 0.10); border.color: Estilo.alfa(tono, 0.5)
                    Rectangle { width: 4; radius: 2; height: parent.height - 12; color: parent.tono
                                anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter } }
                    Column {
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                        Text { text: modelData.msg; color: UI.Theme.texto; font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Medium } }
                        Text { text: modelData.id + " · " + modelData.nivel + " · desde " + root.hora(modelData.t_ini)
                               color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: 11 } }
                    }
                }
            }
        }
    }
}
