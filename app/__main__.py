"""Homepage-Agent.

    python -m app            Dienst: Slack-Buttons verarbeiten + Prüfung nach Zeitplan
    python -m app check      Einmal prüfen und Bericht nach Slack schicken
    python -m app dry-run    Einmal prüfen und nur hier ausgeben
    python -m app reset      Eigene Slack-Nachrichten löschen, Status zurücksetzen, neu prüfen
"""
import argparse
import logging
import threading

from . import analyze, provision
from .settings import Settings
from .state import State

log = logging.getLogger("homepage-agent")


def print_report(report):
    print(f"{report.total} Dienste gefunden, {len(report.missing)} fehlen in Homepage\n")
    for c in report.missing:
        ziel = f" → Label {c.target['stack']}/{c.target['service']}" if c.target else ""
        art = "REST " if c.in_homepage else "FEHLT"
        print(f"{art}  {c.name:<22} {c.href or '-':<42} [{c.health.get('verdict', '?')}] Gruppe={c.group}{ziel}")
        print(f"         {c.description}")
        for s in c.health.get("reasons", []):
            print(f"         - {s}")
    for p in report.provisions:
        print(f"NEU    {p['domain']} (Container {p['container']})" + (f"  PROBLEM: {p['problems']}" if p["problems"] else ""))
        for line in provision.describe(p):
            print(f"         {line}")
    for r in report.revisions:
        print(f"ÄNDERN {r['name']} ({r['where']})" + ("" if r["target"] or r["where"] == "services.yaml"
                                                       else "  [nicht automatisch änderbar]"))
        for field, (old, new) in r["changes"].items():
            print(f"         {field}: {old or '–'} → {new}")
    for title, items in (("VERALTET", report.stale), ("CONFIG", report.lint), ("LABEL", report.labels),
                         ("FEHLER", report.errors)):
        for i in items:
            print(f"{title:<8} {i}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Prüft, ob alle Homelab-Dienste in Homepage stehen.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "check", "dry-run", "reset"])
    command = parser.parse_args().command
    settings = Settings.from_env()

    def check():
        return analyze.run(settings, State(settings.data_dir).load()["ignored"])

    if command == "dry-run":
        print_report(check())
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    from . import slack_ui

    # Socket Mode: Slack ruft nicht per HTTP an, daher keine Signaturprüfung (kein Signing Secret nötig)
    app = App(token=settings.slack_bot_token, request_verification_enabled=False)
    slack_ui.register(app, settings)

    def job(force=False):
        try:
            slack_ui.post_report(app.client, settings, check(), force=force)
        except Exception as exc:
            log.exception("Prüfung fehlgeschlagen")
            app.client.chat_postMessage(channel=settings.slack_channel,
                                        text=f":x: Homepage-Check fehlgeschlagen: {exc}")

    if command == "reset":
        print(f"{slack_ui.reset(app.client, settings)} Nachrichten gelöscht, Status zurückgesetzt")
        job(force=True)
        return

    if command == "check":
        job(force=True)
        return

    scheduler = BackgroundScheduler(timezone=settings.tz)
    scheduler.add_job(job, CronTrigger.from_crontab(settings.schedule, timezone=settings.tz),
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Zeitplan: %s (%s)", settings.schedule, settings.tz)
    if settings.run_on_start:
        threading.Thread(target=job, kwargs={"force": True}, daemon=True).start()
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
