import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Rejilla de 12 columnas y 3 filas de la pantalla principal (PantallaHmi.qml): los paneles van
// como hijos y se colocan con x: xCol(c), width: ancho(n), y: y1…y3, height: h1…h3.
// Hueco g entre paneles y en los bordes; col = ancho de una columna. Las proporciones son exactas
// de 1280×720 a 1920×1080.
//
// Está en su propio archivo, y no como un Item con funciones dentro de PantallaHmi.qml, porque Qt
// Design Studio reconstruye el archivo que se edita nodo por nodo y no evalúa las funciones ni las
// propiedades propias declaradas en él: los paneles le salían amontonados en la esquina. Las de
// un componente cargado desde otro archivo sí las evalúa.
Item {
    id: rejilla

    property bool compacto: false

    readonly property int g: compacto ? 10 : UI.Theme.espL
    readonly property real col: (width - 2 * g - 11 * g) / 12
    function ancho(n) { return n * col + (n - 1) * g }
    function xCol(c) { return g + c * (col + g) }

    readonly property real util: height - 2 * g - 2 * g
    readonly property real h1: Math.round(util * (compacto ? 0.57 : 0.53))
    readonly property real h2: Math.round(util * (compacto ? 0.225 : 0.25))
    readonly property real h3: util - h1 - h2
    readonly property real y1: g
    readonly property real y2: y1 + h1 + g
    readonly property real y3: y2 + h2 + g
}
