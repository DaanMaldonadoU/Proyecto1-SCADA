import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// START / STOP / RESET: pulso de 300 ms sobre STARTV / STOPV / RESETV (lo cronometra el gateway).
// Anillo de confirmación (ARQUITECTURA 6.3): START cuando ACTIVE está arriba; STOP cuando ACTIVE
// baja tras pulsar STOP; RESET cuando la etapa vuelve a X0 tras pulsar RESET.
// Abajo, FranjaMando: quién tiene el mando (HMI local o web), mando remoto on/off y quién está en línea.
PanelHmi {
    id: root
    titulo: "Mandos"
    icono: "plc"
    atenuado: !planta.conectado

    readonly property bool active: planta.bits.ACTIVE === true
    property bool stopPedido: false
    property bool resetPedido: false
    onActiveChanged: if (active) stopPedido = false
    Timer { id: finReset; interval: 2500; onTriggered: root.resetPedido = false }

    accesorios: [
        Row {
            spacing: 12
            UI.Led { tam: 12; color: "ok"; encendido: root.active; etiqueta: "ACTIVE" }
            UI.Led { tam: 12; color: "activo"; encendido: planta.bits.END === true || planta.finReciente
                     etiqueta: planta.fines > 0 ? "END ×" + planta.fines : "END" }
            UI.Led { tam: 12; color: "alarma"; encendido: planta.conectado && planta.bits.STOP_1 === false; etiqueta: "STOP_1" }
        }
    ]

    FranjaMando {
        id: franja
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 28
    }

    Item {
        id: zona
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: franja.top; bottomMargin: 6 }
        readonly property real escala: Math.max(0.55, Math.min(1.0, height / 120, width / 350))
        Row {
            anchors.centerIn: parent
            spacing: 22 * zona.escala
            Repeater {
                model: [{ tipo: "start", tag: "STARTV", etiqueta: "START" },
                        { tipo: "stop", tag: "STOPV", etiqueta: "STOP" },
                        { tipo: "reset", tag: "RESETV", etiqueta: "RESET" }]
                Item {
                    width: 96 * zona.escala; height: 118 * zona.escala
                    UI.BotonIndustrial {
                        anchors.centerIn: parent
                        scale: zona.escala
                        tipo: modelData.tipo
                        etiqueta: modelData.etiqueta
                        habilitado: planta.gatewayVivo
                        confirmado: modelData.tipo === "start" ? root.active
                                  : modelData.tipo === "stop" ? (root.stopPedido && !root.active)
                                  : (root.resetPedido && planta.etapa === 0)
                        onPulsado: {
                            if (modelData.tipo === "stop") root.stopPedido = true
                            if (modelData.tipo === "reset") { root.resetPedido = true; finReset.restart() }
                            planta.pulso(modelData.tag)
                        }
                    }
                }
            }
        }
    }
}
