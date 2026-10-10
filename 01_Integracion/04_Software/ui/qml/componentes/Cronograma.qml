import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Cronograma en vivo (últimos 45 s): posición de 1A/2A/3A en tres bandas + banda de etapa,
// y a la derecha el contador C5:0 (ACC / PRE) con UI.AnilloProgreso.
// El Canvas se repinta solo cuando llega un cronograma nuevo (5 Hz), nunca por frame.
PanelHmi {
    id: root
    titulo: "Cronograma"
    icono: "reloj"
    subtitulo: "últimos 45 s"
    atenuado: !planta.conectado
    readonly property real ventana: 45

    accesorios: [
        Row {
            spacing: 12
            Row { spacing: 5
                Rectangle { width: 12; height: 8; radius: 1; anchors.verticalCenter: parent.verticalCenter
                            color: Estilo.alfa(UI.Theme.texto, 0.16); border.color: UI.Theme.textoSuave }
                Text { text: "posición del vástago"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: Estilo.chico } } }
            Row { spacing: 5
                Rectangle { width: 12; height: 8; radius: 1; anchors.verticalCenter: parent.verticalCenter
                            color: Estilo.alfa(UI.Theme.activo, 0.25); border.color: UI.Theme.activo }
                Text { text: "etapa activa"; color: UI.Theme.textoSuave; font { family: UI.Theme.fuente; pixelSize: Estilo.chico } } }
        }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: root.compacto ? 10 : 16

        Canvas {
            id: gantt
            Layout.fillWidth: true
            Layout.fillHeight: true
            antialiasing: true
            readonly property var datos: planta.cronograma
            onDatosChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var W = width, H = height
                var izq = 40, der = 4, ejeH = 14
                var x0 = izq, x1 = W - der
                var bandaEtapa = Math.max(16, Math.min(22, H * 0.14))
                var huecoB = root.compacto ? 4 : 6
                var hCil = (H - ejeH - bandaEtapa - 3 * huecoB) / 3
                function X(t) { return x1 + (t / root.ventana) * (x1 - x0) }
                ctx.font = Estilo.fuenteCanvas(Font.Medium, 11)
                ctx.textBaseline = "middle"

                // rejilla cada 5 s y etiquetas del eje
                ctx.strokeStyle = Estilo.alfa(UI.Theme.borde, 0.9)
                ctx.lineWidth = 1
                ctx.fillStyle = UI.Theme.textoSuave
                ctx.textAlign = "center"
                for (var s = 0; s <= root.ventana; s += 5) {
                    var gx = Math.round(X(-s)) + 0.5
                    ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H - ejeH); ctx.stroke()
                    if (s % 15 === 0) ctx.fillText(s === 0 ? "ahora" : "−" + s + " s", Math.min(Math.max(gx, x0 + 14), x1 - 16), H - ejeH / 2 + 1)
                }

                var d = datos || []
                // bandas de cilindros
                for (var c = 0; c < 3; c++) {
                    var yb = c * (hCil + huecoB)
                    ctx.fillStyle = Estilo.alfa(UI.Theme.fondo, 0.6)
                    ctx.fillRect(x0, yb, x1 - x0, hCil)
                    ctx.fillStyle = UI.Theme.textoSuave
                    ctx.textAlign = "left"
                    ctx.font = Estilo.fuenteCanvas(Font.Bold, 12)
                    ctx.fillText((c + 1) + "A", 4, yb + hCil / 2)
                    ctx.font = Estilo.fuenteCanvas(Font.Medium, 11)
                    // área de la posición
                    ctx.beginPath()
                    var abierto = false, xs = 0
                    for (var i = 0; i < d.length; i++) {
                        var t = d[i][0], p = d[i][1 + c]
                        if (t < -root.ventana) continue
                        var x = X(t)
                        if (p < 0) {
                            if (abierto) { ctx.lineTo(x, yb + hCil); ctx.lineTo(xs, yb + hCil); ctx.closePath(); abierto = false }
                            continue
                        }
                        var y = yb + hCil - 2 - p * (hCil - 4)
                        if (!abierto) { ctx.moveTo(x, yb + hCil); ctx.lineTo(x, y); xs = x; abierto = true }
                        else ctx.lineTo(x, y)
                        if (i === d.length - 1) { ctx.lineTo(x, yb + hCil); ctx.lineTo(xs, yb + hCil); ctx.closePath(); abierto = false }
                    }
                    ctx.fillStyle = Estilo.alfa(UI.Theme.texto, 0.14)
                    ctx.fill()
                    // trazo superior
                    ctx.beginPath()
                    var trazando = false
                    for (i = 0; i < d.length; i++) {
                        t = d[i][0]; p = d[i][1 + c]
                        if (t < -root.ventana || p < 0) { trazando = false; continue }
                        x = X(t); y = yb + hCil - 2 - p * (hCil - 4)
                        if (!trazando) { ctx.moveTo(x, y); trazando = true } else ctx.lineTo(x, y)
                    }
                    ctx.strokeStyle = Estilo.alfa(UI.Theme.texto, 0.75)
                    ctx.lineWidth = 1.5
                    ctx.stroke()
                }

                // banda de etapas
                var ye = 3 * (hCil + huecoB)
                ctx.fillStyle = UI.Theme.textoSuave
                ctx.textAlign = "left"
                ctx.font = Estilo.fuenteCanvas(Font.Bold, 12)
                ctx.fillText("X", 4, ye + bandaEtapa / 2)
                ctx.font = Estilo.fuenteCanvas(Font.DemiBold, 10)
                ctx.textAlign = "center"
                var ini = -1, et = -2
                function tramo(a, b, e, ultimo) {
                    if (e < 0) return
                    var xa = Math.max(x0, X(d[a][0])), xb = X(d[b][0])
                    if (xb - xa < 1) return
                    ctx.fillStyle = ultimo ? Estilo.alfa(UI.Theme.activo, 0.25) : (e % 2 === 0 ? UI.Theme.surface2 : Estilo.alfa(UI.Theme.borde, 0.9))
                    ctx.fillRect(xa, ye, xb - xa - 1, bandaEtapa)
                    if (ultimo) { ctx.strokeStyle = UI.Theme.activo; ctx.lineWidth = 1; ctx.strokeRect(xa + 0.5, ye + 0.5, xb - xa - 2, bandaEtapa - 1) }
                    if (xb - xa > 18) {
                        ctx.fillStyle = ultimo ? UI.Theme.activo : UI.Theme.textoSuave
                        ctx.fillText("X" + e, (xa + xb) / 2, ye + bandaEtapa / 2 + 0.5)
                    }
                }
                for (i = 0; i < d.length; i++) {
                    var e = d[i][4]
                    if (e !== et) {
                        if (ini >= 0) tramo(ini, i, et, false)
                        // marca de inicio de ciclo: entrada a X1
                        if (e === 1 && i > 0) {
                            var xm = Math.round(X(d[i][0])) + 0.5
                            ctx.save(); ctx.strokeStyle = Estilo.alfa(UI.Theme.textoSuave, 0.5); ctx.setLineDash([3, 3])
                            ctx.beginPath(); ctx.moveTo(xm, 0); ctx.lineTo(xm, ye); ctx.stroke(); ctx.restore()
                        }
                        ini = i; et = e
                    }
                }
                if (ini >= 0 && d.length > 0) tramo(ini, d.length - 1, et, true)
            }
        }

        Item {
            Layout.fillHeight: true
            Layout.preferredWidth: anillo.width
            UI.AnilloProgreso {
                id: anillo
                anchors.centerIn: parent
                width: Math.min(root.compacto ? 104 : 124, parent.height - 16); height: width
                grosor: root.compacto ? 7 : 9
                valor: planta.ints.C_ACC || 0
                maximo: planta.ints.C_PRE || 0
                subtitulo: "CICLOS"
            }
            Text {
                anchors { top: anillo.bottom; horizontalCenter: anillo.horizontalCenter; topMargin: 2 }
                text: planta.direccion("C_ACC").split(".")[0]
                color: UI.Theme.textoSuave; opacity: 0.8
                font { family: UI.Theme.fuente; pixelSize: Estilo.micro; letterSpacing: 0.6 }
            }
        }
    }
}
