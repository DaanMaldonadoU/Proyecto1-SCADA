import QtQuick 2.15
import "." as UI

// Anillo de progreso (contador de ciclos C5:0.ACC / PRE, o tiempo de una etapa).
Item {
    id: root
    property real valor: 0
    property real maximo: 3
    property string texto: Math.round(valor) + " / " + Math.round(maximo)
    property string subtitulo: "ciclos"
    property color colorArco: UI.Theme.aire
    property int grosor: 9
    width: 120; height: 120
    onValorChanged: lienzo.requestPaint()
    onMaximoChanged: lienzo.requestPaint()

    Canvas {
        id: lienzo; anchors.fill: parent; antialiasing: true
        onPaint: {
            var ctx = getContext("2d"); ctx.reset();
            var cx = width/2, cy = height/2, r = Math.min(width, height)/2 - root.grosor;
            var f = root.maximo > 0 ? Math.max(0, Math.min(1, root.valor / root.maximo)) : 0;
            ctx.lineWidth = root.grosor; ctx.lineCap = "round";
            ctx.strokeStyle = UI.Theme.borde; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2*Math.PI); ctx.stroke();
            if (f > 0) { ctx.strokeStyle = root.colorArco; ctx.beginPath();
                         ctx.arc(cx, cy, r, -Math.PI/2, -Math.PI/2 + 2*Math.PI*f); ctx.stroke(); }
        }
    }
    Column {
        anchors.centerIn: parent; spacing: 0
        Text { text: root.texto; color: UI.Theme.texto; anchors.horizontalCenter: parent.horizontalCenter
               font { family: UI.Theme.fuente; pixelSize: 22; weight: Font.DemiBold } }
        Text { text: root.subtitulo; color: UI.Theme.textoSuave; anchors.horizontalCenter: parent.horizontalCenter
               font { family: UI.Theme.fuente; pixelSize: 11; weight: Font.Medium; letterSpacing: 0.8 } }
    }
}
