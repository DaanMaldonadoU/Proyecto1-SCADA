// Generado por ui/herramientas/generar_dummydata.py: no editar a mano.
// Datos de prueba para Qt Design Studio (ui/qml/HMI.qmlproject): planta (ui/cliente.py, Planta) con la secuencia SIM en marcha

import QtQuick 2.15

QtObject {
    property var tablaDirecciones: ({"STOP_1": "I:1.0/0", "START_1": "I:1.0/1", "SC1": "I:1.0/2", "SE1": "I:1.0/3", "SC2": "I:1.0/4", "SE2": "I:1.0/5", "SC3": "I:1.0/6", "SE3": "I:1.0/7", "EV_E1": "O:2.0/0", "EV_C1": "O:2.0/1", "EV_E2": "O:2.0/2", "EV_C2": "O:2.0/3", "EV_E3": "O:2.0/4", "EV_C3": "O:2.0/5", "STARTV": "B3:0/0", "STOPV": "B3:0/1", "ACTIVE": "B3:0/2", "END": "B3:0/3", "RESETV": "B3:0/4", "X0": "B3:3/0", "X1": "B3:3/1", "X2": "B3:3/2", "X3": "B3:3/3", "X4": "B3:3/4", "X5": "B3:3/5", "X6": "B3:3/6", "X7": "B3:3/7", "X8": "B3:3/8", "T0_ACC": "T4:0.ACC", "T0_PRE": "T4:0.PRE", "T0_DN": "T4:0/DN", "T1_ACC": "T4:1.ACC", "T1_PRE": "T4:1.PRE", "T1_DN": "T4:1/DN", "T2_ACC": "T4:2.ACC", "T2_PRE": "T4:2.PRE", "T2_DN": "T4:2/DN", "T3_ACC": "T4:3.ACC", "T3_PRE": "T4:3.PRE", "T3_DN": "T4:3/DN", "T4_ACC": "T4:4.ACC", "T4_PRE": "T4:4.PRE", "T4_DN": "T4:4/DN", "T5_ACC": "T4:5.ACC", "T5_PRE": "T4:5.PRE", "T5_DN": "T4:5/DN", "C_ACC": "C5:0.ACC", "C_PRE": "C5:0.PRE"})
    
    property bool conectado: true
    property bool gatewayVivo: true
    property string modo: "SIM"
    property string fuente: "sim"
    property string calidadTexto: "Good 24/24"
    property bool calidadOk: true
    property int etapa: 7
    property real tEtapa: 1.5
    property var bits: ({"ACTIVE": true, "END": false, "EV_C1": false, "EV_C2": false, "EV_C3": true, "EV_E1": false, "EV_E2": false, "EV_E3": false, "RESETV": false, "SC1": true, "SC2": true, "SC3": true, "SE1": false, "SE2": false, "SE3": false, "STARTV": false, "START_1": false, "STOPV": false, "STOP_1": true, "T0_DN": false, "T1_DN": false, "T2_DN": false, "T3_DN": false, "T4_DN": false, "T5_DN": false, "X0": false, "X1": false, "X2": false, "X3": false, "X4": false, "X5": false, "X6": false, "X7": true, "X8": false})
    property var ints: ({"C_ACC": 1, "C_PRE": 3, "T0_ACC": 0, "T0_PRE": 100, "T1_ACC": 0, "T1_PRE": 100, "T2_ACC": 0, "T2_PRE": 100, "T3_ACC": 0, "T3_PRE": 100, "T4_ACC": 0, "T4_PRE": 100, "T5_ACC": 154, "T5_PRE": 500})
    property var palabras: ({"B3:0": 4, "B3:3": 128, "I:1.0": 85, "O:2.0": 32})
    property var pos: ([0.0, 0.0, 0.0])
    property var posNeum: ([1.0, 0.566])
    property bool posEstimada: false
    property var carreras: ({"1": {"confirmado": true, "direccion": "", "duracion_ms": 750, "moviendo": false, "objetivo": 0.0, "pos": 0.0, "timeout": false}, "2": {"confirmado": true, "direccion": "", "duracion_ms": 794, "moviendo": false, "objetivo": 0.0, "pos": 0.0, "timeout": false}, "3": {"confirmado": true, "direccion": "", "duracion_ms": 706, "moviendo": false, "objetivo": 0.0, "pos": 0.0, "timeout": false}})
    property real latenciaMs: 0.44
    property real latenciaMaxMs: 2.42
    property real latenciaP95Ms: 0.86
    property real periodoMs: 50.0
    property real cicloMs: 0.57
    property string fuenteLatencia: "sim"
    property var alarmas: ([])
    property int alarmasActivas: 0
    property var ultimaEscritura: ({"msg": "", "ok": true, "quien": "gateway", "t": 1791611739.079, "tag": "STARTV", "valor": 0})
    property int escriturasPendientes: 0
    property var calibracion: ({"1": {"ext": {"ms": 751, "muestras": [751]}, "ret": {"ms": 750, "muestras": [750]}}, "2": {"ext": {"ms": 900, "muestras": [900]}, "ret": {"ms": 794, "muestras": [794]}}, "3": {"ext": {"ms": 693, "muestras": [693]}, "ret": {"ms": 706, "muestras": [706]}}})
    property var historialLatencia: ([0.47, 0.45, 0.77, 0.32, 0.44, 0.3, 0.37, 0.4, 0.38, 0.35, 0.28, 0.43, 0.39, 0.8, 0.44, 0.26, 0.46, 0.35, 0.48, 0.34, 0.4, 0.61, 0.55, 0.89, 0.76, 0.55, 0.5, 0.57, 0.47, 0.46, 0.43, 0.39, 0.48, 0.57, 0.44, 0.43, 0.72, 0.44, 0.41, 0.37, 0.37, 0.58, 0.37, 0.48, 0.39, 0.5, 0.36, 0.64, 0.48, 0.57, 0.55, 0.36, 0.39, 0.42, 0.37, 0.4, 0.54, 0.53, 0.42, 0.33, 0.35, 0.32, 0.4, 0.52, 0.45, 0.37, 0.3, 0.77, 0.41, 0.45, 0.33, 0.43, 0.33, 0.36, 0.45, 0.47, 0.42, 0.47, 0.38, 0.52, 0.31, 0.45, 0.65, 0.52, 0.74, 0.64, 0.43, 0.49, 0.49, 0.41, 0.57, 0.66, 0.41, 0.33, 0.36, 0.56, 0.55, 1.22, 0.67, 0.5, 0.53, 0.59, 0.37, 0.51, 0.35, 0.81, 1.31, 0.48, 0.66, 0.39, 0.38, 0.33, 0.38, 0.38, 0.43, 0.54, 0.66, 0.36, 0.38, 0.32, 0.3, 0.48, 0.36, 0.46, 0.33, 0.37, 0.37, 0.46, 0.42, 0.35, 0.44, 0.49, 0.37, 0.49, 0.32, 0.33, 0.33, 0.37, 0.42, 0.42, 0.41, 0.51, 1.02, 1.03, 0.69, 0.51, 0.6, 0.63, 0.71, 0.62, 0.91, 0.62, 0.54, 0.71, 0.53, 0.67, 0.68, 0.58, 0.9, 0.6, 0.83, 0.78, 0.55, 0.64, 0.77, 0.89, 0.64, 0.56, 0.86, 0.64, 0.62, 0.64, 0.47, 0.68, 0.7, 0.58, 0.41, 0.47, 0.45, 0.39, 0.44, 0.49, 0.6, 0.92, 0.41, 0.53, 0.5, 0.43, 0.39, 0.33, 0.48, 0.64, 0.64, 0.63, 0.46, 0.56, 0.48, 0.56, 0.71, 0.55, 0.69, 0.89, 0.62, 0.61, 2.42, 0.65, 0.56, 0.53, 0.53, 0.41, 0.55, 0.47, 0.44, 0.34, 0.58, 0.32, 0.42, 0.34, 0.51, 0.53, 0.36, 0.42, 0.77, 0.41, 0.36, 0.59, 0.71, 0.37, 0.44])
    property var cronograma: ([[-11.97, -1.0, -1.0, -1.0, -1], [-11.865, -1.0, -1.0, -1.0, -1], [-11.761, -1.0, -1.0, -1.0, -1], [-11.655, -1.0, -1.0, -1.0, -1], [-11.551, -1.0, -1.0, -1.0, -1], [-11.445, -1.0, -1.0, -1.0, -1], [-11.34, 0.0, 0.0, 0.0, 0], [-11.235, 0.0, 0.0, 0.0, 0], [-11.13, 0.0, 0.0, 0.0, 0], [-11.025, 0.182, 0.0, 0.0, 1], [-10.92, 0.306, 0.0, 0.0, 1], [-10.815, 0.432, 0.0, 0.0, 1], [-10.71, 0.557, 0.0, 0.0, 1], [-10.605, 0.682, 0.0, 0.0, 1], [-10.501, 0.806, 0.0, 0.0, 1], [-10.395, 0.931, 0.0, 0.0, 1], [-10.289, 1.0, 0.0, 0.0, 2], [-10.185, 1.0, 0.0, 0.0, 2], [-10.08, 1.0, 0.0, 0.0, 2], [-9.975, 1.0, 0.0, 0.0, 2], [-9.87, 1.0, 0.0, 0.0, 2], [-9.764, 1.0, 0.0, 0.0, 2], [-9.66, 1.0, 0.0, 0.0, 2], [-9.555, 1.0, 0.0, 0.0, 2], [-9.45, 1.0, 0.0, 0.0, 2], [-9.345, 0.98, 0.0, 0.0, 2], [-9.24, 0.846, 0.0, 0.0, 2], [-9.135, 0.713, 0.0, 0.0, 2], [-9.029, 0.579, 0.0, 0.0, 2], [-8.925, 0.38, 0.0, 0.0, 2], [-8.82, 0.247, 0.0, 0.0, 2], [-8.715, 0.113, 0.0, 0.0, 2], [-8.61, 0.0, 0.0, 0.0, 3], [-8.505, 0.0, 0.0, 0.0, 3], [-8.401, 0.0, 0.0, 0.0, 3], [-8.295, 0.0, 0.0, 0.0, 3], [-8.19, 0.0, 0.0, 0.0, 3], [-8.085, 0.0, 0.0, 0.0, 3], [-7.98, 0.0, 0.0, 0.0, 3], [-7.875, 0.0, 0.0, 0.0, 3], [-7.77, 0.0, 0.0, 0.0, 3], [-7.665, 0.0, 0.0, 0.0, 3], [-7.56, 0.0, 0.088, 0.0, 3], [-7.455, 0.0, 0.2, 0.0, 3], [-7.35, 0.0, 0.311, 0.0, 3], [-7.245, 0.0, 0.422, 0.0, 3], [-7.14, 0.0, 0.533, 0.0, 3], [-7.036, 0.0, 0.645, 0.0, 3], [-6.93, 0.0, 0.755, 0.0, 3], [-6.825, 0.0, 0.922, 0.0, 3], [-6.72, 0.0, 1.0, 0.0, 4], [-6.615, 0.0, 1.0, 0.0, 4], [-6.51, 0.0, 1.0, 0.0, 4], [-6.405, 0.0, 1.0, 0.0, 4], [-6.3, 0.0, 1.0, 0.0, 4], [-6.195, 0.0, 1.0, 0.0, 4], [-6.09, 0.0, 1.0, 0.0, 4], [-5.985, 0.0, 1.0, 0.0, 4], [-5.88, 0.0, 1.0, 0.0, 4], [-5.775, 0.0, 1.0, 0.0, 4], [-5.669, 0.0, 0.888, 0.0, 4], [-5.564, 0.0, 0.771, 0.0, 4], [-5.46, 0.0, 0.653, 0.0, 4], [-5.355, 0.0, 0.535, 0.0, 4], [-5.25, 0.0, 0.418, 0.0, 4], [-5.145, 0.0, 0.3, 0.0, 4], [-5.04, 0.0, 0.182, 0.0, 4], [-4.936, 0.0, 0.065, 0.0, 4], [-4.83, 0.0, 0.0, 0.0, 5], [-4.724, 0.0, 0.0, 0.0, 5], [-4.62, 0.0, 0.0, 0.0, 5], [-4.515, 0.0, 0.0, 0.0, 5], [-4.409, 0.0, 0.0, 0.0, 5], [-4.305, 0.0, 0.0, 0.0, 5], [-4.199, 0.0, 0.0, 0.0, 5], [-4.095, 0.0, 0.0, 0.0, 5], [-3.989, 0.0, 0.0, 0.0, 5], [-3.885, 0.0, 0.0, 0.021, 5], [-3.779, 0.0, 0.0, 0.164, 5], [-3.674, 0.0, 0.0, 0.379, 5], [-3.57, 0.0, 0.0, 0.522, 5], [-3.465, 0.0, 0.0, 0.665, 5], [-3.36, 0.0, 0.0, 0.807, 5], [-3.254, 0.0, 0.0, 0.95, 5], [-3.15, 0.0, 0.0, 1.0, 6], [-3.045, 0.0, 0.0, 1.0, 6], [-2.94, 0.0, 0.0, 1.0, 6], [-2.834, 0.0, 0.0, 1.0, 6], [-2.73, 0.0, 0.0, 1.0, 6], [-2.625, 0.0, 0.0, 1.0, 6], [-2.52, 0.0, 0.0, 1.0, 6], [-2.414, 0.0, 0.0, 1.0, 6], [-2.31, 0.0, 0.0, 1.0, 6], [-2.206, 0.0, 0.0, 0.958, 6], [-2.1, 0.0, 0.0, 0.815, 6], [-1.995, 0.0, 0.0, 0.672, 6], [-1.89, 0.0, 0.0, 0.529, 6], [-1.786, 0.0, 0.0, 0.387, 6], [-1.68, 0.0, 0.0, 0.244, 6], [-1.575, 0.0, 0.0, 0.029, 6], [-1.47, 0.0, 0.0, 0.0, 7], [-1.364, 0.0, 0.0, 0.0, 7], [-1.26, 0.0, 0.0, 0.0, 7], [-1.156, 0.0, 0.0, 0.0, 7], [-1.05, 0.0, 0.0, 0.0, 7], [-0.945, 0.0, 0.0, 0.0, 7], [-0.84, 0.0, 0.0, 0.0, 7], [-0.735, 0.0, 0.0, 0.0, 7], [-0.63, 0.0, 0.0, 0.0, 7], [-0.524, 0.0, 0.0, 0.0, 7], [-0.42, 0.0, 0.0, 0.0, 7], [-0.315, 0.0, 0.0, 0.0, 7], [-0.21, 0.0, 0.0, 0.0, 7], [-0.105, 0.0, 0.0, 0.0, 7], [0.0, 0.0, 0.0, 0.0, 7]])
    property var parametros: ({"N_CICLOS": {"confirmado": false, "consistente": true, "escrito": -1, "leido": 3}, "T_ESPERA": {"confirmado": false, "consistente": true, "escrito": -1, "leido": 100}, "T_NEUM": {"confirmado": false, "consistente": true, "escrito": -1, "leido": 500}})
    property int seq: 234
    property bool fisicaAutomatica: true
    property string pubEndpoint: "tcp://127.0.0.1:5595"
    property string cmdEndpoint: "tcp://127.0.0.1:5596"
    property int ordenesPendientes: 0
    property int fines: 0
    property bool finReciente: false
    property var mando: ({"conectados": [], "desde": "23:55:38", "enlaceWeb": false, "libre": false, "remotoHabilitado": false, "titularLocal": true, "titularRol": "local", "titularUsuario": "HMI local", "ultimaTexto": "23:55:38 · HMI local pulso STARTV · ok", "venceEnS": 48.9})
    property bool modoSuave: false
    property var suave: ({})
    property string tema: "oscuro"
    property ListModel eventos: ListModel {
        property var filtro: (["info", "aviso", "alarma"])
        property var conteos: ({"alarma": 0, "aviso": 0, "info": 14})
        function alternarNivel(a0) {}
        function limpiar() {}
        ListElement { hora: "23:55:48.482"; nivel: "info"; msg: "Ciclo 1 de 3"; origen: "grafcet"; t: 1791611748.482 }
        ListElement { hora: "23:55:48.438"; nivel: "info"; msg: "X6 → X7"; origen: "grafcet"; t: 1791611748.438 }
        ListElement { hora: "23:55:46.730"; nivel: "info"; msg: "X5 → X6"; origen: "grafcet"; t: 1791611746.731 }
        ListElement { hora: "23:55:45.032"; nivel: "info"; msg: "X4 → X5"; origen: "grafcet"; t: 1791611745.033 }
        ListElement { hora: "23:55:43.232"; nivel: "info"; msg: "X3 → X4"; origen: "grafcet"; t: 1791611743.233 }
        ListElement { hora: "23:55:41.327"; nivel: "info"; msg: "X2 → X3"; origen: "grafcet"; t: 1791611741.327 }
        ListElement { hora: "23:55:39.588"; nivel: "info"; msg: "X1 → X2"; origen: "grafcet"; t: 1791611739.589 }
        ListElement { hora: "23:55:38.838"; nivel: "info"; msg: "X0 → X1"; origen: "grafcet"; t: 1791611738.838 }
        ListElement { hora: "23:55:38.823"; nivel: "info"; msg: "Marcha (ACTIVE = 1)"; origen: "gateway"; t: 1791611738.823 }
        ListElement { hora: "23:55:38.779"; nivel: "info"; msg: "HMI local toma el mando"; origen: "HMI local"; t: 1791611738.779 }
        ListElement { hora: "23:55:38.778"; nivel: "info"; msg: "Pulso STARTV (300 ms) · HMI local"; origen: "HMI local"; t: 1791611738.779 }
        ListElement { hora: "23:55:38.779"; nivel: "info"; msg: "Pulso STARTV · ok (1.1 ms)"; origen: "hmi"; t: 1791611738.78 }
        ListElement { hora: "23:55:38.538"; nivel: "info"; msg: "Gateway en línea (SIM)"; origen: "hmi"; t: 1791611738.538 }
        ListElement { hora: "23:55:37.966"; nivel: "info"; msg: "Suscrito a tcp://127.0.0.1:5595 · órdenes a tcp://127.0.0.1:5596"; origen: "hmi"; t: 1791611737.967 }
    }
    property var etapasDef: ([{"accion": "Reposo · retrae 1A/2A/3A", "direccionTimer": "", "numero": 0, "tagAcc": "", "tagPre": "", "timer": -1}, {"accion": "1A+  (EV_E1)", "direccionTimer": "", "numero": 1, "tagAcc": "", "tagPre": "", "timer": -1}, {"accion": "Espera T4:0 con 1A afuera → 1A−", "direccionTimer": "T4:0", "numero": 2, "tagAcc": "T0_ACC", "tagPre": "T0_PRE", "timer": 0}, {"accion": "Espera T4:1 con 1A adentro → 2A+", "direccionTimer": "T4:1", "numero": 3, "tagAcc": "T1_ACC", "tagPre": "T1_PRE", "timer": 1}, {"accion": "Espera T4:2 con 2A afuera → 2A−", "direccionTimer": "T4:2", "numero": 4, "tagAcc": "T2_ACC", "tagPre": "T2_PRE", "timer": 2}, {"accion": "Espera T4:3 con 2A adentro → 3A+", "direccionTimer": "T4:3", "numero": 5, "tagAcc": "T3_ACC", "tagPre": "T3_PRE", "timer": 3}, {"accion": "Espera T4:4 con 3A afuera → 3A−", "direccionTimer": "T4:4", "numero": 6, "tagAcc": "T4_ACC", "tagPre": "T4_PRE", "timer": 4}, {"accion": "Ventana T4:5 · cadena 4A/5A · C+1", "direccionTimer": "T4:5", "numero": 7, "tagAcc": "T5_ACC", "tagPre": "T5_PRE", "timer": 5}, {"accion": "END", "direccionTimer": "", "numero": 8, "tagAcc": "", "tagPre": "", "timer": -1}])
    property var receptividades: ([{"a": 1, "de": 0, "texto": "SC1·SC2·SC3·START"}, {"a": 2, "de": 1, "texto": "SE1"}, {"a": 3, "de": 2, "texto": "T4:0/DN·SC1"}, {"a": 4, "de": 3, "texto": "T4:1/DN·SE2"}, {"a": 5, "de": 4, "texto": "T4:2/DN·SC2"}, {"a": 6, "de": 5, "texto": "T4:3/DN·SE3"}, {"a": 7, "de": 6, "texto": "T4:4/DN·SC3"}, {"a": 1, "de": 7, "texto": "T4:5/DN·SC3·C<PRE"}, {"a": 8, "de": 7, "texto": "T4:5/DN·C≥PRE"}, {"a": 0, "de": 8, "texto": "GS"}])
    property var palabrasDef: ([{"bits": ["STOP_1", "START_1", "SC1", "SE1", "SC2", "SE2", "SC3", "SE3", "", "", "", "", "", "", "", ""], "nombre": "I:1.0"}, {"bits": ["EV_E1", "EV_C1", "EV_E2", "EV_C2", "EV_E3", "EV_C3", "", "", "", "", "", "", "", "", "", ""], "nombre": "O:2.0"}, {"bits": ["STARTV", "STOPV", "ACTIVE", "END", "RESETV", "", "", "", "", "", "", "", "", "", "", ""], "nombre": "B3:0"}, {"bits": ["X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8", "", "", "", "", "", "", ""], "nombre": "B3:3"}])
    property var cilindrosDef: ([{"evC": "EV_C1", "evE": "EV_E1", "n": 1, "sc": "SC1", "se": "SE1"}, {"evC": "EV_C2", "evE": "EV_E2", "n": 2, "sc": "SC2", "se": "SE2"}, {"evC": "EV_C3", "evE": "EV_E3", "n": 3, "sc": "SC3", "se": "SE3"}])
    property var neumaticoDef: ({"cilindros": [4, 5], "direccion": "T4:5", "tagAcc": "T5_ACC", "tagPre": "T5_PRE"})
    property var parametrosDef: ([{"destino": "T4:0.PRE … T4:4.PRE", "escala": 100, "max": 32767, "sliderMax": 1000, "tag": "T_ESPERA", "unidad": "s"}, {"destino": "T4:5.PRE", "escala": 100, "max": 32767, "sliderMax": 2000, "tag": "T_NEUM", "unidad": "s"}, {"destino": "C5:0.PRE", "escala": 1, "max": 99, "sliderMax": 20, "tag": "N_CICLOS", "unidad": ""}])
    property var sensores: (["SC1", "SE1", "SC2", "SE2", "SC3", "SE3"])
    property bool haySuavizado: true
    property var temas: (["oscuro", "gris"])
    property int pulsoMs: 300
    property bool hayEstimador: true
    function conectar(a0, a1) {}
    function desconectar() {}
    function direccion(a0) { return tablaDirecciones[a0] || "" }
    function entrada(a0, a1) {}
    function escribir(a0, a1) {}
    function fijarModoSuave(a0) {}
    function fijarTema(a0) {}
    function fisicaAuto(a0) {}
    function fuenteOpc(a0) {}
    function mandoLiberar() {}
    function mandoTomar() {}
    function pulso(a0) {}
    function reiniciarCalibracion() {}
    function remotoHabilitar(a0) {}
    signal snapshotAplicado()
}
