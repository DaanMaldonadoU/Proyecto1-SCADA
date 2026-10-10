import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Franja institucional inferior (datos de mds/data.md): discreta, legible, sin color de estado.
Rectangle {
    id: root
    property bool compacto: false
    implicitHeight: compacto ? 24 : 28
    color: UI.Theme.surface
    Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: UI.Theme.borde }

    readonly property var partes: [datosInstitucion.universidad, datosInstitucion.facultad, datosInstitucion.division,
                                   datosInstitucion.departamento, datosInstitucion.materia]
                                  .filter(function (s) { return s !== undefined && s !== "" })

    Row {
        id: izq
        anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter }
        spacing: 10
        Rectangle { width: 3; height: 12; radius: 1; color: UI.Theme.unamOro; anchors.verticalCenter: parent.verticalCenter; opacity: 0.8 }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, root.width - der.width - 80)
            elide: Text.ElideRight
            text: root.partes.join("  ·  ")
            color: UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: root.compacto ? 11 : 12 }
        }
    }
    Row {
        id: der
        anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
        spacing: 14
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !root.compacto
            text: planta.pubEndpoint !== "" ? "PUB " + planta.pubEndpoint + "  ·  seq " + planta.seq : ""
            color: UI.Theme.textoSuave; opacity: 0.7
            font { family: Estilo.mono; pixelSize: 11 }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: datosInstitucion.nombre || ""
            color: UI.Theme.texto
            font { family: UI.Theme.fuente; pixelSize: root.compacto ? 11 : 12; weight: Font.Medium }
        }
    }
}
