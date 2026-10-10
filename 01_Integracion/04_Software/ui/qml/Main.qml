import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15
import "../../assets/assets_cilindros/ui/qml" as UI
import "componentes"

// Ventana principal del HMI. La pantalla en sí está en PantallaHmi.qml (un Item, para poder
// editarla en Qt Design Studio); aquí quedan solo el tamaño, la pantalla completa y la ventana
// de conexión.
ApplicationWindow {
    id: ventana
    width: configVentana.ancho
    height: configVentana.alto
    minimumWidth: 1280
    minimumHeight: 720
    visible: true
    visibility: configVentana.pantallaCompleta ? Window.FullScreen : Window.Windowed
    color: UI.Theme.fondo
    title: (datosInstitucion.proyecto || "HMI") + " · HMI"
    font.family: UI.Theme.fuente

    // Tema de pantalla (oscuro | gris ISA-101): ui/app.py hace que UI.Theme sea ui/qml/tema/Theme.qml,
    // que tiene `variante`. Sin ese Theme (Qt Design Studio) la propiedad no existe y no se enlaza.
    Binding { target: UI.Theme; property: "variante"; value: planta.tema; when: UI.Theme.variante !== undefined }

    // Ventana de conexión (ARQUITECTURA.md 6.4): aparte y no modal. Se abre desde la cabecera y,
    // sola, si a los 2 s de arrancar no hay gateway vivo (salvo --lanzar-gateway / --gateway-falso / --sin-conexion).
    VentanaConexion { id: ventanaConexion }
    function abrirConexion() {
        ventanaConexion.show()
        if (Qt.platform.pluginName !== "offscreen")   // la plataforma offscreen (capturas) avisa que no soporta raise()
            ventanaConexion.raise()
        ventanaConexion.requestActivate()
    }
    Timer {
        interval: 2000; running: true; repeat: false
        onTriggered: if (conexion.autoAbrir && !planta.gatewayVivo) ventana.abrirConexion()
    }

    PantallaHmi {
        anchors.fill: parent
        onConexionPedida: ventana.abrirConexion()
    }
}
