import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// GRAFCET nivel 2 (docs/TABLA_DE_VARIABLES.md sección 4) con 9 UI.EtapaGrafcet en dos columnas:
//   izquierda X0…X4, derecha X5…X8. Enlaces, transiciones y receptividades en un Canvas
//   que solo se repinta al cambiar el tamaño o la etapa activa.
//   · X4→X5 rodea la columna derecha por abajo y por la derecha (sube con flecha).
//   · Divergencia en O bajo X7: rama a X8 (C ≥ PRE) y rama de vuelta a X1 (C < PRE) que sube
//     por el canal central y converge encima de X1.
PanelHmi {
    id: root
    titulo: "GRAFCET"
    icono: "grafcet"
    atenuado: !planta.conectado
    subtitulo: planta.etapa >= 0 ? "etapa X" + planta.etapa + " · " + Estilo.num(planta.tEtapa, 1) + " s" : ""

    readonly property var etapas: planta.etapasDef
    readonly property var recep: planta.receptividades
    // En 1366 px la columna no da para la acción completa: se quitan palabras que ya dice el dibujo
    // (la barra del TON ya indica la espera). El texto completo sale en el ToolTip.
    function abreviar(s) { return s.replace("Espera ", "").replace("Ventana ", "").replace(" con ", " · ") }

    Item {
        id: lienzo
        anchors.fill: parent

        // ---------------- geometría
        readonly property real canal: root.compacto ? 32 : 40     // canal central (retorno X7→X1)
        readonly property real carrilDer: root.compacto ? 12 : 16 // carril exterior derecho (X4→X5)
        readonly property real sup: 10            // margen superior (carril de X4→X5)
        readonly property real inf: 22            // margen inferior (transición X4→X5 + carril)
        // Con poca altura (1366×768) las etapas se escalan hasta 0,8 para que las transiciones
        // conserven unos 18 px de hueco y sus receptividades no pisen los recuadros.
        readonly property real escala: Math.max(0.8, Math.min(1, (height - sup - inf - 26 - 3 * 18) / (5 * 44)))
        readonly property real altoEtapa: 44 * escala
        readonly property real anchoCol: Math.max(120, (width - canal - carrilDer) / 2)
        readonly property real libre: Math.max(32, height - sup - inf - 5 * altoEtapa)
        // el primer hueco lleva la transición X0→X1 y, debajo, la convergencia del retorno
        readonly property real hueco0: Math.max(24, libre / 4)
        readonly property real hueco: Math.max(6, (libre - hueco0) / 3)
        function colX(c) { return c === 0 ? 0 : anchoCol + canal }
        function filaY(f) { return sup + (f > 0 ? f * altoEtapa + hueco0 + (f - 1) * hueco : 0) }
        // columna y fila de cada etapa
        function col(n) { return n <= 4 ? 0 : 1 }
        function fila(n) { return n <= 4 ? n : n - 5 }
        function ejeX(n) { return colX(col(n)) + 22 * escala }             // eje del enlace = centro del número
        function arriba(n) { return filaY(fila(n)) }
        function abajo(n) { return filaY(fila(n)) + altoEtapa }
        readonly property real xCanal: colX(1) - 20
        readonly property real xDer: width - 6

        // posiciones de las transiciones (x del eje, y del trazo)
        function transicion(de, a) {
            if (de === 4) return { x: ejeX(4), y: abajo(4) + 8 }
            if (de === 7 && a === 8) return { x: ejeX(7), y: abajo(7) + Math.max(hueco * 0.6, 10) }
            if (de === 7 && a === 1) return { x: xCanal, y: abajo(7) + 6 - 18 }
            if (de === 0) return { x: ejeX(0), y: abajo(0) + Math.min(hueco0 * 0.34, 12) }
            if (de === 5) return { x: ejeX(5), y: abajo(5) + hueco0 / 2 }
            if (de === 8) return { x: ejeX(8), y: abajo(8) + 10 }
            return { x: ejeX(de), y: abajo(de) + hueco / 2 }
        }

        readonly property int activa: planta.etapa
        onActivaChanged: canvas.requestPaint()
        onWidthChanged: canvas.requestPaint()
        onHeightChanged: canvas.requestPaint()

        Canvas {
            id: canvas
            anchors.fill: parent
            antialiasing: true
            onPaint: {
                var L = lienzo
                var ctx = getContext("2d")
                ctx.reset()
                ctx.lineWidth = 1.5
                ctx.lineCap = "butt"
                var gris = UI.Theme.neutro
                ctx.strokeStyle = gris
                ctx.fillStyle = gris
                function linea(pts) {
                    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1])
                    for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1])
                    ctx.stroke()
                }
                function flechaArriba(x, y) {
                    ctx.beginPath(); ctx.moveTo(x, y - 5); ctx.lineTo(x - 4, y + 3); ctx.lineTo(x + 4, y + 3); ctx.closePath(); ctx.fill()
                }
                function flechaAbajo(x, y) {
                    ctx.beginPath(); ctx.moveTo(x, y + 5); ctx.lineTo(x - 4, y - 3); ctx.lineTo(x + 4, y - 3); ctx.closePath(); ctx.fill()
                }
                function trazo(t, activo) {
                    ctx.save()
                    ctx.strokeStyle = activo ? UI.Theme.activo : UI.Theme.texto
                    ctx.lineWidth = 3
                    ctx.beginPath(); ctx.moveTo(t.x - 8, t.y); ctx.lineTo(t.x + 8, t.y); ctx.stroke()
                    ctx.restore()
                }
                // columna izquierda X0…X4 y derecha X5…X7 (enlaces rectos)
                var n
                for (n = 0; n < 4; n++) linea([[L.ejeX(n), L.abajo(n)], [L.ejeX(n + 1), L.arriba(n + 1)]])
                for (n = 5; n < 7; n++) linea([[L.ejeX(n), L.abajo(n)], [L.ejeX(n + 1), L.arriba(n + 1)]])
                // X4 → X5: abajo, derecha, sube por el carril exterior, entra a X5 por arriba
                var yInf = L.height - 3, ySup = 5
                linea([[L.ejeX(4), L.abajo(4)], [L.ejeX(4), yInf], [L.xDer, yInf], [L.xDer, ySup],
                       [L.ejeX(5), ySup], [L.ejeX(5), L.arriba(5)]])
                flechaArriba(L.xDer, (yInf + ySup) / 2)
                flechaAbajo(L.ejeX(5), L.arriba(5) - 5)
                // divergencia en O bajo X7
                var yDiv = L.abajo(7) + 6
                linea([[L.ejeX(7), L.abajo(7)], [L.ejeX(7), yDiv]])
                linea([[L.xCanal, yDiv], [L.ejeX(7) + 14, yDiv]])
                linea([[L.ejeX(7), yDiv], [L.ejeX(8), L.arriba(8)]])
                // rama X7 → X1: sube por el canal y converge encima de X1
                var yConv = L.arriba(1) - Math.max(4, L.hueco0 * 0.2)
                linea([[L.xCanal, yDiv], [L.xCanal, yConv], [L.ejeX(1), yConv]])
                ctx.beginPath(); ctx.arc(L.ejeX(1), yConv, 2.5, 0, 2 * Math.PI); ctx.fill()
                flechaArriba(L.xCanal, yConv + 14)
                // X8 → GS (forzado a X0): trazo corto sin continuación
                linea([[L.ejeX(8), L.abajo(8)], [L.ejeX(8), L.abajo(8) + 14]])

                // transiciones: la(s) de salida de la etapa activa en ámbar
                for (var i = 0; i < root.recep.length; i++) {
                    var r = root.recep[i]
                    if (r.de === 8) continue
                    var t = L.transicion(r.de, r.a)
                    if (r.de === 7 && r.a === 1) {   // trazo horizontal sobre el canal vertical
                        ctx.save(); ctx.strokeStyle = (L.activa === 7) ? UI.Theme.activo : UI.Theme.texto; ctx.lineWidth = 3
                        ctx.beginPath(); ctx.moveTo(t.x - 8, t.y); ctx.lineTo(t.x + 8, t.y); ctx.stroke(); ctx.restore()
                    } else {
                        trazo(t, L.activa === r.de)
                    }
                }
            }
        }

        // etapas
        Repeater {
            model: root.etapas
            UI.EtapaGrafcet {
                x: lienzo.colX(lienzo.col(modelData.numero))
                y: lienzo.arriba(modelData.numero)
                width: lienzo.anchoCol / lienzo.escala
                height: 44
                scale: lienzo.escala
                transformOrigin: Item.TopLeft
                numero: modelData.numero
                accion: root.compacto ? root.abreviar(modelData.accion) : modelData.accion
                ToolTip.visible: maEtapa.containsMouse
                ToolTip.delay: 300
                ToolTip.text: "X" + modelData.numero + " · " + modelData.accion
                MouseArea { id: maEtapa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                activa: planta.etapa === modelData.numero
                conTemporizador: modelData.timer >= 0
                progreso: modelData.timer >= 0 && (planta.ints[modelData.tagPre] || 0) > 0
                          ? (planta.ints[modelData.tagAcc] || 0) / planta.ints[modelData.tagPre] : 0
            }
        }

        // receptividades
        Repeater {
            model: root.recep
            Text {
                readonly property var t: lienzo.transicion(modelData.de, modelData.a)
                readonly property bool esCanal: modelData.de === 7 && modelData.a === 1
                readonly property bool pendiente: planta.etapa === modelData.de
                x: esCanal ? t.x + 3 : t.x + 13
                y: esCanal ? t.y - 8 : t.y - height / 2
                transformOrigin: Item.TopLeft
                rotation: esCanal ? -90 : 0
                text: modelData.de === 8 ? "GS → X0 · RES contador" : modelData.texto
                color: pendiente ? UI.Theme.activo : UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: pendiente ? Font.DemiBold : Font.Medium } Component.onCompleted: Estilo.cifrasTabulares(this)
            }
        }
    }
}
