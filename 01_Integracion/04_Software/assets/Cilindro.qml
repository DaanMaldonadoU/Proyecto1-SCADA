// Cilindro.qml — apila las capas SVG de un cilindro y anima vástago, muelle y sensores.
// Funciona con Qt 5.15 (PyQt5) y Qt 6 (PySide6) con QtQuick 2 / QtSvg. Sin efectos gráficos.
//
// Uso:
//   Cilindro { carpeta: "assets_cilindros/iso15552_d32"; corte: true; width: 700
//              posicion: plc.vastago1A   // 0..1 (0 = retraído, 1 = extendido)
//              sc: plc.SC1; se: plc.SE1 }
//
// Los datos de geometria.json se pasan a mano en las propiedades (QML no lee JSON sin JS);
// abajo van los valores por defecto del ISO 15552 ø32 x 200.

import QtQuick 2.15

Item {
    id: root
    property string carpeta: "assets_cilindros/iso15552_d32"
    property bool   corte: true          // ventana de corte con pistón visible
    property real   posicion: 0.0        // 0 = retraído · 1 = extendido
    property bool   sc: true             // sensor retraído activo
    property bool   se: false            // sensor extendido activo

    // --- geometría (mm) — copiar de geometria.json de la carpeta usada
    property real vbW: 580
    property real vbH: 78
    property real carreraMm: 200
    property real scX: 50;  property real scY: 59.3
    property real seX: 250; property real seY: 59.3
    // muelle (sólo minicilindro; deja muelleL = 0 si no hay)
    property real muelleL: 0
    property real muelleApoyoX: 0

    implicitWidth: 600
    implicitHeight: width * vbH / vbW
    readonly property real ppm: width / vbW           // px por mm

    // ---- animación suave del vástago (la física real la lleva el PLC/sim; esto sólo alisa el muestreo)
    property real posAnim: posicion
    Behavior on posAnim { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
    onPosicionChanged: posAnim = posicion

    Component.onCompleted: {
        // resolución de rasterizado del SVG = tamaño en pantalla (nítido en cualquier escala)
    }

    // 1) interior del tubo (sólo en corte)
    Image {
        anchors.fill: parent; visible: root.corte
        source: root.carpeta + "/interior.svg"
        sourceSize.width: root.width; sourceSize.height: root.height
        fillMode: Image.PreserveAspectFit; smooth: true
    }

    // 2) muelle (minicilindro): se comprime hacia el apoyo delantero
    Image {
        anchors.fill: parent; visible: root.corte && root.muelleL > 0
        source: root.carpeta + "/muelle.svg"
        sourceSize.width: root.width; sourceSize.height: root.height
        fillMode: Image.PreserveAspectFit; smooth: true
        transform: Scale {
            origin.x: root.muelleApoyoX * root.ppm
            xScale: Math.max(0.08, (root.muelleL - root.posAnim * root.carreraMm) / root.muelleL)
        }
    }

    // 3) vástago + pistón (dibujado retraído; se desplaza en x)
    Image {
        anchors.fill: parent
        source: root.carpeta + "/vastago.svg"
        sourceSize.width: root.width; sourceSize.height: root.height
        fillMode: Image.PreserveAspectFit; smooth: true
        x: root.posAnim * root.carreraMm * root.ppm
    }

    // 4) camisa (opaca o con ventana de corte)
    Image {
        anchors.fill: parent
        source: root.carpeta + (root.corte ? "/camisa_corte.svg" : "/camisa.svg")
        sourceSize.width: root.width; sourceSize.height: root.height
        fillMode: Image.PreserveAspectFit; smooth: true
    }

    // 5) sensores (viewBox propio 30x8 mm; el cuerpo queda centrado en x=17, y=4)
    Repeater {
        model: [ { cx: root.scX, cy: root.scY, on: root.sc },
                 { cx: root.seX, cy: root.seY, on: root.se } ]
        Image {
            width: 30 * root.ppm; height: 8 * root.ppm
            x: (modelData.cx - 17) * root.ppm; y: (modelData.cy - 4) * root.ppm
            source: root.carpeta + (modelData.on ? "/sensor_on.svg" : "/sensor_off.svg")
            sourceSize.width: width; sourceSize.height: height
            smooth: true
        }
    }
}
