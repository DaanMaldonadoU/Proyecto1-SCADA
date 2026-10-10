import QtQuick 2.15
import QtQuick.Shapes 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Marca de verificación: verde (ok) si `confirmado`; ámbar si hay escritura sin relectura; gris si nada.
Item {
    id: root
    property bool confirmado: false
    property bool pendiente: false
    implicitWidth: 18; implicitHeight: 18
    Rectangle {
        anchors.fill: parent; radius: width / 2
        color: root.confirmado ? Estilo.alfa(UI.Theme.ok, 0.18) : "transparent"
        border.color: root.confirmado ? UI.Theme.ok : (root.pendiente ? UI.Theme.activo : UI.Theme.borde)
        border.width: 1.5
        Behavior on color { ColorAnimation { duration: UI.Theme.animNormal } }
    }
    Shape {
        anchors.fill: parent
        visible: root.confirmado
        antialiasing: true   // Qt 5.15 no tiene Shape.CurveRenderer (6.6+): geometría con MSAA
        ShapePath {
            strokeColor: UI.Theme.ok; strokeWidth: 2; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: root.width * 0.28; startY: root.height * 0.52
            PathLine { x: root.width * 0.44; y: root.height * 0.68 }
            PathLine { x: root.width * 0.74; y: root.height * 0.34 }
        }
    }
}
