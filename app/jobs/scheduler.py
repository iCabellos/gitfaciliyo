"""
Programador en proceso (APScheduler) para la versión desplegada.

Se activa con ENABLE_SCHEDULER=1 en una instancia SIEMPRE ACTIVA (no en planes
que se duermen). Programa:
  * Seguimiento de precios: cada día a las 08:07 (Europe/Madrid).
  * Alerta de WhatsApp: cada lunes a las 09:07.

Usa una única instancia con disco persistente para que el histórico se conserve.
"""

import os

_TZ = os.environ.get("SCHEDULER_TZ", "Europe/Madrid")
_started = False


def start_scheduler():
    global _started
    if _started:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        print("APScheduler no instalado; scheduler desactivado.")
        return

    from jobs import track_prices, weekly_whatsapp

    sched = BackgroundScheduler(timezone=_TZ)
    sched.add_job(track_prices.main, CronTrigger(hour=8, minute=7),
                  id="track_prices", replace_existing=True, misfire_grace_time=3600)
    sched.add_job(weekly_whatsapp.main, CronTrigger(day_of_week="mon", hour=9, minute=7),
                  id="weekly_whatsapp", replace_existing=True, misfire_grace_time=3600)
    sched.start()
    _started = True
    print(f"Scheduler activo ({_TZ}): precios diarios 08:07, WhatsApp lunes 09:07.")
