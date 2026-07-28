/* ===========================================================================
   Menú de Configuración: qué falta para que cada fuente se actualice sola.

   Los controles de cada tarjeta ya están en el HTML (los maneja connect.js);
   aquí solo se pinta el ESTADO real que devuelve /api/setup: la insignia, el
   resumen, los pasos hechos/pendientes y las variables que faltan en el
   servidor. Nada se da por hecho: si el backend dice que falta algo, se dice.
   =========================================================================== */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---- navegación entre pestañas desde cualquier enlace -------------------
  function goTo(tab) {
    const btn = $(`#tabs button[data-tab="${tab}"]`);
    if (btn) { btn.click(); btn.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  }
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-goto]");
    if (!el) return;
    ev.preventDefault();
    goTo(el.dataset.goto);
  });

  // ---- pintar el estado ---------------------------------------------------
  function renderCard(source) {
    const card = $("#card-" + source.id);
    if (!card) return;

    // Tres estados distintos, porque se arreglan de forma distinta:
    //   conectado + entra solo   -> listo del todo
    //   conectado, sin auto      -> funciona a mano, pero no se actualiza solo
    //   sin conectar             -> o puedes hacerlo aquí, o falta el servidor
    const listo = source.connected && source.auto_ready !== false;
    const badge = $(".setup-badge", card);
    badge.textContent = listo ? "✓ Conectado"
      : source.connected ? "Solo a mano"
      : source.server_ready ? "Falta conectar" : "Falta en el servidor";
    badge.className = "setup-badge " + (listo ? "ok" : source.server_ready ? "warn-b" : "off");
    card.classList.toggle("is-ready", listo);

    $(".setup-summary", card).textContent = source.summary || "";

    $(".setup-steps", card).innerHTML = (source.steps || []).map((s) =>
      `<li class="${s.done ? "done" : ""}">
         <span class="step-mark">${s.done ? "✓" : "•"}</span>
         <span>${esc(s.text)}</span>
       </li>`).join("");

    const missing = $(".setup-missing", card);
    const vars = (source.missing_env || []).map((v) => `<code>${esc(v)}</code>`).join(", ");
    missing.innerHTML = vars
      ? `<p class="warn">⚠️ Falta definir en el servidor (Render → Environment): ${vars}.
         ${source.server_ready
            ? "Puedes conectarlo aquí igualmente, pero el resumen semanal no podrá actualizarlo solo."
            : "Sin eso no se puede ni empezar."}</p>`
      : "";

    const note = $(".setup-note", card);
    note.textContent = source.note || "";
    note.hidden = !source.note;

    // El detalle público sí se muestra: es lo que te confirma que es LO TUYO.
    const d = source.detail || {};
    if (source.id === "steam" && d.steamid) {
      const input = $("#setupSteamId");
      if (input && !input.value) input.value = d.steamid;
    }
    if (source.id === "imagin" && d.valid_until) {
      note.textContent = `Consentimiento válido hasta ${d.valid_until}. ` + (source.note || "");
      note.hidden = false;
    }
  }

  function renderEnvironment(env, pending) {
    const caida = env.db_ok === false;
    $("#setupEnv").innerHTML = [
      ["Fuentes conectadas", `${4 - pending.length} de 4`],
      ["Base de datos", caida ? "no responde" : env.db,
       caida ? "revisa el aviso de abajo" : env.db_shared ? "compartida" : "solo local"],
      ["Aviso por WhatsApp", env.whatsapp ? "configurado" : "sin configurar"],
      ["Resumen protegido", env.summary_token ? "con token" : "sin token"],
    ].map(([l, v, sub]) =>
      `<div class="m-stat"><span class="m-stat-l">${esc(l)}</span>
       <span class="m-stat-v">${esc(v)}</span>
       ${sub ? `<span class="m-stat-s">${esc(sub)}</span>` : ""}</div>`).join("");

    const avisos = [];
    // Primero lo que rompe todo lo demás: sin base de datos no hay patrimonio,
    // ni ajustes, ni histórico. Antes esto salía como «postgresql · compartida».
    if (caida) {
      avisos.push(`<b>La base de datos no responde</b>, así que ni el patrimonio ni
        los ajustes se pueden leer ni guardar. Motivo que devuelve el servidor:
        <code>${esc(env.db_error || "sin detalle")}</code>.
        Si era la Postgres gratuita de Render: caduca a los 30 días y deja de
        aceptar conexiones. Crea una en <a href="https://neon.com" target="_blank"
        rel="noopener">Neon</a> (gratis, sin caducidad) y pega su cadena en
        <code>DATABASE_URL</code>.`);
    } else if (!env.db_shared) {
      avisos.push(`La base de datos es local (SQLite). En el servidor define
        <code>DATABASE_URL</code> o perderás el histórico en cada reinicio.`);
    }
    if (!env.whatsapp) {
      avisos.push(`Sin credenciales de WhatsApp: el resumen semanal se calcula pero
        no se envía. Define <code>CALLMEBOT_APIKEY</code> y <code>CALLMEBOT_PHONE</code>.`);
    }
    $("#setupEnvWarn").innerHTML = avisos.map((a) => `<p class="warn">⚠️ ${a}</p>`).join("");

    const pill = $("#setupPending");
    if (pill) { pill.hidden = !pending.length; pill.textContent = String(pending.length); }
  }

  async function load() {
    let data;
    try {
      const res = await fetch("/api/setup");
      data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error");
    } catch (e) {
      $("#setupEnvWarn").innerHTML =
        `<p class="warn">⚠️ No pude leer el estado de configuración: ${esc(e.message)}</p>`;
      return;
    }
    (data.sources || []).forEach(renderCard);
    renderEnvironment(data.environment || {}, data.pending || []);
  }

  // ---- Steam: guardar y comprobar ----------------------------------------
  function note(msg, err) {
    $("#setupSteamResult").innerHTML = msg
      ? `<p class="${err ? "warn" : "status"}">${err ? "⚠️ " : ""}${esc(msg)}</p>` : "";
  }

  const save = $("#setupSteamSave");
  if (save) save.addEventListener("click", async () => {
    const steamid = $("#setupSteamId").value.trim();
    save.disabled = true;
    note("Guardando…");
    try {
      const res = await fetch("/api/setup/steam", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ steamid }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || "Error");
      $("#setupSteamId").value = j.steamid;
      note(`Guardado: ${j.steamid}. Pulsa «Comprobar inventario» para verificarlo.`);
      load();
    } catch (e) { note(e.message, true); }
    finally { save.disabled = false; }
  });

  const check = $("#setupSteamCheck");
  if (check) check.addEventListener("click", async () => {
    check.disabled = true;
    note("Leyendo tu inventario y valorándolo en el Steam Market (puede tardar)…");
    try {
      const res = await fetch("/api/steam");
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || "Error");
      const conPrecio = (j.positions || []).filter((p) => p.unit_value).length;
      note(`✓ ${(j.positions || []).length} objetos, ${conPrecio} con precio. `
           + `Valor total: ${Number(j.total).toLocaleString("es-ES",
             { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €.`);
    } catch (e) { note(e.message, true); }
    finally { check.disabled = false; }
  });

  $$('#tabs button[data-tab="config"]').forEach((b) => b.addEventListener("click", load));

  window.Setup = { load };
  load();
})();
