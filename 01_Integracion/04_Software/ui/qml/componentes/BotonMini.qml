import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Botón rectangular pequeño (misma familia visual que UI.BotonPlano, alto 28 px) para zonas densas.
// Emite presionado()/soltado() además de pulsado() (pulsadores físicos simulados).
Rectangle {
    id: root
    property string texto: ""
    property bool habilitado: true
    property bool primario: false
    property bool activo: false               // indicador de estado (borde del tono)
    property color tonoActivo: UI.Theme.activo
    signal pulsado()
    signal presionado()
    signal soltado()
    implicitWidth: Math.max(52, t.implicitWidth + 20); implicitHeight: 28
    radius: 6
    readonly property color base: primario ? UI.Theme.aire : UI.Theme.surface2
    color: !habilitado ? UI.Theme.surface : (area.pressed ? Qt.darker(base, 1.25) : (area.containsMouse ? Qt.lighter(base, 1.12) : base))
    border.color: activo ? tonoActivo : (primario ? Qt.lighter(UI.Theme.aire, 1.1) : UI.Theme.borde)
    border.width: 1
    Behavior on color { ColorAnimation { duration: UI.Theme.animRapida } }
    Rectangle {  // fondo tenue cuando está activo
        anchors.fill: parent; radius: parent.radius; visible: root.activo
        color: Estilo.alfa(root.tonoActivo, 0.14)
    }
    Text {
        id: t; anchors.centerIn: parent; text: root.texto
        color: !root.habilitado ? UI.Theme.textoSuave : (root.activo ? root.tonoActivo
               : (root.primario ? (UI.Theme.textoSobreAcento || UI.Theme.texto) : UI.Theme.texto))
        font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium; letterSpacing: 0.3 }
    }
    MouseArea {
        id: area; anchors.fill: parent; hoverEnabled: true; enabled: root.habilitado
        cursorShape: Qt.PointingHandCursor
        onClicked: root.pulsado()
        onPressed: root.presionado()
        onReleased: root.soltado()
        onCanceled: root.soltado()
    }
}
