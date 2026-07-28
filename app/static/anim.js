/* ===========================================================================
   Capa de animación: GSAP/ScrollTrigger (parallax, reveals, contadores).
   Con failsafes: si algo falla, todo queda visible.

   Sin scroll «suave» por JavaScript (antes, Lenis): interceptaba la rueda y
   repintaba la página durante ~1,15 s en cada gesto, así que cualquier
   fotograma lento se arrastraba durante todo ese tiempo y el scroll se sentía
   pegajoso. El scroll nativo del navegador ya va a la tasa de refresco de la
   pantalla y no compite con el resto de la página.
   =========================================================================== */
(function () {
  "use strict";

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hasGSAP = typeof window.gsap !== "undefined";

  // Failsafe global: pase lo que pase, nada se queda invisible.
  function showAll() { document.querySelectorAll(".reveal").forEach((el) => (el.style.opacity = "1")); }
  if (!hasGSAP || reduce) { showAll(); }
  setTimeout(() => { document.querySelectorAll(".reveal").forEach((el) => {
    if (getComputedStyle(el).opacity === "0") el.style.opacity = "1"; }); }, 2600);

  if (!hasGSAP || reduce) { exposeFX(false); return; }

  try {
    gsap.registerPlugin(ScrollTrigger);

    // ---- Parallax del fondo (aurora) ----
    const par = [["blob-a", -120], ["blob-b", 180], ["blob-c", -220], ["grid", 90]];
    par.forEach(([cls, dist]) => {
      const el = document.querySelector("." + cls);
      if (el) gsap.to(el, { y: dist, ease: "none",
        scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 0.6 } });
    });

    // ---- Hero: parallax + desvanecido al hacer scroll ----
    gsap.to(".hero-inner", { yPercent: 16, opacity: 0.35, ease: "none",
      scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });

    // ---- Reveal al entrar en viewport ----
    gsap.utils.toArray(".reveal").forEach((el) => {
      gsap.fromTo(el, { y: 42, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.95, ease: "power3.out",
          scrollTrigger: { trigger: el, start: "top 88%", once: true } });
    });

    // ---- Resplandor que sigue al cursor en los paneles ----
    // Una sola actualización por fotograma: antes se medía el panel
    // (`getBoundingClientRect`, que fuerza un cálculo de maquetado) y se
    // repintaba un degradado grande en CADA evento del ratón, que llegan
    // muchos más que fotogramas hay.
    let glowCard = null, glowX = 0, glowY = 0, glowPending = false;
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest(".glass");
      if (!card) return;
      glowCard = card; glowX = e.clientX; glowY = e.clientY;
      if (glowPending) return;
      glowPending = true;
      requestAnimationFrame(() => {
        glowPending = false;
        if (!glowCard) return;
        const r = glowCard.getBoundingClientRect();
        glowCard.style.setProperty("--mx", (glowX - r.left) + "px");
        glowCard.style.setProperty("--my", (glowY - r.top) + "px");
      });
    }, { passive: true });

    // ---- Transición al cambiar de pestaña ----
    document.querySelectorAll("#tabs button").forEach((b) => {
      b.addEventListener("click", () => {
        const pane = document.querySelector(".tabpane.active");
        if (pane) gsap.fromTo(pane, { y: 22, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.55, ease: "power3.out", clearProps: "transform" });
        ScrollTrigger.refresh();
      });
    });

    exposeFX(true);
  } catch (err) {
    console.warn("anim.js:", err);
    showAll();
    exposeFX(false);
  }

  // -------------------------------------------------------------------------
  // API que app.js invoca tras renderizar (contadores + reveal de filas).
  // -------------------------------------------------------------------------
  function exposeFX(animated) {
    const counted = new Set();

    function parseNum(txt) {
      const m = txt.match(/-?\s*[€$]?\s*[\d.]*\d(?:,\d+)?/);
      if (!m) return null;
      const neg = /-/.test(m[0]);
      const n = parseFloat(m[0].replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", "."));
      return isNaN(n) ? null : (neg ? -Math.abs(n) : n);
    }
    function fmt(v, sym) {
      return (v < 0 ? "-" : "") + sym +
        Math.abs(v).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    window.AppFX = {
      onRender(scope) {
        if (!scope || !animated) return;
        const key = scope.id || "_";
        // Contadores: solo la primera vez por contenedor (evita recuentos al editar).
        if (!counted.has(key)) {
          counted.add(key);
          scope.querySelectorAll(".val").forEach((el) => {
            const target = parseNum(el.textContent);
            if (target === null) return;
            const sym = (el.textContent.match(/[€$]/) || [""])[0];
            const o = { v: 0 };
            gsap.to(o, { v: target, duration: 1.1, ease: "power2.out",
              onUpdate() { el.textContent = fmt(o.v, sym); } });
          });
        }
        // Filas y KPIs: entrada escalonada cada vez que se renderiza.
        const items = scope.querySelectorAll("tbody tr, .kpi");
        if (items.length) gsap.fromTo(items, { y: 16, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.5, ease: "power2.out", stagger: 0.035, clearProps: "transform" });
        // Barras de porcentaje: crecen desde 0.
        scope.querySelectorAll(".bar > span").forEach((s) => {
          const w = s.style.width; gsap.fromTo(s, { width: 0 }, { width: w, duration: 0.9, ease: "power3.out" });
        });
      },
    };
  }
})();
