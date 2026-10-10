pragma Singleton
import QtQuick 2.15

// Tokens del sistema de diseño (espejo de ui/tokens.json). Cargar las fuentes Inter desde Python
// con QFontDatabase.addApplicationFont(...) antes de crear el motor QML.
QtObject {
    readonly property color fondo:      "#0F1319"
    readonly property color surface:    "#171C24"
    readonly property color surface2:   "#1F2630"
    readonly property color borde:      "#2C3542"
    readonly property color texto:      "#E6EAF0"
    readonly property color textoSuave: "#8B96A5"
    readonly property color unamAzul:   "#1B3A6B"
    readonly property color unamOro:    "#C9A227"
    readonly property color aire:       "#3D8BFF"
    readonly property color ok:         "#2ECC71"
    readonly property color activo:     "#FFB000"
    readonly property color alarma:     "#FF4D4F"
    readonly property color neutro:     "#7B8794"

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

    readonly property string rutaUi: "../"      // relativa a este archivo: ui/botones, ui/leds, ui/iconos
}
