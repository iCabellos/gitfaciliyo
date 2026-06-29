"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
// Escapa texto antes de inyectarlo en innerHTML (evita XSS desde nombres de
// cartas, items de Steam, conceptos del banco, etc.). Sirve para texto y atributos.
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n, cur = "EUR") =>
  (n < 0 ? "-" : "") + (cur === "USD" ? "$" : "€") +
  Math.abs(n).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Contribuciones al patrimonio consolidado (por categoría).
const CONTRIB = {};         // label -> valor en EUR (activos)
window.CONTRIB = CONTRIB;   // accesible para la vista de gráficos
let BANK_NET = null;        // gasto neto del mes (informativo, no patrimonio)
const FLOWS = { gastos: null, ganancias: null };   // flujos del mes (banco)
const EVOL = { prev: null };   // total del mes anterior (para la variación)

const thisMonth = () => new Date().toISOString().slice(0, 7);   // YYYY-MM

function setContrib(label, value, month) {
  CONTRIB[label] = value;
  renderSummary();
  // Snapshot mensual en la base de datos (compartido entre dispositivos).
  const m = month || thisMonth();
  fetch("/api/snapshot", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ month: m, category: label, value }),
  }).finally(() => { if (window.Charts) window.Charts.refresh(); });
  if (window.Charts) window.Charts.refreshPie(CONTRIB);
}

function renderSummary() {
  const entries = Object.entries(CONTRIB);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const el = $("#summary");
  if (!entries.length && FLOWS.gastos === null && FLOWS.ganancias === null) { el.innerHTML = ""; return; }
  let deltaHtml = "";
  if (EVOL.prev !== null && EVOL.prev !== undefined) {
    const d = total - EVOL.prev, pct = EVOL.prev ? (d / EVOL.prev) * 100 : 0, up = d >= 0;
    deltaHtml = `<div class="delta ${up ? "pos" : "neg"}">${up ? "▲" : "▼"} ${up ? "+" : ""}${money(d)} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%) vs mes anterior</div>`;
  }
  let html = `<div class="kpi big"><div class="label">Patrimonio total</div>
              <div class="val pos">${money(total)}</div>${deltaHtml}</div>`;
  for (const [label, v] of entries.sort((a, b) => b[1] - a[1])) {
    html += `<div class="kpi"><div class="label">${esc(label)}</div><div class="val">${money(v)}</div></div>`;
  }
  if (FLOWS.ganancias !== null) {
    html += `<div class="kpi"><div class="label">Ganancias del mes</div>
             <div class="val pos">${money(FLOWS.ganancias)}</div></div>`;
  }
  if (FLOWS.gastos !== null) {
    html += `<div class="kpi"><div class="label">Gastos del mes</div>
             <div class="val neg">${money(-FLOWS.gastos)}</div></div>`;
  }
  el.innerHTML = html;
  $("#summaryHint").style.display = "none";
  if (window.AppFX) AppFX.onRender(el);
}

// ---- pestañas ----------------------------------------------------------
$$("#tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    $$("#tabs button").forEach((x) => x.classList.remove("active"));
    $$(".tabpane").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#pane-" + b.dataset.tab).classList.add("active");
  }));

// ---- file inputs con nombre de archivo + drag --------------------------
$$(".filebox").forEach((box) => {
  const input = $("input", box), span = $("span", box);
  const base = span.textContent;
  input.addEventListener("change", () => { span.textContent = input.files[0] ? "📄 " + input.files[0].name : base; });
  ["dragover", "dragenter"].forEach((e) => box.addEventListener(e, (ev) => { ev.preventDefault(); box.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((e) => box.addEventListener(e, () => box.classList.remove("drag")));
  box.addEventListener("drop", (ev) => { ev.preventDefault(); if (ev.dataTransfer.files[0]) { input.files = ev.dataTransfer.files; span.textContent = "📄 " + input.files[0].name; } });
});

function statusEl(target) {
  let s = $(".status", target.parentElement);
  if (!s) { s = document.createElement("p"); s.className = "status"; target.before(s); }
  return s;
}
function setStatus(target, msg, err) { const s = statusEl(target); s.textContent = msg; s.classList.toggle("err", !!err); }

function warningsHtml(warnings) {
  if (!warnings || !warnings.length) return "";
  return warnings.map((w) => `<p class="warn">⚠️ ${esc(w)}</p>`).join("");
}

// ---- subida genérica (Trade Republic, Nexo, Banco) ---------------------
$$("form[data-upload]").forEach((form) => {
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("input[type=file]", form);
    const target = $("#" + form.dataset.target);
    if (!input.files[0]) { setStatus(target, "Elige un archivo primero.", true); return; }
    const fd = new FormData();
    fd.append(form.dataset.field, input.files[0]);
    const btn = $("button", form); btn.disabled = true;
    setStatus(target, "Procesando…");
    try {
      const res = await fetch(form.dataset.upload, { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Error");
      setStatus(target, "");
      if (form.dataset.target === "bankResult") renderBank(json, target);
      else renderPositions(json, target);
    } catch (e) { setStatus(target, e.message, true); }
    finally { btn.disabled = false; }
  });
});

// ---- tabla de posiciones (TR, Nexo, CS:GO, Magic) ----------------------
function renderPositions(data, target) {
  const cur = data.currency || "EUR";
  const rows = data.positions.map((p) => {
    const icon = p.extra && p.extra.icon ? `<img class="thumb" src="${esc(p.extra.icon)}">` : "";
    const sub = p.extra && (p.extra.tag || p.extra.isin || p.extra.asset || p.extra.deck || p.extra.type) || "";
    return `<tr>
      <td>${icon}${esc(p.name)}${sub ? ` <span class="tag">${esc(sub)}</span>` : ""}</td>
      <td class="num muted">${p.quantity.toLocaleString("es-ES")}</td>
      <td class="num muted">${p.unit_value ? money(p.unit_value, p.currency) : "—"}</td>
      <td class="num">${money(p.value, p.currency)}</td>
    </tr>`;
  }).join("");
  target.innerHTML = `
    ${warningsHtml(data.warnings)}
    <table>
      <thead><tr><th>Activo</th><th class="num">Cantidad</th>
        <th class="num">Precio ud.</th><th class="num">Valor</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="muted">Sin posiciones.</td></tr>`}</tbody>
      <tfoot><tr><td colspan="3">Total ${esc(data.source)}</td>
        <td class="num pos">${money(data.total, cur)}</td></tr></tfoot>
    </table>`;
  if (window.AppFX) AppFX.onRender(target);
  setContrib(data.category, data.total, data.month);   // suma al patrimonio consolidado
}

// ---- CS:GO (Steam) -----------------------------------------------------
$("#steamForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const target = $("#steamResult");
  const steamid = $("#steamid").value.trim();
  const btn = $("button", ev.target); btn.disabled = true;
  setStatus(target, "Conectando con Steam y valorando en el Market (puede tardar)…");
  try {
    const res = await fetch("/api/steam?currency=eur&steamid=" + encodeURIComponent(steamid));
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || "Error");
    setStatus(target, "");
    renderPositions(json, target);
  } catch (e) { setStatus(target, e.message, true); }
  finally { btn.disabled = false; }
});

// ---- Wealth Reader (banca automática) ----------------------------------
const wrBtn = $("#wrBtn");
if (wrBtn) wrBtn.addEventListener("click", async () => {
  const target = $("#wrResult");
  const code = $("#wrCode").value.trim(), token = $("#wrToken").value.trim();
  if (!code || !token) { setStatus(target, "Pon el banco y el token del widget.", true); return; }
  wrBtn.disabled = true;
  setStatus(target, "Conectando con tu banco vía Wealth Reader…");
  try {
    const res = await fetch("/api/wealthreader", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, token }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || "Error");
    setStatus(target, "");
    renderBank(json, target);
  } catch (e) { setStatus(target, e.message, true); }
  finally { wrBtn.disabled = false; }
});

// ---- Magic: gestor de cartas claro -------------------------------------
let CARDS = [];   // {qty, name, set, cn, foil}

function cardToLine(c) {
  let s = `${c.qty} ${c.name}`;
  if (c.set) s += ` (${c.set})${c.cn ? " " + c.cn : ""}`;
  if (c.foil) s += " *F*";
  return s;
}
function cardsToDecklist() { return CARDS.map(cardToLine).join("\n"); }

function parseDecklistJS(text) {
  const out = [];
  for (let raw of (text || "").split("\n")) {
    let line = raw.trim();
    if (!line || /^(\/\/|#|Deck|Commander|Sideboard|About|Maybeboard)/.test(line)) continue;
    if (line.startsWith("SB:")) line = line.slice(3).trim();
    const m = line.match(/^(?:(\d+)\s*x?\s+)?(.+?)(?:\s+\(([A-Za-z0-9]{2,6})\)\s+(\S+))?((?:\s+[*#][^*#\s]+[*#]?)*)\s*$/);
    if (!m) continue;
    const flags = (m[5] || "").toLowerCase();
    out.push({ qty: m[1] ? parseInt(m[1]) : 1, name: m[2].trim(), set: m[3] || "", cn: m[4] || "",
               foil: flags.includes("*f*") || flags.includes("*e*") });
  }
  return out;
}

let CARD_Q = "";

function renderCards() {
  const el = $("#cardList");
  const tools = $("#cardTools"), pill = $("#cardCount");
  const totalQty = CARDS.reduce((s, c) => s + (c.qty || 1), 0);
  if (tools) tools.hidden = CARDS.length <= 8;
  if (pill) { pill.hidden = !CARDS.length; pill.textContent = `${CARDS.length} líneas · ${totalQty} cartas`; }
  if (!CARDS.length) {
    el.innerHTML = `<p class="hint">Aún no hay cartas. Añade una arriba o importa una decklist.</p>`;
    return;
  }
  const q = CARD_Q.toLowerCase();
  // Conserva el índice real en CARDS para poder borrar tras filtrar.
  const rows = CARDS.map((c, i) => [c, i]).filter(([c]) =>
    !q || (c.name + " " + (c.set || "")).toLowerCase().includes(q));
  if (!rows.length) { el.innerHTML = `<p class="hint">Sin coincidencias para «${esc(CARD_Q)}».</p>`; return; }
  el.innerHTML = rows.map(([c, i]) => `<div class="card-row">
    <span class="card-q">${c.qty}×</span>
    <span class="card-n">${esc(c.name)}${c.set ? ` <span class="tag">${esc(c.set.toUpperCase())}${c.cn ? " " + esc(c.cn) : ""}</span>` : ""}${c.foil ? ` <span class="tag tag-foil">foil</span>` : ""}</span>
    <button type="button" class="card-del" data-i="${i}" aria-label="Quitar">×</button>
  </div>`).join("");
}

// Borrado por delegación (un único listener, robusto con miles de filas).
$("#cardList").addEventListener("click", (ev) => {
  const b = ev.target.closest(".card-del");
  if (!b) return;
  CARDS.splice(+b.dataset.i, 1);
  renderCards(); saveCards();
});
const cardSearch = $("#cardSearch");
if (cardSearch) cardSearch.addEventListener("input", (e) => { CARD_Q = e.target.value; renderCards(); });
const cardClear = $("#cardClear");
if (cardClear) cardClear.addEventListener("click", () => {
  if (CARDS.length && confirm("¿Vaciar toda la lista de cartas?")) { CARDS = []; CARD_Q = ""; if (cardSearch) cardSearch.value = ""; renderCards(); saveCards(); }
});

function saveCards() {
  fetch("/api/cards", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reference: $("#moxfield").value.trim(), decklist: cardsToDecklist() }) }).catch(() => {});
}

$("#cardAddForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const name = $("#cardName").value.trim();
  if (!name) return;
  CARDS.push({ qty: Math.max(1, parseInt($("#cardQty").value) || 1), name,
               set: $("#cardSet").value.trim(), cn: $("#cardCn").value.trim(), foil: $("#cardFoil").checked });
  $("#cardName").value = ""; $("#cardSet").value = ""; $("#cardCn").value = ""; $("#cardFoil").checked = false; $("#cardQty").value = 1;
  $("#cardName").focus();
  renderCards(); saveCards();
});

$("#importBtn").addEventListener("click", () => {
  const parsed = parseDecklistJS($("#decklist").value);
  if (parsed.length) { CARDS = CARDS.concat(parsed); $("#decklist").value = ""; renderCards(); saveCards(); }
});

$("#valuarBtn").addEventListener("click", async () => {
  const target = $("#magicResult");
  const ref = $("#moxfield").value.trim();
  if (!CARDS.length && !ref) { setStatus(target, "Añade cartas o pon un mazo de Moxfield.", true); return; }
  const btn = $("#valuarBtn"); btn.disabled = true;
  setStatus(target, "Pidiendo precios en vivo a Scryfall…");
  try {
    const res = await fetch("/api/magic", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moxfield: ref, decklist: cardsToDecklist() }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || "Error");
    setStatus(target, json.deck && json.deck !== "Decklist" ? "Mazo: " + json.deck : "");
    renderMagic(json, target);
  } catch (e) { setStatus(target, e.message, true); }
  finally { btn.disabled = false; }
});

// ---- Magic: vista de la colección (tarjetas compactas + filtros + orden) --
// Lista potencialmente enorme: sin paginación, pero con búsqueda/filtros/orden
// instantáneos y renderizado progresivo (bloques al hacer scroll), para que el
// DOM no crezca de golpe. Tarjetas sin imagen para aprovechar el espacio.
const MAGIC = { all: [], view: [], shown: 0, chunk: 80, q: "", sort: "value", foil: false,
               rar: new Set(), set: "", layout: "grid", io: null, currency: "EUR" };

const RAR_ORDER = { mythic: 4, rare: 3, uncommon: 2, common: 1 };
const RAR_DEFS = [["mythic", "Mítica"], ["rare", "Rara"], ["uncommon", "Infrecuente"], ["common", "Común"]];
const setLabel = (x) => x.set_name || ((x.edition || "").split(" ")[0]) || "";

function magicStats(list) {
  const units = list.reduce((s, p) => s + (p.quantity || 0), 0);
  const total = list.reduce((s, p) => s + (p.value || 0), 0);
  const foils = list.filter((p) => p.extra && p.extra.foil).reduce((s, p) => s + (p.quantity || 0), 0);
  const top = list.reduce((m, p) => (p.unit_value || 0) > (m.unit_value || 0) ? p : m, list[0] || {});
  return [
    ["Cartas", units.toLocaleString("es-ES")],
    ["Valor total", money(total)],
    ["Más cara", top && top.unit_value ? money(top.unit_value) : "—", top && top.name ? esc(top.name) : ""],
    ["Foils", foils.toLocaleString("es-ES")],
  ];
}

function magicApplyFilters() {
  const q = MAGIC.q.toLowerCase();
  let list = MAGIC.all.filter((p) => {
    const x = p.extra || {};
    if (MAGIC.foil && !x.foil) return false;
    if (MAGIC.rar.size && !MAGIC.rar.has((x.rarity || "").toLowerCase())) return false;
    if (MAGIC.set && setLabel(x) !== MAGIC.set) return false;
    if (!q) return true;
    const hay = [p.name, x.edition, x.set_name, x.type].filter(Boolean).join(" ").toLowerCase();
    return hay.includes(q);
  });
  const rk = (p) => RAR_ORDER[((p.extra || {}).rarity || "").toLowerCase()] || 0;
  const by = {
    value: (a, b) => (b.value || 0) - (a.value || 0),
    value_asc: (a, b) => (a.value || 0) - (b.value || 0),
    unit: (a, b) => (b.unit_value || 0) - (a.unit_value || 0),
    unit_asc: (a, b) => (a.unit_value || 0) - (b.unit_value || 0),
    qty: (a, b) => (b.quantity || 0) - (a.quantity || 0),
    name: (a, b) => (a.name || "").localeCompare(b.name || "", "es"),
    name_desc: (a, b) => (b.name || "").localeCompare(a.name || "", "es"),
    rarity: (a, b) => rk(b) - rk(a) || (b.value || 0) - (a.value || 0),
    set: (a, b) => setLabel(a.extra || {}).localeCompare(setLabel(b.extra || {}), "es"),
  }[MAGIC.sort] || (() => 0);
  list.sort(by);
  MAGIC.view = list;
  MAGIC.shown = 0;
}

function magicTile(p) {
  const x = p.extra || {};
  const r = (x.rarity || "").toLowerCase();
  const rarity = r ? `<span class="m-rar r-${esc(r)}" title="${esc(x.rarity)}">${esc(x.rarity[0].toUpperCase())}</span>` : "";
  const ed = setLabel(x) || (x.edition || "");
  const qty = (p.quantity || 1);
  return `<article class="mcard${x.foil ? " is-foil" : ""}">
    <div class="m-head">
      <span class="m-qty">×${qty}</span>
      ${rarity}
      ${x.foil ? `<span class="m-foil">✦ foil</span>` : ""}
    </div>
    <div class="m-name" title="${esc(p.name)}">${esc(p.name)}</div>
    <div class="m-ed" title="${esc(x.edition || ed)}">${esc(ed)}</div>
    <div class="m-prices">
      <span class="m-unit">${p.unit_value ? money(p.unit_value) + " ud." : "—"}${x.usd_note ? ` <span class="m-usd">${esc(x.usd_note)}</span>` : ""}</span>
      <span class="m-val">${money(p.value)}</span>
    </div>
  </article>`;
}

function magicRenderChunk(grid) {
  const next = MAGIC.view.slice(MAGIC.shown, MAGIC.shown + MAGIC.chunk);
  if (!next.length) return;
  grid.insertAdjacentHTML("beforeend", next.map(magicTile).join(""));
  MAGIC.shown += next.length;
  const left = MAGIC.view.length - MAGIC.shown;
  const count = grid.parentElement.querySelector(".m-count");
  if (count) count.textContent = `Mostrando ${MAGIC.shown} de ${MAGIC.view.length} cartas` + (left ? " · sigue bajando" : "");
}

function magicRefresh(target) {
  magicApplyFilters();
  const grid = $("#magicGrid", target);
  if (!grid) return;
  grid.className = "m-grid" + (MAGIC.layout === "list" ? " is-list" : "");
  grid.innerHTML = "";
  const stats = $("#magicStats", target);
  if (stats) stats.innerHTML = magicStats(MAGIC.view).map(([l, v, sub]) =>
    `<div class="m-stat"><span class="m-stat-l">${l}</span><span class="m-stat-v">${v}</span>${sub ? `<span class="m-stat-s">${sub}</span>` : ""}</div>`).join("");
  magicRenderChunk(grid);
  if (window.AppFX) AppFX.onRender(grid);
}

function renderMagic(data, target) {
  MAGIC.all = data.positions || [];
  MAGIC.currency = data.currency || "EUR";
  MAGIC.shown = 0;
  MAGIC.q = ""; MAGIC.set = ""; MAGIC.foil = false; MAGIC.sort = "value"; MAGIC.rar = new Set();
  if (MAGIC.io) { MAGIC.io.disconnect(); MAGIC.io = null; }
  if (!MAGIC.all.length) {
    target.innerHTML = `${warningsHtml(data.warnings)}<p class="hint">No se encontraron cartas para valorar.</p>`;
    return;
  }
  // Opciones de set y rarezas presentes en la colección.
  const setCounts = {}, rarCounts = {};
  for (const p of MAGIC.all) {
    const x = p.extra || {};
    const sl = setLabel(x); if (sl) setCounts[sl] = (setCounts[sl] || 0) + 1;
    const rr = (x.rarity || "").toLowerCase(); if (rr) rarCounts[rr] = (rarCounts[rr] || 0) + 1;
  }
  const setOpts = Object.keys(setCounts).sort((a, b) => a.localeCompare(b, "es"));
  const setSelect = `<option value="">Todos los sets (${setOpts.length})</option>` +
    setOpts.map((s) => `<option value="${esc(s)}">${esc(s)} · ${setCounts[s]}</option>`).join("");
  const rarChips = RAR_DEFS.filter(([k]) => rarCounts[k]).map(([k, lbl]) =>
    `<button type="button" class="m-rchip r-${k}" data-rar="${k}">${lbl} <b>${rarCounts[k]}</b></button>`).join("");

  target.innerHTML = `
    <div class="m-statbar" id="magicStats"></div>
    <div class="m-toolbar">
      <div class="m-search"><span>🔎</span><input type="search" id="magicQ" placeholder="Buscar carta, set o tipo…" autocomplete="off"></div>
      <select id="magicSort" aria-label="Ordenar">
        <optgroup label="Valor total"><option value="value">Mayor ↓</option><option value="value_asc">Menor ↑</option></optgroup>
        <optgroup label="Precio unidad"><option value="unit">Mayor ↓</option><option value="unit_asc">Menor ↑</option></optgroup>
        <option value="qty">Cantidad ↓</option>
        <option value="rarity">Rareza ↓</option>
        <option value="set">Set A-Z</option>
        <option value="name">Nombre A-Z</option>
        <option value="name_desc">Nombre Z-A</option>
      </select>
      <select id="magicSet" aria-label="Set">${setSelect}</select>
      <button type="button" class="m-chip" id="magicFoil" aria-pressed="false">✦ Solo foil</button>
      <div class="m-views">
        <button type="button" id="magicGridV" class="active" aria-label="Cuadrícula">▦</button>
        <button type="button" id="magicListV" aria-label="Lista">≣</button>
      </div>
    </div>
    ${rarChips ? `<div class="m-rars" id="magicRars">${rarChips}<button type="button" class="m-rclear" id="magicRarClear" hidden>Limpiar</button></div>` : ""}
    <div id="magicGrid" class="m-grid"></div>
    <p class="m-count hint"></p>
    ${warningsHtml(data.warnings)}`;

  $("#magicQ", target).addEventListener("input", (e) => { MAGIC.q = e.target.value; magicRefresh(target); });
  $("#magicSort", target).addEventListener("change", (e) => { MAGIC.sort = e.target.value; magicRefresh(target); });
  $("#magicSet", target).addEventListener("change", (e) => { MAGIC.set = e.target.value; magicRefresh(target); });
  $("#magicFoil", target).addEventListener("click", (e) => {
    MAGIC.foil = !MAGIC.foil; e.target.setAttribute("aria-pressed", MAGIC.foil); e.target.classList.toggle("active", MAGIC.foil);
    magicRefresh(target);
  });
  $$(".m-rchip", target).forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.rar;
    if (MAGIC.rar.has(k)) MAGIC.rar.delete(k); else MAGIC.rar.add(k);
    b.classList.toggle("active", MAGIC.rar.has(k));
    const clr = $("#magicRarClear", target); if (clr) clr.hidden = !MAGIC.rar.size;
    magicRefresh(target);
  }));
  const rarClear = $("#magicRarClear", target);
  if (rarClear) rarClear.addEventListener("click", () => {
    MAGIC.rar.clear();
    $$(".m-rchip", target).forEach((b) => b.classList.remove("active"));
    rarClear.hidden = true; magicRefresh(target);
  });
  const setView = (v) => {
    MAGIC.layout = v;
    $("#magicGridV", target).classList.toggle("active", v === "grid");
    $("#magicListV", target).classList.toggle("active", v === "list");
    magicRefresh(target);
  };
  $("#magicGridV", target).addEventListener("click", () => setView("grid"));
  $("#magicListV", target).addEventListener("click", () => setView("list"));

  magicRefresh(target);
  // Renderizado progresivo: cuando el centinela entra en viewport, añade el siguiente bloque.
  const sentinel = document.createElement("div");
  sentinel.className = "m-sentinel";
  $("#magicGrid", target).after(sentinel);
  MAGIC.io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) magicRenderChunk($("#magicGrid", target));
  }, { rootMargin: "600px" });
  MAGIC.io.observe(sentinel);

  setContrib(data.category, data.total, data.month);   // suma al patrimonio consolidado
}

// Cargar lista de cartas guardada.
fetch("/api/cards").then((r) => r.json()).then((j) => {
  if (j.reference) $("#moxfield").value = j.reference;
  if (j.decklist) { CARDS = parseDecklistJS(j.decklist); }
  renderCards();
}).catch(() => renderCards());

// ===== BANCO: desglose de gastos netos + enlace de bizums ===============
let BANK = null, LINKS = {};

function renderBank(data, target) {
  BANK = data; LINKS = {};
  for (const t of BANK.transactions) if (t.kind === "bizum_in") LINKS[t.id] = t.suggested_link;
  target.innerHTML = `
    <div class="cards" id="bankKpis"></div>
    <h3 style="margin-top:18px">Gasto neto por categoría</h3>
    <table id="catTable"><thead><tr><th>Categoría</th><th class="num">Bruto</th>
      <th class="num">Devoluciones</th><th class="num">Neto</th><th class="num">%</th></tr></thead>
      <tbody></tbody><tfoot></tfoot></table>
    <h3 style="margin-top:18px">Bizums recibidos <small class="muted">— ¿devolución o ingreso real?</small></h3>
    <p class="hint">Liga cada bizum al gasto que te devuelven (cena 30 € con dos bizums de 10 € → 10 €).</p>
    <table id="bizumTable"><thead><tr><th>Fecha</th><th class="num">Importe</th><th>Ligar a gasto…</th></tr></thead><tbody></tbody></table>`;
  bankRender();
  if (BANK.available_balance != null) setContrib("Liquidez (banco)", BANK.available_balance, BANK.month);
  if (window.AppFX) AppFX.onRender(target);
}

const bById = (id) => BANK.transactions.find((t) => t.id === id);
const isExp = (t) => t.kind === "expense" || t.kind === "bizum_out";

function bankCompute() {
  const refundByExp = {};
  for (const [bid, eid] of Object.entries(LINKS)) {
    if (eid === null || eid === undefined) continue;
    refundByExp[eid] = (refundByExp[eid] || 0) + bById(Number(bid)).amount;
  }
  const cats = {}; let gross = 0, refund = 0, inv = 0, income = 0;
  for (const t of BANK.transactions) {
    if (isExp(t)) {
      const g = Math.abs(t.amount), r = Math.min(refundByExp[t.id] || 0, g);
      gross += g; refund += r;
      const c = (cats[t.category] = cats[t.category] || { gross: 0, refund: 0 });
      c.gross += g; c.refund += r;
    } else if (t.kind === "investment") inv += Math.abs(t.amount);
    else if (t.kind === "income") income += t.amount;
    else if (t.kind === "bizum_in" && (LINKS[t.id] === null || LINKS[t.id] === undefined)) income += t.amount;
  }
  return { cats, gross, refund, net: gross - refund, inv, income };
}

function bankRender() {
  const c = bankCompute();
  BANK_NET = c.net;
  FLOWS.gastos = c.net; FLOWS.ganancias = c.income;
  renderSummary();
  // Persistir los flujos del mes en la DB (gastos, ganancias, inversión).
  if (BANK && BANK.month) {
    const m = BANK.month;
    const post = (cat, value) => fetch("/api/snapshot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month: m, category: cat, value }),
    });
    post("_flow:gastos", c.net); post("_flow:ganancias", c.income); post("_flow:inversion", c.inv);
  }
  $("#bankKpis").innerHTML = [
    ["Gasto neto", money(-c.net), "neg"], ["Gasto bruto", money(-c.gross), "muted"],
    ["Devoluciones bizum", money(c.refund), "pos"], ["Ingresos reales", money(c.income), "pos"],
    ["Inversión (no es gasto)", money(c.inv), "muted"],
  ].map(([l, v, cls]) => `<div class="kpi"><div class="label">${l}</div><div class="val ${cls}">${v}</div></div>`).join("");

  const rows = Object.entries(c.cats).sort((a, b) => (b[1].gross - b[1].refund) - (a[1].gross - a[1].refund));
  $("#catTable tbody").innerHTML = rows.map(([cat, v]) => {
    const net = v.gross - v.refund, pct = c.net ? (net / c.net) * 100 : 0;
    return `<tr><td>${esc(cat)}</td><td class="num muted">${money(-v.gross)}</td>
      <td class="num ${v.refund ? "pos" : "muted"}">${v.refund ? money(v.refund) : "—"}</td>
      <td class="num neg">${money(-net)}</td>
      <td class="num">${pct.toFixed(1)}%<div class="bar"><span style="width:${Math.max(0, pct)}%"></span></div></td></tr>`;
  }).join("");
  $("#catTable tfoot").innerHTML = `<tr><td>Total</td><td class="num">${money(-c.gross)}</td>
    <td class="num pos">${money(c.refund)}</td><td class="num neg">${money(-c.net)}</td><td class="num">100%</td></tr>`;

  const bizums = BANK.transactions.filter((t) => t.kind === "bizum_in");
  const opts = (sel) => {
    const none = (sel === null || sel === undefined) ? " selected" : "";
    return `<option value=""${none}>— Ingreso real (no devolución) —</option>` +
      BANK.transactions.filter(isExp).map((e) =>
        `<option value="${e.id}"${e.id === sel ? " selected" : ""}>${esc(e.date)} · ${esc(e.concept)} (${money(e.amount)})</option>`).join("");
  };
  $("#bizumTable tbody").innerHTML = bizums.length ? bizums.map((b) => {
    const flag = b.recurring_income ? ` <span class="tag">posible ingreso recurrente</span>` : "";
    return `<tr><td>${esc(b.date)}${flag}</td><td class="num pos">${money(b.amount)}</td>
      <td><select data-bizum="${b.id}">${opts(LINKS[b.id])}</select></td></tr>`;
  }).join("") : `<tr><td colspan="3" class="muted">No hay bizums recibidos.</td></tr>`;
  $$("#bizumTable select").forEach((s) => s.addEventListener("change", () => {
    LINKS[Number(s.dataset.bizum)] = s.value === "" ? null : Number(s.value); bankRender();
  }));
}

// ---- valores por defecto desde config.json -----------------------------
fetch("/api/config").then((r) => r.json()).then((c) => {
  if (c.steamid && !c.steamid.startsWith("TU_")) $("#steamid").value = c.steamid;
  if (c.moxfield) $("#moxfield").value = c.moxfield;
}).catch(() => {});

// ---- restaurar desde la base de datos (mismo dato en móvil/PC/amigos) ---
fetch("/api/snapshots").then((r) => r.json()).then((snaps) => {
  const months = Object.keys(snaps || {}).sort();
  if (!months.length) return;
  // Variación mensual: total (sin flujos) del mes anterior.
  if (months.length > 1) {
    const pm = snaps[months[months.length - 2]];
    EVOL.prev = Object.entries(pm).reduce((s, [k, v]) => s + (k.startsWith("_flow:") ? 0 : v), 0);
  }
  const last = snaps[months[months.length - 1]];      // mes más reciente
  for (const [k, v] of Object.entries(last)) {
    if (k === "_flow:gastos") FLOWS.gastos = v;
    else if (k === "_flow:ganancias") FLOWS.ganancias = v;
    else if (k.startsWith("_flow:")) { /* inversión u otros: no se muestran como patrimonio */ }
    else CONTRIB[k] = v;                              // categoría de patrimonio
  }
  renderSummary();
  if (window.Charts) window.Charts.refreshPie(CONTRIB);
  const hint = document.getElementById("summaryHint");
  if (hint) hint.textContent = "Datos guardados en la nube. Sube un documento para actualizar.";
}).catch(() => {});
