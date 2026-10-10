import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Parámetros del ladder: T_ESPERA (los cinco T4:0…T4:4.PRE), T_NEUM (T4:5.PRE), N_CICLOS (C5:0.PRE).
PanelHmi {
    id: root
    titulo: "Parámetros"
    icono: "ajustes"
    atenuado: !planta.conectado

    accesorios: [
        Text {
            readonly property var u: planta.ultimaEscritura
            visible: u && u.tag !== undefined
            text: visible ? "última escritura: " + u.tag + (u.valor === undefined || u.valor === null ? ""
                            : " = " + (typeof u.valor === "boolean" ? (u.valor ? 1 : 0) : u.valor)) + (u.ok ? "" : " (rechazada)") : ""
            color: visible && !u.ok ? UI.Theme.alarma : UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Medium }
        }
    ]

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Repeater {
            model: planta.parametrosDef
            FilaParametro {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.maximumHeight: 44
                def: modelData
                compacto: root.compacto
            }
        }
    }
}
