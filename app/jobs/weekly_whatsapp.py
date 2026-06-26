"""
Alerta SEMANAL por WhatsApp: cartas/skins que han subido >10% algún día de la semana.

Ejecuta una vez por semana (cron). Lee data/price_history.json, calcula la
variación día a día de los últimos 7 días y avisa de los artículos cuya subida
diaria máxima superó el umbral (10% por defecto).

Envío por Twilio WhatsApp (si hay credenciales en variables de entorno); si no,
imprime el mensaje (modo simulación) para que puedas probar sin enviar nada.

Variables de entorno necesarias para enviar de verdad:
    TWILIO_ACCOUNT_SID       SID de la cuenta de Twilio
    TWILIO_AUTH_TOKEN        token de autenticación
    TWILIO_WHATSAPP_FROM     remitente, p. ej. 'whatsapp:+14155238886' (sandbox)
    ALERT_WHATSAPP_TO        destino, p. ej. 'whatsapp:+34640253466'
Opcional:
    ALERT_THRESHOLD          umbral en % (por defecto 10)
"""

import base64
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(HERE, "data")
HISTORY = os.path.join(DATA_DIR, "price_history.json")
THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "10"))


def _read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def weekly_gainers(history, threshold=THRESHOLD, days=7):
    """Artículos con una subida diaria > umbral en los últimos `days` días.

    Devuelve [{key, name, kind, pct, day, price_from, price_to}] ordenado desc.
    """
    dates = sorted(history.keys())
    if len(dates) < 2:
        return []
    window = dates[-(days + 1):]          # incluye el día previo para comparar
    gainers = {}
    for prev, cur in zip(window, window[1:]):
        a, b = history.get(prev, {}), history.get(cur, {})
        for key, price in b.items():
            old = a.get(key)
            if not old or old <= 0 or price is None:
                continue
            pct = (price - old) / old * 100
            if pct > threshold and pct > gainers.get(key, {"pct": 0})["pct"]:
                kind, _, name = key.partition(":")
                gainers[key] = {"key": key, "name": name, "kind": kind,
                                "pct": pct, "day": cur, "price_from": old, "price_to": price}
    return sorted(gainers.values(), key=lambda g: -g["pct"])


def compose_message(gainers, threshold=THRESHOLD):
    today = datetime.date.today().strftime("%d/%m/%Y")
    if not gainers:
        return f"📊 Resumen semanal ({today}): ninguna carta o skin subió más del {threshold:.0f}% esta semana."
    lines = [f"📈 *Subidas >{threshold:.0f}% esta semana* ({today})", ""]
    icon = {"card": "🃏", "skin": "🔫"}
    for g in gainers:
        lines.append(f"{icon.get(g['kind'], '•')} {g['name']}\n"
                     f"   +{g['pct']:.1f}% el {g['day']}  "
                     f"(€{g['price_from']:.2f} → €{g['price_to']:.2f})")
    lines.append("")
    lines.append("Mi patrimonio · alerta automática")
    return "\n".join(lines)


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
    history = _read(HISTORY, {})
    gainers = weekly_gainers(history)
    # Por defecto no se envía si no hay subidas (evita ruido). ALERT_SEND_EMPTY=1 lo fuerza.
    if not gainers and os.environ.get("ALERT_SEND_EMPTY", "0") != "1":
        print("Sin subidas >umbral esta semana; no se envía WhatsApp.")
        return gainers
    send_whatsapp(compose_message(gainers))
    return gainers


if __name__ == "__main__":
    main()
