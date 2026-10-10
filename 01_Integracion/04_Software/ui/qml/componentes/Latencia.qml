import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Latencia de lectura (perf_counter del gateway alrededor de cada lectura de grupo):
// valor actual, p95, periodo efectivo y fuente; tendencia de `historialLatencia` con la línea p95.
// Selector caché / dispositivo solo en modos OPC (EMULATE / REAL).
PanelHmi {
    id: root
    titulo: "Latencia"
    icono: "latencia"
    atenuado: !planta.conectado
    readonly property bool opc: planta.modo === "EMULATE" || planta.modo === "REAL"
    readonly property bool lenta: planta.periodoMs > 0 && planta.latenciaP95Ms > planta.periodoMs

    accesorios: [
        Row {
            spacing: 6
            visible: root.opc
            Chip { texto: "caché"; tono: UI.Theme.aire; marcado: planta.fuente === "cache"; onPulsado: planta.fuenteOpc("cache") }
            Chip { texto: "dispositivo"; tono: UI.Theme.aire; marcado: planta.fuente === "dispositivo"; onPulsado: planta.fuenteOpc("dispositivo") }
        }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: root.compacto ? 10 : 14

        ColumnLayout {
            Layout.fillHeight: true
            Layout.fillWidth: false
            Layout.preferredWidth: root.compacto ? 104 : 124
            Layout.maximumWidth: root.compacto ? 104 : 124
            spacing: 2
            Row {
                spacing: 4
                Text { text: planta.conectado ? Estilo.num(planta.latenciaMs, 1) : "—"
                       color: root.lenta ? UI.Theme.activo : UI.Theme.texto
                       font { family: UI.Theme.fuente; pixelSize: root.compacto ? 24 : UI.Theme.valor; weight: Font.DemiBold } Component.onCompleted: Estilo.cifrasTabulares(this) }
                Text { text: "ms"; color: UI.Theme.textoSuave; y: root.compacto ? 10 : 13
                       font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium } }
            }
            Repeater {
                model: [
                    { k: "p95", v: Estilo.num(planta.latenciaP95Ms, 1) + " ms" },
                    { k: "máx", v: Estilo.num(planta.latenciaMaxMs, 1) + " ms" },
                    { k: "periodo", v: Estilo.num(planta.periodoMs, 0) + " ms" },
                    { k: "fuente", v: planta.fuenteLatencia || "—" }
                ]
                RowLayout {
                    Layout.fillWidth: true
                    visible: !root.compacto || index !== 1
                    Text { text: modelData.k; color: UI.Theme.textoSuave; Layout.fillWidth: true
                           font { family: UI.Theme.fuente; pixelSize: Estilo.chico } }
                    Text { text: planta.conectado ? modelData.v : "—"; color: UI.Theme.texto
                           font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Medium } Component.onCompleted: Estilo.cifrasTabulares(this) }
                }
            }
            Item { Layout.fillHeight: true }
        }

        Canvas {
            id: grafica
            Layout.fillWidth: true
            Layout.fillHeight: true
            antialiasing: true
            readonly property var datos: planta.historialLatencia
            onDatosChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d"); ctx.reset()
                var W = width, H = height, d = datos || []
                ctx.fillStyle = Estilo.alfa(UI.Theme.fondo, 0.6)
                ctx.fillRect(0, 0, W, H)
                if (d.length < 2) return
                var max = 0
                for (var i = 0; i < d.length; i++) max = Math.max(max, d[i])
                var p95 = planta.latenciaP95Ms
                var tope = Math.max(1, max * 1.15, p95 * 1.3)
                var n = d.length, paso = W / Math.max(1, (n - 1))
                function Y(v) { return H - 2 - (v / tope) * (H - 6) }
                // relleno y trazo
                ctx.beginPath(); ctx.moveTo(0, H)
                for (i = 0; i < n; i++) ctx.lineTo(i * paso, Y(d[i]))
                ctx.lineTo((n - 1) * paso, H); ctx.closePath()
                ctx.fillStyle = Estilo.alfa(UI.Theme.texto, 0.10); ctx.fill()
                ctx.beginPath()
                for (i = 0; i < n; i++) { if (i === 0) ctx.moveTo(0, Y(d[0])); else ctx.lineTo(i * paso, Y(d[i])) }
                ctx.strokeStyle = Estilo.alfa(UI.Theme.texto, 0.8); ctx.lineWidth = 1.2; ctx.stroke()
                // línea p95
                if (p95 > 0) {
                    ctx.save(); ctx.setLineDash([4, 3]); ctx.strokeStyle = UI.Theme.activo; ctx.lineWidth = 1
                    ctx.beginPath(); ctx.moveTo(0, Math.round(Y(p95)) + 0.5); ctx.lineTo(W, Math.round(Y(p95)) + 0.5); ctx.stroke(); ctx.restore()
                    ctx.fillStyle = UI.Theme.activo; ctx.font = Estilo.fuenteCanvas(Font.DemiBold, 10)
                    ctx.textAlign = "right"; ctx.textBaseline = "bottom"
                    ctx.fillText("p95", W - 3, Math.round(Y(p95)) - 1)
                }
                ctx.fillStyle = UI.Theme.textoSuave; ctx.font = Estilo.fuenteCanvas(Font.Medium, 10)
                ctx.textAlign = "left"; ctx.textBaseline = "top"
                ctx.fillText(Math.round(tope) + " ms", 3, 2)
            }
        }
    }
}
