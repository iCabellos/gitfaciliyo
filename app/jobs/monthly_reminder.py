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
    return (
        f"🗓️ *Recordatorio mensual ({mes})*\n\n"
        "Adjúntame los informes de este mes para actualizar tu patrimonio:\n"
        "🏦 Extracto del banco (PDF)\n"
        "📈 Trade Republic — patrimonio neto (PDF)\n"
        "🪙 Nexo — balances (CSV/PDF)\n\n"
        "Puedes *enviarme los PDF aquí mismo por WhatsApp* y los proceso al momento. 📎\n"
        "Mi patrimonio · recordatorio automático"
    )


def main():
    return send_whatsapp(compose_message())


if __name__ == "__main__":
    main()
