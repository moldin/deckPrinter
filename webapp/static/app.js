// Deckprint front end: fetch decks, edit quantities, request the PDF.
const $ = (sel) => document.querySelector(sel);
const state = {
  decks: [],                                  // payloads from /api/resolve with .qty edited in place
  options: { paper: "a4", backs: "auto", gap: "0" },
  sideboard: false,
};
const SECTION_LABEL = { Hero: "Hjältar", Main: "Lek", Sideboard: "Sidebord", Investigator: "Investigator" };
const PER_PAGE = { standard: 9, mini: 16 };
const RECENT_KEY = "deckprint.recent";

// ---------- persistence (per browser, best effort) ----------
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};
Object.assign(state.options, store.get("deckprint.options", {}));
state.sideboard = store.get("deckprint.sideboard", false);

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
    showErrors([`Kunde inte nå servern: ${err.message}`]);
  } finally {
    btn.classList.remove("busy"); btn.disabled = false;
  }
}

async function uploadO8d(files) {
  const form = new FormData();
  [...files].forEach((f) => form.append("file", f));
  const res = await fetch("/api/o8d", { method: "POST", body: form });
  const data = await res.json();
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

// ---------- rendering ----------
function render() {
  const root = $("#decks");
  root.innerHTML = "";
  $("#empty").hidden = state.decks.length > 0;
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
      <span class="badge ${deck.game}">${deck.game === "lotr" ? "LotR" : "Arkham"}</span>
      <h3>${title}</h3>
      <span class="deck-count">${total} kort</span>
      <button class="icon-btn" title="Ta bort leken">✕</button>
    </div>
    <div class="deck-tools">
      <button class="link-btn" data-act="all">Alla kort</button>·
      <button class="link-btn" data-act="none">Inga kort</button>·
      <button class="link-btn" data-act="one">1 av varje</button>
    </div>`;
  el.querySelector(".icon-btn").onclick = () => { state.decks.splice(di, 1); hideResult(); render(); };
  el.querySelectorAll(".deck-tools button").forEach((b) => b.onclick = () => {
    for (const e of deck.entries) {
      if (e.missing) continue;
      e.qty = b.dataset.act === "all" ? e.orig : b.dataset.act === "none" ? 0 : 1;
    }
    render();
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
    s.entries.forEach((e) => grid.appendChild(renderTile(deck, e)));
    el.appendChild(grid);
  }
  return el;
}

function renderTile(deck, e) {
  const t = document.createElement("div");
  t.className = "tile" + (e.landscape ? " landscape" : "") + (e.qty === 0 ? " off" : "");
  const flags = [];
  if (e.double_sided) flags.push(`<span class="flag">2-sidig</span>`);
  if (e.landscape) flags.push(`<span class="flag">liggande</span>`);
  if (e.size === "mini") flags.push(`<span class="flag">mini</span>`);
  if (e.low_res) flags.push(`<span class="flag warn">låg upplösning</span>`);
  t.innerHTML = `
    <div class="img">${e.thumb ? `<img loading="lazy" src="${e.thumb}" alt="">` : `<div class="missing">Bild saknas</div>`}</div>
    <div class="flags">${flags.join("")}</div>
    ${e.missing ? "" : `<div class="stepper"><button data-d="-1">−</button><span>${e.qty}</span><button data-d="1">+</button></div>`}
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
      <div class="big-num">${cards} kort</div>
      <div class="sub">≈ ${pages} sidor${backs ? ` · ${backs} dubbelsidiga` : ""}</div>
      ${missing ? `<div class="warn">${missing} kort saknar bild och hoppas över</div>` : ""}`
    : `<div class="sub">Välj kort för att skriva ut.</div>`;
  $("#pdf-btn").disabled = cards === 0;
  const hints = {
    auto: "Baksidesark bara där det finns dubbelsidiga kort.",
    all: "Alla kort får baksida (tryckt eller standardbaksida).",
    none: "Bara framsidor.",
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
    showErrors([`PDF misslyckades: ${err.message}`]);
  } finally {
    btn.classList.remove("busy");
    renderSummary();
  }
}

function showResult(r) {
  const duplex = r.duplex.length
    ? `<li>Skriv ut sidorna <b style="display:inline">${r.duplex.map((p) => `${p}–${p + 1}`).join(", ")}</b> dubbelsidigt, vänd längs långsidan.</li>`
    : "";
  const box = $("#result");
  box.hidden = false;
  box.innerHTML = `
    <b>PDF klar: ${r.cards} kort, ${r.pages} sidor</b>
    <span class="hint">${r.mb} MB på ${r.seconds} s · <a href="${r.url}" download="${escapeHtml(r.name)}">ladda ner igen</a> · <a href="${r.url}" target="_blank">öppna</a></span>
    <ul>
      <li>Skriv ut i <b style="display:inline">100 %</b>, inte "anpassa till sida", annars blir korten fel storlek.</li>
      ${duplex}
      <li>Skär längs märkena i marginalen.</li>
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
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("#lightbox").hidden = true; });

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

async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const part = (g, label) => s[g]
      ? `${label}: ${s[g].cards.toLocaleString("sv")} kort, synkad ${new Date(s[g].generated).toLocaleDateString("sv")}`
      : `${label}: ingen bildsamling`;
    $("#library").textContent = `${part("lotr", "LotR")} · ${part("arkham", "Arkham")}`;
  } catch { $("#library").textContent = "Servern svarar inte"; }
}

renderRecent();
render();
loadStatus();
