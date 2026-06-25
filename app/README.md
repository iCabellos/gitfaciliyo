# Desglose de gastos desde PDF

App web para subir un extracto bancario en **PDF** y obtener el **gasto neto
desglosado por categorías**, aplicando reglas pensadas para que el número final
refleje el gasto real:

- 🟢 **Las inversiones no son gastos.** Los cargos de **Nexo** se clasifican como
  *Inversión* y se excluyen del total de gastos.
- 🔁 **Bizums recibidos = posibles devoluciones.** Si te devuelven dinero por una
  compra (p. ej. tu parte de una cena), ese bizum **resta del gasto** en lugar de
  contar como ingreso.
- 🍽️ **Gasto neto.** Si una cena costó 30 € y te hacen dos bizums de 10 €, el gasto
  de restaurante es **10 €**, no 30 €.

La app detecta automáticamente bizums recurrentes del mismo importe (probable
ingreso real, no devolución) y propone a qué gasto ligar cada bizum recibido.
**Tú revisas y ajustas** cada enlace con un desplegable, y los totales se
recalculan al instante.

## Ejecutar

```bash
cd app
pip install -r requirements.txt
python app.py
# abre http://127.0.0.1:5000
```

Sube el PDF, revisa los enlaces bizum → gasto en la sección *«Bizums recibidos»*
y consulta el desglose en *«Gasto neto por categoría»*.

## Cómo funciona

| Fichero | Responsabilidad |
|---|---|
| `parser.py` | Parseo del PDF por coordenadas (robusto frente al orden del texto), categorización por reglas y sugerencia automática de devoluciones bizum → gasto. |
| `app.py` | Servidor Flask: sirve la página y expone `POST /api/analyze`. |
| `templates/index.html` + `static/` | Interfaz: carga del PDF, tarjetas resumen, tabla por categoría, enlace interactivo de bizums y listado de movimientos. |

### Reglas de categorización

Las categorías se definen en `RULES` (en `parser.py`) como pares
*patrón → categoría → tipo*. El `tipo` determina cómo cuenta cada movimiento:

- `expense` — gasto normal (cuenta para el total).
- `investment` — inversión (Nexo): **no** es gasto.
- `bizum_in` — bizum recibido (posible devolución).
- `bizum_out` — bizum enviado (salida de dinero).
- `income` — ingreso real (nómina, transferencias a favor).

Para añadir comercios o ajustar categorías, edita la lista `RULES`.

## Notas

- El extracto de ejemplo no incluye el emisor del bizum, así que el enlace
  bizum → gasto es una **sugerencia heurística** (por cercanía de fecha e importe
  y categoría compartible). Por eso la decisión final es manual.
- Probado con extractos cuyo formato de tabla es *Concepto · Fecha · Importe · Saldo*.
