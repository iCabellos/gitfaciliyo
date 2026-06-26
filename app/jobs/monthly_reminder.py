"""
Recordatorio MENSUAL por WhatsApp: avisa de adjuntar los PDFs del mes.

Se ejecuta a principios de mes (cron). Recuerda enviar los extractos del banco,
Trade Republic y Nexo — y que puedes mandarlos directamente por WhatsApp como
adjunto (el webhook los procesa y actualiza tu patrimonio).
"""

import datetime
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from jobs.weekly_whatsapp import send_whatsapp   # noqa: E402


def compose_message():
    mes = datetime.date.today().strftime("%m/%Y")
    panel = os.environ.get("APP_URL", "").strip()
    donde = (f"Súbelos en el panel: {panel}" if panel
             else "Súbelos en el panel web (o por WhatsApp si tienes el intake de Twilio activado).")
    return (
        f"🗓️ *Recordatorio mensual ({mes})*\n\n"
        "Adjunta los informes de este mes para actualizar tu patrimonio:\n"
        "🏦 Extracto del banco (PDF)\n"
        "📈 Trade Republic — patrimonio neto (PDF)\n"
        "🪙 Nexo — balances (CSV/PDF)\n\n"
        f"📎 {donde}\n"
        "Mi patrimonio · recordatorio automático"
    )


def main():
    return send_whatsapp(compose_message())


if __name__ == "__main__":
    main()
