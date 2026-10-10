import QtQuick 2.15
import QtQuick.Shapes 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Cadena puramente neumática 4A/5A (ISO 6432 ø20 × 50, simple efecto, retorno por muelle).
// El PLC no tiene sensores de estos cilindros: la posición es el modelo de tiempos del gateway
// (`pos_neum`), por eso se dibuja atenuada y con marco punteado. Cuenta regresiva de T4:5.
Item {
    id: root
    property bool compacto: false
    readonly property var def: planta.neumaticoDef
    readonly property int acc: planta.ints[def.tagAcc] !== undefined ? planta.ints[def.tagAcc] : 0
    readonly property int pre: planta.ints[def.tagPre] !== undefined ? planta.ints[def.tagPre] : 0
    readonly property bool enVentana: planta.etapa === 7
    readonly property real restante: enVentana ? Math.max(0, pre - acc) / 100.0 : pre / 100.0

    // --- geometría iso6432_d20/geometria.json
    readonly property real vbW: 215
    readonly property real vbH: 40

    // marco punteado: la posición es una estimación
    Shape {
        anchors.fill: parent
        antialiasing: true   // Qt 5.15 no tiene Shape.CurveRenderer (6.6+): geometría con MSAA
        ShapePath {
            strokeColor: UI.Theme.borde; strokeWidth: 1; fillColor: "transparent"
            strokeStyle: ShapePath.DashLine; dashPattern: [4, 3]
            startX: 8; startY: 0.5
            PathLine { x: root.width - 8; y: 0.5 }
            PathArc { x: root.width - 0.5; y: 8; radiusX: 7.5; radiusY: 7.5 }
            PathLine { x: root.width - 0.5; y: root.height - 8 }
            PathArc { x: root.width - 8; y: root.height - 0.5; radiusX: 7.5; radiusY: 7.5 }
            PathLine { x: 8; y: root.height - 0.5 }
            PathArc { x: 0.5; y: root.height - 8; radiusX: 7.5; radiusY: 7.5 }
            PathLine { x: 0.5; y: 8 }
            PathArc { x: 8; y: 0.5; radiusX: 7.5; radiusY: 7.5 }
        }
    }

    Text {
        id: titulo
        anchors { left: parent.left; top: parent.top; leftMargin: 12; topMargin: root.compacto ? 7 : 10 }
        text: "CADENA NEUMÁTICA 4A/5A"
        color: UI.Theme.textoSuave
        font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.DemiBold; letterSpacing: 1 }
    }
    Text {
        id: leyenda
        anchors { left: parent.left; bottom: parent.bottom; leftMargin: 12; bottomMargin: root.compacto ? 6 : 10 }
        text: "sin sensores en el PLC · posición estimada"
        color: UI.Theme.textoSuave; opacity: 0.8
        font { family: UI.Theme.fuente; pixelSize: Estilo.chico; italic: true }
    }

    // anillo: cuenta regresiva de la ventana T4:5
    Item {
        id: zonaAnillo
        width: Math.min(root.compacto ? 78 : 104, root.height - 40)
        height: width
        anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter; verticalCenterOffset: 2 }
        UI.AnilloProgreso {
            anchors.fill: parent
            grosor: root.compacto ? 5 : 7
            valor: root.restante
            maximo: Math.max(0.01, root.pre / 100.0)
            texto: Estilo.num(root.restante, 1) + " s"
            subtitulo: root.def.direccion
            colorArco: root.enVentana ? UI.Theme.activo : UI.Theme.neutro
        }
    }

    // los dos minicilindros
    Column {
        id: cols
        anchors { left: parent.left; leftMargin: 12; right: zonaAnillo.left; rightMargin: 12
                  top: titulo.bottom; bottom: leyenda.top; topMargin: 4; bottomMargin: 2 }
        spacing: 2
        Repeater {
            model: 2
            Item {
                id: fila
                width: cols.width
                height: (cols.height - cols.spacing) / 2
                readonly property real p: planta.posNeum.length > index ? planta.posNeum[index] : 0
                property real pAnt: 0
                property bool subiendo: false
                onPChanged: { subiendo = p > 0.005 && p >= pAnt - 0.0005; pAnt = p }
                property real pVista: p
                Behavior on pVista { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }

                Text {
                    id: etq
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    width: 30
                    text: root.def.cilindros[index] + "A"
                    color: fila.p > 0.02 ? UI.Theme.texto : UI.Theme.textoSuave
                    font { family: UI.Theme.fuente; pixelSize: root.compacto ? 15 : 17; weight: Font.Bold }
                }
                CapasCilindro {
                    anchors { left: etq.right; leftMargin: 6; verticalCenter: parent.verticalCenter }
                    width: Math.min(fila.width - 36, fila.height * root.vbW / root.vbH)
                    height: width * root.vbH / root.vbW
                    opacity: 0.75
                    carpeta: rutaAssets + "iso6432_d20"
                    posicion: fila.pVista
                    mostrarSensores: false
                    vbW: root.vbW; vbH: root.vbH; carreraMm: 50
                    boreX0: 26; boreX1: 96; boreY0: 10; boreY1: 30
                    pistonX0: 25; pistonX1: 35
                    muelleL: 60.0; muelleApoyoX: 95.5
                    camaraTrasera: fila.subiendo
                }
            }
        }
    }
}
