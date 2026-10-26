// Deckprint front end: manage card images, load decks, edit quantities, request the PDF.
const $ = (sel) => document.querySelector(sel);
const state = {
  decks: [],                                  // payloads from /api/resolve with .qty edited in place
  options: { paper: "a4", backs: "auto", gap: "0" },
  sideboard: false,
  games: {},                                  // /api/status games: null when not downloaded yet
  sync: null,                                 // /api/status sync state
};
const SECTION_LABEL = { Hero: "Heroes", Main: "Deck", Sideboard: "Sideboard", Investigator: "Investigator" };
const PER_PAGE = { standard: 9, mini: 16 };
const RECENT_KEY = "deckprint.recent";
const GAMES = {
  lotr: { label: "The Lord of the Rings LCG", short: "LotR", size: "about 1 GB", extra: "+1.3 GB",
          note: "Player cards incl. ALeP community packs" },
  arkham: { label: "Arkham Horror LCG", short: "Arkham", size: "about 0.5 GB", extra: "+1.6 GB",
            note: "Player cards incl. investigators" },
};

// ---------- persistence (per browser, best effort) ----------
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};
Object.assign(state.options, store.get("deckprint.options", {}));
state.sideboard = store.get("deckprint.sideboard", false);

// ---------- card images (download / update) ----------
async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    state.games = s.games;
    state.sync = s.sync;
  } catch {
    $("#library").textContent = "Deckprint is not running - start it again";
    return;
  }
  renderLibrary();
  if (state.sync.running) pollSync();
}

function renderLibrary() {
  const parts = Object.entries(GAMES).map(([g, info]) => {
    const s = state.games[g];
    return s ? `${info.short}: ${s.cards.toLocaleString("en")} cards` : `${info.short}: not downloaded`;
  });
  $("#library").textContent = parts.join(" · ");
  const none = Object.values(state.games).every((s) => !s);
  $("#welcome").hidden = !none;
  $("#intake").hidden = none;
  $("#empty").hidden = none || state.decks.length > 0;
  document.querySelectorAll(".game-rows").forEach(renderGameRows);
}

function renderGameRows(box) {
  const sync = state.sync || {};
  box.innerHTML = "";
  for (const [g, info] of Object.entries(GAMES)) {
    const s = state.games[g];
    const busy = sync.running && sync.game === g;
    const row = document.createElement("div");
    row.className = "game-row";
    const status = s
      ? `${s.cards.toLocaleString("en")} cards · ${(s.size_mb / 1000).toFixed(1)} GB · updated ${new Date(s.generated).toLocaleDateString()}`
        + (s.encounter ? " · incl. encounter cards" : "")
      : `Not downloaded yet · ${info.size}`;
    row.innerHTML = `
      <div class="game-info">
        <div class="game-name">${info.label}</div>
        <div class="hint">${info.note}. ${status}</div>
        ${s && s.encounter ? "" : `<label class="check small"><input type="checkbox" data-enc> Also encounter, quest &amp; scenario cards (${info.extra})</label>`}
      </div>
      <button class="btn ${s ? "" : "primary"}" ${sync.running ? "disabled" : ""}>${s ? "Update" : "Download"}</button>
      ${busy || (sync.game === g && sync.returncode !== null && sync.returncode !== undefined) ? progressHtml(sync) : ""}`;
    row.querySelector("button").onclick = () => startSync(g, !!row.querySelector("[data-enc]")?.checked);
    box.appendChild(row);
  }
}

function progressHtml(sync) {
  if (!sync.running) {
    return sync.returncode === 0
      ? `<div class="progress done">Done. You can load decks now.</div>`
      : `<div class="progress failed">The download stopped with an error. Check your internet connection and press the button again; it continues where it left off.<pre>${escapeHtml(sync.log.join("\n"))}</pre></div>`;
  }
  const pct = sync.total ? Math.round((100 * sync.done) / sync.total) : 0;
  return `<div class="progress">
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="hint">${escapeHtml(sync.stage || "Starting…")}${sync.total ? ` - ${sync.done.toLocaleString("en")} / ${sync.total.toLocaleString("en")}` : ""}</div>
      <div class="hint">This can take 10-30 minutes the first time. You can keep using Deckprint meanwhile, but leave the Deckprint window open.</div>
    </div>`;
}

async function startSync(game, encounter) {
  const res = await fetch("/api/sync", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ game, encounter }),
  });
  const data = await res.json();
  if (!res.ok) { showErrors([data.error || res.statusText]); return; }
  state.sync = data;
  renderLibrary();
  pollSync();
}

let polling = false;
async function pollSync() {
  if (polling) return;
  polling = true;
  while (true) {
    await new Promise((r) => setTimeout(r, 1500));
    try { state.sync = await (await fetch("/api/sync")).json(); } catch { break; }
    if (!state.sync.running) break;
    document.querySelectorAll(".game-rows").forEach(renderGameRows);
  }
  polling = false;
  await loadStatus();
}

$("#images-btn").onclick = () => { $("#images-modal").hidden = false; };
$("#images-close").onclick = () => { $("#images-modal").hidden = true; };
$("#images-modal").onclick = (ev) => { if (ev.target.id === "images-modal") $("#images-modal").hidden = true; };

// ---------- fetching decks ----------
async function fetchDecks(sources) {
  sources = sources.trim();
  if (!sources) return;
  const btn = $("#fetch-btn");
  btn.classList.add("busy"); btn.disabled = true;
  try {
    const game = document.querySelector('input[name="game"]:checked').value;
    const res = await fetch("/api/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, game }),
    });
    const data = await res.json();
    addDecks(data.decks, data.errors);
    if (data.decks.length) {
      rememberRecent(sources, data.decks.map((d) => d.name).join(" + "));
      $("#sources").value = "";
    }
  } catch (err) {
    showErrors([`Could not reach Deckprint: ${err.message}. Is the Deckprint window still open?`]);
  } finally {
    btn.classList.remove("busy"); btn.disabled = false;
  }
}

async function uploadO8d(files) {
  const form = new FormData();
  [...files].forEach((f) => form.append("file", f));
  const res = await fetch("/api/o8d", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) { showErrors([data.error || res.statusText]); return; }
  addDecks(data.decks, data.errors);
}

function addDecks(decks, errors) {
  for (const d of decks) {
    for (const e of d.entries) {
      e.orig = e.qty;
      if (e.section === "Sideboard") e.qty = state.sideboard ? e.orig : 0;
    }
    state.decks.push(d);
  }
  showErrors(errors);
  hideResult();
  render();
}

function showErrors(errors) {
  const box = $("#errors");
  box.hidden = !errors.length;
  box.innerHTML = errors.map((e) => `<div>${escapeHtml(e)}</div>`).join("");
}

// ---------- recent ----------
function rememberRecent(sources, name) {
  const list = store.get(RECENT_KEY, []).filter((r) => r.sources !== sources);
  list.unshift({ sources, name });
  store.set(RECENT_KEY, list.slice(0, 8));
  renderRecent();
}
function renderRecent() {
  const box = $("#recent");
  box.innerHTML = "";
  for (const r of store.get(RECENT_KEY, [])) {
    const chip = document.createElement("button");
    chip.type = "button"; chip.className = "chip"; chip.textContent = r.name; chip.title = r.sources;
    chip.onclick = () => fetchDecks(r.sources);
    box.appendChild(chip);
  }
}

// ---------- rendering decks ----------
function render() {
  const root = $("#decks");
  root.innerHTML = "";
  $("#empty").hidden = state.decks.length > 0 || $("#intake").hidden;
  state.decks.forEach((deck, di) => root.appendChild(renderDeck(deck, di)));
  renderSummary();
}

function renderDeck(deck, di) {
  const el = document.createElement("article");
  el.className = "deck";
  const total = deck.entries.reduce((n, e) => n + e.qty, 0);
  const title = deck.url ? `<a href="${deck.url}" target="_blank" rel="noopener">${escapeHtml(deck.name)}</a>` : escapeHtml(deck.name);
  el.innerHTML = `
    <div class="deck-head">
      <span class="badge ${deck.game}">${GAMES[deck.game].short}</span>
      <h3>${title}</h3>
      <span class="deck-count">${total} cards</span>
      <button class="icon-btn" title="Remove this deck">✕</button>
    </div>
    <div class="deck-tools">
      <button class="link-btn" data-act="all">All cards</button>·
      <button class="link-btn" data-act="none">No cards</button>·
      <button class="link-btn" data-act="one">One of each</button>
    </div>`;
  el.querySelector(".icon-btn").onclick = () => { state.decks.splice(di, 1); hideResult(); render(); };
  el.querySelectorAll(".deck-tools button").forEach((b) => b.onclick = () => {
    for (const e of deck.entries) {
      if (e.missing) continue;
      e.qty = b.dataset.act === "all" ? e.orig : b.dataset.act === "none" ? 0 : 1;
    }
    hideResult(); render();
  });

  const sections = [];
  for (const e of deck.entries) {
    let s = sections.find((x) => x.name === e.section);
    if (!s) sections.push(s = { name: e.section, entries: [] });
    s.entries.push(e);
  }
  for (const s of sections) {
    const count = s.entries.reduce((n, e) => n + e.qty, 0);
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = `${SECTION_LABEL[s.name] || s.name} · ${count}`;
    el.appendChild(h);
    const grid = document.createElement("div");
    grid.className = "grid";
    s.entries.forEach((e) => grid.appendChild(renderTile(e)));
    el.appendChild(grid);
  }
  return el;
}

function renderTile(e) {
  const t = document.createElement("div");
  t.className = "tile" + (e.landscape ? " landscape" : "") + (e.qty === 0 ? " off" : "");
  const flags = [];
  if (e.double_sided) flags.push(`<span class="flag">2-sided</span>`);
  if (e.landscape) flags.push(`<span class="flag">landscape</span>`);
  if (e.size === "mini") flags.push(`<span class="flag">mini</span>`);
  if (e.low_res) flags.push(`<span class="flag warn">low res</span>`);
  t.innerHTML = `
    <div class="img">${e.thumb ? `<img loading="lazy" src="${e.thumb}" alt="">` : `<div class="missing">No image</div>`}</div>
    <div class="flags">${flags.join("")}</div>
    ${e.missing ? "" : `<div class="stepper"><button data-d="-1" title="One less">−</button><span>${e.qty}</span><button data-d="1" title="One more">+</button></div>`}
    <div class="name" title="${escapeHtml(e.name)}">${escapeHtml(e.name)}</div>`;
  t.querySelectorAll(".stepper button").forEach((b) => b.onclick = () => {
    e.qty = Math.max(0, Math.min(9, e.qty + Number(b.dataset.d)));
    hideResult(); render();
  });
  if (e.thumb) t.querySelector(".img").onclick = () => openLightbox(e);
  return t;
}

// Mirrors deckprint.render: every deck and card size starts a new page; in auto mode only
// pages holding double-sided cards (sorted first) get a back page.
function estimate() {
  let cards = 0, backs = 0, missing = 0, pages = 0;
  for (const d of state.decks) {
    for (const size of Object.keys(PER_PAGE)) {
      const es = d.entries.filter((e) => !e.missing && e.size === size);
      const n = es.reduce((s, e) => s + e.qty, 0);
      const b = es.filter((e) => e.double_sided).reduce((s, e) => s + e.qty, 0);
      const fronts = Math.ceil(n / PER_PAGE[size]);
      cards += n; backs += b; pages += fronts;
      if (state.options.backs === "all") pages += fronts;
      if (state.options.backs === "auto") pages += Math.ceil(b / PER_PAGE[size]);
    }
    missing += d.entries.filter((e) => e.missing).reduce((s, e) => s + e.orig, 0);
  }
  return { cards, backs, missing, pages };
}

function renderSummary() {
  const { cards, backs, missing, pages } = estimate();
  $("#summary").innerHTML = cards ? `
      <div class="big-num">${cards} cards</div>
      <div class="sub">≈ ${pages} pages${backs ? ` · ${backs} double-sided` : ""}</div>
      ${missing ? `<div class="warn">${missing} cards have no image and will be skipped</div>` : ""}`
    : `<div class="sub">Load a deck to print it.</div>`;
  $("#pdf-btn").disabled = cards === 0;
  const hints = {
    auto: "Back pages only where the deck has double-sided cards.",
    all: "Every card gets a back (its printed back or the standard card back).",
    none: "Fronts only.",
  };
  $("#backs-hint").textContent = hints[state.options.backs];
}

// ---------- PDF ----------
async function makePdf() {
  const btn = $("#pdf-btn");
  btn.classList.add("busy"); btn.disabled = true;
  hideResult();
  try {
    const body = {
      options: state.options,
      decks: state.decks.map((d) => ({
        id: d.id, quantities: Object.fromEntries(d.entries.map((e) => [e.key, e.qty])),
      })),
    };
    const res = await fetch("/api/pdf", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || res.statusText);
    }
    const blob = await res.blob();
    const name = filenameFrom(res.headers.get("Content-Disposition")) || "deck.pdf";
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    showResult({
      name, url,
      cards: res.headers.get("X-Cards"), pages: res.headers.get("X-Pages"),
      duplex: (res.headers.get("X-Duplex") || "").split(",").filter(Boolean).map(Number),
      seconds: res.headers.get("X-Seconds"), mb: (blob.size / 1e6).toFixed(1),
    });
  } catch (err) {
    showErrors([`Could not create the PDF: ${err.message}`]);
  } finally {
    btn.classList.remove("busy");
    renderSummary();
  }
}

function showResult(r) {
  const duplex = r.duplex.length
    ? `<li>Print pages <b>${r.duplex.map((p) => `${p}-${p + 1}`).join(", ")}</b> double-sided, flipping on the long edge.</li>`
    : "";
  const box = $("#result");
  box.hidden = false;
  box.innerHTML = `
    <strong>PDF ready: ${r.cards} cards, ${r.pages} pages</strong>
    <span class="hint">${r.mb} MB in ${r.seconds} s · <a href="${r.url}" download="${escapeHtml(r.name)}">download again</a> · <a href="${r.url}" target="_blank">open</a></span>
    <ul>
      <li>Print at <b>100 % / actual size</b>, not "fit to page", or the cards come out the wrong size.</li>
      ${duplex}
      <li>Cut along the marks in the margin.</li>
    </ul>`;
}
function hideResult() { $("#result").hidden = true; }

// ---------- lightbox ----------
function openLightbox(e) {
  const full = (thumb) => thumb && thumb.replace("/thumb/", "/image/");
  $("#lb-inner").innerHTML = [full(e.thumb), full(e.back_thumb)].filter(Boolean)
    .map((src) => `<img src="${src}" alt="">`).join("");
  $("#lightbox").hidden = false;
}
$("#lightbox").onclick = () => { $("#lightbox").hidden = true; };
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { $("#lightbox").hidden = true; $("#images-modal").hidden = true; }
});

// ---------- options ----------
document.querySelectorAll(".seg").forEach((seg) => {
  const opt = seg.dataset.opt;
  seg.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("on", b.dataset.v === String(state.options[opt]));
    b.onclick = () => {
      state.options[opt] = b.dataset.v;
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      store.set("deckprint.options", state.options);
      hideResult(); renderSummary();
    };
  });
});
$("#sideboard").checked = state.sideboard;
$("#sideboard").onchange = (ev) => {
  state.sideboard = ev.target.checked;
  store.set("deckprint.sideboard", state.sideboard);
  for (const d of state.decks) for (const e of d.entries)
    if (e.section === "Sideboard") e.qty = state.sideboard ? e.orig : 0;
  hideResult(); render();
};

// ---------- input ----------
$("#intake").onsubmit = (ev) => { ev.preventDefault(); fetchDecks($("#sources").value); };
$("#sources").addEventListener("paste", () => setTimeout(() => fetchDecks($("#sources").value), 0));
$("#sources").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); fetchDecks($("#sources").value); }
});
$("#pdf-btn").onclick = makePdf;

let dragDepth = 0;
window.addEventListener("dragenter", (ev) => { ev.preventDefault(); dragDepth++; document.body.classList.add("dragging"); });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
window.addEventListener("dragover", (ev) => ev.preventDefault());
window.addEventListener("drop", (ev) => {
  ev.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
  const files = [...ev.dataTransfer.files].filter((f) => f.name.toLowerCase().endsWith(".o8d"));
  if (files.length) uploadO8d(files);
  else {
    const text = ev.dataTransfer.getData("text");
    if (text) fetchDecks(text);
  }
});

// ---------- helpers ----------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function filenameFrom(header) {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain && plain[1];
}

renderRecent();
render();
loadStatus();
