import QtQuick 2.15
import QtQuick.Controls 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Franja de mando (core.mando): quién puede escribir en el PLC ahora mismo.
//   · Interruptor «Web»: habilita o deshabilita el mando remoto (solo el HMI local puede).
//   · LED de enlace: el puente web está vivo (la presencia llega cada 5 s).
//   · Titular del mando y segundos para que venza; en ámbar si lo tiene alguien en la web.
//   · Tomar / Liberar: el HMI local manda sobre la web; liberar deja pedirlo desde la web.
//   · El número junto al LED = personas en línea; el tooltip dice quién y con qué rol.
//   · Tooltip de la franja: la última orden que escribió (quién, qué, cuándo, resultado).
Item {
    id: root
    readonly property var m: planta.mando || ({})
    readonly property bool hayDato: planta.gatewayVivo && m.remotoHabilitado !== undefined
    readonly property bool web: hayDato && !m.libre && !m.titularLocal
    implicitHeight: 28

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: root.web ? Estilo.alfa(UI.Theme.activo, 0.10) : UI.Theme.surface2
        border.color: root.web ? UI.Theme.activo : UI.Theme.borde
        border.width: 1
    }

    Row {
        id: fila
        anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
        spacing: 10
        Interruptor {
            anchors.verticalCenter: parent.verticalCenter
            textoDer: "Web"
            marcado: root.hayDato && root.m.remotoHabilitado === true
            habilitado: root.hayDato
            onConmutado: planta.remotoHabilitar(valor)
        }
        Item {
            id: enlace
            anchors.verticalCenter: parent.verticalCenter
            width: led.width; height: 20
            readonly property int n: root.m.conectados ? root.m.conectados.length : 0
            UI.Led {
                id: led
                anchors.verticalCenter: parent.verticalCenter
                tam: 10; color: "ok"; encendido: root.hayDato && root.m.enlaceWeb === true
                etiqueta: root.hayDato && root.m.enlaceWeb === true ? String(enlace.n) : "—"
            }
            MouseArea { id: areaEnlace; anchors.fill: parent; hoverEnabled: true }
            ToolTip.visible: areaEnlace.containsMouse
            ToolTip.text: {
                if (!root.hayDato || root.m.enlaceWeb !== true)
                    return "Enlace web caído (sin noticias del puente)"
                var l = root.m.conectados || []
                var s = ["Enlace web activo · " + l.length + " en línea"]
                for (var i = 0; i < l.length; i++)
                    s.push(l[i].usuario + " · " + l[i].rol + " · desde " + l[i].desde)
                return s.join("
")
            }
        }
        Text {
            id: titular
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(40, root.width - fila.x - x - boton.width - 16)
            elide: Text.ElideRight
            color: root.web ? UI.Theme.activo : UI.Theme.texto
            font { family: UI.Theme.fuente; pixelSize: 12; weight: Font.Medium }
            text: !root.hayDato ? "Mando —"
                : root.m.libre ? "Mando libre"
                : root.m.titularLocal ? "HMI local · " + Math.round(root.m.venceEnS) + " s"
                : root.m.titularUsuario + " (" + root.m.titularRol + ") " + Math.round(root.m.venceEnS) + " s"
            Component.onCompleted: Estilo.cifrasTabulares(this)
        }
    }

    // Un solo botón: si el mando es del HMI local, «Liberar»; si es de la web o está libre, «Tomar».
    BotonMini {
        id: boton
        anchors { right: parent.right; rightMargin: 3; verticalCenter: parent.verticalCenter }
        implicitHeight: 22
        visible: root.hayDato
        texto: root.m.titularLocal ? "Liberar" : "Tomar"
        habilitado: planta.gatewayVivo
        onPulsado: root.m.titularLocal ? planta.mandoLiberar() : planta.mandoTomar()
    }

    ToolTip.visible: areaFranja.containsMouse && root.m.ultimaTexto !== undefined && root.m.ultimaTexto !== ""
    ToolTip.text: "Última orden: " + (root.m.ultimaTexto || "")
    MouseArea { id: areaFranja; anchors.fill: fila; hoverEnabled: true; acceptedButtons: Qt.NoButton; z: -1 }
}
