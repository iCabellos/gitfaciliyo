# Preferencias de trabajo (iCabellos)

## Flujo de PRs
- **Mergea SIEMPRE tú solo (autónomo).** No esperes aprobación para mergear: crea la
  rama, commitea, abre el PR, espera CI en verde y **haz el merge tú mismo, siempre**.
  Nunca preguntes "¿lo fusiono?".

## Cierre de cada tarea — DÉJAMELO FÁCIL
Después de mergear, termina SIEMPRE con el bloque de despliegue. Yo solo quiero
pinchar y darle a un botón, no buscar nada:

1. **La URL del deploy, pinchable**, para darle yo:
   `https://dashboard.render.com/` → servicio **mi-patrimonio** (blueprint en
   `render.yaml`, `autoDeploy: true`).
2. **Los pasos numerados y cortos**, en el orden exacto en que hay que hacerlos.
3. **Qué debo ver cuando funcione** (cómo sé que ha salido bien), y el enlace a
   la app: <https://mi-patrimonio.onrender.com>.
4. **Si hace falta configurar algo en Render** (variables de entorno) o en los
   secrets del repo, dime el nombre exacto de cada variable y dónde se pega.
5. Comprueba antes la versión desplegada (`/api/version`) contra la de `master`,
   y dime si el deploy está pendiente o ya al día.

Nada de "revisa el autodeploy": dame el enlace concreto y los clics.

## Estilo de código — REGLA DURA
- **Nunca inventes nada.** El código siempre ha de ser **real**: APIs reales, datos
  reales, integraciones reales.
- **Nunca mocks, nunca datos fake, nunca fallbacks a datos de ejemplo.**
- El código **puede fallar y no pasa nada**: si falla, se soluciona. Prefiero un fallo
  real y visible antes que un fallback que oculte el problema o muestre datos que no
  son míos.
- (Los mocks/monkeypatch en la carpeta de tests SÍ son válidos: son pruebas, no el
  camino de ejecución real.)
