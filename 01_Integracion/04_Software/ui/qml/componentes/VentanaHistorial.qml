import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Visor del historial del gateway (datos/historial.sqlite): ventana aparte, no modal.
// Pestañas Eventos / Alarmas / Escrituras, barra de filtros (rango rápido, nivel, texto, tag,
// solo activas / solo fallidas), tabla con cabecera fija y filas alternas, contador, Actualizar y
// Exportar CSV. Habla con el QObject `historial` (ui/historial.py); aquí no hay SQL.
// Mismo QML para Qt 5.15 y Qt 6 (ARQUITECTURA 6.3): sin API exclusiva de Qt 6.
ApplicationWindow {
    id: root
    objectName: "ventanaHistorial"
    title: "Historial · " + (datosInstitucion.proyecto || "HMI")
    minimumWidth: 900
    minimumHeight: 600
    width: 1100
    height: 680
    color: UI.Theme.fondo
    font.family: UI.Theme.fuente
    modality: Qt.NonModal
    visible: false

    property int rango: 1                                   // horas del rango rápido; 0 = todo
    readonly property string tabla: historial.tabla
    readonly property int altoFila: 26
    readonly property int margenFila: 14

    // Columnas por pestaña: t = título, r = rol del modelo, w = ancho fijo (0 = la que se estira)
    readonly property var colEventos: [
        { t: "Fecha", r: "fecha", w: 92 }, { t: "Hora", r: "hora", w: 104 }, { t: "Nivel", r: "nivel", w: 72 },
        { t: "Origen", r: "origen", w: 130 }, { t: "Mensaje", r: "msg", w: 0 } ]
    readonly property var colAlarmas: [
        { t: "Fecha", r: "fecha", w: 92 }, { t: "Inicio", r: "tIni", w: 104 }, { t: "Fin", r: "tFin", w: 104 },
        { t: "Duración", r: "duracion", w: 100 }, { t: "Nivel", r: "nivel", w: 72 }, { t: "Alarma", r: "id", w: 140 },
        { t: "Mensaje", r: "msg", w: 0 } ]
    readonly property var colEscrituras: [
        { t: "Fecha", r: "fecha", w: 92 }, { t: "Hora", r: "hora", w: 104 }, { t: "Tag", r: "tag", w: 110 },
        { t: "Valor", r: "valor", w: 84 }, { t: "Resultado", r: "ok", w: 96 }, { t: "Quién", r: "origen", w: 150 },
        { t: "Detalle", r: "msg", w: 0 } ]
    readonly property var columnas: tabla === "alarmas" ? colAlarmas : (tabla === "escrituras" ? colEscrituras : colEventos)
    function anchoFijo() { var s = 0; for (var i = 0; i < columnas.length; i++) s += columnas[i].w; return s }
    function anchoColumna(w, total) { return w > 0 ? w : Math.max(120, total - margenFila - 8 - anchoFijo()) }
    function esMono(r) { return r === "hora" || r === "tIni" || r === "tFin" || r === "fecha" || r === "valor" || r === "duracion" }

    function tono(n) { return n === "alarma" ? UI.Theme.alarma : (n === "aviso" ? UI.Theme.activo : UI.Theme.neutro) }
    function cambiarTabla(t) { if (historial.tabla !== t) { historial.tabla = t; historial.consultar() } }
    function fijarRango(h) { rango = h; historial.ultimas(h) }
    function alternarNivel(n) {
        var lista = historial.niveles.slice()
        var i = lista.indexOf(n)
        if (i >= 0) lista.splice(i, 1); else lista.push(n)
        historial.niveles = lista
        historial.consultar()
    }

    // Al mostrarse por primera vez: última hora.
    onVisibleChanged: if (visible && historial.filas.cuenta === 0) fijarRango(rango)

    ColumnLayout {
        anchors { fill: parent; margins: UI.Theme.espL }
        spacing: UI.Theme.espM

        // ------------------------------------------------------------ cabecera: título, pestañas, resumen
        RowLayout {
            Layout.fillWidth: true
            spacing: UI.Theme.espM
            Image {
                source: rutaAssets + "ui/iconos/registro" + (UI.Theme.sufijoIcono || "_claro") + ".svg"
                sourceSize: Qt.size(22, 22); width: 22; height: 22; opacity: 0.85
            }
            Text {
                text: "HISTORIAL"
                color: UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: UI.Theme.seccion; weight: Font.DemiBold; letterSpacing: 1.1 }
            }
            Rectangle { width: 1; height: 22; color: UI.Theme.borde }
            Row {
                spacing: 6
                Chip { texto: "Eventos · " + (historial.resumen.eventos || 0); tono: UI.Theme.aire
                       marcado: root.tabla === "eventos"; onPulsado: root.cambiarTabla("eventos") }
                Chip { texto: "Alarmas · " + (historial.resumen.alarmas || 0); tono: UI.Theme.aire
                       marcado: root.tabla === "alarmas"; onPulsado: root.cambiarTabla("alarmas") }
                Chip { texto: "Escrituras · " + (historial.resumen.escrituras || 0); tono: UI.Theme.aire
                       marcado: root.tabla === "escrituras"; onPulsado: root.cambiarTabla("escrituras") }
            }
            Item { Layout.fillWidth: true }
            Text {
                Layout.maximumWidth: 420
                elide: Text.ElideLeft
                visible: historial.resumen.desdeTexto !== undefined && historial.resumen.desdeTexto !== ""
                text: "Base: " + (historial.resumen.desdeTexto || "") + "  →  " + (historial.resumen.hastaTexto || "")
                color: UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
                Component.onCompleted: Estilo.cifrasTabulares(this)
            }
        }

        // ------------------------------------------------------------ barra de filtros
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: filtros.implicitHeight + 2 * UI.Theme.espM
            color: UI.Theme.surface
            radius: UI.Theme.radioPanel
            border.color: UI.Theme.borde
            border.width: 1

            RowLayout {
                id: filtros
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: UI.Theme.espM }
                spacing: UI.Theme.espM

                Text {
                    text: "Rango"
                    color: UI.Theme.textoSuave
                    font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.DemiBold; letterSpacing: 0.6 }
                }
                Row {
                    spacing: 6
                    Repeater {
                        model: [{ h: 1, t: "1 h" }, { h: 8, t: "8 h" }, { h: 24, t: "24 h" }, { h: 0, t: "Todo" }]
                        Chip {
                            texto: modelData.t; tono: UI.Theme.aire
                            marcado: root.rango === modelData.h
                            onPulsado: root.fijarRango(modelData.h)
                        }
                    }
                }
                Rectangle { width: 1; height: 22; color: UI.Theme.borde; visible: root.tabla !== "escrituras" }
                Row {
                    visible: root.tabla !== "escrituras"
                    spacing: 6
                    Repeater {
                        model: [{ n: "info", t: "Info" }, { n: "aviso", t: "Aviso" }, { n: "alarma", t: "Alarma" }]
                        Chip {
                            texto: modelData.t
                            // ISA-101: el chip solo toma color de estado para aviso y alarma
                            tono: modelData.n === "info" ? UI.Theme.textoSuave : root.tono(modelData.n)
                            marcado: historial.niveles.indexOf(modelData.n) >= 0
                            onPulsado: root.alternarNivel(modelData.n)
                        }
                    }
                }
                Chip {
                    visible: root.tabla === "alarmas"
                    texto: "Solo activas"; tono: UI.Theme.alarma
                    marcado: historial.soloActivas
                    onPulsado: { historial.soloActivas = !historial.soloActivas; historial.consultar() }
                }
                Chip {
                    visible: root.tabla === "escrituras"
                    texto: "Solo fallidas"; tono: UI.Theme.alarma
                    marcado: historial.soloFallidas
                    onPulsado: { historial.soloFallidas = !historial.soloFallidas; historial.consultar() }
                }
                Rectangle { width: 1; height: 22; color: UI.Theme.borde }
                TextField {
                    id: campoTag
                    visible: root.tabla === "escrituras"
                    Layout.preferredWidth: 150
                    Layout.preferredHeight: 28
                    placeholderText: "Tag (T_ESPERA, STARTV…)"
                    placeholderTextColor: UI.Theme.textoSuave
                    color: UI.Theme.texto
                    selectByMouse: true
                    text: historial.tag
                    font { family: UI.Theme.fuente; pixelSize: 12 }
                    leftPadding: 8; rightPadding: 8
                    background: Rectangle {
                        radius: 6; color: UI.Theme.fondo
                        border.color: campoTag.activeFocus ? UI.Theme.aire : UI.Theme.borde
                    }
                    onTextEdited: historial.tag = text
                    onAccepted: historial.consultar()
                }
                TextField {
                    id: campoTexto
                    Layout.fillWidth: true
                    Layout.minimumWidth: 120
                    Layout.preferredHeight: 28
                    placeholderText: root.tabla === "alarmas" ? "Buscar en mensaje o id…" : "Buscar en el mensaje…"
                    placeholderTextColor: UI.Theme.textoSuave
                    color: UI.Theme.texto
                    selectByMouse: true
                    text: historial.texto
                    font { family: UI.Theme.fuente; pixelSize: 12 }
                    leftPadding: 8; rightPadding: 8
                    background: Rectangle {
                        radius: 6; color: UI.Theme.fondo
                        border.color: campoTexto.activeFocus ? UI.Theme.aire : UI.Theme.borde
                    }
                    onTextEdited: historial.texto = text
                    onAccepted: historial.consultar()
                }
                BotonMini { texto: "Buscar"; onPulsado: historial.consultar() }
            }
        }

        // ------------------------------------------------------------ tabla
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: UI.Theme.surface
            radius: UI.Theme.radioPanel
            border.color: UI.Theme.borde
            border.width: 1
            clip: true

            Item {
                id: cabecera
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                height: 30
                // Fondo con las esquinas superiores redondeadas sin topLeftRadius (Qt 6.7+): un
                // rectángulo redondeado y otro recto que tapa la mitad inferior.
                Rectangle { anchors.fill: parent; radius: UI.Theme.radioPanel; color: UI.Theme.surface2 }
                Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                            height: parent.height / 2; color: UI.Theme.surface2 }
                Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                            height: 1; color: UI.Theme.borde }
                Row {
                    anchors { fill: parent; leftMargin: root.margenFila; rightMargin: 8 }
                    Repeater {
                        model: root.columnas
                        Text {
                            width: root.anchoColumna(modelData.w, cabecera.width)
                            height: cabecera.height
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: modelData.t.toUpperCase()
                            color: UI.Theme.textoSuave
                            font { family: UI.Theme.fuente; pixelSize: Estilo.micro; weight: Font.DemiBold; letterSpacing: 0.8 }
                        }
                    }
                }
            }

            ListView {
                id: lista
                anchors { left: parent.left; right: parent.right; top: cabecera.bottom; bottom: parent.bottom; margins: 1 }
                clip: true
                model: historial.filas
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 5; radius: 2.5; color: UI.Theme.borde }
                }
                delegate: Item {
                    id: fila
                    width: lista.width
                    height: root.altoFila
                    // Los roles se leen por nombre (`model.x`): `id` es palabra reservada de QML.
                    function celda(r) {
                        switch (r) {
                        case "fecha": return model.fecha
                        case "hora": return model.hora
                        case "nivel": return String(model.nivel).toUpperCase()
                        case "origen": return model.origen
                        case "msg": return model.msg
                        case "id": return model.id
                        case "tIni": return model.tIni
                        case "tFin": return model.tFin
                        case "duracion": return model.duracion
                        case "tag": return model.tag
                        case "valor": return model.valor
                        case "ok": return model.ok ? "OK" : "RECHAZADA"
                        }
                        return ""
                    }
                    function colorCelda(r) {
                        if (r === "nivel") return model.nivel === "info" ? UI.Theme.textoSuave : root.tono(model.nivel)
                        if (r === "ok") return model.ok ? UI.Theme.ok : UI.Theme.alarma
                        if (r === "tFin") return model.tFin === "activa" ? UI.Theme.alarma : UI.Theme.textoSuave
                        if (r === "msg") return model.nivel === "info" ? UI.Theme.texto : root.tono(model.nivel)
                        if (r === "tag" || r === "valor" || r === "id") return UI.Theme.texto
                        return UI.Theme.textoSuave
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: index % 2 === 0 ? "transparent" : Estilo.alfa(UI.Theme.surface2, 0.6)
                    }
                    Rectangle {   // marca de nivel (o de resultado en escrituras)
                        width: 3; height: parent.height - 8; radius: 1.5; x: 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.tabla === "escrituras" ? (model.ok ? UI.Theme.ok : UI.Theme.alarma) : root.tono(model.nivel)
                    }
                    Row {
                        anchors { fill: parent; leftMargin: root.margenFila; rightMargin: 8 }
                        Repeater {
                            model: root.columnas
                            Text {
                                width: root.anchoColumna(modelData.w, fila.width)
                                height: fila.height
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                text: fila.celda(modelData.r)
                                color: fila.colorCelda(modelData.r)
                                font {
                                    family: root.esMono(modelData.r) ? Estilo.mono : UI.Theme.fuente
                                    pixelSize: root.esMono(modelData.r) ? 11 : 12
                                    weight: (modelData.r === "nivel" || modelData.r === "ok") ? Font.Bold : Font.Normal
                                    letterSpacing: (modelData.r === "nivel" || modelData.r === "ok") ? 0.6 : 0
                                }
                            }
                        }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    visible: lista.count === 0
                    text: historial.error !== "" ? "Sin datos: no se pudo leer la base" : "Sin filas para estos filtros"
                    color: UI.Theme.textoSuave
                    font { family: UI.Theme.fuente; pixelSize: 12 }
                }
            }
        }

        // ------------------------------------------------------------ pie: contador, exporte, botones
        RowLayout {
            Layout.fillWidth: true
            spacing: UI.Theme.espM
            Text {
                text: historial.filas.cuenta + " filas · total en la base: " + historial.total
                color: UI.Theme.texto
                font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium }
                Component.onCompleted: Estilo.cifrasTabulares(this)
            }
            Text {
                visible: historial.consultaMs > 0
                text: "· consulta en " + Estilo.num(historial.consultaMs, 1) + " ms"
                color: UI.Theme.textoSuave
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
                Component.onCompleted: Estilo.cifrasTabulares(this)
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideMiddle
                text: historial.ultimoExporte !== "" ? "CSV guardado en " + historial.ultimoExporte : ""
                color: UI.Theme.ok
                font { family: UI.Theme.fuente; pixelSize: Estilo.chico }
            }
            BotonMini { texto: "Actualizar"; onPulsado: historial.consultar() }
            BotonMini {
                texto: "Exportar CSV"; primario: true
                habilitado: historial.filas.cuenta > 0
                onPulsado: historial.exportarCsv()
            }
            BotonMini { texto: "Cerrar"; onPulsado: root.close() }
        }

        // ------------------------------------------------------------ línea de estado
        Text {
            Layout.fillWidth: true
            elide: Text.ElideMiddle
            text: historial.error !== "" ? "Error: " + historial.error
                                         : "Base de datos: " + historial.ruta + "  (solo lectura; la escribe el gateway)"
            color: historial.error !== "" ? UI.Theme.alarma : UI.Theme.textoSuave
            font { family: UI.Theme.fuente; pixelSize: Estilo.micro }
        }
    }
}
