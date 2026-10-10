%% graficar_tiempos_p1.m - Diagramas de tiempos de la simulación P1_secuencia
% Simula el modelo con parametros_p1.m y guarda en figuras/:
%   espacio_fase_simulink.png     un ciclo, los cinco pistones
%   tiempos_plc.png               bobinas O:2 y finales de carrera I:1 de un ciclo
%   tiempos_cadena_neumatica.png  señales de la cadena 4A/5A alrededor de la ventana X7
%   tiempos_3_ciclos.png          corrida completa: etapas, contador y pistones

carpeta = fileparts(mfilename('fullpath'));
mdl = 'P1_secuencia';
load_system(fullfile(carpeta, [mdl '.slx']));
run(fullfile(carpeta, 'parametros_p1.m'));
out = sim(mdl);
L = out.logsout;

salida = fullfile(carpeta, 'figuras');
if ~isfolder(salida), mkdir(salida); end

est = estilo_p1();

%% Etapas y ventanas de tiempo
[tE, E] = senal(L, 'ETAPA');
cambio = [false; diff(E) ~= 0];
tX1 = tE(cambio & E == 1);
tX7 = tE(cambio & E == 7);
tFinX7 = tE([false; diff(E == 7) == -1]);      % salida de X7 (fin de t2)
ciclo1 = [tX1(1) - 0.5, tX1(2) + 0.5];
ventanasX7 = [tX7(:), tFinX7(:)];

carreras = [CARRERA_13 CARRERA_13 CARRERA_13 CARRERA_45 CARRERA_45];
nombresX = {'x1', 'x2', 'x3', 'x4', 'x5'};
pistones = {'1A', '2A', '3A', '4A', '5A'};
colores = {est.azul, est.azul, est.azul, est.naranja, est.naranja};

%% 1. Diagrama espacio-fase de un ciclo
fig = figure('Color', est.fondo, 'Units', 'inches', 'Position', [1 1 7.2 4.6]);
T = tiledlayout(fig, 6, 1, 'TileSpacing', 'tight', 'Padding', 'compact');
banda_etapas(nexttile(T), tE, E, ciclo1, est);
h = gobjects(1, 5);
for k = 1:5
    [t, x] = senal(L, nombresX{k});
    [ax, h(k)] = fila(T, t, x / carreras(k), colores{k}, pistones{k}, 'posicion', ciclo1, est);
    sombrear(ax, ventanasX7, est);
end
eje_tiempo(ax, est);
lg = legend(h([1 4]), {'Gobernado por el PLC (1A-3A)', 'Cadena puramente neumática (4A-5A)'}, ...
    'Orientation', 'horizontal', 'Box', 'off', 'TextColor', est.tinta2, 'FontSize', 8);
lg.Layout.Tile = 'north';
titulo(T, 'Diagrama espacio-fase simulado (ciclo 1)', ...
    sprintf('t1 = %g s, t2 = %g s; franja gris: ventana neumática de la etapa X7', T_ESPERA, T_NEUM), est);
exportgraphics(fig, fullfile(salida, 'espacio_fase_simulink.png'), 'Resolution', 200);

%% 2. Entradas y salidas del PLC en un ciclo
bobinas = {'EV_E1', 'EV_C1', 'EV_E2', 'EV_C2', 'EV_E3', 'EV_C3'};
detectores = {'SC1', 'SE1', 'SC2', 'SE2', 'SC3', 'SE3'};
fig = figure('Color', est.fondo, 'Units', 'inches', 'Position', [1 1 7.2 6.4]);
T = tiledlayout(fig, 13, 1, 'TileSpacing', 'tight', 'Padding', 'compact');
banda_etapas(nexttile(T), tE, E, ciclo1, est);
for k = 1:6
    [t, y] = senal(L, bobinas{k});
    [ax, hb] = fila(T, t, y, est.azul, ['O:2/' num2str(k - 1) '  ' bobinas{k}], 'digital', ciclo1, est);
    sombrear(ax, ventanasX7, est);
end
for k = 1:6
    [t, y] = senal(L, detectores{k});
    [ax, hd] = fila(T, t, y, est.tinta2, ['I:1/' num2str(k + 1) '  ' detectores{k}], 'digital', ciclo1, est);
    sombrear(ax, ventanasX7, est);
end
eje_tiempo(ax, est);
lg = legend([hb hd], {'Salidas (bobinas de las válvulas 5/2)', 'Entradas (finales de carrera magnéticos)'}, ...
    'Orientation', 'horizontal', 'Box', 'off', 'TextColor', est.tinta2, 'FontSize', 8);
lg.Layout.Tile = 'north';
titulo(T, 'Entradas y salidas del SLC 5/04 (ciclo 1)', ...
    'EV_C3 se mantiene durante X7 hasta que vence t2', est);
exportgraphics(fig, fullfile(salida, 'tiempos_plc.png'), 'Resolution', 200);

%% 3. Cadena neumática 4A/5A alrededor de la ventana X7 del ciclo 1
[t3, x3] = senal(L, 'x3');
inicio3A = t3(find(t3 < tX7(1) & x3 > TOL_SENSOR, 1));
zoom = [inicio3A - 0.5, tFinX7(1) + 0.5];
filas = {
    'x3',       '3A (posición)',          'posicion', est.azul,    []
    'p_3E',     '3E·C4A → 14 M',          'presion',  est.naranja, []
    'p_M4',     'Memoria M (vía 4)',      'presion',  est.naranja, []
    'p_3C',     '3C',                     'presion',  est.naranja, []
    'p_Y1',     'Y1 = M·3C → 14 V4A',     'presion',  est.naranja, []
    'p_4A',     'Cámara 4A',              'presion',  est.naranja, []
    'x4',       '4A (posición)',          'posicion', est.naranja, []
    'p_E4A',    'E4A → T1',               'presion',  est.naranja, []
    'p_dep_T1', 'Depósito T1',            'presion',  est.naranja, P_CONM
    'p_T1',     'T1 → piloto V5A',        'presion',  est.naranja, []
    'p_5A',     'Cámara 5A',              'presion',  est.naranja, []
    'x5',       '5A (posición)',          'posicion', est.naranja, []
    'p_E5A',    'E5A → T2',               'presion',  est.naranja, []
    'p_dep_T2', 'Depósito T2',            'presion',  est.naranja, P_CONM
    'p_T2',     'T2 → 12 M',              'presion',  est.naranja, []
    'p_C5A',    'C5A·M2 → 12 V4A',        'presion',  est.naranja, []
    };
fig = figure('Color', est.fondo, 'Units', 'inches', 'Position', [1 1 7.2 9.6]);
T = tiledlayout(fig, size(filas, 1), 1, 'TileSpacing', 'tight', 'Padding', 'compact');
for k = 1:size(filas, 1)
    [t, y] = senal(L, filas{k, 1});
    if strcmp(filas{k, 3}, 'posicion')
        y = y / max(carreras(strcmp(nombresX, filas{k, 1})));
    end
    ax = fila(T, t, y, filas{k, 4}, filas{k, 2}, filas{k, 3}, zoom, est, filas{k, 5});
    sombrear(ax, ventanasX7, est);
    switch filas{k, 1}
        case 'x4', rotular_movimientos(ax, t, y, '4A', zoom, est);
        case 'x5', rotular_movimientos(ax, t, y, '5A', zoom, est);
    end
end
eje_tiempo(ax, est);
[t4, x4] = senal(L, 'x4');
mueve = t4(t4 >= tX7(1) & t4 <= tFinX7(1) & x4 > TOL_SENSOR);
duracion = mueve(end) - tX7(1);
titulo(T, 'Cadena puramente neumática 4A/5A (ciclo 1)', ...
    sprintf(['Presiones en bar (0-%g); línea punteada: conmutación del pilotaje (%g bar). ' ...
    'La cadena dura %.2f s de los %g s de la ventana X7.'], P_RED, P_CONM, duracion, T_NEUM), est);
exportgraphics(fig, fullfile(salida, 'tiempos_cadena_neumatica.png'), 'Resolution', 200);

%% 4. Corrida completa
completa = [0, tE(end)];
fig = figure('Color', est.fondo, 'Units', 'inches', 'Position', [1 1 7.2 5.2]);
T = tiledlayout(fig, 8, 1, 'TileSpacing', 'tight', 'Padding', 'compact');
ax = fila(T, tE, E, est.azul, 'Etapa GP', 'entero', completa, est);
ax.YLim = [-0.5 10.5];
rotular_escalones(ax, tE, E, 'X%d', est);
[t, y] = senal(L, 'C');
ax = fila(T, t, y, est.azul, 'Contador C5:0.ACC', 'entero', completa, est);
ax.YLim = [-0.3 N_CICLOS + 1.2];
rotular_escalones(ax, t, y, 'C = %d', est);
[t, y] = senal(L, 'ACTIVE');
fila(T, t, y, est.azul, 'ACTIVE (B3:0/2)', 'digital', completa, est);
for k = 1:5
    [t, x] = senal(L, nombresX{k});
    ax = fila(T, t, x / carreras(k), colores{k}, pistones{k}, 'posicion', completa, est);
    sombrear(ax, ventanasX7, est);
end
eje_tiempo(ax, est);
tFin = tE(find(E == 8, 1));
titulo(T, sprintf('Corrida completa: START en t = %g s y N = %d ciclos', T_START, N_CICLOS), ...
    sprintf('X8 (END) en t = %.2f s: GS fuerza X0, reinicia C y apaga ACTIVE', tFin), est);
exportgraphics(fig, fullfile(salida, 'tiempos_3_ciclos.png'), 'Resolution', 200);

fprintf('Figuras guardadas en %s\n', salida);

%% Funciones locales
function est = estilo_p1()
% Paleta y tinta (azul = zona del PLC, naranja = cadena neumática).
hex = @(s) sscanf(s(2:end), '%2x%2x%2x', [1 3]) / 255;
est.fondo   = hex('#fcfcfb');
est.tinta   = hex('#0b0b0b');
est.tinta2  = hex('#52514e');
est.mudo    = hex('#898781');
est.rejilla = hex('#e1e0d9');
est.lavado  = hex('#f0efec');
est.azul    = hex('#2a78d6');
est.naranja = hex('#eb6834');
est.fuente  = 'Segoe UI';
end

function [t, y] = senal(L, nombre)
v = L.getElement(nombre).Values;
t = v.Time;
y = double(squeeze(v.Data));
[t, i] = unique(t, 'last');
y = y(i);
end

function [ax, h] = fila(T, t, y, color, etiqueta, tipo, ventana, est, umbral)
ax = nexttile(T);
hold(ax, 'on');
switch tipo
    case {'digital', 'entero'}
        [xs, ys] = stairs(t, y);
        if strcmp(tipo, 'digital')
            fill(ax, [xs; xs(end); xs(1)], [ys; 0; 0], color, ...
                'FaceAlpha', 0.15, 'EdgeColor', 'none');
            ax.YLim = [-0.15 1.3];
        end
        h = plot(ax, xs, ys, 'Color', color, 'LineWidth', 1.5);
    case 'posicion'
        h = plot(ax, t, y, 'Color', color, 'LineWidth', 1.5);
        ax.YLim = [-0.12 1.2];
    case 'presion'
        fill(ax, [t; t(end); t(1)], [y; 0; 0], color, 'FaceAlpha', 0.15, 'EdgeColor', 'none');
        h = plot(ax, t, y, 'Color', color, 'LineWidth', 1.5);
        ax.YLim = [-0.3 7.2];
        if nargin > 8 && ~isempty(umbral)
            yline(ax, umbral, ':', 'Color', est.tinta2, 'LineWidth', 1);
        end
end
ax.YTick = [];
ax.XLim = ventana;
ax.XTick = ceil(ventana(1)):paso_rejilla(ventana):floor(ventana(2));
ax.XTickLabel = [];
ax.Box = 'off';
ax.Color = est.fondo;
ax.XColor = est.mudo;
ax.YColor = est.mudo;
ax.XGrid = 'on';
ax.GridColor = est.rejilla;
ax.GridAlpha = 1;
ax.TickLength = [0 0];
ax.FontName = est.fuente;
ax.FontSize = 8;
ylabel(ax, etiqueta, 'Rotation', 0, 'HorizontalAlignment', 'right', ...
    'VerticalAlignment', 'middle', 'Color', est.tinta2, 'Interpreter', 'none', 'FontSize', 8);
end

function banda_etapas(ax, tE, E, ventana, est)
% Una casilla por etapa activa del GRAFCET GP, separadas por un hueco del color de fondo.
hold(ax, 'on');
k = [1; find(diff(E) ~= 0) + 1];
ini = tE(k);
fin = [tE(k(2:end)); tE(end)];
val = E(k);
sel = find(fin > ventana(1) & ini < ventana(2));
for i = sel(:)'
    a = max(ini(i), ventana(1));
    b = min(fin(i), ventana(2));
    patch(ax, [a b b a], [0 0 1 1], est.lavado, 'EdgeColor', est.fondo, 'LineWidth', 2);
    if b - a > 0.4
        text(ax, (a + b) / 2, 0.5, sprintf('X%d', val(i)), 'HorizontalAlignment', 'center', ...
            'Color', est.tinta2, 'FontSize', 8, 'FontName', est.fuente);
    end
end
ax.XLim = ventana;
ax.YLim = [0 1];
ax.Visible = 'off';
ax.YLabel.Visible = 'on';
ylabel(ax, 'GRAFCET GP', 'Rotation', 0, 'HorizontalAlignment', 'right', ...
    'VerticalAlignment', 'middle', 'Color', est.tinta2, 'FontSize', 8, 'FontName', est.fuente);
end

function sombrear(ax, ventanas, est)
% Franja de fondo en las ventanas X7 (detrás de las curvas).
for i = 1:size(ventanas, 1)
    p = patch(ax, ventanas(i, [1 2 2 1]), ax.YLim([1 1 2 2]), est.lavado, 'EdgeColor', 'none');
    uistack(p, 'bottom');
end
end

function rotular_movimientos(ax, t, y, nombre, ventana, est)
% Etiqueta directa de cada salida (+) y regreso (-) dentro de la ventana mostrada.
cruces = find(diff(y >= 0.5) ~= 0);
for c = cruces(:)'
    if t(c) < ventana(1) || t(c) > ventana(2), continue; end
    if y(c + 1) > y(c), signo = '+'; else, signo = char(8722); end
    text(ax, t(c) + 0.08, 0.55, [nombre signo], 'Color', est.tinta, 'FontSize', 8, ...
        'FontName', est.fuente, 'FontWeight', 'bold');
end
end

function rotular_escalones(ax, t, y, formato, est)
% Rótulo directo en cada subida a un valor nuevo (X7, X8 / C = 1, 2, 3).
k = find(diff(y) > 0) + 1;
if contains(formato, 'X'), k = k(y(k) >= 7); end
for i = k(:)'
    text(ax, t(i) + 0.3, y(i), sprintf(formato, y(i)), 'VerticalAlignment', 'bottom', ...
        'Color', est.tinta2, 'FontSize', 7, 'FontName', est.fuente);
end
end

function eje_tiempo(ax, est)
ax.XTick = ceil(ax.XLim(1)):paso_rejilla(ax.XLim):floor(ax.XLim(2));
ax.XTickLabelMode = 'auto';
xlabel(ax, 'Tiempo [s]', 'Color', est.tinta2, 'FontSize', 8);
end

function paso = paso_rejilla(ventana)
% Una línea de rejilla por segundo; cada 4 s en la corrida completa.
paso = 1 + 3 * (diff(ventana) > 20);
end

function titulo(T, texto, subtitulo, est)
T.Title.String = texto;
T.Title.FontName = est.fuente;
T.Title.FontSize = 10;
T.Title.FontWeight = 'bold';
T.Title.Color = est.tinta;
T.Subtitle.String = subtitulo;
T.Subtitle.FontName = est.fuente;
T.Subtitle.FontSize = 8;
T.Subtitle.Color = est.tinta2;
T.Subtitle.Interpreter = 'none';
end
