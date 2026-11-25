/* Thin wrapper over the Griductive API. The base URL comes from config.js (served by server.py). */
const API = (() => {
  const fallback = "http://127.0.0.1:8000";
  const base = ((window.GRIDUCTIVE_CONFIG && window.GRIDUCTIVE_CONFIG.apiBase) || fallback).replace(/\/+$/, "");

  async function request(method, path, body) {
    const options = { method };
    if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(base + path, options);   // a network failure rejects with TypeError
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : response.status + " " + response.statusText);
    }
    return data;
  }

  return {
    base,
    puzzles: () => request("GET", "/api/puzzles"),
    load: (puzzleId) => request("POST", "/api/game/load", { puzzle_id: puzzleId }),
    loadPuzzle: (puzzle) => request("POST", "/api/game/load", { puzzle }),
    state: () => request("GET", "/api/game/state"),
    restart: () => request("POST", "/api/game/restart"),
    verdict: (name, verdict) => request("POST", "/api/game/verdict", { name, verdict }),
    hint: () => request("GET", "/api/game/hint"),
    step: () => request("POST", "/api/game/step"),
    generateOptions: () => request("GET", "/api/generate/options"),
    generate: (seed, size, difficulty) => request("POST", "/api/generate", { seed, size, difficulty }),
  };
})();