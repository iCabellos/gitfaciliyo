/* ===========================================================================
   Histórico SEMANAL de precios: qué carta/skin se ha movido y entre qué precios.

   Lee /api/prices/weekly (serie semanal de cada elemento) y
   /api/prices/movers (lo que se ha movido al menos el umbral, arriba o abajo).
   Si no hay histórico se dice, no se rellena con nada.
   =========================================================================== */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const eur = (n) => "€" + Number(n).toLocaleString("es-ES",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  // Coma decimal, igual que los importes de la misma fila.
  const pct = (n) => (n >= 0 ? "+" : "") + Number(n).toFixed(1).replace(".", ",") + "%";
  const ICON = { card: "🃏", skin: "🔫" };

  const H = { items: [], movers: [], coverage: {}, threshold: 5, q: "", kind: "", selected: null, chart: null };

  // ---- carga -------------------------------------------------------------
  async function load() {
    const table = $("#histTable");
    if (!table) return;
    table.innerHTML = `<p class="hint">Cargando histórico…</p>`;
    try {
      const [weekly, movers] = await Promise.all([
        fetch("/api/prices/weekly").then((r) => r.json()),
        fetch("/api/prices/movers").then((r) => r.json()),
      ]);
      if (weekly.error) throw new Error(weekly.error);
      H.items = weekly.items || [];
      H.coverage = weekly.coverage || {};
      H.threshold = movers.threshold || weekly.threshold || 5;
      H.movers = movers.movers || [];
    } catch (e) {
      table.innerHTML = `<p class="warn">⚠️ No pude leer el histórico: ${esc(e.message)}</p>`;
      return;
    }
    const th = $("#histThreshold");
    if (th) th.textContent = String(H.threshold);
    renderStats();
    renderMovers();
    renderTable();
  }

  function renderStats() {
    const c = H.coverage || {};
    const stats = [
      ["Días registrados", (c.days || 0).toLocaleString("es-ES")],
      ["Elementos seguidos", (c.items || 0).toLocaleString("es-ES")],
      ["Último registro", c.last_day || "—",
        c.stale_days != null ? `hace ${c.stale_days} día(s)` : ""],
      [`Movimientos ≥${H.threshold}%`, String(H.movers.length)],
    ];
    $("#histStats").innerHTML = stats.map(([l, v, sub]) =>
      `<div class="m-stat"><span class="m-stat-l">${esc(l)}</span>
       <span class="m-stat-v">${esc(v)}</span>
       ${sub ? `<span class="m-stat-s">${esc(sub)}</span>` : ""}</div>`).join("");

    // El seguimiento parado es la causa de que el resumen repita cifras: se dice.
    const warn = $("#histWarn");
    if (!c.days) {
      warn.innerHTML = `<p class="warn">⚠️ Todavía no hay histórico de precios. El
        seguimiento diario necesita tu SteamID64 (<code>STEAM_ID64</code>) y/o tu
        lista de Magic guardada.</p>`;
    } else if (c.stale_days > 2) {
      warn.innerHTML = `<p class="warn">⚠️ El último precio registrado es del
        ${esc(c.last_day)} (hace ${c.stale_days} días): el seguimiento diario está parado.</p>`;
    } else {
      warn.innerHTML = "";
    }
  }

  function renderMovers() {
    const el = $("#histMovers");
    if (!H.movers.length) {
      el.innerHTML = `<p class="hint">Ninguna carta ni skin se movió más de un
        ${H.threshold}% en la última semana.</p>`;
      return;
    }
    const rows = H.movers.map((m) => `<tr data-key="${esc(m.key)}" class="hist-row">
        <td>${ICON[m.kind] || "•"} ${esc(m.name)}</td>
        <td class="num muted">${eur(m.price_from)}</td>
        <td class="num">${eur(m.price_to)}</td>
        <td class="num ${m.pct >= 0 ? "pos" : "neg"}">${m.pct >= 0 ? "🔺" : "🔻"} ${pct(m.pct)}</td>
      </tr>`).join("");
    el.innerHTML = `<table><thead><tr>
        <th>Elemento</th><th class="num">Antes (${esc(H.movers[0].date_from)})</th>
        <th class="num">Ahora (${esc(H.movers[0].date_to)})</th><th class="num">Variación</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function filtered() {
    const q = H.q.toLowerCase();
    return H.items.filter((it) =>
      (!H.kind || it.kind === H.kind) && (!q || it.name.toLowerCase().includes(q)));
  }

  function renderTable() {
    const list = filtered();
    const pill = $("#histCount");
    if (pill) { pill.hidden = !H.items.length; pill.textContent = `${list.length} elementos`; }
    const el = $("#histTable");
    if (!H.items.length) {
      el.innerHTML = `<p class="hint">Sin elementos que mostrar todavía.</p>`;
      return;
    }
    if (!list.length) {
      el.innerHTML = `<p class="hint">Sin coincidencias para «${esc(H.q)}».</p>`;
      return;
    }
    const rows = list.map((it) => {
      const move = it.pct == null ? `<span class="muted">—</span>`
        : `<span class="${it.pct >= 0 ? "pos" : "neg"}">${pct(it.pct)}</span>`;
      const flag = it.pct != null && Math.abs(it.pct) >= H.threshold ? " ⚑" : "";
      return `<tr class="hist-row" data-key="${esc(it.key)}">
        <td>${ICON[it.kind] || "•"} ${esc(it.name)}${flag}
            <span class="tag">${esc(it.points.length)} semanas</span></td>
        <td class="num muted">${it.prev == null ? "—" : eur(it.prev)}</td>
        <td class="num">${eur(it.price)}</td>
        <td class="num">${move}</td>
        <td class="num muted">${esc(it.week)}</td>
      </tr>`;
    }).join("");
    el.innerHTML = `<table><thead><tr>
        <th>Elemento</th><th class="num">Semana anterior</th><th class="num">Última semana</th>
        <th class="num">Variación</th><th class="num">Semana</th>
      </tr></thead><tbody>${rows}</tbody></table>
      <p class="hint">Toca cualquier fila para ver su serie semanal completa.</p>`;
  }

  // ---- detalle: serie semanal de un elemento ------------------------------
  function showDetail(key) {
    const item = H.items.find((i) => i.key === key);
    const box = $("#histDetail");
    if (!item || typeof Chart === "undefined") return;
    H.selected = key;
    box.hidden = false;
    $("#histDetailName").textContent = `${ICON[item.kind] || "•"} ${item.name}`;
    $("#histDetailSub").textContent =
      `${item.points.length} semanas registradas · última ${item.week} (${item.date})`
      + (item.pct == null ? "" : ` · ${pct(item.pct)} vs semana anterior`);
    if (H.chart) H.chart.destroy();
    const color = item.kind === "skin" ? "#6ea8ff" : "#46d39a";
    H.chart = new Chart($("#histChart"), {
      type: "line",
      data: {
        labels: item.points.map((p) => p.week),
        datasets: [{
          label: item.name, data: item.points.map((p) => p.price),
          borderColor: color, backgroundColor: color + "22", borderWidth: 2,
          pointRadius: 3, tension: 0.3, fill: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (c) => item.points[c[0].dataIndex].date,
              label: (c) => " " + eur(c.parsed.y),
            },
          },
        },
        scales: { y: { ticks: { callback: (v) => eur(v) } } },
      },
    });
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---- eventos -----------------------------------------------------------
  const pane = $("#pane-historico");
  if (pane) {
    pane.addEventListener("click", (ev) => {
      const row = ev.target.closest(".hist-row");
      if (row && row.dataset.key) showDetail(row.dataset.key);
    });
    $("#histQ").addEventListener("input", (e) => { H.q = e.target.value; renderTable(); });
    $("#histKind").addEventListener("change", (e) => { H.kind = e.target.value; renderTable(); });
  }
  $$('#tabs button[data-tab="historico"]').forEach((b) => b.addEventListener("click", load));

  window.PriceHistory = { load };
  load();
})();
