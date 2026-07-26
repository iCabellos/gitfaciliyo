"""
Alerta SEMANAL por WhatsApp: cartas/skins que se han movido ≥5% en la semana.

Ejecuta una vez por semana (cron). Compara el precio de hoy con el de hace una
semana (histórico de `sources/prices.py`) y avisa de todo lo que se haya movido
al menos el umbral, EN LOS DOS SENTIDOS: sube y baja interesan igual. Cada línea
lleva el elemento, su precio anterior y el actual.

Envío por CallMeBot (gratis) o Twilio; si no hay credenciales, imprime el
mensaje (modo simulación) para poder probar sin enviar nada.

Variables de entorno necesarias para enviar de verdad:
    CALLMEBOT_APIKEY / CALLMEBOT_PHONE      vía gratuita recomendada
    TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN  alternativa
    TWILIO_WHATSAPP_FROM / ALERT_WHATSAPP_TO
Opcional:
    ALERT_THRESHOLD          umbral en % (por defecto 5)
"""

import base64
import datetime
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from sources import prices, patrimonio  # noqa: E402

DATA_DIR = prices.DATA_DIR
HISTORY = prices.HISTORY_FILE
THRESHOLD = prices.THRESHOLD


def weekly_movers(history=None, threshold=THRESHOLD, days=prices.WINDOW_DAYS):
    """Elementos que se han movido ≥ umbral en la semana (subidas y bajadas)."""
    return prices.movers(prices.history() if history is None else history,
                         threshold=threshold, window=days)


def compose_message(movers, threshold=THRESHOLD, coverage=None):
    """Mensaje de la alerta. Si el histórico está vacío o parado, lo dice."""
    today = datetime.date.today().strftime("%d/%m/%Y")
    lines = [f"📊 *Precios de la semana* ({today})", ""]
    lines.extend(patrimonio.movers_lines(movers, threshold))
    for warning in coverage_warnings(coverage or {}):
        lines.append(f"\n⚠️ {warning}")
    lines.append("")
    lines.append("Mi patrimonio · alerta automática")
    return "\n".join(lines)


def coverage_warnings(cov):
    """Avisos cuando el seguimiento diario no está registrando precios.

    Un histórico vacío o congelado es la causa de que el resumen repita cifras;
    debe verse en el mensaje, no quedarse en los logs del cron.
    """
    if not cov or not cov.get("days"):
        return ["Sin histórico de precios: el seguimiento diario no está "
                "registrando nada (revisa STEAM_ID64 y tu lista de Magic)."]
    stale = cov.get("stale_days")
    if stale is not None and stale > 2:
        return [f"El último precio registrado es del {cov['last_day']} "
                f"(hace {stale} días): el seguimiento diario está parado."]
    return []


def send_whatsapp(body):
    """Envía por WhatsApp. Prioriza CallMeBot (gratis); si no, Twilio; si no, simula."""
    # 1) CallMeBot — gratuito para uso personal.
    apikey = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    phone = "".join(ch for ch in os.environ.get("CALLMEBOT_PHONE", "") if ch.isdigit())
    if apikey and phone:
        url = ("https://api.callmebot.com/whatsapp.php?"
               + urllib.parse.urlencode({"phone": phone, "apikey": apikey, "text": body}))
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                print(f"WhatsApp enviado por CallMeBot (HTTP {resp.status}).")
            return True
        except Exception as exc:  # noqa: BLE001
            print("CallMeBot falló, intento otra vía:", exc)

    # 2) Twilio.
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    sender = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
    to = os.environ.get("ALERT_WHATSAPP_TO", "").strip()
    if all([sid, token, sender, to]):
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = urllib.parse.urlencode({"From": sender, "To": to, "Body": body}).encode()
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": "Basic " + auth,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"WhatsApp enviado por Twilio (HTTP {resp.status}).")
        return True

    # 3) Sin credenciales: modo simulación.
    print("[simulación] Sin credenciales de WhatsApp; no se envía. Mensaje:\n")
    print(body)
    return False


def main():
    history = prices.history()
    cov = prices.coverage(history)
    movers = weekly_movers(history)
    warnings = coverage_warnings(cov)
    # Sin movimientos ni avisos no se envía nada (evita ruido); ALERT_SEND_EMPTY=1
    # lo fuerza. Un aviso de seguimiento parado SÍ se envía siempre: es el caso
    # en el que callar significaría repetir cifras viejas sin explicación.
    if not movers and not warnings and os.environ.get("ALERT_SEND_EMPTY", "0") != "1":
        print(f"Sin movimientos ≥{THRESHOLD:g}% esta semana; no se envía WhatsApp.")
        return movers
    send_whatsapp(compose_message(movers, THRESHOLD, cov))
    return movers


if __name__ == "__main__":
    main()
