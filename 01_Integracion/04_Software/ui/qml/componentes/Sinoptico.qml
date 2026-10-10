import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Sinóptico: 1A/2A/3A (zona PLC) a la izquierda; cadena neumática 4A/5A y "Simular planta" a la derecha.
PanelHmi {
    id: root
    titulo: "Sinóptico"
    icono: "cilindro"
    subtitulo: planta.modoSuave ? "modo suave · animación prevista" + root.notaSuave
             : (planta.posEstimada ? "posición estimada (calibración)" : "posición del gateway")
    atenuado: !planta.conectado
    readonly property bool simulable: planta.modo === "SIM" || planta.modo === "EMULATE"
    readonly property var infoSuave: planta.suave || ({})
    readonly property string notaSuave: (infoSuave.sinEtapa ? " · sin etapa (B3:3): por bobinas" : "")
                                        + (infoSuave.repuestas > 0 ? " · " + infoSuave.repuestas + " carreras repuestas" : "")

    accesorios: [
        Row {
            spacing: 14
            Row { spacing: 6
                Rectangle { width: 14; height: 10; radius: 2; anchors.verticalCenter: parent.verticalCenter
                            color: Estilo.alfa(UI.Theme.aire, 0.28); border.color: UI.Theme.aire }
                Text { text: "aire"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: Estilo.chico } } }
            UI.Led { tam: 12; color: "activo"; encendido: true; etiqueta: "bobina / sensor" }
            // Modo suave: anima con bobinas, sensores y GRAFCET cuando las lecturas llegan tarde.
            Chip { visible: planta.haySuavizado; texto: "Suave"; tono: UI.Theme.aire; marcado: planta.modoSuave
                   anchors.verticalCenter: parent.verticalCenter
                   onPulsado: planta.fijarModoSuave(!planta.modoSuave) }
            Row { spacing: 6; visible: planta.hayEstimador
                Text { text: "calibración"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: Estilo.chico } }
                Text { text: "↺"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.Bold }
                       MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor
                                   onClicked: planta.reiniciarCalibracion() } } }
        }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: root.compacto ? 10 : 16

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.compacto ? 2 : 6
            Repeater {
                model: planta.cilindrosDef
                Cilindro {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    compacto: root.compacto
                    numero: modelData.n
                    tagEvE: modelData.evE; tagEvC: modelData.evC; tagSc: modelData.sc; tagSe: modelData.se
                    posicion: planta.pos.length >= modelData.n ? planta.pos[modelData.n - 1] : 0
                    posEstimada: planta.posEstimada
                    suave: planta.modoSuave
                    discrepancia: planta.modoSuave && !!root.infoSuave.discrepancia && root.infoSuave.discrepancia[modelData.n - 1] === true
                    carrera: planta.carreras[String(modelData.n)] || ({})
                    calib: planta.calibracion[String(modelData.n)] || ({})
                    sc: planta.bits[modelData.sc] === true
                    se: planta.bits[modelData.se] === true
                    evE: planta.bits[modelData.evE] === true
                    evC: planta.bits[modelData.evC] === true
                }
            }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: UI.Theme.borde; opacity: 0.6 }
        ColumnLayout {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(root.width * 0.34)
            Layout.maximumWidth: Math.round(root.width * 0.34)
            spacing: root.compacto ? 8 : 12
            CadenaNeumatica {
                Layout.fillWidth: true
                Layout.fillHeight: true
                compacto: root.compacto
            }
            SimularPlanta {
                visible: root.simulable
                Layout.fillWidth: true
                Layout.preferredHeight: root.compacto ? 104 : 124
                compacto: root.compacto
            }
        }
    }
}
