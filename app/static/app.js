"use strict";

let DATA = null;          // respuesta del backend
let LINKS = {};           // bizumId -> expenseId | null (null = ingreso real)

const $ = (s) => document.querySelector(s);
const eur = (n) =>
  (n < 0 ? "-" : "") + "€" + Math.abs(n).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ---- carga de archivo --------------------------------------------------
const drop = $("#drop");
const input = $("#pdf");
const label = $("#filelabel");

input.addEventListener("change", () => {
  if (input.files[0]) label.textContent = "📄 " + input.files[0].name;
});
["dragover", "dragenter"].forEach((e) =>
  drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((e) =>
  drop.addEventListener(e, () => drop.classList.remove("drag")));
drop.addEventListener("drop", (ev) => {
  ev.preventDefault();
  if (ev.dataTransfer.files[0]) {
    input.files = ev.dataTransfer.files;
    label.textContent = "📄 " + input.files[0].name;
  }
});

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!input.files[0]) { setStatus("Elige un PDF primero.", true); return; }
  const fd = new FormData();
  fd.append("pdf", input.files[0]);
  $("#go").disabled = true;
  setStatus("Analizando…");
  try {
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || "Error al procesar");
    DATA = json;
    initLinks();
    setStatus("Periodo: " + DATA.period + " · " + DATA.transactions.length + " movimientos");
    $("#results").hidden = false;
    renderAll();
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("#go").disabled = false;
  }
});

function setStatus(msg, err) {
  const s = $("#status");
  s.textContent = msg;
  s.classList.toggle("err", !!err);
}

// ---- modelo ------------------------------------------------------------
function initLinks() {
  LINKS = {};
  for (const t of DATA.transactions) {
    if (t.kind === "bizum_in") {
      // por defecto usamos la sugerencia del backend (null si es ingreso real)
      LINKS[t.id] = t.suggested_link;
    }
  }
}

const byId = (id) => DATA.transactions.find((t) => t.id === id);
const isExpense = (t) => t.kind === "expense" || t.kind === "bizum_out";

// devoluciones (bizums ligados) agrupadas por id de gasto
function refundsByExpense() {
  const m = {};
  for (const [bid, eid] of Object.entries(LINKS)) {
    if (eid === null || eid === undefined) continue;
    const b = byId(Number(bid));
    m[eid] = (m[eid] || 0) + b.amount;
  }
  return m;
}

function compute() {
  const refunds = refundsByExpense();
  const cats = {};        // categoria -> {gross, refund}
  let grossExpense = 0, totalRefund = 0, investment = 0, realIncome = 0;

  for (const t of DATA.transactions) {
    if (isExpense(t)) {
      const gross = Math.abs(t.amount);
      const ref = Math.min(refunds[t.id] || 0, gross); // no baja de 0
      grossExpense += gross;
      totalRefund += ref;
      const c = (cats[t.category] = cats[t.category] || { gross: 0, refund: 0 });
      c.gross += gross;
      c.refund += ref;
    } else if (t.kind === "investment") {
      investment += Math.abs(t.amount);
    } else if (t.kind === "income") {
      realIncome += t.amount;
    } else if (t.kind === "bizum_in") {
      if (LINKS[t.id] === null || LINKS[t.id] === undefined) realIncome += t.amount;
    }
  }
  const netExpense = grossExpense - totalRefund;
  return { cats, grossExpense, totalRefund, netExpense, investment, realIncome };
}

// ---- render ------------------------------------------------------------
function renderAll() {
  const c = compute();
  renderSummary(c);
  renderCats(c);
  renderBizums();
  renderTx();
}

function renderSummary(c) {
  const cards = [
    ["Gasto neto", eur(-c.netExpense), "neg"],
    ["Gasto bruto", eur(-c.grossExpense), "muted"],
    ["Devoluciones (bizum)", eur(c.totalRefund), "pos"],
    ["Ingresos reales", eur(c.realIncome), "pos"],
    ["Inversión (no es gasto)", eur(c.investment), "muted"],
    ["Balance del periodo", eur(c.realIncome - c.netExpense - c.investment),
      (c.realIncome - c.netExpense - c.investment) >= 0 ? "pos" : "neg"],
  ];
  $("#summary").innerHTML = cards.map(([l, v, cls]) =>
    `<div class="kpi"><div class="label">${l}</div><div class="val ${cls}">${v}</div></div>`).join("");
}

function renderCats(c) {
  const rows = Object.entries(c.cats).sort((a, b) => (b[1].gross - b[1].refund) - (a[1].gross - a[1].refund));
  const tb = $("#catTable tbody");
  tb.innerHTML = rows.map(([cat, v]) => {
    const net = v.gross - v.refund;
    const pct = c.netExpense ? (net / c.netExpense) * 100 : 0;
    return `<tr>
      <td>${cat}</td>
      <td class="num muted">${eur(-v.gross)}</td>
      <td class="num ${v.refund ? "pos" : "muted"}">${v.refund ? eur(v.refund) : "—"}</td>
      <td class="num neg">${eur(-net)}</td>
      <td class="num">${pct.toFixed(1)}%<div class="bar"><span style="width:${Math.max(0, pct)}%"></span></div></td>
    </tr>`;
  }).join("");
  $("#catTable tfoot").innerHTML = `<tr>
    <td>Total</td>
    <td class="num">${eur(-c.grossExpense)}</td>
    <td class="num pos">${eur(c.totalRefund)}</td>
    <td class="num neg">${eur(-c.netExpense)}</td>
    <td class="num">100%</td></tr>`;
}

function expenseOptions(selectedId) {
  const opts = DATA.transactions.filter(isExpense).map((e) => {
    const sel = e.id === selectedId ? " selected" : "";
    return `<option value="${e.id}"${sel}>${e.date} · ${e.concept} (${eur(e.amount)})</option>`;
  }).join("");
  const none = (selectedId === null || selectedId === undefined) ? " selected" : "";
  return `<option value=""${none}>— Ingreso real (no devolución) —</option>` + opts;
}

function renderBizums() {
  const bizums = DATA.transactions.filter((t) => t.kind === "bizum_in");
  const tb = $("#bizumTable tbody");
  if (!bizums.length) { tb.innerHTML = `<tr><td colspan="3" class="muted">No hay bizums recibidos.</td></tr>`; return; }
  tb.innerHTML = bizums.map((b) => {
    const flag = b.recurring_income
      ? ` <span class="tag">posible ingreso recurrente</span>` : "";
    return `<tr>
      <td>${b.date}${flag}</td>
      <td class="num pos">${eur(b.amount)}</td>
      <td><select data-bizum="${b.id}">${expenseOptions(LINKS[b.id])}</select></td>
    </tr>`;
  }).join("");
  tb.querySelectorAll("select").forEach((s) =>
    s.addEventListener("change", () => {
      const bid = Number(s.dataset.bizum);
      LINKS[bid] = s.value === "" ? null : Number(s.value);
      renderAll();
    }));
}

function renderTx() {
  const tb = $("#txTable tbody");
  tb.innerHTML = DATA.transactions.map((t) => {
    const cls = t.amount < 0 ? "neg" : "pos";
    return `<tr>
      <td>${t.date}</td>
      <td>${t.concept}</td>
      <td><span class="tag">${t.category}</span></td>
      <td class="num ${cls}">${eur(t.amount)}</td>
    </tr>`;
  }).join("");
}
