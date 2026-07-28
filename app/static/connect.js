/* ===========================================================================
   Conexiones por API: imagin (PSD2 · Enable Banking) y Trade Republic.
   Además, el registro de valores (nombre y número de títulos) por mes.

   Todo lo que se muestra viene del servidor. Si una fuente no está conectada o
   falla, se dice con su mensaje real; nunca se rellena con datos de ejemplo.
   =========================================================================== */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const eur = (n) => "€" + Number(n).toLocaleString("es-ES",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (n) => Number(n).toLocaleString("es-ES", { maximumFractionDigits: 4 });

  function note(target, message, isError) {
    const el = $(target);
    if (el) el.innerHTML = message
      ? `<p class="${isError ? "warn" : "status"}">${isError ? "⚠️ " : ""}${esc(message)}</p>`
      : "";
  }

  async function api(url, options) {
    const res = await fetch(url, options);
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.error || `Error ${res.status}`);
    return json;
  }

  const postJSON = (url, body) => api(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });

  function busy(button, on) { if (button) button.disabled = on; }

  // =========================================================================
  // imagin (Enable Banking)
  // =========================================================================
  // Consentimiento máximo (en segundos) que admite el banco elegido: se manda
  // al autorizar para no pedir más días de los que ese banco acepta.
  let BANK_MAX_CONSENT = null;

  async function imaginStatus() {
    const chip = $("#imaginState");
    const redirect = $("#imaginRedirect");
    let s;
    try {
      s = await api("/api/imagin/status");
    } catch (e) {
      if (chip) chip.textContent = "sin conectar";
      return;
    }
    // La URL de retorno hay que registrarla en Enable Banking tal cual: es el
    // dato que antes no se veía en ninguna parte.
    if (redirect && s.redirect_url) redirect.value = s.redirect_url;
    if (!chip) return;
    if (s.connected) {
      const accounts = (s.accounts || []).map((a) => a.name || `···${a.iban_end}`).join(", ");
      chip.textContent = "conectado";
      note("#imaginResult", `Autorizado${accounts ? " · " + accounts : ""}`
        + (s.valid_until ? ` · consentimiento hasta ${s.valid_until}` : ""));
    } else {
      chip.textContent = "sin conectar";
    }
  }

  const imaginCopy = $("#imaginCopyRedirect");
  if (imaginCopy) imaginCopy.addEventListener("click", async () => {
    const value = ($("#imaginRedirect") || {}).value || "";
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      note("#imaginResult", "URL de retorno copiada. Pégala en tu aplicación de Enable Banking.");
    } catch (e) {
      // Sin permiso de portapapeles: al menos se deja seleccionada para copiar.
      $("#imaginRedirect").select();
      note("#imaginResult", "Selecciona y copia la URL de retorno (Ctrl+C).", true);
    }
  });

  // ---- lista de bancos: los nombres EXACTOS que reconoce Enable Banking ----
  const imaginBanks = $("#imaginBanksBtn");
  if (imaginBanks) imaginBanks.addEventListener("click", () => loadBanks(true));

  async function loadBanks(verbose) {
    const select = $("#imaginBank");
    if (!select) return;
    if (verbose) note("#imaginResult", "Pidiendo a Enable Banking los bancos de tu país…");
    busy(imaginBanks, true);
    try {
      const r = await api("/api/imagin/banks");
      const selected = (r.selected || {}).name || "";
      select.innerHTML = (r.aspsps || []).map((a) =>
        `<option value="${esc(a.name)}" data-max="${esc(a.maximum_consent_validity || "")}"${
          a.name === selected ? " selected" : ""}>${esc(a.name)}${a.beta ? " (beta)" : ""}</option>`
      ).join("") || `<option value="">Enable Banking no devolvió ningún banco para ${esc(r.country)}</option>`;
      select.disabled = !!r.fixed_by_env;
      rememberMaxConsent(select);
      if (verbose) {
        note("#imaginResult", r.fixed_by_env
          ? `El banco lo fija ENABLE_BANKING_ASPSP en el servidor (${esc(selected)}).`
          : `${(r.aspsps || []).length} bancos en ${esc(r.country)}. Elige el tuyo.`);
      }
    } catch (e) { note("#imaginResult", e.message, true); }
    finally { busy(imaginBanks, false); }
  }

  function rememberMaxConsent(select) {
    const opt = select.selectedOptions[0];
    const max = opt && opt.dataset.max ? Number(opt.dataset.max) : null;
    BANK_MAX_CONSENT = Number.isFinite(max) && max > 0 ? max : null;
  }

  const imaginBank = $("#imaginBank");
  if (imaginBank) imaginBank.addEventListener("change", async (ev) => {
    const name = ev.target.value;
    if (!name) return;
    rememberMaxConsent(ev.target);
    try {
      await postJSON("/api/imagin/bank", { name });
      note("#imaginResult", `Banco guardado: ${name}. Ya puedes pulsar «Autorizar».`);
      if (window.Setup) window.Setup.load();
    } catch (e) { note("#imaginResult", e.message, true); }
  });

  const imaginAuth = $("#imaginAuthBtn");
  if (imaginAuth) imaginAuth.addEventListener("click", async () => {
    busy(imaginAuth, true);
    note("#imaginResult", "Pidiendo la autorización a tu banco…");
    try {
      const r = await postJSON("/api/imagin/auth",
        BANK_MAX_CONSENT ? { maximum_consent_validity: BANK_MAX_CONSENT } : {});
      // Se navega en ESTA pestaña: al volver, el retorno completa la conexión
      // solo. Abrirlo en otra pestaña es lo que obligaba a copiar el «code».
      note("#imaginResult", "Abriendo tu banco para que autorices…");
      window.location.href = r.url;
    } catch (e) {
      note("#imaginResult", e.message, true);
      busy(imaginAuth, false);
    }
  });

  const imaginSession = $("#imaginSessionBtn");
  if (imaginSession) imaginSession.addEventListener("click", async () => {
    const code = $("#imaginCode").value.trim();
    if (!code) { note("#imaginResult", "Pega el code que devuelve imagin al autorizar.", true); return; }
    busy(imaginSession, true);
    note("#imaginResult", "Creando la sesión con tu banco…");
    try {
      const r = await postJSON("/api/imagin/session", { code });
      $("#imaginCode").value = "";
      note("#imaginResult", `Conectado: ${(r.accounts || []).length} cuenta(s).`);
      imaginStatus();
      if (window.Setup) window.Setup.load();
    } catch (e) { note("#imaginResult", e.message, true); }
    finally { busy(imaginSession, false); }
  });

  // ---- vuelta del banco tras el SCA ---------------------------------------
  // /imagin/callback ya ha cambiado el `code` por una sesión y nos manda aquí
  // con el resultado. Si alguien registró la raíz («/») como URL de retorno, el
  // `code` llega aquí sin canjear: se canjea en ese momento.
  async function handleReturn() {
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("imagin");
    const code = params.get("code");
    if (!outcome && !code) return;
    const clean = () => window.history.replaceState({}, "", window.location.pathname);
    // El resultado se pinta dentro de la pestaña de Configuración: si no se
    // abre, el usuario vuelve del banco y no ve nada.
    const tab = $('#tabs button[data-tab="config"]');
    if (tab) tab.click();
    if (outcome === "ok") {
      const n = params.get("accounts");
      note("#imaginResult", `✓ Banco conectado${n ? `: ${n} cuenta(s)` : ""}.`);
      clean(); imaginStatus();
      if (window.Setup) window.Setup.load();
    } else if (outcome === "error") {
      note("#imaginResult", params.get("detail") || "El banco rechazó la autorización.", true);
      clean();
    } else if (code) {
      note("#imaginResult", "Completando la conexión con tu banco…");
      try {
        const r = await postJSON("/api/imagin/session", { code, state: params.get("state") });
        note("#imaginResult", `✓ Banco conectado: ${(r.accounts || []).length} cuenta(s).`);
        imaginStatus();
        if (window.Setup) window.Setup.load();
      } catch (e) { note("#imaginResult", e.message, true); }
      clean();
    }
  }

  const imaginRefresh = $("#imaginRefreshBtn");
  if (imaginRefresh) imaginRefresh.addEventListener("click", async () => {
    busy(imaginRefresh, true);
    note("#imaginResult", "Leyendo saldo y movimientos de imagin…");
    try {
      const data = await postJSON("/api/imagin/refresh");
      note("#imaginResult", "");
      if (typeof window.renderBank === "function") {
        window.renderBank(data, $("#imaginResult"));
      } else {
        note("#imaginResult", `Saldo: ${eur(data.available_balance || 0)} · `
          + `${(data.transactions || []).length} movimientos.`);
      }
    } catch (e) { note("#imaginResult", e.message, true); }
    finally { busy(imaginRefresh, false); }
  });

  // =========================================================================
  // Trade Republic (API no oficial: emparejado + cartera)
  // =========================================================================
  let TR_PROCESS = null;

  async function trStatus() {
    const chip = $("#trApiState");
    if (!chip) return;
    try {
      const s = await api("/api/trade-republic/status");
      chip.textContent = s.paired ? `emparejado (···${s.phone_end || ""})` : "sin emparejar";
    } catch (e) { chip.textContent = "sin emparejar"; }
  }

  const trPair = $("#trPairBtn");
  if (trPair) trPair.addEventListener("click", async () => {
    const phone = $("#trPhone").value.trim(), pin = $("#trPin").value.trim();
    if (!phone || !pin) { note("#trApiResult", "Pon tu teléfono (+34…) y tu PIN.", true); return; }
    busy(trPair, true);
    note("#trApiResult", "Pidiendo el código a Trade Republic…");
    try {
      const r = await postJSON("/api/trade-republic/pair", { phone, pin });
      TR_PROCESS = r.process_id;
      note("#trApiResult", "Código enviado. Escríbelo arriba y pulsa «Emparejar».");
    } catch (e) { note("#trApiResult", e.message, true); }
    finally { busy(trPair, false); }
  });

  const trVerify = $("#trPairVerifyBtn");
  if (trVerify) trVerify.addEventListener("click", async () => {
    const code = $("#trCode").value.trim();
    if (!TR_PROCESS) { note("#trApiResult", "Pide primero el código.", true); return; }
    if (!code) { note("#trApiResult", "Escribe el código que te ha llegado.", true); return; }
    busy(trVerify, true);
    note("#trApiResult", "Registrando este dispositivo en Trade Republic…");
    try {
      await postJSON("/api/trade-republic/pair/verify", {
        process_id: TR_PROCESS, code,
        phone: $("#trPhone").value.trim(), pin: $("#trPin").value.trim(),
      });
      $("#trCode").value = ""; $("#trPin").value = ""; TR_PROCESS = null;
      note("#trApiResult", "Emparejado. Ya puedes traer tu cartera cuando quieras.");
      trStatus();
    } catch (e) { note("#trApiResult", e.message, true); }
    finally { busy(trVerify, false); }
  });

  const trLive = $("#trLiveBtn");
  if (trLive) trLive.addEventListener("click", async () => {
    busy(trLive, true);
    note("#trApiResult", "Leyendo tu cartera en Trade Republic…");
    try {
      const data = await postJSON("/api/trade-republic/live");
      note("#trApiResult", "");
      if (typeof window.renderPositions === "function") {
        window.renderPositions(data, $("#trApiResult"));
      }
      loadHoldings();
    } catch (e) { note("#trApiResult", e.message, true); }
    finally { busy(trLive, false); }
  });

  const trUnpair = $("#trUnpairBtn");
  if (trUnpair) trUnpair.addEventListener("click", async () => {
    if (!confirm("¿Olvidar el emparejado con Trade Republic?")) return;
    try {
      await postJSON("/api/trade-republic/unpair");
      note("#trApiResult", "Dispositivo desemparejado.");
      trStatus();
    } catch (e) { note("#trApiResult", e.message, true); }
  });

  // =========================================================================
  // Registro de valores: nombre y número de títulos
  // =========================================================================
  async function loadHoldings(month) {
    const table = $("#holdTable");
    if (!table) return;
    let data;
    try {
      data = await api("/api/holdings" + (month ? `?month=${encodeURIComponent(month)}` : ""));
    } catch (e) {
      table.innerHTML = `<p class="warn">⚠️ ${esc(e.message)}</p>`;
      return;
    }
    const select = $("#holdMonth");
    if (select) {
      select.innerHTML = (data.months || []).map((m) =>
        `<option value="${esc(m)}"${m === data.month ? " selected" : ""}>${esc(m)}</option>`).join("");
      select.hidden = !(data.months || []).length;
    }
    const pill = $("#holdCount");
    const rows = data.holdings || [];
    if (pill) { pill.hidden = !rows.length; pill.textContent = `${rows.length} valores`; }
    if (!rows.length) {
      table.innerHTML = `<p class="hint">Todavía no hay valores registrados. Conecta
        Trade Republic por API o sube su extracto y quedarán aquí con su nombre y
        número de títulos.</p>`;
      return;
    }
    table.innerHTML = `<table><thead><tr>
        <th>Valor</th><th class="num">Títulos</th><th class="num">Precio ud.</th>
        <th class="num">Valor</th><th>Fuente</th>
      </tr></thead><tbody>${rows.map((h) => `<tr>
        <td>${esc(h.name)}${h.isin ? ` <span class="tag">${esc(h.isin)}</span>` : ""}</td>
        <td class="num">${num(h.quantity)}</td>
        <td class="num muted">${h.unit_value ? eur(h.unit_value) : "—"}</td>
        <td class="num">${eur(h.value)}</td>
        <td class="muted">${esc(h.source)}</td>
      </tr>`).join("")}</tbody>
      <tfoot><tr><td>Total ${esc(data.month || "")}</td>
        <td class="num">${num(data.titles)}</td><td></td>
        <td class="num pos">${eur(data.total)}</td><td></td></tr></tfoot></table>`;
  }

  const holdMonth = $("#holdMonth");
  if (holdMonth) holdMonth.addEventListener("change", (e) => loadHoldings(e.target.value));

  imaginStatus().then(handleReturn);
  trStatus();
  loadHoldings();
  window.Holdings = { load: loadHoldings };
})();
