import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// "Simular planta" (solo SIM / EMULATE): pulsadores físicos START_1 / STOP_1, física
// automática/manual y los seis sensores. En REAL no se muestra y el cliente además bloquea
// `planta.entrada()`; el gateway también lo rechaza (core.tags.validar_escritura).
Rectangle {
    id: root
    property bool compacto: false
    readonly property bool manual: !planta.fisicaAutomatica
    color: UI.Theme.surface2
    radius: UI.Theme.radioControl
    border.color: UI.Theme.borde

    ColumnLayout {
        anchors { fill: parent; margins: root.compacto ? 8 : 12 }
        spacing: root.compacto ? 6 : 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "SIMULAR PLANTA"; color: UI.Theme.textoSuave
                   font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.DemiBold; letterSpacing: 1 } }
            Text { text: planta.modo; color: UI.Theme.textoSuave; opacity: 0.7
                   font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.Bold; letterSpacing: 0.8 } }
            Item { Layout.fillWidth: true }
            Interruptor {
                textoIzq: "Manual"; textoDer: "Auto"
                marcado: planta.fisicaAutomatica
                onConmutado: function (v) { planta.fisicaAuto(v) }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            BotonMini {
                Layout.fillWidth: true
                texto: "START_1"
                activo: planta.bits.START_1 === true; tonoActivo: UI.Theme.ok
                onPresionado: planta.entrada("START_1", true)
                onSoltado: planta.entrada("START_1", false)
            }
            BotonMini {
                Layout.fillWidth: true
                texto: "STOP_1 (NC)"
                activo: planta.conectado && planta.bits.STOP_1 === false; tonoActivo: UI.Theme.alarma
                onPresionado: planta.entrada("STOP_1", false)
                onSoltado: planta.entrada("STOP_1", true)
            }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 6
            columnSpacing: 5; rowSpacing: 5
            Repeater {
                model: planta.sensores
                Chip {
                    Layout.fillWidth: true
                    texto: modelData
                    tono: UI.Theme.activo
                    marcado: planta.bits[modelData] === true
                    habilitado: root.manual
                    onPulsado: planta.entrada(modelData, !(planta.bits[modelData] === true))
                }
            }
        }
    }
}
