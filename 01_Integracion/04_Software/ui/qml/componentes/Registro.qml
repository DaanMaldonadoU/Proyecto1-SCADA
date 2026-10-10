import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Registro de eventos (gateway + HMI): hora, nivel en color (info gris, aviso ámbar, alarma rojo),
// origen y mensaje. Filtro por nivel con los chips de la cabecera del panel. Lo más reciente arriba.
PanelHmi {
    id: root
    titulo: "Registro de eventos"
    icono: "registro"
    readonly property var modelo: planta.eventos
    function tono(n) { return n === "alarma" ? UI.Theme.alarma : (n === "aviso" ? UI.Theme.activo : UI.Theme.neutro) }

    accesorios: [
        Row {
            spacing: 6
            Repeater {
                model: [{ n: "info", t: "Info" }, { n: "aviso", t: "Aviso" }, { n: "alarma", t: "Alarma" }]
                Chip {
                    texto: modelData.t + " " + (root.modelo.conteos[modelData.n] || 0)
                    // ISA-101: el chip solo toma color si hay eventos de ese nivel
                    tono: modelData.n === "info" || !(root.modelo.conteos[modelData.n] > 0) ? UI.Theme.textoSuave : root.tono(modelData.n)
                    marcado: root.modelo.filtro.indexOf(modelData.n) >= 0
                    onPulsado: root.modelo.alternarNivel(modelData.n)
                }
            }
            BotonMini {
                texto: "Historial…"
                implicitHeight: 22              // misma altura que los chips de la línea del título
                onPulsado: { ventanaHistorial.show(); ventanaHistorial.raise(); ventanaHistorial.requestActivate() }
            }
        }
    ]

    // Visor del historial SQLite del gateway: ventana aparte, se abre con «Historial…».
    VentanaHistorial { id: ventanaHistorial }

    ListView {
        id: lista
        anchors.fill: parent
        clip: true
        model: root.modelo
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle { implicitWidth: 4; radius: 2; color: UI.Theme.borde }
        }
        delegate: Item {
            width: lista.width
            height: root.compacto ? 19 : 22
            Rectangle { anchors.fill: parent; color: index % 2 === 0 ? "transparent" : Estilo.alfa(UI.Theme.surface2, 0.6); radius: 3 }
            Rectangle { width: 3; height: parent.height - 6; radius: 1.5; anchors.verticalCenter: parent.verticalCenter
                        x: 2; color: root.tono(nivel) }
            Text {
                id: tHora
                x: 12; width: 84; anchors.verticalCenter: parent.verticalCenter
                text: hora; color: UI.Theme.textoSuave
                font { family: Estilo.mono; pixelSize: 11 }
            }
            Text {
                id: tNivel
                anchors { left: tHora.right; verticalCenter: parent.verticalCenter }
                width: 50
                text: nivel.toUpperCase()
                color: nivel === "info" ? UI.Theme.textoSuave : root.tono(nivel)
                font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.Bold; letterSpacing: 0.6 }
            }
            Text {
                id: tOrigen
                anchors { left: tNivel.right; verticalCenter: parent.verticalCenter }
                width: root.width > 560 ? 62 : 0; visible: width > 0; elide: Text.ElideRight
                text: origen; color: UI.Theme.textoSuave; opacity: 0.8
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
            }
            Text {
                anchors { left: tOrigen.right; right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: msg
                color: nivel === "info" ? UI.Theme.texto : root.tono(nivel)
                font { family: UI.Theme.fuente; pixelSize: 12; weight: nivel === "info" ? Font.Normal : Font.Medium }
            }
        }
        Text {
            anchors.centerIn: parent
            visible: lista.count === 0
            text: "Sin eventos"
            color: UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: 12 }
        }
    }
}
