import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Pila de capas SVG de un cilindro (assets/assets_cilindros/README.md, "Orden de capas"):
//   interior → cámaras presurizadas (azul 28 %) → muelle → vástago → camisa → sensores.
// 1 unidad SVG = 1 mm; todas las capas comparten viewBox y se escalan con ppm = width / vbW.
// La geometría llega por propiedades (copiada de geometria.json por quien la usa).
Item {
    id: root
    property url carpeta
    property bool corte: true
    property real posicion: 0            // 0 = retraído · 1 = extendido (ya animada por el padre)
    property bool mostrarSensores: true
    property bool sc: false
    property bool se: false
    property bool camaraTrasera: false   // EV_E energizada → cámara entre tapa trasera y pistón
    property bool camaraDelantera: false // EV_C energizada → cámara entre pistón y tapa delantera

    // --- geometría (mm)
    property real vbW: 580
    property real vbH: 78
    property real carreraMm: 200
    property real scX: 50;  property real scY: 59.3
    property real seX: 250; property real seY: 59.3
    property real boreX0: 40;  property real boreX1: 270      // interior.svg
    property real boreY0: 24;  property real boreY1: 56
    property real pistonX0: 39; property real pistonX1: 61     // vastago.svg (retraído)
    property real muelleL: 0
    property real muelleApoyoX: 0

    implicitWidth: 580
    implicitHeight: width * vbH / vbW
    readonly property real ppm: width / vbW
    readonly property real dx: posicion * carreraMm * ppm

    Image {
        anchors.fill: parent; visible: root.corte
        source: root.carpeta + "/interior.svg"
        sourceSize: Qt.size(Math.max(1, root.width), Math.max(1, root.height))
        smooth: true
    }
    Rectangle {   // cámara trasera presurizada
        visible: root.corte && root.camaraTrasera
        x: root.boreX0 * root.ppm; y: root.boreY0 * root.ppm
        width: Math.max(0, (root.pistonX0 - root.boreX0) * root.ppm + root.dx)
        height: (root.boreY1 - root.boreY0) * root.ppm
        color: Estilo.alfa(UI.Theme.aire, 0.28)
    }
    Rectangle {   // cámara delantera presurizada
        visible: root.corte && root.camaraDelantera
        x: root.pistonX1 * root.ppm + root.dx; y: root.boreY0 * root.ppm
        width: Math.max(0, root.boreX1 * root.ppm - x)
        height: (root.boreY1 - root.boreY0) * root.ppm
        color: Estilo.alfa(UI.Theme.aire, 0.28)
    }
    Image {   // muelle: se comprime alrededor de su apoyo delantero
        anchors.fill: parent; visible: root.corte && root.muelleL > 0
        source: root.muelleL > 0 ? root.carpeta + "/muelle.svg" : ""
        sourceSize: Qt.size(Math.max(1, root.width), Math.max(1, root.height))
        smooth: true
        transform: Scale {
            origin.x: root.muelleApoyoX * root.ppm
            xScale: root.muelleL > 0 ? Math.max(0.08, (root.muelleL - root.posicion * root.carreraMm) / root.muelleL) : 1
        }
    }
    Image {   // vástago + pistón, dibujado retraído
        width: root.width; height: root.height
        x: root.dx
        source: root.carpeta + "/vastago.svg"
        sourceSize: Qt.size(Math.max(1, root.width), Math.max(1, root.height))
        smooth: true
    }
    Image {
        anchors.fill: parent
        source: root.carpeta + (root.corte ? "/camisa_corte.svg" : "/camisa.svg")
        sourceSize: Qt.size(Math.max(1, root.width), Math.max(1, root.height))
        smooth: true
    }
    Repeater {  // sensores magnéticos (viewBox 30×8 mm, cuerpo centrado en x=17, y=4)
        model: root.mostrarSensores ? [{ cx: root.scX, cy: root.scY, on: root.sc }, { cx: root.seX, cy: root.seY, on: root.se }] : []
        Image {
            width: 30 * root.ppm; height: 8 * root.ppm
            x: (modelData.cx - 17) * root.ppm; y: (modelData.cy - 4) * root.ppm
            source: root.carpeta + (modelData.on ? "/sensor_on.svg" : "/sensor_off.svg")
            sourceSize: Qt.size(Math.max(1, width), Math.max(1, height))
            smooth: true
        }
    }
}
