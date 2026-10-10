import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Un parámetro: nombre + deslizador + campo + botón "Escribir" + check de confirmación.
// Internamente en unidades del PLC (centésimas para T_ESPERA / T_NEUM, entero para N_CICLOS).
// El check se pone verde cuando la relectura de los tags de core.tags.CONFIRMACION_PARAMETRO
// coincide con lo último que escribió este HMI (lo calcula planta.parametros).
Item {
    id: root
    property var def: ({})                    // de planta.parametrosDef
    property bool compacto: false
    readonly property var estado: planta.parametros[def.tag] || ({})
    readonly property int escala: def.escala || 1
    readonly property int leido: estado.leido !== undefined ? estado.leido : -1
    property int valor: 0                     // valor en edición (unidades PLC)
    property bool editado: false              // el usuario lo tocó: deja de seguir la relectura
    implicitHeight: 30

    onLeidoChanged: if (!editado && leido >= 0) valor = leido
    Component.onCompleted: if (leido >= 0) valor = leido

    function texto(v) { return escala > 1 ? Estilo.num(v / escala, 2) : String(v) }
    function desdeTexto(s) {
        var x = parseFloat(String(s).replace(",", "."))
        if (isNaN(x)) return -1
        return Math.round(x * escala)
    }
    function escribir() {
        var v = Math.max(root.def.tag === "N_CICLOS" ? 1 : 0, Math.min(root.def.max, root.valor))
        planta.escribir(root.def.tag, v)
        root.editado = false
    }

    RowLayout {
        anchors.fill: parent
        spacing: root.compacto ? 6 : 10
        Column {
            Layout.preferredWidth: root.compacto ? 70 : 84
            Text { text: root.def.tag; color: UI.Theme.texto
                   font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.DemiBold } }
            Text { text: root.def.destino; color: UI.Theme.textoSuave; visible: !root.compacto
                   font { family: UI.Theme.fuente; pixelSize: Estilo.micro } }
        }
        Slider {
            id: des
            Layout.fillWidth: true
            Layout.minimumWidth: 40
            from: root.def.tag === "N_CICLOS" ? 1 : 0
            to: root.def.sliderMax || 100
            stepSize: root.escala > 1 ? 5 : 1
            value: root.valor
            onMoved: { root.valor = Math.round(value); root.editado = true }
            background: Rectangle {
                x: des.leftPadding; y: des.topPadding + des.availableHeight / 2 - height / 2
                width: des.availableWidth; height: 4; radius: 2; color: UI.Theme.borde
                Rectangle { width: des.visualPosition * parent.width; height: parent.height; radius: 2
                            color: root.editado ? UI.Theme.aire : UI.Theme.neutro }
            }
            handle: Rectangle {
                x: des.leftPadding + des.visualPosition * (des.availableWidth - width)
                y: des.topPadding + des.availableHeight / 2 - height / 2
                width: 14; height: 14; radius: 7
                color: des.pressed ? UI.Theme.texto : UI.Theme.surface2
                border.color: root.editado ? UI.Theme.aire : UI.Theme.textoSuave; border.width: 2
            }
        }
        TextField {
            id: campo
            Layout.preferredWidth: root.compacto ? 58 : 70
            Layout.preferredHeight: 28
            horizontalAlignment: TextInput.AlignRight
            text: root.leido < 0 && !root.editado ? "—" : root.texto(root.valor)
            color: UI.Theme.texto
            selectByMouse: true
            font { family: UI.Theme.fuente; pixelSize: 13; weight: Font.DemiBold } Component.onCompleted: Estilo.cifrasTabulares(this)
            leftPadding: 6; rightPadding: root.def.unidad ? 18 : 6
            validator: RegularExpressionValidator { regularExpression: root.escala > 1 ? /\d{0,3}([.,]\d{0,2})?/ : /\d{0,2}/ }
            background: Rectangle {
                radius: 6; color: UI.Theme.fondo
                border.color: campo.activeFocus ? UI.Theme.aire : (root.editado ? Estilo.alfa(UI.Theme.aire, 0.6) : UI.Theme.borde)
            }
            Text { visible: !!root.def.unidad; text: root.def.unidad || ""; color: UI.Theme.textoSuave
                   anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                   font { family: UI.Theme.fuente; pixelSize: Estilo.chico } }
            onTextEdited: { var v = root.desdeTexto(text); if (v >= 0) { root.valor = v; root.editado = true } }
            onAccepted: root.escribir()
        }
        BotonMini {
            Layout.preferredWidth: root.compacto ? 58 : 72
            texto: "Escribir"
            primario: root.editado
            habilitado: planta.gatewayVivo
            onPulsado: root.escribir()
        }
        Check {
            confirmado: root.estado.confirmado === true && !root.editado
            pendiente: (root.estado.escrito !== undefined && root.estado.escrito >= 0) && root.estado.confirmado !== true
        }
    }
}
