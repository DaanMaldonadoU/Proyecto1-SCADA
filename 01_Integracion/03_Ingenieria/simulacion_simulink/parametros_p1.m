%% parametros_p1.m - Parámetros del modelo P1_secuencia.slx
% Se ejecuta solo al abrir y al simular el modelo (callbacks PreLoadFcn e InitFcn).
% Unidades: tiempo en s, presión en bar (relativa), carrera en mm.

%% PLC SLC 5/04 (valores que el HMI escribe por OPC)
T_ESPERA = 1.0;   % t1: T4:0..T4:4.PRE = 100 (base 0.01 s)
T_NEUM   = 5.0;   % t2: ventana neumática de X7, T4:5.PRE = 500
N_CICLOS = 3;     % N: C5:0.PRE
Ts_PLC   = 0.01;  % periodo de escaneo del PLC

%% Mandos del operador (escenario de la simulación)
T_START   = 0.5;  % instante en que se pulsa START_1
DUR_START = 0.3;  % duración de la pulsación
T_SIM     = 55;   % duración de la simulación (3 ciclos de ~16 s)

%% Red neumática
P_RED     = 6;     % presión de alimentación
P_CONM    = 3;     % presión de conmutación de los pilotajes
TAU_LINEA = 0.03;  % llenado de las líneas de señal y de las cámaras

%% Cilindros 1A, 2A y 3A: doble efecto (Parker P1D), válvula 5/2 biestable
% La velocidad se ajusta con las reguladoras de caudal; 1 s por carrera,
% como en el diagrama espacio-fase.
CARRERA_13 = 100;  % supuesto
V_EXT_13   = 100;
V_RET_13   = 100;
TOL_SENSOR = 1;    % zona de detección de SC/SE y de los rodillos

%% Cilindros 4A y 5A: simple efecto con retorno por muelle (Parker P1A)
CARRERA_45 = 50;   % supuesto
V_EXT_45   = 100;  % 0.5 s de salida
V_RET_45   = 125;  % 0.4 s de retorno por muelle
P_MIN_45   = 2;    % presión que vence al muelle

%% Temporizadores neumáticos: depósito + estrangulador + antirretorno
% El depósito se llena por el estrangulador como un RC: el pilotaje conmuta
% cuando su presión pasa de P_CONM, es decir, RETARDO = TAU*ln(P_RED/(P_RED-P_CONM)).
RETARDO_T1   = 1.0;  % E4A -> 5A+
RETARDO_T2   = 1.0;  % tiempo que 5A permanece expandido
TAU_T1       = RETARDO_T1 / log(P_RED/(P_RED - P_CONM));
TAU_T2       = RETARDO_T2 / log(P_RED/(P_RED - P_CONM));
TAU_DESCARGA = 0.05; % vaciado rápido por el antirretorno
