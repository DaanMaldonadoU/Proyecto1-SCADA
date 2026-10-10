import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Cilindro de doble efecto 1A/2A/3A (ISO 15552 ø32 × 200), a partir del Cilindro.qml del usuario.
//  · Capas iso15552_d32 con corte, cámara presurizada azul en la cámara de la bobina energizada.
//  · Sensores SC/SE en las coordenadas de geometria.json; bobinas EV_E/EV_C con LED ámbar
//    sobre el racor de la cámara que alimentan.
//  · Animación:
//      - `pos` del gateway (SIM/EMULATE): Behavior de 150 ms que solo alisa el muestreo.
//      - REAL (posición estimada): NumberAnimation hacia `objetivo` con la duración calibrada que
//        arranca con cada carrera; al terminar la carrera (flanco moviendo 1→0) salta al extremo.
//      - Modo suave (`suave`, core/suavizado.py): Python ya entrega la posición animada en cada vuelta
//        de 15 ms, así que se dibuja tal cual, sin Behavior ni animación propia. `discrepancia` = el
//        sensor contradice a las bobinas desde hace rato (sin aire, atascado): se avisa.
Item {
    id: root
    property int numero: 1
    property real posicion: 0
    property bool posEstimada: false
    property bool suave: false
    property bool discrepancia: false
    property var carrera: ({})
    property var calib: ({})
    property bool sc: false
    property bool se: false
    property bool evE: false
    property bool evC: false
    property string tagEvE: "EV_E" + numero
    property string tagEvC: "EV_C" + numero
    property string tagSc: "SC" + numero
    property string tagSe: "SE" + numero
    property bool compacto: false

    // --- geometría iso15552_d32/geometria.json
    readonly property real vbW: 580
    readonly property real vbH: 78
    readonly property real puertoTraseroX: 22      // racor trasero (camisa.svg)
    readonly property real puertoDelanteroX: 288   // racor delantero
    readonly property int infoAncho: compacto ? 84 : 104
    readonly property int franjaSup: compacto ? 16 : 20
    readonly property int franjaInf: compacto ? 13 : 16
    readonly property real anchoGrafico: Math.max(120, Math.min(width - infoAncho - 8, (height - franjaSup - franjaInf) * vbW / vbH))

    // ------------------------------------------------------------------ animación del vástago
    property real posVista: 0
    property bool _movAnt: false
    property real _objAnt: -1
    property bool sinConfirmar: false

    Behavior on posVista { enabled: !root.posEstimada && !root.suave; NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }
    onPosicionChanged: if (!posEstimada || suave) posVista = posicion
    onPosEstimadaChanged: { animCal.stop(); posVista = posicion }
    onSuaveChanged: { animCal.stop(); animSalto.stop(); posVista = posicion }
    Component.onCompleted: posVista = posicion

    NumberAnimation { id: animCal; target: root; property: "posVista"; easing.type: Easing.Linear }
    NumberAnimation { id: animSalto; target: root; property: "posVista"; duration: 140; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
    Timer { id: tSinConf; interval: 5000; onTriggered: root.sinConfirmar = false }

    onCarreraChanged: {
        var c = carrera
        if (!c || c.objetivo === undefined) return
        if (c.timeout) { sinConfirmar = true; tSinConf.restart() }
        if (!posEstimada || suave) { _movAnt = c.moviendo; _objAnt = c.objetivo; return }
        if (c.moviendo) {
            if (!_movAnt || c.objetivo !== _objAnt) {      // nueva carrera: animación calibrada
                animSalto.stop(); animCal.stop()
                animCal.from = posVista; animCal.to = c.objetivo
                animCal.duration = Math.max(1, c.duracion_ms * Math.abs(c.objetivo - posVista))
                animCal.start()
            }
        } else if (Math.abs(posVista - c.pos) > 0.002 && !animSalto.running) {
            animCal.stop()                                  // llegó el sensor (o timeout): ajuste visual
            animSalto.from = posVista; animSalto.to = c.pos; animSalto.start()
        }
        _movAnt = c.moviendo; _objAnt = c.objetivo
    }

    function msCal(dir) {
        if (!calib || !calib[dir] || calib[dir].ms === undefined) return "—"
        return Estilo.seg(calib[dir].ms, 2)
    }

    // ------------------------------------------------------------------ columna de información
    Column {
        id: info
        width: root.infoAncho
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        spacing: root.compacto ? 1 : 3
        Row {
            spacing: 6
            Text { text: root.numero + "A"; color: UI.Theme.texto
                   font { family: UI.Theme.fuente; pixelSize: root.compacto ? 20 : 24; weight: Font.Bold } }
            Text { y: root.compacto ? 7 : 9
                   text: Math.round(root.posVista * 100) + " %"
                   color: UI.Theme.textoSuave
                   font { family: UI.Theme.fuente; pixelSize: 12 } Component.onCompleted: Estilo.cifrasTabulares(this) }
        }
        Text { text: "doble efecto"; color: UI.Theme.textoSuave
               font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.Medium; letterSpacing: 0.4 } }
        Text { text: "ext " + root.msCal("ext"); color: UI.Theme.textoSuave; visible: root.height > 70
               font { family: UI.Theme.fuente; pixelSize: Estilo.chico } Component.onCompleted: Estilo.cifrasTabulares(this) }
        Text { text: "ret " + root.msCal("ret"); color: UI.Theme.textoSuave; visible: root.height > 70
               font { family: UI.Theme.fuente; pixelSize: Estilo.chico } Component.onCompleted: Estilo.cifrasTabulares(this) }
        Text { visible: root.sinConfirmar || root.discrepancia; text: "sin confirmación"; color: UI.Theme.activo
               font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.DemiBold } }
    }

    // ------------------------------------------------------------------ gráfico
    Item {
        id: zona
        x: root.infoAncho + 8
        width: root.anchoGrafico
        height: root.franjaSup + capas.height + root.franjaInf
        anchors.verticalCenter: parent.verticalCenter

        // bobinas sobre los racores
        Repeater {
            model: [{ px: root.puertoTraseroX, tag: root.tagEvE, on: root.evE },
                    { px: root.puertoDelanteroX, tag: root.tagEvC, on: root.evC }]
            UI.Led {
                x: modelData.px * capas.ppm - tam / 2
                y: 0
                tam: root.compacto ? 12 : 14
                color: "activo"; encendido: modelData.on
                etiqueta: modelData.tag
            }
        }
        CapasCilindro {
            id: capas
            y: root.franjaSup
            width: root.anchoGrafico; height: width * root.vbH / root.vbW
            carpeta: rutaAssets + "iso15552_d32"
            posicion: root.posVista
            sc: root.sc; se: root.se
            camaraTrasera: root.evE && !root.evC
            camaraDelantera: root.evC && !root.evE
        }
        // etiquetas de sensores bajo cada sensor
        Repeater {
            model: [{ cx: capas.scX, tag: root.tagSc, on: root.sc }, { cx: capas.seX, tag: root.tagSe, on: root.se }]
            Text {
                x: modelData.cx * capas.ppm - width / 2
                y: capas.y + capas.height - 2
                text: modelData.tag
                color: modelData.on ? UI.Theme.activo : UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: root.compacto ? 10 : 11; weight: modelData.on ? Font.Bold : Font.Medium }
            }
        }
    }
}
