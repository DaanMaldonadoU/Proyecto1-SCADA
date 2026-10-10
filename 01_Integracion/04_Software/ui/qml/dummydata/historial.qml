// Generado por ui/herramientas/generar_dummydata.py: no editar a mano.
// Datos de prueba para Qt Design Studio (ui/qml/HMI.qmlproject): historial (ui/historial.py, Historial) sin consultas

import QtQuick 2.15

QtObject {
    property string ruta: "datos/historial.sqlite"
    property string tabla: "eventos"
    property real desde: 0.0
    property real hasta: 0.0
    property var niveles: (["info", "aviso", "alarma"])
    property string texto: ""
    property string tag: ""
    property bool soloActivas: false
    property bool soloFallidas: false
    property int limite: 500
    property ListModel filas: ListModel {
        property int cuenta: 0
        function fila(a0) { return ({}) }
    }
    property int total: 0
    property var resumen: ({})
    property string error: "no existe el archivo datos/historial.sqlite"
    property string ultimoExporte: ""
    property real consultaMs: 0.0
    property var tablas: (["eventos", "alarmas", "escrituras"])
    signal consultado()
    function consultar() {}
    function exportarCsv() { return "" }
    function ultimas(a0) {}
}
