# Preferencias de trabajo (iCabellos)

## Flujo de PRs
- **Fusiona tú solo (autónomo).** No esperes aprobación para mergear: crea la rama,
  commitea, abre el PR, espera CI en verde y **haz el merge tú mismo**. No preguntes
  "¿lo fusiono?".

## Estilo de código — REGLA DURA
- **Nunca inventes nada.** El código siempre ha de ser **real**: APIs reales, datos
  reales, integraciones reales.
- **Nunca mocks, nunca datos fake, nunca fallbacks a datos de ejemplo.**
- El código **puede fallar y no pasa nada**: si falla, se soluciona. Prefiero un fallo
  real y visible antes que un fallback que oculte el problema o muestre datos que no
  son míos.
- (Los mocks/monkeypatch en la carpeta de tests SÍ son válidos: son pruebas, no el
  camino de ejecución real.)
