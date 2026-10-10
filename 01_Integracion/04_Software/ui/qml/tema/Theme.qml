pragma Singleton
import QtQuick 2.15

// Tokens del sistema de diseño con DOS variantes de pantalla (sesión 14).
//
// El sistema de diseño del usuario (assets/assets_cilindros/ui/qml/Theme.qml) es de solo lectura y sus
// colores son `readonly`: no se pueden cambiar en marcha. ui/app.py instala un interceptor de URL que
// hace que el motor QML cargue ESTE archivo cuando cualquier QML (el HMI o los componentes del sistema
// de diseño: Led, AnilloProgreso, EtapaGrafcet…) pide aquel Theme.qml. Así nada se copia ni se toca en
// assets/, y `UI.Theme` sigue siendo el único origen de colores.
//
//   variante "oscuro": exactamente los valores del sistema de diseño (por defecto).
//   variante "gris":   fondo gris claro de baja saturación, texto oscuro (criterio ISA-101: la pantalla
//                      en reposo es gris y el color se reserva para el estado; evita fondos oscuros).
//
// Main.qml fija `variante` con `planta.tema` (se elige en la cabecera o en la ventana de conexión y se
// guarda en datos/preferencias_hmi.json). Qt Design Studio no pasa por ui/app.py: allí se ve el original.
// Los tokens que no son colores son idénticos al original; si el sistema de diseño cambia, copiarlos aquí.
QtObject {
    property string variante: "oscuro"
    readonly property bool gris: variante === "gris"

    readonly property color fondo:      gris ? "#BFC4CA" : "#0F1319"
    readonly property color surface:    gris ? "#D3D7DB" : "#171C24"
    readonly property color surface2:   gris ? "#E2E5E8" : "#1F2630"
    readonly property color borde:      gris ? "#99A0A9" : "#2C3542"
    readonly property color texto:      gris ? "#1B2129" : "#E6EAF0"
    readonly property color textoSuave: gris ? "#4A5461" : "#8B96A5"
    readonly property color unamAzul:   "#1B3A6B"
    readonly property color unamOro:    gris ? "#9C7A12" : "#C9A227"
    readonly property color aire:       gris ? "#1B5FD1" : "#3D8BFF"
    readonly property color ok:         gris ? "#178A47" : "#2ECC71"
    readonly property color activo:     gris ? "#B07200" : "#FFB000"
    readonly property color alarma:     gris ? "#CC2B2B" : "#FF4D4F"
    readonly property color neutro:     gris ? "#6B7480" : "#7B8794"
    // Texto sobre un relleno de acento (botón primario azul): blanco sobre gris; en oscuro, el de siempre.
    readonly property color textoSobreAcento: gris ? "#FFFFFF" : "#E6EAF0"

    // Archivos que dependen del fondo: iconos de línea (_claro sobre oscuro, _oscuro sobre claro) y
    // escudos (blanco para la cabecera oscura, azul sobre gris).
    readonly property string sufijoIcono: gris ? "_oscuro" : "_claro"
    readonly property string sufijoLogo: gris ? "_azul" : "_blanco"

    readonly property string fuente: "Inter"
    readonly property int  titulo: 22
    readonly property int  seccion: 14
    readonly property int  cuerpo: 14
    readonly property int  etiqueta: 12
    readonly property int  valor: 28

    readonly property int  espS: 8
    readonly property int  espM: 12
    readonly property int  espL: 16
    readonly property int  espXL: 24
    readonly property int  radioPanel: 12
    readonly property int  radioControl: 8

    readonly property int  animRapida: 120
    readonly property int  animNormal: 220
    readonly property int  pulsoBoton: 300

    // Igual que el original: los componentes del sistema de diseño resuelven esta ruta relativa a SU
    // archivo (assets/assets_cilindros/ui/qml/), no a este.
    readonly property string rutaUi: "../"
}
