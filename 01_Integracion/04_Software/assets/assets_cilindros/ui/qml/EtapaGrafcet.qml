import QtQuick 2.15
import "." as UI

// Etapa del GRAFCET: cuadro con número, acción y barra de progreso del temporizador de la etapa.
Rectangle {
    id: root
    property int numero: 0
    property string accion: ""
    property bool activa: false
    property bool inicial: numero === 0
    property real progreso: 0        // 0..1 = T4:n.ACC / T4:n.PRE (sólo etapas con TON)
    property bool conTemporizador: false

    width: 150; height: 44; radius: 6
    color: activa ? Qt.rgba(1, 0.69, 0, 0.14) : UI.Theme.surface2
    border.color: activa ? UI.Theme.activo : UI.Theme.borde
    border.width: activa ? 2 : 1
    Behavior on color { ColorAnimation { duration: UI.Theme.animNormal } }
    Behavior on border.color { ColorAnimation { duration: UI.Theme.animNormal } }

    // doble marco de la etapa inicial
    Rectangle { visible: root.inicial; anchors.fill: parent; anchors.margins: 3; radius: 4; color: "transparent"; border.color: root.border.color; border.width: 1 }

    Rectangle {  // cuadro del número
        x: 6; y: 6; width: 32; height: 32; radius: 4
        color: root.activa ? UI.Theme.activo : UI.Theme.borde
        Text { anchors.centerIn: parent; text: "X" + root.numero; color: root.activa ? "#111417" : UI.Theme.texto
               font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Bold } }
    }
    Text {
        x: 46; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 54; elide: Text.ElideRight
        text: root.accion; color: root.activa ? UI.Theme.texto : UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: 12; weight: root.activa ? Font.DemiBold : Font.Normal }
    }
    Rectangle {  // barra del temporizador
        visible: root.conTemporizador
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 2 }
        height: 3; radius: 2; color: Qt.rgba(1,1,1,0.06)
        Rectangle { width: parent.width * Math.max(0, Math.min(1, root.progreso)); height: parent.height; radius: 2
                    color: UI.Theme.activo; visible: root.activa
                    Behavior on width { NumberAnimation { duration: 150 } } }
    }
}
