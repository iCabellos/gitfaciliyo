/* ===========================================================================
   Capa de animación: Lenis (scroll suave) + GSAP/ScrollTrigger (parallax,
   reveals, contadores). Con failsafes: si algo falla, todo queda visible.
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

    // ---- Lenis: scroll con inercia, sincronizado con ScrollTrigger ----
    let lenis = null;
    if (typeof window.Lenis !== "undefined") {
      lenis = new Lenis({ duration: 1.15, smoothWheel: true,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)) });
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add((t) => lenis.raf(t * 1000));
      gsap.ticker.lagSmoothing(0);
    }

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
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest(".glass");
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - r.left) + "px");
      card.style.setProperty("--my", (e.clientY - r.top) + "px");
    });

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
