import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Campo de texto con etiqueta a la izquierda, estilo del HMI (ventana de conexión).
// Sincronización manual en los dos sentidos: `texto` viene del modelo (conexion.*) y `editado(valor)`
// se emite solo cuando escribe el usuario (textEdited), así una relectura del modelo no pisa lo
// que se está tecleando ni el binding se rompe al editar.
Item {
    id: root
    property string etiqueta: ""
    property int anchoEtiqueta: 0              // 0 = ancho natural
    property string texto: ""
    property string marcador: ""               // placeholder
    property bool habilitado: true
    property bool mono: false                  // Consolas (rutas, URLs, endpoints)
    property bool numerico: false
    property bool secreto: false               // contraseñas y claves: no se muestran al escribir
    property int anchoCampo: 0                 // 0 = ocupa lo que queda
    signal editado(string valor)
    signal aceptado(string valor)
    function textoActual() { return campo.text }
    function limpiar() { campo.text = "" }
    implicitHeight: 28
    implicitWidth: fila.implicitWidth
    opacity: habilitado ? 1 : 0.5

    // cursorPosition = 0: sin esto un texto largo asignado desde el modelo queda desplazado al final
    onTextoChanged: if (campo.text !== texto) { campo.text = texto; if (!campo.activeFocus) campo.cursorPosition = 0 }
    Component.onCompleted: { campo.text = texto; campo.cursorPosition = 0 }

    RowLayout {
        id: fila
        anchors.fill: parent
        spacing: 6
        Text {
            visible: root.etiqueta !== ""
            Layout.preferredWidth: root.anchoEtiqueta > 0 ? root.anchoEtiqueta : implicitWidth
            text: root.etiqueta
            color: UI.Theme.textoSuave
            elide: Text.ElideRight
            font { family: UI.Theme.fuente; pixelSize: Estilo.chico; weight: Font.Medium }
        }
        TextField {
            id: campo
            Layout.fillWidth: root.anchoCampo === 0
            Layout.preferredWidth: root.anchoCampo > 0 ? root.anchoCampo : -1
            Layout.preferredHeight: 28
            enabled: root.habilitado
            color: UI.Theme.texto
            placeholderText: root.marcador
            placeholderTextColor: Estilo.alfa(UI.Theme.textoSuave, 0.6)
            selectByMouse: true
            echoMode: root.secreto ? TextInput.Password : TextInput.Normal
            leftPadding: 7; rightPadding: 7; topPadding: 0; bottomPadding: 0
            verticalAlignment: TextInput.AlignVCenter
            horizontalAlignment: root.numerico ? TextInput.AlignRight : TextInput.AlignLeft
            font { family: root.mono ? Estilo.mono : UI.Theme.fuente; pixelSize: 12 }
            selectionColor: Estilo.alfa(UI.Theme.aire, 0.5)
            selectedTextColor: UI.Theme.texto
            background: Rectangle {
                radius: 6; color: UI.Theme.fondo
                border.color: campo.activeFocus ? UI.Theme.aire : UI.Theme.borde
                border.width: 1
            }
            onTextEdited: root.editado(text)
            onAccepted: root.aceptado(text)
        }
    }
}
