import QtQuick 2.15
import QtQuick.Layouts 1.15
import "../../assets/assets_cilindros/ui/qml" as UI
import "componentes"

// Pantalla principal del HMI (distribución de assets/assets_cilindros/ui/DISENO.md):
//   cabecera 72 px · banda de alarmas (solo con alarmas activas)
//   fila 1: sinóptico (8 col) + GRAFCET (4 col)
//   fila 2: mandos (3) + parámetros (3) + cronograma (6)
//   fila 3: monitor E/S (4) + registro (5) + latencia (3)
//   pie institucional (mds/data.md)
// Rejilla de 12 columnas (componentes/RejillaHmi.qml) para que las proporciones sean exactas de 1280×720 a 1920×1080.
//
// Es un Item y no una ventana para poder abrirla en Qt Design Studio (ui/qml/HMI.qmlproject, con los
// datos de prueba de ui/qml/dummydata/). Main.qml la pone dentro de la ventana real.
// Para Design Studio: aquí no se declaran funciones ni cálculos propios (no los evalúa en el archivo
// que se edita); las fórmulas de la rejilla viven en RejillaHmi.qml.
Item {
    id: pantalla
    width: 1920      // tamaño de diseño; en Main.qml se ancla a la ventana
    height: 1080

    readonly property bool compacto: height < 940 || width < 1600

    signal conexionPedida()

    Rectangle {
        anchors.fill: parent
        color: UI.Theme.fondo
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        CabeceraHmi {
            Layout.fillWidth: true
            titulo: datosInstitucion.proyecto || ""
            subtitulo: "Estación electroneumática · SLC 5/04 · 1A/2A/3A doble efecto · 4A/5A cadena neumática"
            compacto: pantalla.compacto
            onConexionPedida: pantalla.conexionPedida()
        }
        BandaAlarmas {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
        }

        RejillaHmi {
            id: rejilla
            Layout.fillWidth: true
            Layout.fillHeight: true
            compacto: pantalla.compacto

            Sinoptico {
                x: rejilla.xCol(0); y: rejilla.y1; width: rejilla.ancho(8); height: rejilla.h1
                compacto: pantalla.compacto
            }
            Grafcet {
                x: rejilla.xCol(8); y: rejilla.y1; width: rejilla.ancho(4); height: rejilla.h1
                compacto: pantalla.compacto
            }
            Mandos {
                x: rejilla.xCol(0); y: rejilla.y2; width: rejilla.ancho(3); height: rejilla.h2
                compacto: pantalla.compacto
            }
            Parametros {
                x: rejilla.xCol(3); y: rejilla.y2; width: rejilla.ancho(3); height: rejilla.h2
                compacto: pantalla.compacto
            }
            Cronograma {
                x: rejilla.xCol(6); y: rejilla.y2; width: rejilla.ancho(6); height: rejilla.h2
                compacto: pantalla.compacto
            }
            MonitorES {
                x: rejilla.xCol(0); y: rejilla.y3; width: rejilla.ancho(4); height: rejilla.h3
                compacto: pantalla.compacto
            }
            Registro {
                x: rejilla.xCol(4); y: rejilla.y3; width: rejilla.ancho(5); height: rejilla.h3
                compacto: pantalla.compacto
            }
            Latencia {
                x: rejilla.xCol(9); y: rejilla.y3; width: rejilla.ancho(3); height: rejilla.h3
                compacto: pantalla.compacto
            }
        }

        PieInstitucional {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            compacto: pantalla.compacto
        }
    }
}
