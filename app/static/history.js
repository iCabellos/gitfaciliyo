/* ===========================================================================
   Histórico SEMANAL de TODO el patrimonio.

   La misma serie cubre el patrimonio total, cada categoría, cada acción, carta
   y skin: lee /api/prices/weekly (serie semanal de cada clave) y
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
  // Ticks de eje: sin céntimos, que ahí solo hacen ruido.
  const eurShort = (n) => "€" + Number(n).toLocaleString("es-ES", { maximumFractionDigits: 0 });
  // Coma decimal, igual que los importes de la misma fila.
  const pct = (n) => (n >= 0 ? "+" : "") + Number(n).toFixed(1).replace(".", ",") + "%";
  const ICON = { total: "💼", cat: "📦", stock: "📄", card: "🃏", skin: "🔫" };
  // Blanco para el total y color por categoría, como el resto de gráficos.
  const SERIES_COLORS = ["#6ea8ff", "#46d39a", "#ff6b9d", "#ffce6b", "#b388ff", "#c7c7cc"];

  const H = { items: [], portfolio: [], movers: [], coverage: {}, threshold: 5,
              totalKey: "total:Patrimonio", q: "", kind: "", selected: null,
              chart: null, portfolioChart: null };

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
      H.portfolio = weekly.portfolio || [];
      H.totalKey = weekly.total_key || H.totalKey;
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
    renderPortfolio();
    renderMovers();
    renderTable();
  }

  function renderStats() {
    const c = H.coverage || {};
    const total = H.portfolio.find((p) => p.key === H.totalKey);
    const stats = [
      ["Semanas registradas", String(new Set(H.items.flatMap((i) => i.points.map((p) => p.week))).size)],
      ["Patrimonio (última semana)", total ? eur(total.price) : "—",
        total && total.pct != null ? `${pct(total.pct)} vs semana anterior` : ""],
      ["Series seguidas", `${(c.portfolio_items || 0) + (c.items || 0)}`,
        `${c.portfolio_items || 0} del patrimonio · ${c.items || 0} artículos`],
      [`Movimientos ≥${H.threshold}%`, String(H.movers.length)],
    ];
    $("#histStats").innerHTML = stats.map(([l, v, sub]) =>
      `<div class="m-stat"><span class="m-stat-l">${esc(l)}</span>
       <span class="m-stat-v">${esc(v)}</span>
       ${sub ? `<span class="m-stat-s">${esc(sub)}</span>` : ""}</div>`).join("");

    // Un seguimiento parado o a medias es la causa de que el resumen repita
    // cifras: se dice aquí, no se disimula.
    const warn = $("#histWarn");
    const avisos = [];
    if (!c.days) {
      avisos.push(`Todavía no hay histórico. El patrimonio se registra con cada
        resumen semanal, y las cartas y skins necesitan tu SteamID64
        (<code>STEAM_ID64</code>) y/o tu lista de Magic guardada.`);
    } else {
      if (!c.tracks_portfolio) {
        avisos.push(`El histórico solo tiene artículos sueltos: el patrimonio total
          aún no se ha registrado. Pulsa «Registrar punto de hoy» o espera al
          próximo resumen semanal.`);
      }
      if (!c.items) {
        avisos.push(`No se está siguiendo ninguna carta ni skin: revisa
          <code>STEAM_ID64</code> y tu lista de Magic.`);
      }
      if (c.stale_days > 2) {
        avisos.push(`El último registro es del ${esc(c.last_day)}
          (hace ${c.stale_days} días): el seguimiento diario está parado.`);
      }
    }
    warn.innerHTML = avisos.map((a) => `<p class="warn">⚠️ ${a}</p>`).join("");
  }

  // ---- patrimonio semana a semana ----------------------------------------
  function renderPortfolio() {
    const card = $("#histPortfolioCard");
    if (!card) return;
    const total = H.portfolio.find((p) => p.key === H.totalKey);
    const cats = H.portfolio.filter((p) => p.kind === "cat");
    if (!total && !cats.length) { card.hidden = true; return; }
    card.hidden = false;
    if (typeof Chart === "undefined") return;

    // Eje común: todas las semanas vistas en cualquiera de las series.
    const weeks = [...new Set(H.portfolio.flatMap((p) => p.points.map((q) => q.week)))].sort();
    const serie = (row) => {
      const byWeek = Object.fromEntries(row.points.map((q) => [q.week, q.price]));
      return weeks.map((w) => (w in byWeek ? byWeek[w] : null));
    };
    // El total es un orden de magnitud mayor que cada categoría: con un solo eje
    // las categorías quedarían aplastadas contra el suelo. Total a la derecha,
    // categorías a la izquierda.
    const datasets = cats.map((row, i) => ({
      label: row.name, data: serie(row), borderColor: SERIES_COLORS[i % SERIES_COLORS.length],
      backgroundColor: SERIES_COLORS[i % SERIES_COLORS.length] + "22",
      borderWidth: 2, pointRadius: 2, tension: 0.3, fill: false, spanGaps: true,
      yAxisID: "cats",
    }));
    if (total) {
      datasets.unshift({
        label: "Patrimonio total", data: serie(total), borderColor: "#f5f5f7",
        backgroundColor: "rgba(245,245,247,.10)", borderWidth: 3, pointRadius: 3,
        tension: 0.3, fill: true, spanGaps: true, yAxisID: "total",
      });
    }
    $("#histPortfolioSub").textContent = total
      ? `${weeks.length} semanas · última ${total.week} (${total.date})`
        + (total.prev != null ? ` · ${eur(total.prev)} → ${eur(total.price)} (${pct(total.pct)})` : "")
      : `${weeks.length} semanas · aún sin total registrado`;

    if (H.portfolioChart) H.portfolioChart.destroy();
    H.portfolioChart = new Chart($("#histPortfolioChart"), {
      type: "line",
      data: { labels: weeks, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { boxWidth: 12, usePointStyle: true } },
          tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${eur(c.parsed.y)}` } },
        },
        scales: {
          cats: { position: "left", ticks: { callback: (v) => eurShort(v) },
                  title: { display: true, text: "Por categoría" } },
          total: { position: "right", display: !!total, grid: { drawOnChartArea: false },
                   ticks: { callback: (v) => eurShort(v) },
                   title: { display: true, text: "Patrimonio total" } },
        },
      },
    });
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
    const kinds = H.kind ? H.kind.split(",") : null;
    return H.items.filter((it) =>
      (!kinds || kinds.includes(it.kind)) && (!q || it.name.toLowerCase().includes(q)));
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
            <span class="tag">${esc(it.kind_label || "")}</span>
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
      <p class="hint">Toca cualquier fila para ver su serie semanal completa.
         Las acciones, las cartas y las skins van a precio por unidad; el total y
         las categorías, a valor completo.</p>`;
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
      `${item.kind_label || ""} · ${item.points.length} semanas registradas · `
      + `última ${item.week} (${item.date})`
      + (item.pct == null ? "" : ` · ${pct(item.pct)} vs semana anterior`);
    if (H.chart) H.chart.destroy();
    const color = { total: "#f5f5f7", cat: "#ffce6b", stock: "#b388ff",
                    skin: "#6ea8ff", card: "#46d39a" }[item.kind] || "#46d39a";
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
    // Registrar el patrimonio de hoy sin esperar al resumen semanal.
    const rec = $("#histRecordBtn");
    if (rec) rec.addEventListener("click", async () => {
      rec.disabled = true;
      const previo = rec.textContent;
      rec.textContent = "Registrando…";
      try {
        const r = await fetch("/api/prices/record", { method: "POST" });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || "Error");
        await load();
        rec.textContent = j.recorded ? `✓ ${j.recorded} series` : "Sin datos que registrar";
      } catch (e) {
        rec.textContent = "⚠️ " + e.message;
      } finally {
        rec.disabled = false;
        setTimeout(() => { rec.textContent = previo; }, 4000);
      }
    });
  }
  $$('#tabs button[data-tab="historico"]').forEach((b) => b.addEventListener("click", load));

  window.PriceHistory = { load };
  load();
})();
