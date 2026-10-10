import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Monitor de E/S: las cuatro palabras del grupo rápido (core.tags.PALABRAS) bit a bit, 15 → 0.
// LED por bit y nombre del tag si lo tiene. Los bits 9…15 no tienen tag en ninguna palabra:
// sus celdas son estrechas para dar sitio a los nombres (las columnas siguen alineadas).
PanelHmi {
    id: root
    titulo: "Monitor E/S"
    icono: "io"
    atenuado: !planta.conectado
    subtitulo: "bit 15 … 0"

    Item {
        id: zona
        anchors.fill: parent
        readonly property int etiquetaAncho: root.compacto ? 38 : 60
        readonly property int angosta: root.compacto ? 8 : 11
        readonly property real ancha: (width - etiquetaAncho - 7 * angosta - 4) / 9
        readonly property real altoFila: height / 4
        readonly property bool conNombres: altoFila >= 18
        readonly property int ledTam: Math.max(8, Math.min(root.compacto ? 11 : 14, altoFila - 12))
        function celdaX(bit) { return bit >= 9 ? (15 - bit) * angosta : 7 * angosta + 4 + (8 - bit) * ancha }
        function celdaAncho(bit) { return bit >= 9 ? angosta : ancha }

        Repeater {
            model: planta.palabrasDef
            Item {
                id: filaPalabra
                y: index * zona.altoFila
                width: zona.width; height: zona.altoFila
                readonly property var p: modelData
                readonly property int valor: planta.palabras[p.nombre] !== undefined ? planta.palabras[p.nombre] : -1
                Rectangle { visible: index > 0; width: parent.width; height: 1; color: UI.Theme.borde; opacity: 0.5 }
                Column {
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    Text { text: filaPalabra.p.nombre; color: UI.Theme.texto
                           font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.DemiBold } }
                    Text { visible: !root.compacto
                           text: filaPalabra.valor >= 0 ? "0x" + ("0000" + filaPalabra.valor.toString(16).toUpperCase()).slice(-4) : "0x----"
                           color: UI.Theme.textoSuave
                           font { family: Estilo.mono; pixelSize: Estilo.micro } }
                }
                Repeater {
                    model: 16
                    Item {
                        readonly property int bit: 15 - index
                        readonly property string nombre: filaPalabra.p.bits[bit]
                        readonly property bool on: filaPalabra.valor >= 0 && ((filaPalabra.valor >> bit) & 1) === 1
                        x: zona.etiquetaAncho + zona.celdaX(bit)
                        width: zona.celdaAncho(bit); height: filaPalabra.height
                        Image {
                            id: led
                            readonly property int tam: nombre !== "" ? zona.ledTam : 7
                            width: tam; height: tam
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: zona.conNombres && nombre !== "" ? (parent.height - tam - 10) / 2 : (parent.height - tam) / 2
                            source: rutaAssets + "ui/leds/" + (nombre !== "" ? "activo" : "neutro") + "_" + (parent.on ? "on" : "off") + ".svg"
                            sourceSize: Qt.size(tam * 2, tam * 2)
                            opacity: nombre !== "" ? 1 : 0.6
                        }
                        Text {
                            visible: zona.conNombres && nombre !== ""
                            anchors { top: led.bottom; topMargin: 0; horizontalCenter: parent.horizontalCenter }
                            width: parent.width; horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                            text: nombre
                            color: parent.on ? UI.Theme.texto : UI.Theme.textoSuave
                            font { family: UI.Theme.fuente; pixelSize: root.compacto ? 9 : 10; weight: parent.on ? Font.DemiBold : Font.Medium }
                        }
                        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true }
                        ToolTip.visible: ma.containsMouse
                        ToolTip.delay: 400
                        ToolTip.text: filaPalabra.p.nombre + "/" + bit + (nombre !== "" ? " · " + nombre : "") + " = " + (on ? 1 : 0)
                    }
                }
            }
        }
    }
}
