pragma Singleton
import QtQuick 2.15
import "../../../assets/assets_cilindros/ui/qml" as UI

// Utilidades de estilo del HMI. No define colores nuevos: todo deriva de UI.Theme
// (tokens del sistema de diseño). Aquí solo hay transparencias, formatos y tamaños.
QtObject {
    // Color del tema con otra opacidad (p. ej. fondo ámbar al 14 % de una etapa activa).
    function alfa(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

    // Números con coma decimal (es-MX de laboratorio) y dígitos tabulares.
    function num(v, dec) {
        if (v === undefined || v === null || isNaN(v)) return "—"
        return Number(v).toFixed(dec === undefined ? 1 : dec).replace(".", ",")
    }
    function seg(ms, dec) { return num(ms / 1000.0, dec === undefined ? 2 : dec) + " s" }

    // Familia monoespaciada del token `tipografia.mono` (Consolas existe en Windows).
    readonly property string mono: "Consolas"
    // Rasgos OpenType de Inter: cifras tabulares para que los valores no bailen.
    readonly property var tnum: ({ "tnum": 1 })
    // `font.features` solo existe desde Qt 6.6: escrito como propiedad en QML rompe la carga en
    // Qt 5.15 ("Cannot assign to non-existent property"). Por eso se aplica desde JS al completar
    // el componente y solo si la fuente la tiene; en Qt 5 las cifras quedan proporcionales.
    // Uso: `Text { font { ... } Component.onCompleted: Estilo.cifrasTabulares(this) }`.
    function cifrasTabulares(t) {
        if (t && t.font && t.font.features !== undefined)
            t.font.features = tnum
    }

    // Fuente de Canvas (Context2D) con peso numérico. Se pasa el enum de QML (Font.Medium,
    // Font.DemiBold, Font.Bold) y no "500"/"600"/"700": Qt 5 usa la escala de pesos 0…99
    // (Medium = 57) y Qt 6 la escala CSS 1…1000 (Medium = 500); el enum da el valor correcto en ambos.
    function fuenteCanvas(peso, px) {
        return peso + " " + px + "px '" + UI.Theme.fuente + "'"
    }

    // Tamaños derivados del token `tipografia` para las zonas densas.
    readonly property int chico: 11
    readonly property int micro: 10
}
