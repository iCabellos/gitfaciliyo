"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const money = (n, cur = "EUR") =>
  (n < 0 ? "-" : "") + (cur === "USD" ? "$" : "€") +
  Math.abs(n).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Contribuciones al patrimonio consolidado (por categoría).
const CONTRIB = {};         // label -> valor en EUR (activos)
window.CONTRIB = CONTRIB;   // accesible para la vista de gráficos
let BANK_NET = null;        // gasto neto del mes (informativo, no patrimonio)

const thisMonth = () => new Date().toISOString().slice(0, 7);   // YYYY-MM

function setContrib(label, value, month) {
  CONTRIB[label] = value;
  renderSummary();
  // Persistir snapshot mensual (para el histórico de gráficos).
  const m = month || thisMonth();
  fetch("/api/snapshot", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ month: m, category: label, value }),
  }).then(() => { if (window.Charts) window.Charts.refresh(); }).catch(() => {});
  if (window.Charts) window.Charts.refreshPie(CONTRIB);
}

function renderSummary() {
  const entries = Object.entries(CONTRIB);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const el = $("#summary");
  if (!entries.length && BANK_NET === null) { el.innerHTML = ""; return; }
  let html = `<div class="kpi big"><div class="label">Patrimonio total</div>
              <div class="val pos">${money(total)}</div></div>`;
  for (const [label, v] of entries.sort((a, b) => b[1] - a[1])) {
    html += `<div class="kpi"><div class="label">${label}</div><div class="val">${money(v)}</div></div>`;
  }
  if (BANK_NET !== null) {
    html += `<div class="kpi"><div class="label">Gasto neto del mes</div>
             <div class="val neg">${money(-BANK_NET)}</div></div>`;
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
  return warnings.map((w) => `<p class="warn">⚠️ ${w}</p>`).join("");
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
    const icon = p.extra && p.extra.icon ? `<img class="thumb" src="${p.extra.icon}">` : "";
    const sub = p.extra && (p.extra.tag || p.extra.isin || p.extra.asset || p.extra.deck || p.extra.type) || "";
    return `<tr>
      <td>${icon}${p.name}${sub ? ` <span class="tag">${sub}</span>` : ""}</td>
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
      <tfoot><tr><td colspan="3">Total ${data.source}</td>
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

// ---- Magic (Moxfield + Scryfall) ---------------------------------------
$("#magicForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const target = $("#magicResult");
  const btn = $("button", ev.target); btn.disabled = true;
  setStatus(target, "Obteniendo cartas y pidiendo precios en vivo a Scryfall…");
  try {
    const res = await fetch("/api/magic", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moxfield: $("#moxfield").value.trim(), decklist: $("#decklist").value }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || "Error");
    setStatus(target, json.deck ? "Mazo: " + json.deck : "");
    renderPositions(json, target);
  } catch (e) { setStatus(target, e.message, true); }
  finally { btn.disabled = false; }
});

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
  BANK_NET = c.net; renderSummary();
  $("#bankKpis").innerHTML = [
    ["Gasto neto", money(-c.net), "neg"], ["Gasto bruto", money(-c.gross), "muted"],
    ["Devoluciones bizum", money(c.refund), "pos"], ["Ingresos reales", money(c.income), "pos"],
    ["Inversión (no es gasto)", money(c.inv), "muted"],
  ].map(([l, v, cls]) => `<div class="kpi"><div class="label">${l}</div><div class="val ${cls}">${v}</div></div>`).join("");

  const rows = Object.entries(c.cats).sort((a, b) => (b[1].gross - b[1].refund) - (a[1].gross - a[1].refund));
  $("#catTable tbody").innerHTML = rows.map(([cat, v]) => {
    const net = v.gross - v.refund, pct = c.net ? (net / c.net) * 100 : 0;
    return `<tr><td>${cat}</td><td class="num muted">${money(-v.gross)}</td>
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
        `<option value="${e.id}"${e.id === sel ? " selected" : ""}>${e.date} · ${e.concept} (${money(e.amount)})</option>`).join("");
  };
  $("#bizumTable tbody").innerHTML = bizums.length ? bizums.map((b) => {
    const flag = b.recurring_income ? ` <span class="tag">posible ingreso recurrente</span>` : "";
    return `<tr><td>${b.date}${flag}</td><td class="num pos">${money(b.amount)}</td>
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
