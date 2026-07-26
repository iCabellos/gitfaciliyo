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
  async function imaginStatus() {
    const chip = $("#imaginState");
    if (!chip) return;
    try {
      const s = await api("/api/imagin/status");
      if (s.connected) {
        const accounts = (s.accounts || []).map((a) => a.name || `···${a.iban_end}`).join(", ");
        chip.textContent = "conectado";
        note("#imaginResult", `Autorizado${accounts ? " · " + accounts : ""}`
          + (s.valid_until ? ` · consentimiento hasta ${s.valid_until}` : ""));
      } else {
        chip.textContent = "sin conectar";
      }
    } catch (e) {
      chip.textContent = "sin conectar";
    }
  }

  const imaginAuth = $("#imaginAuthBtn");
  if (imaginAuth) imaginAuth.addEventListener("click", async () => {
    busy(imaginAuth, true);
    note("#imaginResult", "Pidiendo la autorización a imagin…");
    try {
      const r = await postJSON("/api/imagin/auth");
      note("#imaginResult", `Abre esta URL, autoriza en imagin y pega aquí el "code" del retorno.`);
      window.open(r.url, "_blank", "noopener");
    } catch (e) { note("#imaginResult", e.message, true); }
    finally { busy(imaginAuth, false); }
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
    } catch (e) { note("#imaginResult", e.message, true); }
    finally { busy(imaginSession, false); }
  });

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

  imaginStatus();
  trStatus();
  loadHoldings();
  window.Holdings = { load: loadHoldings };
})();
