const manifest = {"name":"Aparejo"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
}
const call = api.call;

const { useState, useEffect, useRef } = SP_REACT;
const h = SP_JSX.jsx;
const hs = SP_JSX.jsxs;

const mhz = (hz) => Math.round(hz / 1000000);
const khzToMhz = (khz) => Math.round(khz / 1000);

// ---- languages: Steam's own language picks the text (English when it has none of these) ----
const STRINGS = {
    en: {
        mode_off: "Fixed", lim_gamescope: "Steam", lim_off: "Game",
        modetxt_off: "Fixed clocks: the limits below apply.",
        modetxt_gpu: "The GPU looks for the lowest clock that keeps up with the game. The CPU stays at the limits below.",
        modetxt_cpu: "The CPU looks for the lowest clock that holds the target. The GPU stays at the limits below.",
        modetxt_both: "CPU and GPU look for the lowest clocks that hold the target. Saves the most.",
        st_base: "measuring", st_gpu: "tuning the GPU", st_down: "looking for the lowest clock", st_hold: "stable", st_recover: "recovering",
        limtxt_gamescope: "Steam's frame limiter (gamescope). Applies at once and goes back to normal when the game closes.",
        limtxt_mangohud: "Invisible MangoHud inside the game. Turns on and off at once (only the first launch after the profile is made needs a restart of the game).",
        limtxt_off: "The game locks its own FPS: set it in the game's graphics options.",
        core_small: "Small cores", core_mid: "Mid cores", core_big: "Big cores", cluster: "Cluster {0}", game_n: "Game {0}",
        loading: "Loading…", nogame_title: "No game running",
        nogame_text: "Open a game and come back here. Settings are saved per game and come back on their own when it starts; outside them Armada's power profile applies.",
        own_label: "Own settings", own_on: "Saved for this game; they come back on their own when it starts.", own_off: "Off: Armada's power profile applies.",
        auto_label: "Automatic", fps_label: "FPS target: {0}", fps_none: "FPS target: none",
        fps_desc_on: "Clocks go down to the lowest that holds this target.", fps_desc_off: "No target: the GPU only follows how busy it is.",
        lock_label: "Lock FPS with",
        status_fps: "{0} FPS  ·  target {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1}% busy", applying: "Applying…",
        note_fpserr: "FPS target has no effect: {0}",
        note_mh_pending: "MangoHud isn't loaded in this game yet: restart the game once. Until then Steam's limiter holds the FPS.",
        note_lim_fail: "The FPS went over the target: the chosen lock isn't holding this game.",
        note_vela: "Game with Vela: without an FPS target the automatic GPU may stutter a little. With a target, every step down is checked.",
        ceil_suffix: " · ceiling", gpu_ceil: "GPU · ceiling", gpu_max: "GPU maximum", gpu_floor: "GPU · floor", gpu_min: "GPU minimum",
        note_userspace: "Steam's manual GPU clock is on; the GPU limits here only apply with it off.",
        learned: "Learned: CPU {0} MHz. The next session starts from there.", forget: "Restart learning",
        limits_auto: "Automatic limits", limits: "Limits", error: "Error: {0}", mh_read_err: "could not read the game's launch options",
    },
    pt: {
        mode_off: "Fixo", lim_gamescope: "Steam", lim_off: "Jogo",
        modetxt_off: "Clocks fixos: valem os limites abaixo.",
        modetxt_gpu: "A GPU busca o menor clock que dá conta do jogo. A CPU fica nos limites abaixo.",
        modetxt_cpu: "A CPU busca o menor clock que segura a meta. A GPU fica nos limites abaixo.",
        modetxt_both: "CPU e GPU buscam o menor clock que segura a meta. É o que mais economiza.",
        st_base: "medindo", st_gpu: "ajustando a GPU", st_down: "procurando o menor clock", st_hold: "estável", st_recover: "recuperando",
        limtxt_gamescope: "Trava do Steam (gamescope). Vale na hora e volta ao normal quando o jogo fecha.",
        limtxt_mangohud: "MangoHud invisível dentro do jogo. Liga e desliga na hora (só na primeira vez que o jogo tem perfil é preciso reabri-lo).",
        limtxt_off: "O próprio jogo trava o FPS: ajuste nas opções gráficas dele.",
        core_small: "Núcleos menores", core_mid: "Núcleos médios", core_big: "Núcleos maiores", cluster: "Cluster {0}", game_n: "Jogo {0}",
        loading: "Carregando…", nogame_title: "Nenhum jogo aberto",
        nogame_text: "Abra um jogo e volte aqui. Os ajustes ficam salvos para cada jogo e voltam sozinhos quando ele abrir; fora deles vale o perfil de energia do Armada.",
        own_label: "Ajustes próprios", own_on: "Salvos para este jogo; voltam sozinhos quando ele abrir.", own_off: "Desligado: vale o perfil de energia do Armada.",
        auto_label: "Automático", fps_label: "Meta de FPS: {0}", fps_none: "Meta de FPS: sem meta",
        fps_desc_on: "Os clocks descem até o menor que segura essa meta.", fps_desc_off: "Sem meta: a GPU segue só o quanto está ocupada.",
        lock_label: "Travar FPS pelo",
        status_fps: "{0} FPS  ·  meta {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1}% ocupada", applying: "Aplicando…",
        note_fpserr: "Meta de FPS sem efeito: {0}",
        note_mh_pending: "O MangoHud ainda não está carregado neste jogo: reabra o jogo uma vez. Até lá, a trava do Steam segura o FPS.",
        note_lim_fail: "O FPS passou da meta: a trava escolhida não está segurando este jogo.",
        note_vela: "Jogo com Vela: sem meta de FPS a GPU automática pode dar pequenos engasgos. Com meta, cada descida é conferida.",
        ceil_suffix: " · teto", gpu_ceil: "GPU · teto", gpu_max: "GPU máxima", gpu_floor: "GPU · piso", gpu_min: "GPU mínima",
        note_userspace: "O clock manual da GPU do Steam está ligado; os limites de GPU daqui só valem com ele desligado.",
        learned: "Aprendido: CPU {0} MHz. A próxima partida começa daí.", forget: "Recomeçar o aprendizado",
        limits_auto: "Limites do automático", limits: "Limites", error: "Erro: {0}", mh_read_err: "não consegui ler as opções de inicialização do jogo",
    },
    es: {
        mode_off: "Fijo", lim_gamescope: "Steam", lim_off: "Juego",
        modetxt_off: "Relojes fijos: se aplican los límites de abajo.",
        modetxt_gpu: "La GPU busca el reloj más bajo que da abasto con el juego. La CPU queda en los límites de abajo.",
        modetxt_cpu: "La CPU busca el reloj más bajo que mantiene el objetivo. La GPU queda en los límites de abajo.",
        modetxt_both: "CPU y GPU buscan los relojes más bajos que mantienen el objetivo. Es lo que más ahorra.",
        st_base: "midiendo", st_gpu: "ajustando la GPU", st_down: "buscando el reloj más bajo", st_hold: "estable", st_recover: "recuperando",
        limtxt_gamescope: "Limitador de Steam (gamescope). Se aplica al instante y vuelve a la normalidad al cerrar el juego.",
        limtxt_mangohud: "MangoHud invisible dentro del juego. Se activa y desactiva al instante (solo el primer inicio tras crear el perfil requiere reiniciar el juego).",
        limtxt_off: "El propio juego limita los FPS: ajústalo en sus opciones gráficas.",
        core_small: "Núcleos pequeños", core_mid: "Núcleos medios", core_big: "Núcleos grandes", cluster: "Clúster {0}", game_n: "Juego {0}",
        loading: "Cargando…", nogame_title: "Ningún juego abierto",
        nogame_text: "Abre un juego y vuelve aquí. Los ajustes se guardan por juego y vuelven solos cuando se inicia; fuera de ellos se aplica el perfil de energía de Armada.",
        own_label: "Ajustes propios", own_on: "Guardados para este juego; vuelven solos cuando se inicia.", own_off: "Desactivado: se aplica el perfil de energía de Armada.",
        auto_label: "Automático", fps_label: "Objetivo de FPS: {0}", fps_none: "Objetivo de FPS: ninguno",
        fps_desc_on: "Los relojes bajan hasta el mínimo que mantiene este objetivo.", fps_desc_off: "Sin objetivo: la GPU solo sigue cuán ocupada está.",
        lock_label: "Limitar FPS con",
        status_fps: "{0} FPS  ·  objetivo {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1}% ocupada", applying: "Aplicando…",
        note_fpserr: "El objetivo de FPS no tiene efecto: {0}",
        note_mh_pending: "MangoHud aún no está cargado en este juego: reinicia el juego una vez. Mientras tanto, el limitador de Steam mantiene los FPS.",
        note_lim_fail: "Los FPS superaron el objetivo: el limitador elegido no está frenando este juego.",
        note_vela: "Juego con Vela: sin objetivo de FPS la GPU automática puede dar pequeños tirones. Con objetivo, cada bajada se comprueba.",
        ceil_suffix: " · techo", gpu_ceil: "GPU · techo", gpu_max: "GPU máxima", gpu_floor: "GPU · piso", gpu_min: "GPU mínima",
        note_userspace: "El reloj manual de GPU de Steam está activado; los límites de GPU de aquí solo valen con él desactivado.",
        learned: "Aprendido: CPU {0} MHz. La próxima sesión empieza desde ahí.", forget: "Reiniciar el aprendizaje",
        limits_auto: "Límites del modo automático", limits: "Límites", error: "Error: {0}", mh_read_err: "no se pudieron leer las opciones de lanzamiento del juego",
    },
    fr: {
        mode_off: "Fixe", lim_gamescope: "Steam", lim_off: "Jeu",
        modetxt_off: "Fréquences fixes : les limites ci-dessous s'appliquent.",
        modetxt_gpu: "Le GPU cherche la fréquence la plus basse qui suffit au jeu. Le CPU reste aux limites ci-dessous.",
        modetxt_cpu: "Le CPU cherche la fréquence la plus basse qui tient l'objectif. Le GPU reste aux limites ci-dessous.",
        modetxt_both: "CPU et GPU cherchent les fréquences les plus basses qui tiennent l'objectif. C'est le plus économe.",
        st_base: "mesure", st_gpu: "réglage du GPU", st_down: "recherche de la fréquence la plus basse", st_hold: "stable", st_recover: "récupération",
        limtxt_gamescope: "Limiteur de Steam (gamescope). S'applique tout de suite et revient à la normale à la fermeture du jeu.",
        limtxt_mangohud: "MangoHud invisible dans le jeu. S'active et se désactive tout de suite (seul le premier lancement après la création du profil demande de relancer le jeu).",
        limtxt_off: "Le jeu limite lui-même ses FPS : réglez-le dans ses options graphiques.",
        core_small: "Petits cœurs", core_mid: "Cœurs moyens", core_big: "Grands cœurs", cluster: "Groupe {0}", game_n: "Jeu {0}",
        loading: "Chargement…", nogame_title: "Aucun jeu lancé",
        nogame_text: "Lancez un jeu et revenez ici. Les réglages sont enregistrés par jeu et reviennent d'eux-mêmes à son lancement ; ailleurs, le profil d'énergie d'Armada s'applique.",
        own_label: "Réglages propres", own_on: "Enregistrés pour ce jeu ; ils reviennent d'eux-mêmes à son lancement.", own_off: "Désactivé : le profil d'énergie d'Armada s'applique.",
        auto_label: "Automatique", fps_label: "Objectif FPS : {0}", fps_none: "Objectif FPS : aucun",
        fps_desc_on: "Les fréquences descendent jusqu'à la plus basse qui tient cet objectif.", fps_desc_off: "Sans objectif : le GPU suit seulement sa charge.",
        lock_label: "Limiter les FPS avec",
        status_fps: "{0} FPS  ·  objectif {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1} % occupé", applying: "Application…",
        note_fpserr: "L'objectif FPS est sans effet : {0}",
        note_mh_pending: "MangoHud n'est pas encore chargé dans ce jeu : relancez le jeu une fois. D'ici là, le limiteur de Steam tient les FPS.",
        note_lim_fail: "Les FPS ont dépassé l'objectif : le limiteur choisi ne retient pas ce jeu.",
        note_vela: "Jeu avec Vela : sans objectif FPS, le GPU automatique peut avoir de petites saccades. Avec un objectif, chaque baisse est vérifiée.",
        ceil_suffix: " · plafond", gpu_ceil: "GPU · plafond", gpu_max: "GPU maximum", gpu_floor: "GPU · plancher", gpu_min: "GPU minimum",
        note_userspace: "La fréquence GPU manuelle de Steam est activée ; les limites GPU d'ici ne s'appliquent que si elle est désactivée.",
        learned: "Appris : CPU {0} MHz. La prochaine session part de là.", forget: "Recommencer l'apprentissage",
        limits_auto: "Limites du mode automatique", limits: "Limites", error: "Erreur : {0}", mh_read_err: "impossible de lire les options de lancement du jeu",
    },
    de: {
        mode_off: "Fest", lim_gamescope: "Steam", lim_off: "Spiel",
        modetxt_off: "Feste Takte: Es gelten die Grenzen unten.",
        modetxt_gpu: "Die GPU sucht den niedrigsten Takt, der für das Spiel reicht. Die CPU bleibt bei den Grenzen unten.",
        modetxt_cpu: "Die CPU sucht den niedrigsten Takt, der das Ziel hält. Die GPU bleibt bei den Grenzen unten.",
        modetxt_both: "CPU und GPU suchen die niedrigsten Takte, die das Ziel halten. Spart am meisten.",
        st_base: "misst", st_gpu: "stellt die GPU ein", st_down: "sucht den niedrigsten Takt", st_hold: "stabil", st_recover: "erholt sich",
        limtxt_gamescope: "Steams Bildratenbegrenzer (gamescope). Wirkt sofort und wird beim Beenden des Spiels zurückgesetzt.",
        limtxt_mangohud: "Unsichtbares MangoHud im Spiel. Schaltet sofort ein und aus (nur der erste Start nach dem Anlegen des Profils braucht einen Neustart des Spiels).",
        limtxt_off: "Das Spiel begrenzt seine FPS selbst: in den Grafikoptionen des Spiels einstellen.",
        core_small: "Kleine Kerne", core_mid: "Mittlere Kerne", core_big: "Große Kerne", cluster: "Cluster {0}", game_n: "Spiel {0}",
        loading: "Lädt…", nogame_title: "Kein Spiel geöffnet",
        nogame_text: "Starte ein Spiel und komm hierher zurück. Einstellungen werden pro Spiel gespeichert und beim Start automatisch übernommen; sonst gilt Armadas Energieprofil.",
        own_label: "Eigene Einstellungen", own_on: "Für dieses Spiel gespeichert; werden beim Start automatisch übernommen.", own_off: "Aus: Armadas Energieprofil gilt.",
        auto_label: "Automatik", fps_label: "FPS-Ziel: {0}", fps_none: "FPS-Ziel: keins",
        fps_desc_on: "Die Takte sinken bis zum niedrigsten, der dieses Ziel hält.", fps_desc_off: "Ohne Ziel folgt die GPU nur ihrer Auslastung.",
        lock_label: "FPS begrenzen mit",
        status_fps: "{0} FPS  ·  Ziel {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1} % ausgelastet", applying: "Wird angewendet…",
        note_fpserr: "FPS-Ziel ohne Wirkung: {0}",
        note_mh_pending: "MangoHud ist in diesem Spiel noch nicht geladen: Spiel einmal neu starten. Bis dahin hält Steams Begrenzer die FPS.",
        note_lim_fail: "Die FPS liegen über dem Ziel: Der gewählte Begrenzer hält dieses Spiel nicht.",
        note_vela: "Spiel mit Vela: Ohne FPS-Ziel kann die automatische GPU leicht ruckeln. Mit Ziel wird jeder Schritt nach unten geprüft.",
        ceil_suffix: " · Obergrenze", gpu_ceil: "GPU · Obergrenze", gpu_max: "GPU maximal", gpu_floor: "GPU · Untergrenze", gpu_min: "GPU minimal",
        note_userspace: "Steams manueller GPU-Takt ist an; die GPU-Grenzen hier gelten nur, wenn er aus ist.",
        learned: "Gelernt: CPU {0} MHz. Die nächste Sitzung beginnt dort.", forget: "Lernen neu starten",
        limits_auto: "Grenzen der Automatik", limits: "Grenzen", error: "Fehler: {0}", mh_read_err: "Startoptionen des Spiels konnten nicht gelesen werden",
    },
    it: {
        mode_off: "Fisso", lim_gamescope: "Steam", lim_off: "Gioco",
        modetxt_off: "Frequenze fisse: valgono i limiti qui sotto.",
        modetxt_gpu: "La GPU cerca la frequenza più bassa che basta al gioco. La CPU resta ai limiti qui sotto.",
        modetxt_cpu: "La CPU cerca la frequenza più bassa che mantiene l'obiettivo. La GPU resta ai limiti qui sotto.",
        modetxt_both: "CPU e GPU cercano le frequenze più basse che mantengono l'obiettivo. È ciò che fa risparmiare di più.",
        st_base: "misurazione", st_gpu: "regolazione della GPU", st_down: "ricerca della frequenza più bassa", st_hold: "stabile", st_recover: "recupero",
        limtxt_gamescope: "Limitatore di Steam (gamescope). Si applica subito e torna normale alla chiusura del gioco.",
        limtxt_mangohud: "MangoHud invisibile nel gioco. Si attiva e disattiva subito (solo il primo avvio dopo la creazione del profilo richiede di riavviare il gioco).",
        limtxt_off: "Il gioco limita da sé gli FPS: impostalo nelle sue opzioni grafiche.",
        core_small: "Core piccoli", core_mid: "Core medi", core_big: "Core grandi", cluster: "Cluster {0}", game_n: "Gioco {0}",
        loading: "Caricamento…", nogame_title: "Nessun gioco aperto",
        nogame_text: "Apri un gioco e torna qui. Le impostazioni sono salvate per ogni gioco e tornano da sole quando si avvia; altrimenti vale il profilo energetico di Armada.",
        own_label: "Impostazioni proprie", own_on: "Salvate per questo gioco; tornano da sole quando si avvia.", own_off: "Disattivato: vale il profilo energetico di Armada.",
        auto_label: "Automatico", fps_label: "Obiettivo FPS: {0}", fps_none: "Obiettivo FPS: nessuno",
        fps_desc_on: "Le frequenze scendono fino alla più bassa che mantiene questo obiettivo.", fps_desc_off: "Senza obiettivo la GPU segue solo il proprio carico.",
        lock_label: "Limita FPS con",
        status_fps: "{0} FPS  ·  obiettivo {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  {1}% occupata", applying: "Applicazione…",
        note_fpserr: "L'obiettivo FPS non ha effetto: {0}",
        note_mh_pending: "MangoHud non è ancora caricato in questo gioco: riavvia il gioco una volta. Fino ad allora il limitatore di Steam tiene gli FPS.",
        note_lim_fail: "Gli FPS hanno superato l'obiettivo: il limitatore scelto non trattiene questo gioco.",
        note_vela: "Gioco con Vela: senza obiettivo FPS la GPU automatica può avere piccoli scatti. Con un obiettivo, ogni discesa viene verificata.",
        ceil_suffix: " · tetto", gpu_ceil: "GPU · tetto", gpu_max: "GPU massima", gpu_floor: "GPU · minimo", gpu_min: "GPU minima",
        note_userspace: "La frequenza GPU manuale di Steam è attiva; i limiti GPU qui valgono solo se è disattivata.",
        learned: "Appreso: CPU {0} MHz. La prossima sessione parte da qui.", forget: "Ricomincia l'apprendimento",
        limits_auto: "Limiti dell'automatico", limits: "Limiti", error: "Errore: {0}", mh_read_err: "impossibile leggere le opzioni di avvio del gioco",
    },
    ru: {
        mode_off: "Фикс.", lim_gamescope: "Steam", lim_off: "Игра",
        modetxt_off: "Фиксированные частоты: действуют ограничения ниже.",
        modetxt_gpu: "GPU ищет самую низкую частоту, которой хватает игре. CPU остаётся в пределах ниже.",
        modetxt_cpu: "CPU ищет самую низкую частоту, при которой держится цель. GPU остаётся в пределах ниже.",
        modetxt_both: "CPU и GPU ищут самые низкие частоты, при которых держится цель. Экономит больше всего.",
        st_base: "измерение", st_gpu: "настройка GPU", st_down: "поиск минимальной частоты", st_hold: "стабильно", st_recover: "восстановление",
        limtxt_gamescope: "Ограничитель Steam (gamescope). Действует сразу и сбрасывается при закрытии игры.",
        limtxt_mangohud: "Невидимый MangoHud внутри игры. Включается и выключается сразу (перезапуск игры нужен только при первом запуске после создания профиля).",
        limtxt_off: "Игра сама ограничивает FPS: настройте это в её графических параметрах.",
        core_small: "Малые ядра", core_mid: "Средние ядра", core_big: "Большие ядра", cluster: "Кластер {0}", game_n: "Игра {0}",
        loading: "Загрузка…", nogame_title: "Игра не запущена",
        nogame_text: "Запустите игру и вернитесь сюда. Настройки сохраняются для каждой игры и применяются сами при её запуске; в остальное время действует профиль питания Armada.",
        own_label: "Свои настройки", own_on: "Сохранены для этой игры; применяются сами при запуске.", own_off: "Выкл.: действует профиль питания Armada.",
        auto_label: "Автоматика", fps_label: "Цель FPS: {0}", fps_none: "Цель FPS: нет",
        fps_desc_on: "Частоты опускаются до минимальных, при которых держится эта цель.", fps_desc_off: "Без цели GPU следит только за своей загрузкой.",
        lock_label: "Ограничивать FPS через",
        status_fps: "{0} FPS  ·  цель {1}  ·  {2}", status_cpu: "CPU {0} МГц", status_gpu: "GPU {0} МГц  ·  загрузка {1}%", applying: "Применяется…",
        note_fpserr: "Цель FPS не действует: {0}",
        note_mh_pending: "MangoHud ещё не загружен в эту игру: перезапустите игру один раз. До тех пор FPS держит ограничитель Steam.",
        note_lim_fail: "FPS выше цели: выбранный ограничитель не сдерживает эту игру.",
        note_vela: "Игра с Vela: без цели FPS автоматический GPU может немного подтормаживать. С целью каждое снижение проверяется.",
        ceil_suffix: " · потолок", gpu_ceil: "GPU · потолок", gpu_max: "GPU макс.", gpu_floor: "GPU · минимум", gpu_min: "GPU мин.",
        note_userspace: "Ручная частота GPU в Steam включена; ограничения GPU здесь действуют, только когда она выключена.",
        learned: "Выучено: CPU {0} МГц. Следующая сессия начнётся отсюда.", forget: "Начать обучение заново",
        limits_auto: "Пределы автоматики", limits: "Пределы", error: "Ошибка: {0}", mh_read_err: "не удалось прочитать параметры запуска игры",
    },
    ja: {
        mode_off: "固定", lim_gamescope: "Steam", lim_off: "ゲーム",
        modetxt_off: "クロック固定：下の上限・下限が適用されます。",
        modetxt_gpu: "GPU がゲームに足りる最低のクロックを探します。CPU は下の上限のままです。",
        modetxt_cpu: "CPU が目標を保てる最低のクロックを探します。GPU は下の上限のままです。",
        modetxt_both: "CPU と GPU が目標を保てる最低のクロックを探します。最も省電力です。",
        st_base: "測定中", st_gpu: "GPU を調整中", st_down: "最低クロックを探索中", st_hold: "安定", st_recover: "回復中",
        limtxt_gamescope: "Steam のフレームリミッター（gamescope）。すぐに効き、ゲーム終了時に元に戻ります。",
        limtxt_mangohud: "ゲーム内の非表示の MangoHud。すぐにオン・オフできます（プロファイル作成後の最初の起動だけゲームの再起動が必要です）。",
        limtxt_off: "ゲーム自体が FPS を制限します：ゲームのグラフィック設定で調整してください。",
        core_small: "小コア", core_mid: "中コア", core_big: "大コア", cluster: "クラスター {0}", game_n: "ゲーム {0}",
        loading: "読み込み中…", nogame_title: "ゲームが起動していません",
        nogame_text: "ゲームを起動してからここに戻ってください。設定はゲームごとに保存され、起動時に自動で適用されます。それ以外は Armada の電源プロファイルが使われます。",
        own_label: "個別設定", own_on: "このゲーム用に保存済み。起動時に自動で適用されます。", own_off: "オフ：Armada の電源プロファイルが適用されます。",
        auto_label: "自動", fps_label: "目標 FPS：{0}", fps_none: "目標 FPS：なし",
        fps_desc_on: "この目標を保てる最低のクロックまで下げます。", fps_desc_off: "目標なし：GPU は使用率だけを見ます。",
        lock_label: "FPS の制限方法",
        status_fps: "{0} FPS  ·  目標 {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  使用率 {1}%", applying: "適用中…",
        note_fpserr: "目標 FPS が効いていません：{0}",
        note_mh_pending: "このゲームにはまだ MangoHud が読み込まれていません。ゲームを一度再起動してください。それまでは Steam のリミッターが FPS を保ちます。",
        note_lim_fail: "FPS が目標を超えています：選んだリミッターがこのゲームを抑えていません。",
        note_vela: "Vela 使用のゲーム：目標 FPS がないと自動 GPU で小さなカクつきが出ることがあります。目標ありでは下げるたびに確認します。",
        ceil_suffix: "・上限", gpu_ceil: "GPU・上限", gpu_max: "GPU 最大", gpu_floor: "GPU・下限", gpu_min: "GPU 最小",
        note_userspace: "Steam の手動 GPU クロックがオンです。ここでの GPU 制限はオフのときだけ有効です。",
        learned: "学習済み：CPU {0} MHz。次回はここから始まります。", forget: "学習をやり直す",
        limits_auto: "自動の範囲", limits: "上限・下限", error: "エラー：{0}", mh_read_err: "ゲームの起動オプションを読み取れませんでした",
    },
    ko: {
        mode_off: "고정", lim_gamescope: "Steam", lim_off: "게임",
        modetxt_off: "클럭 고정: 아래 한도가 적용됩니다.",
        modetxt_gpu: "GPU가 게임에 충분한 가장 낮은 클럭을 찾습니다. CPU는 아래 한도를 유지합니다.",
        modetxt_cpu: "CPU가 목표를 유지하는 가장 낮은 클럭을 찾습니다. GPU는 아래 한도를 유지합니다.",
        modetxt_both: "CPU와 GPU가 목표를 유지하는 가장 낮은 클럭을 찾습니다. 가장 많이 절약됩니다.",
        st_base: "측정 중", st_gpu: "GPU 조정 중", st_down: "최저 클럭 찾는 중", st_hold: "안정", st_recover: "복구 중",
        limtxt_gamescope: "Steam 프레임 제한(gamescope). 즉시 적용되며 게임을 닫으면 원래대로 돌아갑니다.",
        limtxt_mangohud: "게임 안의 보이지 않는 MangoHud. 즉시 켜고 끌 수 있습니다(프로필을 만든 뒤 첫 실행만 게임을 다시 시작해야 합니다).",
        limtxt_off: "게임이 직접 FPS를 제한합니다: 게임의 그래픽 설정에서 조정하세요.",
        core_small: "작은 코어", core_mid: "중간 코어", core_big: "큰 코어", cluster: "클러스터 {0}", game_n: "게임 {0}",
        loading: "불러오는 중…", nogame_title: "실행 중인 게임 없음",
        nogame_text: "게임을 실행한 뒤 여기로 돌아오세요. 설정은 게임별로 저장되며 실행 시 자동으로 적용됩니다. 그 외에는 Armada 전원 프로필이 적용됩니다.",
        own_label: "개별 설정", own_on: "이 게임에 저장됨. 실행 시 자동으로 적용됩니다.", own_off: "꺼짐: Armada 전원 프로필이 적용됩니다.",
        auto_label: "자동", fps_label: "목표 FPS: {0}", fps_none: "목표 FPS: 없음",
        fps_desc_on: "이 목표를 유지하는 가장 낮은 클럭까지 내립니다.", fps_desc_off: "목표 없음: GPU는 사용률만 따릅니다.",
        lock_label: "FPS 제한 방식",
        status_fps: "{0} FPS  ·  목표 {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  사용률 {1}%", applying: "적용 중…",
        note_fpserr: "목표 FPS가 적용되지 않음: {0}",
        note_mh_pending: "이 게임에는 아직 MangoHud가 로드되지 않았습니다. 게임을 한 번 다시 시작하세요. 그동안은 Steam 제한이 FPS를 유지합니다.",
        note_lim_fail: "FPS가 목표를 넘었습니다: 선택한 제한이 이 게임을 막지 못하고 있습니다.",
        note_vela: "Vela 게임: 목표 FPS가 없으면 자동 GPU에서 약간 끊길 수 있습니다. 목표가 있으면 내릴 때마다 확인합니다.",
        ceil_suffix: " · 상한", gpu_ceil: "GPU · 상한", gpu_max: "GPU 최대", gpu_floor: "GPU · 하한", gpu_min: "GPU 최소",
        note_userspace: "Steam 수동 GPU 클럭이 켜져 있습니다. 여기의 GPU 한도는 꺼져 있을 때만 적용됩니다.",
        learned: "학습됨: CPU {0} MHz. 다음 세션은 여기서 시작합니다.", forget: "학습 다시 시작",
        limits_auto: "자동 한도", limits: "한도", error: "오류: {0}", mh_read_err: "게임 실행 옵션을 읽을 수 없습니다",
    },
    zh: {
        mode_off: "固定", lim_gamescope: "Steam", lim_off: "游戏",
        modetxt_off: "固定频率：使用下方的限制。",
        modetxt_gpu: "GPU 寻找足以运行游戏的最低频率。CPU 保持下方的限制。",
        modetxt_cpu: "CPU 寻找能维持目标的最低频率。GPU 保持下方的限制。",
        modetxt_both: "CPU 和 GPU 寻找能维持目标的最低频率。最省电。",
        st_base: "测量中", st_gpu: "调整 GPU", st_down: "寻找最低频率", st_hold: "稳定", st_recover: "恢复中",
        limtxt_gamescope: "Steam 帧率限制（gamescope）。立即生效，游戏关闭后恢复原状。",
        limtxt_mangohud: "游戏内隐藏的 MangoHud。可即时开关（仅在创建配置后的首次启动需要重启游戏）。",
        limtxt_off: "由游戏自身限制 FPS：在游戏的图形设置中调整。",
        core_small: "小核", core_mid: "中核", core_big: "大核", cluster: "集群 {0}", game_n: "游戏 {0}",
        loading: "加载中…", nogame_title: "没有正在运行的游戏",
        nogame_text: "打开一个游戏后再回到这里。设置按游戏保存，启动时自动生效；其余时间使用 Armada 的电源配置。",
        own_label: "独立设置", own_on: "已为此游戏保存；启动时自动生效。", own_off: "关闭：使用 Armada 的电源配置。",
        auto_label: "自动", fps_label: "目标 FPS：{0}", fps_none: "目标 FPS：无",
        fps_desc_on: "频率会降到能维持此目标的最低值。", fps_desc_off: "无目标：GPU 只根据占用率调整。",
        lock_label: "FPS 限制方式",
        status_fps: "{0} FPS  ·  目标 {1}  ·  {2}", status_cpu: "CPU {0} MHz", status_gpu: "GPU {0} MHz  ·  占用 {1}%", applying: "正在应用…",
        note_fpserr: "目标 FPS 未生效：{0}",
        note_mh_pending: "此游戏尚未加载 MangoHud：请重启游戏一次。在此之前由 Steam 限制器维持 FPS。",
        note_lim_fail: "FPS 超出目标：所选的限制方式没有限住此游戏。",
        note_vela: "使用 Vela 的游戏：没有目标 FPS 时自动 GPU 可能会轻微卡顿。有目标时每次降频都会检查。",
        ceil_suffix: " · 上限", gpu_ceil: "GPU · 上限", gpu_max: "GPU 最高", gpu_floor: "GPU · 下限", gpu_min: "GPU 最低",
        note_userspace: "Steam 的手动 GPU 频率已开启；此处的 GPU 限制仅在其关闭时有效。",
        learned: "已学习：CPU {0} MHz。下次从这里开始。", forget: "重新学习",
        limits_auto: "自动范围", limits: "限制", error: "错误：{0}", mh_read_err: "无法读取游戏的启动选项",
    },
};
// Steam's language names -> ours
const STEAM_LANGS = {
    english: "en", brazilian: "pt", portuguese: "pt", spanish: "es", latam: "es", french: "fr", german: "de",
    italian: "it", russian: "ru", ukrainian: "ru", japanese: "ja", koreana: "ko", schinese: "zh", tchinese: "zh",
};
let LANG = (() => {
    const fromUrl = new URLSearchParams(window.location.search).get("LANGUAGE");
    if (fromUrl && STEAM_LANGS[fromUrl]) return STEAM_LANGS[fromUrl];
    const nav = String(navigator.language || "en").slice(0, 2).toLowerCase();
    return STRINGS[nav] ? nav : "en";
})();
try {
    Promise.resolve(SteamClient.Settings.GetCurrentLanguage()).then((l) => { if (STEAM_LANGS[l]) LANG = STEAM_LANGS[l]; }).catch(() => { });
} catch (e) { }
function t(key, ...args) {
    const s = (STRINGS[LANG] && STRINGS[LANG][key]) ?? STRINGS.en[key] ?? key;
    return s.replace(/\{(\d)\}/g, (_, i) => String(args[Number(i)] ?? ""));
}

// Every choice is a notched slider, like Steam's own Performance tab: a dropdown opens its menu over the library
// and closes the quick access panel (2026-11-18), so the plugin had to be opened again after each pick.
const MODE_IDS = ["off", "gpu", "cpu", "both"];
const modeOptions = () => [
    { data: "off", label: t("mode_off") },
    { data: "gpu", label: "GPU" },
    { data: "cpu", label: "CPU" },
    { data: "both", label: "CPU + GPU" },
];
const LIMITER_IDS = ["gamescope", "mangohud", "off"];
const limiterOptions = () => [
    { data: "gamescope", label: t("lim_gamescope") },
    { data: "mangohud", label: "MangoHud" },
    { data: "off", label: t("lim_off") },
];
const limiterOf = (cfg) => (cfg && LIMITER_IDS.includes(cfg.limiter) ? cfg.limiter : "gamescope");const MH_RX = /MANGOHUD=1 MANGOHUD_CONFIGFILE=\S+ ?/g;

// The game's launch options through Steam's own API (the way its Properties page reads them).
function launchOptions(appid) {
    return new Promise((resolve) => {
        let done = false, reg = null;
        const finish = (value) => {
            if (done) return;
            done = true;
            setTimeout(() => { try { reg && reg.unregister(); } catch (e) { } }, 0);
            resolve(value);
        };
        try {
            reg = SteamClient.Apps.RegisterForAppDetails(Number(appid), (d) => finish(typeof d?.strLaunchOptions === "string" ? d.strLaunchOptions : null));
        } catch (e) { finish(null); }
        setTimeout(() => finish(null), 5000);
    });
}

// Adds or removes the MangoHud limiter (its env vars) at the start of the game's launch options.
async function setMangohudLaunch(appid, on, mh) {
    const cur = await launchOptions(appid);
    if (cur === null) throw new Error(t("mh_read_err"));
    const rest = cur.replace(MH_RX, "").trim();
    let next = rest;
    if (on) {
        const prefix = `${mh.env}${mh.dir}/${appid}.conf `;
        next = prefix + (!rest ? "%command%" : (rest.includes("%command%") ? rest : `%command% ${rest}`));
    }
    if (next !== cur) SteamClient.Apps.SetAppLaunchOptions(Number(appid), next);
}

// Steam's own frame limit, as the quick access menu's Performance tab sets it on Armada: two client settings,
// "Disable frame limit" (gamescope_disable_framelimit, must be off) and the app's target framerate
// (gamescope_app_target_framerate). Found by what the settings module does (webpack ids change between Steam
// builds). Measured 2026-11-18, Yakuza uncapped: gamescope's limiter came on (GAMESCOPE_LIMITER_FEEDBACK 1),
// 9.4 -> 6.4 W. Writing GAMESCOPE_FPS_LIMIT, or the perf store's SetFPSLimit, did nothing here.
let steamSettingsMod = null;
function steamSettings() {
    if (steamSettingsMod) return steamSettingsMod;
    try {
        let req = null;
        window.webpackChunksteamui.push([[Symbol("aparejo")], {}, (r) => { req = r; }]);
        for (const id of Object.keys(req.m)) {
            const src = String(req.m[id]);
            if (!src.includes("SteamClient.Settings.SetSetting(") || !src.includes("clientSettings")) continue;
            const ex = req(id);
            let set = null, store = null;
            for (const k in ex) {
                try {
                    const v = ex[k];
                    if (typeof v === "function" && String(v).includes("BinaryWriter")) set = v;
                    else if (v && typeof v === "object" && v.clientSettings) store = v;
                } catch (e) { }
            }
            if (set && store) { steamSettingsMod = { set, store }; return steamSettingsMod; }
        }
    } catch (e) { }
    return null;
}

// While a game with an FPS target runs (gamescope limiter, or MangoHud not loaded yet), Steam's frame limit is set
// to the target; what was there before is put back when the game ends or the profile changes.
let limitSaved = null;
async function limitTick() {
    let s;
    try { s = await call("get_state"); } catch (e) { return; }
    const lim = s.limiter || {};
    const want = (lim.kind === "gamescope" || lim.kind === "mangohud-pending") && lim.fps ? lim.fps : 0;
    // profiles made before 0.2.6 have no layer in their launch options yet: add it once (from the next launch)
    if (s.active && s.games && s.games[s.active] && s.mangohud && !layerAsked[s.active]) {
        layerAsked[s.active] = true;
        setMangohudLaunch(s.active, true, s.mangohud).catch(() => { layerAsked[s.active] = false; });
    }
    const st = steamSettings();
    if (!st) return;
    const cs = st.store.clientSettings || {};
    try {
        if (want) {
            if (!limitSaved) limitSaved = { disable: cs.gamescope_disable_framelimit, target: cs.gamescope_app_target_framerate };
            if (cs.gamescope_disable_framelimit) st.set("gamescope_disable_framelimit", false);
            if (cs.gamescope_app_target_framerate !== want) st.set("gamescope_app_target_framerate", want);
        }
        else if (limitSaved) {
            restoreLimit(st);
        }
    } catch (e) { }
}
function restoreLimit(st) {
    const cs = st.store.clientSettings || {};
    if (typeof limitSaved.target === "number" && cs.gamescope_app_target_framerate !== limitSaved.target) st.set("gamescope_app_target_framerate", limitSaved.target);
    if (typeof limitSaved.disable === "boolean" && cs.gamescope_disable_framelimit !== limitSaved.disable) st.set("gamescope_disable_framelimit", limitSaved.disable);
    limitSaved = null;
}

// Every game with a profile gets the (invisible, unlimited) MangoHud layer in its launch options, so MangoHud's
// FPS lock can go on, off or change value with the game running (the layer re-reads its config file). A layer can
// only be loaded when the game starts: the first launch after the profile is made has none yet.
const wantsMangohud = (cfg) => !!cfg;
const layerAsked = {};

// Same rule as the backend's game_mode(): profiles saved before 0.1.7 have no mode.
function modeOf(cfg) {
    if (!cfg) return "off";
    if (MODE_IDS.includes(cfg.mode)) return cfg.mode;
    if (cfg.fps_target) return "both";
    return cfg.gpu_auto ? "gpu" : "off";
}

function nearestIndex(freqs, value) {
    let best = 0;
    for (let i = 0; i < freqs.length; i++) {
        if (freqs[i] <= value) best = i;
    }
    return best;
}

function clusterLabel(policies, index) {
    if (policies.length === 2) return index === 0 ? t("core_small") : t("core_big");
    if (policies.length === 3) return [t("core_small"), t("core_mid"), t("core_big")][index];
    return t("cluster", index + 1);
}

function cpusText(cpus) {
    const list = String(cpus || "").split(/\s+/).filter(Boolean).map(Number);
    if (list.length > 1 && list[list.length - 1] - list[0] === list.length - 1) return `${list[0]}-${list[list.length - 1]}`;
    return list.join(",");
}

function runningGame(state) {
    const app = DFL.Router?.MainRunningApp || window.Router?.MainRunningApp;
    const running = state?.running || [];
    const uiId = app?.appid != null ? String(app.appid) : null;
    let appid = null;
    if (uiId && running.includes(uiId)) appid = uiId;
    else if (running.length === 1) appid = running[0];
    else if (uiId && running.length === 0) appid = null;
    else if (uiId) appid = uiId;
    if (!appid) return null;
    const name = (app && String(app.appid) === appid ? app.display_name : null)
        || state?.games?.[appid]?.name || t("game_n", appid);
    return { appid, name };
}

function defaultsFromNow(state, name) {
    const cpu = {};
    for (const p of state.policies) cpu[String(p.id)] = p.max;
    const cfg = { enabled: true, name, cpu, mode: "off" };
    if (state.gpu) {
        cfg.gpu_max = state.gpu.max;
        cfg.gpu_min = state.gpu.min;
    }
    return cfg;
}

function Row({ children }) {
    return h(DFL.PanelSectionRow, { children });
}

function Note({ children, warn }) {
    return h("div", { style: { fontSize: "12px", color: warn ? "#e8b44a" : "#9aa3ad", padding: "2px 0 6px", lineHeight: "16px" }, children });
}

// A small panel with the live numbers of the running game.
function Status({ lines }) {
    return h(Row, { children: h("div", {
        style: { background: "rgba(255,255,255,0.06)", borderRadius: "6px", padding: "8px 10px", margin: "4px 0 8px",
            fontSize: "12px", lineHeight: "18px", color: "#dfe3e6" },
        children: lines.map((l, i) => h("div", { style: i === 0 ? { fontSize: "14px", fontWeight: 600 } : { color: "#9aa3ad" }, children: l }, i)),
    }) });
}

function ChoiceSlider({ label, description, options, value, onChange }) {
    const idx = Math.max(0, options.findIndex((o) => o.data === value));
    return h(Row, { children: h(DFL.SliderField, {
        label, description, value: idx, min: 0, max: Math.max(options.length - 1, 1), step: 1,
        notchCount: options.length, notchLabels: options.map((o, i) => ({ notchIndex: i, label: o.label, value: i })),
        notchTicksVisible: true, showValue: false, childrenContainerWidth: "max",
        onChange: (i) => {
            const o = options[Math.min(Math.max(Math.round(i), 0), options.length - 1)];
            if (o && o.data !== value) onChange(o.data);
        },
    }) });
}

function FreqSlider({ label, freqs, value, onChange, toMhz }) {
    const idx = nearestIndex(freqs, value);
    return h(Row, { children: h(DFL.SliderField, {
        label: `${label}: ${toMhz(freqs[idx])} MHz`,
        value: idx, min: 0, max: Math.max(freqs.length - 1, 1), step: 1,
        childrenContainerWidth: "max",
        onChange: (i) => onChange(freqs[Math.min(Math.max(Math.round(i), 0), freqs.length - 1)]),
    }) });
}

function Content() {
    const [state, setState] = useState(null);
    const [error, setError] = useState("");
    const [draft, setDraft] = useState(null);
    const saveTimer = useRef(null);
    const pending = useRef(null);
    const lastJson = useRef("");

    // redraw only when something changed
    const refresh = () => call("get_state").then((s) => {
        const json = JSON.stringify(s);
        if (json !== lastJson.current) { lastJson.current = json; setState(s); }
        setError("");
    }).catch((e) => setError(String(e)));

    useEffect(() => {
        refresh();
        const timer = setInterval(refresh, 2000);
        return () => {
            clearInterval(timer);
            if (saveTimer.current) {
                clearTimeout(saveTimer.current);
                if (pending.current) call("save_game", pending.current.appid, pending.current.cfg).catch(() => { });
            }
        };
    }, []);

    if (!state) return h(DFL.PanelSection, { children: h(Row, { children: h(Note, { children: error || t("loading") }) }) });

    const game = runningGame(state);
    if (!game) {
        return h(DFL.PanelSection, { title: t("nogame_title"), children: h(Row, { children: h(Note, {
            children: t("nogame_text"),
        }) }) });
    }

    const saved = state.games[game.appid];
    const cfg = draft && draft.appid === game.appid ? draft.cfg : saved;

    const queueSave = (next) => {
        const appid = game.appid;
        setDraft({ appid, cfg: next });
        pending.current = { appid, cfg: next };
        if (saveTimer.current) clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(() => {
            saveTimer.current = null;
            const job = pending.current;
            pending.current = null;
            const before = wantsMangohud(state.games[job.appid]);
            call("save_game", job.appid, job.cfg).then((s) => {
                lastJson.current = JSON.stringify(s);
                setState(s); setError("");
                const after = wantsMangohud(s.games[job.appid]);
                if (after !== before && s.mangohud) {
                    setMangohudLaunch(job.appid, after, s.mangohud).catch((e) => setError(String(e)));
                }
            }).catch((e) => setError(String(e)));
        }, 400);
    };
    const save = (changes) => queueSave({ ...cfg, name: game.name, ...changes });

    const enabled = !!cfg && cfg.enabled !== false;
    const main = [h(Row, { children: h(DFL.ToggleField, {
        label: t("own_label"),
        description: enabled ? t("own_on") : t("own_off"),
        checked: enabled,
        onChange: (on) => {
            if (on) queueSave({ ...(saved || defaultsFromNow(state, game.name)), enabled: true, name: game.name });
            else if (saved) queueSave({ ...saved, enabled: false });
        },
    }) }, "toggle")];
    const sections = [];

    if (enabled) {
        const mode = modeOf(cfg);
        const cpuAuto = mode === "cpu" || mode === "both";
        const gpuAuto = mode === "gpu" || mode === "both";
        const target = cfg.fps_target || 0;
        const lim = limiterOf(cfg);

        main.push(h(ChoiceSlider, {
            label: t("auto_label"), description: t("modetxt_" + mode), options: modeOptions(), value: mode,
            onChange: (m) => {
                const needsTarget = m === "cpu" || m === "both";
                save({ mode: m, gpu_auto: undefined, fps_target: needsTarget && !target ? 30 : (target || undefined) });
            },
        }, "mode"));

        if (mode !== "off") {
            // 0-200; 0 = no target (only for the GPU alone: the CPU needs one)
            const minFps = cpuAuto ? 10 : 0;
            main.push(h(Row, { children: h(DFL.SliderField, {
                label: target ? t("fps_label", target) : t("fps_none"),
                description: target ? t("fps_desc_on") : t("fps_desc_off"),
                value: Math.max(target, minFps), min: minFps, max: 200, step: 1, showValue: false,
                notchCount: 5, notchLabels: [0, 50, 100, 150, 200].map((n, i) => ({ notchIndex: i, label: String(n), value: n })),
                notchTicksVisible: true, childrenContainerWidth: "max",
                onChange: (n) => { const v = Math.round(n); if (v !== target) save({ fps_target: v >= 10 ? v : undefined }); },
            }) }, "fps"));
            if (target) {
                main.push(h(ChoiceSlider, {
                    label: t("lock_label"), description: t("limtxt_" + lim), options: limiterOptions(), value: lim,
                    onChange: (l) => save({ limiter: l }),
                }, "limiter"));
            }
        }

        // live numbers
        const live = state.active === game.appid;
        const lines = [];
        const f = state.fps && state.fps.appid === game.appid ? state.fps : null;
        if (f) {
            lines.push(t("status_fps", f.fps, f.target, t("st_" + f.state)));
            lines.push(t("status_cpu", state.policies.map((p) => f.cpu[String(p.id)]).filter(Boolean).join(" / ")));
        }
        else if (state.live_fps && state.live_fps.appid === game.appid) {
            lines.push(t("status_fps", state.live_fps.fps, state.live_fps.target, "").replace(/\s*·\s*$/, ""));
        }
        if (gpuAuto && state.auto && state.auto.appid === game.appid) {
            lines.push(t("status_gpu", state.auto.mhz, Math.round(state.auto.busy * 100)));
        }
        if (!live) lines.splice(0, lines.length, t("applying"));
        if (lines.length) main.push(h(Status, { lines }, "status"));

        const notes = [];
        if (mode !== "off" && target && state.fps_error) notes.push(t("note_fpserr", state.fps_error));
        if (state.limiter && state.limiter.appid === game.appid && state.limiter.kind === "mangohud-pending") {
            notes.push(t("note_mh_pending"));
        }
        if (state.limiter && state.limiter.appid === game.appid && state.limiter.holds === false) {
            notes.push(t("note_lim_fail"));
        }
        if (gpuAuto && !target && (state.vela || []).includes(game.appid)) {
            notes.push(t("note_vela"));
        }
        for (const [i, n] of notes.entries()) main.push(h(Row, { children: h(Note, { warn: true, children: n }) }, `note${i}`));

        sections.push(h(DFL.PanelSection, { title: game.name, children: main }, "game"));

        // limits: fixed, or the ceilings / floor the automatic parts work within
        const lims = [];
        state.policies.forEach((p, i) => {
            lims.push(h(FreqSlider, {
                label: `${clusterLabel(state.policies, i)} (${cpusText(p.cpus)})${cpuAuto ? t("ceil_suffix") : ""}`,
                freqs: p.freqs, value: cfg.cpu?.[String(p.id)] ?? p.max, toMhz: khzToMhz,
                onChange: (khz) => save({ cpu: { ...(cfg.cpu || {}), [String(p.id)]: khz } }),
            }, `cpu${p.id}`));
        });
        if (state.gpu) {
            const gmax = cfg.gpu_max ?? state.gpu.max;
            const gmin = Math.min(cfg.gpu_min ?? state.gpu.min, gmax);
            lims.push(h(FreqSlider, {
                label: gpuAuto ? t("gpu_ceil") : t("gpu_max"), freqs: state.gpu.freqs, value: gmax, toMhz: mhz,
                onChange: (hz) => save({ gpu_max: hz, gpu_min: Math.min(gmin, hz) }),
            }, "gmax"));
            lims.push(h(FreqSlider, {
                label: gpuAuto ? t("gpu_floor") : t("gpu_min"), freqs: state.gpu.freqs, value: gmin, toMhz: mhz,
                onChange: (hz) => save({ gpu_min: Math.min(hz, gmax) }),
            }, "gmin"));
            if (state.gpu.governor === "userspace") {
                lims.push(h(Row, { children: h(Note, { warn: true, children: t("note_userspace") }) }, "gpunote"));
            }
        }
        const learned = cfg.fps_learned && cfg.fps_learned.target === target ? cfg.fps_learned : null;
        if (cpuAuto && learned) {
            const cpuL = state.policies.map((p) => khzToMhz(learned.cpu?.[String(p.id)] || 0)).join(" / ");
            lims.push(h(Row, { children: h(DFL.ButtonItem, {
                layout: "below",
                description: t("learned", cpuL),
                onClick: () => call("forget_learned", game.appid).then((s) => { lastJson.current = JSON.stringify(s); setState(s); setDraft(null); }).catch((e) => setError(String(e))),
                children: t("forget"),
            }) }, "forget"));
        }
        sections.push(h(DFL.PanelSection, { title: cpuAuto || gpuAuto ? t("limits_auto") : t("limits"), children: lims }, "limits"));
    }
    else {
        sections.push(h(DFL.PanelSection, { title: game.name, children: main }, "game"));
    }

    if (error) sections.push(h(DFL.PanelSection, { children: h(Row, { children: h(Note, { warn: true, children: t("error", error) }) }) }, "err"));
    return hs(SP_JSX.Fragment, { children: sections });
}

let limitTimer = null;
const index = () => {
    if (limitTimer) clearInterval(limitTimer);
    limitTimer = setInterval(limitTick, 3000);
    return plugin();
};
const plugin = () => ({
    name: "Aparejo",
    titleView: h("div", { className: DFL.staticClasses?.Title, children: "Aparejo" }),
    content: h(Content, {}),
    icon: hs("svg", { xmlns: "http://www.w3.org/2000/svg", width: "24", height: "24", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [h("path", { d: "M13 2 3 14h9l-1 8 10-12h-9l1-8z" })] }),
    onDismount() {
        if (limitTimer) { clearInterval(limitTimer); limitTimer = null; }
        const st = limitSaved ? steamSettings() : null;
        try { if (st) restoreLimit(st); } catch (e) { }
        limitSaved = null;
    },
});

export { index as default };
