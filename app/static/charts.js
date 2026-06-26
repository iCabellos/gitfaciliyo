/* ===========================================================================
   Vista de gráficos (Chart.js): tarta del patrimonio + histórico mensual.
   =========================================================================== */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return;

  const PALETTE = ["#7c5cff", "#34e0c4", "#45c0ff", "#ff6b9d", "#ffce6b", "#43d39e", "#b388ff", "#ff9f6b"];
  const GRID = "rgba(255,255,255,.08)";
  const TICK = "#9aa6c9";
  const eur = (n) => "€" + Number(n).toLocaleString("es-ES", { maximumFractionDigits: 0 });

  Chart.defaults.color = TICK;
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.animation = { duration: 900, easing: "easeOutQuart" };

  let pie = null, total = null;
  const minis = {};

  function color(i) { return PALETTE[i % PALETTE.length]; }

  // ---- Tarta del patrimonio (datos en vivo de CONTRIB) ----
  function refreshPie(contrib) {
    const entries = Object.entries(contrib || {}).filter(([, v]) => v > 0);
    const empty = document.getElementById("pieEmpty");
    if (!entries.length) { if (empty) empty.style.display = "block"; if (pie) { pie.destroy(); pie = null; } return; }
    if (empty) empty.style.display = "none";
    const labels = entries.map((e) => e[0]);
    const data = entries.map((e) => e[1]);
    const colors = labels.map((_, i) => color(i));
    if (pie) {
      pie.data.labels = labels; pie.data.datasets[0].data = data;
      pie.data.datasets[0].backgroundColor = colors; pie.update();
      return;
    }
    pie = new Chart(document.getElementById("pieChart"), {
      type: "doughnut",
      data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: "rgba(7,10,22,.7)", borderWidth: 3, hoverOffset: 8 }] },
      options: {
        cutout: "62%", responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, padding: 14, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const t = c.dataset.data.reduce((a, b) => a + b, 0);
                return ` ${c.label}: ${eur(c.parsed)} (${(c.parsed / t * 100).toFixed(1)}%)`;
              },
            },
          },
        },
      },
    });
  }

  // ---- Histórico mensual (snapshots del servidor) ----
  async function refresh() {
    let snaps = {};
    try { snaps = await (await fetch("/api/snapshots")).json(); } catch (e) { return; }
    const months = Object.keys(snaps).sort();
    const monthlyEmpty = document.getElementById("monthlyEmpty");
    if (!months.length) { if (monthlyEmpty) monthlyEmpty.style.display = "block"; return; }
    if (monthlyEmpty) monthlyEmpty.style.display = "none";

    const cats = [...new Set(months.flatMap((m) => Object.keys(snaps[m])))];
    const series = (cat) => months.map((m) => snaps[m][cat] || 0);
    const totals = months.map((m) => Object.values(snaps[m]).reduce((a, b) => a + b, 0));

    // Total por mes: barras apiladas por categoría + línea de total.
    const datasets = cats.map((cat, i) => ({
      label: cat, data: series(cat), backgroundColor: color(i), borderRadius: 6, stack: "s",
    }));
    datasets.push({
      type: "line", label: "Total", data: totals, borderColor: "#eef1fb", borderWidth: 2,
      pointBackgroundColor: "#eef1fb", pointRadius: 4, tension: 0.35, fill: false, stack: "_t",
    });
    if (total) total.destroy();
    total = new Chart(document.getElementById("totalChart"), {
      type: "bar",
      data: { labels: months, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { color: GRID }, ticks: { color: TICK } },
          y: { stacked: true, grid: { color: GRID }, ticks: { color: TICK, callback: (v) => eur(v) } },
        },
        plugins: {
          legend: { labels: { boxWidth: 12, usePointStyle: true } },
          tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${eur(c.parsed.y)}` } },
        },
      },
    });

    // Mini-gráficas: una línea por categoría (evolución).
    const wrap = document.getElementById("miniCharts");
    wrap.innerHTML = "";
    cats.forEach((cat, i) => {
      const card = document.createElement("div");
      card.className = "mini-card";
      const last = series(cat).at(-1);
      card.innerHTML = `<div class="mini-head"><span>${cat}</span><b>${eur(last)}</b></div><canvas></canvas>`;
      wrap.appendChild(card);
      const cv = card.querySelector("canvas");
      if (minis[cat]) minis[cat].destroy();
      minis[cat] = new Chart(cv, {
        type: "line",
        data: { labels: months, datasets: [{ data: series(cat), borderColor: color(i),
          backgroundColor: color(i) + "33", borderWidth: 2, pointRadius: 3, tension: 0.35, fill: true }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => " " + eur(c.parsed.y) } } },
          scales: { x: { display: false }, y: { display: false } },
        },
      });
    });
  }

  window.Charts = { refresh, refreshPie };

  // Refresca al abrir la pestaña de gráficos.
  document.querySelectorAll('#tabs button[data-tab="graficos"]').forEach((b) =>
    b.addEventListener("click", () => { refresh(); refreshPie(window.CONTRIB || {}); }));
  // Primera carga.
  refresh();
})();
