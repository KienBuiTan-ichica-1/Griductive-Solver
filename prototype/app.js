/* Griductive UI. Talks to the backend through api.js. */
(function () {
  "use strict";

  const TOAST_MS = 3200;
  const AUTO_STEP_MS = 700;
  const POPUP_MARGIN = 8;
  const RANDOM_SEED_RANGE = 1000000;
  const HINT_DEFAULT = "Hint: ask for a tile you can prove from the clues.";
  const STATUS_LABEL = { unknown: "Unknown", innocent: "Civilian", criminal: "Criminal" };

  const app = {
    levels: [],
    levelId: null,         // id of the loaded existing level (null for a generated game)
    menuSize: 3,
    difficulty: "easy",
    game: null,            // last state returned by the API
    selected: null,        // selected character name
    hint: null,            // { name, clueId }
    hoverClueId: null,
    pinClueId: null,
    popupFor: null,
    busy: false,
    generating: false,
    autoRunning: false,
    tiles: new Map(),      // cell -> tile element
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const statusKey = (character) => (character.status ? character.status.toLowerCase() : "unknown");
  const charByName = (name) => (app.game && name ? app.game.characters.find((c) => c.name === name) : null) || null;
  const clueByOwner = (name) => (app.game && name ? app.game.clues.find((c) => c.owner === name) : null) || null;
  const clueById = (id) => (app.game && id ? app.game.clues.find((c) => c.id === id) : null) || null;

  /* ---------- feedback ---------- */
  let toastTimer = null;

  function toast(message, tone) {
    const node = $("#toast");
    node.textContent = message;
    node.className = "toast toast--" + (tone || "ok") + " is-visible";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("is-visible"), TOAST_MS);
  }

  const setBanner = (visible) => $("#banner").classList.toggle("is-visible", visible);

  /* run one API action; network failures show the banner, API errors show a toast */
  async function run(action) {
    if (app.busy) return null;
    app.busy = true;
    refreshControls();
    try {
      const result = await action();
      setBanner(false);
      return result;
    } catch (error) {
      if (error instanceof TypeError) setBanner(true);
      else toast(error.message, "error");
      return null;
    } finally {
      app.busy = false;
      refreshControls();
    }
  }

  function refreshControls() {
    const locked = app.busy || app.autoRunning;
    const game = app.game;
    const play = $("#play");
    play.disabled = locked;
    play.textContent = app.generating ? "Generating…" : "Play";
    $("#seed-random").disabled = locked;
    $("#hint-btn").disabled = locked || !game || game.solved;
    $("#restart-btn").disabled = locked || !game;
    const auto = $("#auto-btn");
    auto.textContent = app.autoRunning ? "Stop" : "Auto solve";
    auto.disabled = (app.busy && !app.autoRunning) || !game || (game.solved && !app.autoRunning);
  }

  /* ---------- clue roles ---------- */
  function clueRoles(clue) {
    const owner = charByName(clue.owner).cell;
    const left = clue.left || [];
    const right = clue.right || [];
    const split = left.length > 0 || right.length > 0;
    const target = split ? clue.cells.filter((cell) => !left.includes(cell) && !right.includes(cell)) : clue.cells;
    return { owner, target, left, right };
  }

  function syncPin() {
    const own = clueByOwner(app.selected);
    app.pinClueId = app.hint ? app.hint.clueId : own ? own.id : null;
  }

  function applyHighlight() {
    app.tiles.forEach((tile) => tile.classList.remove("hl-owner", "hl-target", "hl-left", "hl-right", "is-hint", "is-selected"));
    const mark = (cell, className) => {
      const tile = app.tiles.get(cell);
      if (tile) tile.classList.add(className);
    };
    const clue = clueById(app.hoverClueId) || clueById(app.pinClueId);
    if (clue) {
      const roles = clueRoles(clue);
      mark(roles.owner, "hl-owner");
      roles.target.forEach((cell) => mark(cell, "hl-target"));
      roles.left.forEach((cell) => mark(cell, "hl-left"));
      roles.right.forEach((cell) => mark(cell, "hl-right"));
    }
    if (app.hint) {
      const hinted = charByName(app.hint.name);
      if (hinted) mark(hinted.cell, "is-hint");
    }
    const selected = charByName(app.selected);
    if (selected) mark(selected.cell, "is-selected");
  }

  function setHover(clueId) {
    if (app.hoverClueId === clueId) return;
    app.hoverClueId = clueId;
    applyHighlight();
  }

  /* ---------- rendering ---------- */
  function renderRulers(n) {
    const cols = $("#ruler-cols");
    const rows = $("#ruler-rows");
    cols.replaceChildren();
    rows.replaceChildren();
    for (let i = 0; i < n; i += 1) {
      cols.append(make("span", "ruler__mark", String.fromCharCode(65 + i)));
      rows.append(make("span", "ruler__mark", String(i + 1)));
    }
  }

  function renderBoard() {
    const board = $("#board");
    board.replaceChildren();
    app.tiles.clear();
    if (!app.game) return;
    const n = app.game.puzzle.size;
    $("#board-frame").style.setProperty("--board-n", n);
    board.dataset.size = String(n);
    app.game.characters.forEach((character) => {
      const tile = make("div", "tile tile--" + statusKey(character));
      tile.setAttribute("role", "button");
      tile.tabIndex = 0;
      tile.dataset.name = character.name;
      tile.dataset.cell = character.cell;
      const head = make("div", "tile__head");
      head.append(make("span", "tile__name", character.name), make("span", "tile__cell", character.cell));
      tile.append(head, make("span", "tile__job", character.job));
      const clue = clueByOwner(character.name);
      if (clue) tile.append(make("p", "tile__clue", clue.text));
      board.append(tile);
      app.tiles.set(character.cell, tile);
    });
    renderRulers(n);
    updateTileDensity();
  }

  /* a tile shows its cell id, occupation and clue only if it is big enough (limits are CSS tokens) */
  function tokenPx(token) {
    const probe = make("div");
    probe.style.cssText = "position:absolute;visibility:hidden;width:var(" + token + ")";
    document.body.append(probe);
    const width = probe.getBoundingClientRect().width;
    probe.remove();
    return width;
  }

  function updateTileDensity() {
    const board = $("#board");
    const tile = board.firstElementChild;
    if (!app.game || !tile) return;
    const side = Math.min(tile.clientWidth, tile.clientHeight);
    const show = (token) => (side >= tokenPx(token) ? "show" : "hide");
    board.dataset.cell = show("--tile-show-cell-min");
    board.dataset.job = show("--tile-show-job-min");
    board.dataset.clue = show("--tile-show-clue-min-" + app.game.puzzle.size);
  }

  function renderInfo() {
    const character = charByName(app.selected);
    const clue = character ? clueByOwner(character.name) : null;
    $("#info-name").textContent = character ? character.name : "No tile selected";
    $("#info-job").textContent = character ? character.job + " · " + character.cell : "Click a tile to see its details.";
    const badge = $("#info-status");
    badge.classList.toggle("is-hidden", !character);
    if (character) {
      const key = statusKey(character);
      badge.className = "badge badge--" + key;
      badge.textContent = STATUS_LABEL[key];
    }
    $("#info-clue").textContent = clue ? clue.text : character ? "Hidden until this tile is proved." : "";
    const chips = $("#info-chips");
    chips.replaceChildren();
    if (clue) {
      const roles = clueRoles(clue);
      chips.append(make("span", "chip chip--owner", roles.owner));
      roles.target.forEach((cell) => chips.append(make("span", "chip chip--target", cell)));
      roles.left.forEach((cell) => chips.append(make("span", "chip chip--left", cell)));
      roles.right.forEach((cell) => chips.append(make("span", "chip chip--right", cell)));
    }
  }

  function renderKnown() {
    const list = $("#known-list");
    list.replaceChildren();
    const clues = app.game ? app.game.clues : [];
    const selected = charByName(app.selected);
    clues.forEach((clue) => {
      const owner = charByName(clue.owner);
      const classes = ["clue-row"];
      if (selected && clue.owner === selected.name) classes.push("is-owner");
      else if (selected && clue.cells.includes(selected.cell)) classes.push("is-related");
      if (app.hint && app.hint.clueId === clue.id) classes.push("is-hint");
      const row = make("li", classes.join(" "));
      row.dataset.clueId = clue.id;
      row.dataset.owner = clue.owner;
      row.append(make("span", "clue-row__cell", owner.cell), make("span", "clue-row__text", clue.text));
      list.append(row);
    });
    $("#known-label").textContent = "Known clues (" + clues.length + ")";
  }

  function renderProgress() {
    const game = app.game;
    $("#progress").textContent = game
      ? game.puzzle.id + " · proved " + game.characters.filter((c) => c.status).length + " / " + game.total + " · steps " + game.steps
      : "No level loaded.";
  }

  function renderLevels() {
    const list = $("#level-list");
    list.replaceChildren();
    const shown = app.levels.filter((level) => level.size === app.menuSize);
    if (!shown.length) {
      list.append(make("p", "level-list__empty", "No levels of this size."));
      return;
    }
    shown.forEach((level) => {
      const item = make("button", "level-item" + (level.id === app.levelId ? " is-active" : ""));
      item.type = "button";
      item.dataset.id = level.id;
      item.append(make("span", "", level.id), make("span", "level-item__meta", level.size + "×" + level.size + " · " + level.clues + " clues"));
      list.append(item);
    });
  }

  function renderDifficulties(names) {
    if (!names.includes(app.difficulty)) app.difficulty = names[0];
    const group = $('[data-group="difficulty"]');
    group.replaceChildren();
    names.forEach((name) => {
      const button = make("button", "segmented__item", name.charAt(0).toUpperCase() + name.slice(1));
      button.type = "button";
      button.dataset.value = name;
      button.setAttribute("aria-pressed", String(name === app.difficulty));
      group.append(button);
    });
  }

  function renderAll() {
    renderBoard();
    renderInfo();
    renderKnown();
    renderProgress();
    applyHighlight();
    refreshControls();
  }

  /* ---------- game actions ---------- */
  function applyGame(game) {
    app.game = game;
    if (app.selected && !charByName(app.selected)) app.selected = null;
    syncPin();
    renderAll();
  }

  function clearHint() {
    app.hint = null;
    $("#hint-text").textContent = HINT_DEFAULT;
  }

  function selectTile(name) {
    if (app.hint && app.hint.name !== name) clearHint();
    app.selected = name;
    syncPin();
    renderInfo();
    renderKnown();
    applyHighlight();
  }

  function showPanel(name) {
    $$("#panel-toggle [data-panel]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.panel === name)));
    $("#panel-menu").classList.toggle("is-active", name === "menu");
    $("#panel-game").classList.toggle("is-active", name === "game");
  }

  /* start a game from any API call that returns a game state */
  async function startGame(action, showGame) {
    const game = await run(action);
    if (!game) return false;
    app.selected = null;
    clearHint();
    applyGame(game);
    if (showGame) showPanel("game");
    return true;
  }

  async function playExistingLevel(id) {
    if (await startGame(() => API.load(id), true)) {
      app.levelId = id;
      renderLevels();
    }
  }

  /* Play: generate a level from difficulty + size + seed, then load it */
  async function generateAndPlay() {
    const seedInput = $("#seed");
    const seed = seedInput.value.trim();
    app.generating = true;
    refreshControls();
    const result = await run(async () => {
      const { level } = await API.generate(seed || null, app.menuSize, app.difficulty);
      const game = await API.loadPuzzle(level);
      return { level, game };
    });
    app.generating = false;
    refreshControls();
    if (!result) return;
    app.levelId = null;
    renderLevels();
    seedInput.value = result.level.meta.seed;      // so the level can be reproduced
    app.selected = null;
    clearHint();
    applyGame(result.game);
    showPanel("game");
    toast("Generated " + result.level.id + " (difficulty score " + result.level.meta.score + ").", "ok");
  }

  async function submitVerdict(verdict) {
    const name = app.popupFor;
    closePopup();
    if (!name) return;
    const result = await run(() => API.verdict(name, verdict));
    if (!result) return;
    switch (result.result) {
      case "ACCEPTED":
        clearHint();
        app.selected = name;
        applyGame(result.state);
        toast(result.state.solved ? "Solved in " + result.state.steps + " steps!" : name + ": correct.", "ok");
        break;
      case "NOT_PROVABLE":
        toast("Not provable yet: the revealed clues do not force " + name + "'s status.", "warn");
        break;
      case "CONTRADICTED":
        toast("Contradicted: the clues prove the opposite for " + name + ".", "error");
        break;
      case "ALREADY_KNOWN":
        toast(name + " is already known.", "warn");
        break;
      case "INCONSISTENT":
        toast("The revealed clues contradict each other.", "error");
        break;
      default:
        toast(result.reason || "Verdict rejected.", "error");
    }
  }

  async function doHint() {
    const result = await run(() => API.hint());
    if (!result) return;
    if (result.available) {
      app.hint = { name: result.name, clueId: result.clue_id };
      const clue = clueById(result.clue_id);
      const owner = clue ? charByName(clue.owner) : null;
      $("#hint-text").textContent = "Hint: " + result.name + " (" + result.cell + ") can be proved"
        + (owner ? " from the clue of " + owner.name + " (" + owner.cell + ")." : ".");
    } else {
      app.hint = null;
      const messages = {
        STUCK: "Hint: no tile can be proved from the current clues.",
        SOLVED: "Hint: the puzzle is already solved.",
        INCONSISTENT: "Hint: the revealed clues contradict each other.",
      };
      $("#hint-text").textContent = messages[result.status] || "Hint: nothing to suggest.";
    }
    syncPin();
    renderKnown();
    applyHighlight();
  }

  async function doRestart() {
    const game = await run(() => API.restart());
    if (!game) return;
    app.selected = null;
    clearHint();
    applyGame(game);
  }

  async function toggleAuto() {
    if (app.autoRunning) {
      app.autoRunning = false;
      refreshControls();
      return;
    }
    app.autoRunning = true;
    closePopup();
    clearHint();
    refreshControls();
    while (app.autoRunning && app.game && !app.game.solved) {
      const step = await run(() => API.step());
      if (!step) break;
      const history = step.state.history;
      if (history.length) app.selected = history[history.length - 1].name;
      applyGame(step.state);
      if (!step.ok) {
        toast(step.status === "STUCK" ? "Auto solve stopped: no tile can be proved." : "Auto solve stopped: " + (step.status || step.result), "warn");
        break;
      }
      await sleep(AUTO_STEP_MS);
    }
    app.autoRunning = false;
    refreshControls();
    if (app.game && app.game.solved) toast("Solved in " + app.game.steps + " steps!", "ok");
  }

  /* ---------- verdict popup ---------- */
  function openPopup(tile) {
    app.popupFor = tile.dataset.name;
    $("#popup-title").textContent = "Who is " + tile.dataset.name + "?";
    const popup = $("#popup");
    popup.classList.add("is-open");
    const rect = tile.getBoundingClientRect();
    const width = popup.offsetWidth;
    const height = popup.offsetHeight;
    let left = rect.left + rect.width / 2 - width / 2;
    let top = rect.bottom + POPUP_MARGIN;
    if (top + height > window.innerHeight - POPUP_MARGIN) top = rect.top - height - POPUP_MARGIN;
    left = Math.max(POPUP_MARGIN, Math.min(left, window.innerWidth - width - POPUP_MARGIN));
    popup.style.left = left + "px";
    popup.style.top = Math.max(POPUP_MARGIN, top) + "px";
  }

  function closePopup() {
    $("#popup").classList.remove("is-open");
    app.popupFor = null;
  }

  /* ---------- wiring ---------- */
  function pressOnly(container, pressed) {
    $$(".segmented__item", container).forEach((button) => button.setAttribute("aria-pressed", String(button === pressed)));
  }

  function wireSidebar() {
    $("#panel-toggle").addEventListener("click", (event) => {
      const button = event.target.closest("[data-panel]");
      if (button) showPanel(button.dataset.panel);
    });

    $$("[data-group]").forEach((group) => {
      group.addEventListener("click", (event) => {
        const button = event.target.closest("[data-value]");
        if (!button) return;
        pressOnly(group, button);
        if (group.dataset.group === "difficulty") {
          app.difficulty = button.dataset.value;
        } else {
          app.menuSize = Number(button.dataset.value);
          renderLevels();
        }
      });
    });

    $("#level-list").addEventListener("click", (event) => {
      const item = event.target.closest(".level-item");
      if (item && !app.busy && !app.autoRunning) playExistingLevel(item.dataset.id);
    });

    $("#play").addEventListener("click", generateAndPlay);
    $("#seed").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !app.busy && !app.autoRunning) generateAndPlay();
    });
    $("#seed-random").addEventListener("click", () => {
      $("#seed").value = String(Math.floor(Math.random() * RANDOM_SEED_RANGE));
    });

    $("#hint-btn").addEventListener("click", doHint);
    $("#restart-btn").addEventListener("click", doRestart);
    $("#auto-btn").addEventListener("click", toggleAuto);
    $("#banner-retry").addEventListener("click", init);

    const list = $("#known-list");
    list.addEventListener("mouseover", (event) => {
      const row = event.target.closest(".clue-row");
      setHover(row ? row.dataset.clueId : null);
    });
    list.addEventListener("mouseleave", () => setHover(null));
    list.addEventListener("click", (event) => {
      const row = event.target.closest(".clue-row");
      if (row) selectTile(row.dataset.owner);
    });
  }

  function wireBoard() {
    const board = $("#board");
    new ResizeObserver(updateTileDensity).observe(board);   // re-check tile sizes on resize / rotation
    board.addEventListener("mouseover", (event) => {
      const tile = event.target.closest(".tile");
      const clue = tile ? clueByOwner(tile.dataset.name) : null;
      setHover(clue ? clue.id : null);
    });
    board.addEventListener("mouseleave", () => setHover(null));
    board.addEventListener("click", (event) => {
      const tile = event.target.closest(".tile");
      if (!tile) return;
      const name = tile.dataset.name;
      selectTile(name);
      const character = charByName(name);
      const canGuess = character && character.status === null && !app.game.solved && !app.busy && !app.autoRunning;
      if (canGuess) openPopup(tile);
      else closePopup();
    });
    board.addEventListener("keydown", (event) => {
      const tile = event.target.closest(".tile");
      if (tile && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        tile.click();
      }
    });

    $("#popup").addEventListener("click", (event) => {
      const button = event.target.closest("[data-verdict]");
      if (button) submitVerdict(button.dataset.verdict);
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest("#popup, .tile")) closePopup();
    });
  }

  function wireModal() {
    const modal = $("#how-modal");
    const close = () => modal.classList.remove("is-open");
    $("#how-open").addEventListener("click", () => modal.classList.add("is-open"));
    modal.addEventListener("click", (event) => {
      if (event.target === modal || event.target.closest("[data-close]")) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
        closePopup();
      }
    });
  }

  /* ---------- start ---------- */
  async function init() {
    $("#banner-text").textContent = "Cannot reach the API at " + API.base;
    const levels = await run(() => API.puzzles());
    if (!levels) return;
    app.levels = levels;

    // difficulty names come from the generator config (tiers.json); keep the defaults if unavailable
    API.generateOptions()
      .then((options) => renderDifficulties(options.difficulties))
      .catch(() => {});

    if (!levels.length) {
      renderLevels();
      toast("The server has no levels. Press Play to generate one.", "warn");
      return;
    }
    if (!app.game) {
      app.levelId = levels[0].id;
      app.menuSize = levels[0].size;
    }
    const sizeGroup = $('[data-group="size"]');
    pressOnly(sizeGroup, $('[data-value="' + app.menuSize + '"]', sizeGroup));
    renderLevels();
    if (!app.game) await startGame(() => API.load(app.levelId), false);
  }

  clearHint();
  wireSidebar();
  wireBoard();
  wireModal();
  refreshControls();
  renderProgress();
  init();
})();