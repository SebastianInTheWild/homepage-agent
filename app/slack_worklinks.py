"""Slack: Links aus dem Arbeits-Channel in die zweite Homepage-Instanz übernehmen.

Neue Nachricht mit Links → sofort eintragen, Ergebnis als Thread-Antwort mit „Anpassen …“ und „Entfernen“.
"""
import json
import logging
import uuid

from . import homepage, worklinks
from .state import LOCK

log = logging.getLogger(__name__)
IGNORED_SUBTYPES = {"bot_message", "message_changed", "message_deleted", "channel_join", "channel_leave",
                    "channel_topic", "channel_purpose", "thread_broadcast"}


def _pt(text):
    return {"type": "plain_text", "text": text[:75]}


class Store:
    """Eingetragene Links mit ihrer Slack-Antwort, damit die Buttons sie wiederfinden."""

    def __init__(self, data_dir):
        self.path = data_dir / "worklinks.json"

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def _blocks(entry, status):
    text = (f"{status}\n*{entry['name']}* · Gruppe *{entry['group']}*\n<{entry['href']}>"
            + (f"\n_{entry['description']}_" if entry.get("description") else ""))
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if not entry.get("removed"):
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "action_id": "wl_edit", "text": _pt("Anpassen …"), "value": entry["id"]},
            {"type": "button", "action_id": "wl_remove", "text": _pt("Entfernen"), "value": entry["id"],
             "style": "danger"},
        ]})
    return blocks


def _cfg(entry):
    return {"href": entry["href"], "description": entry.get("description"), "icon": entry.get("icon")}


def register(app, settings):
    config_dir, backups = settings.work_config_dir, settings.data_dir / "backups-work"
    store = Store(settings.data_dir)

    def post(client, channel, thread_ts, entry, status):
        resp = client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=f"{status} {entry['name']}",
                                       blocks=_blocks(entry, status), unfurl_links=False)
        entry.update(channel=channel, reply_ts=resp["ts"])
        with LOCK:
            data = store.load()
            data[entry["id"]] = entry
            store.save(data)

    def refresh(client, entry, status):
        try:
            client.chat_update(channel=entry["channel"], ts=entry["reply_ts"], text=f"{status} {entry['name']}",
                               blocks=_blocks(entry, status))
        except Exception as exc:
            log.warning("Antwort nicht aktualisierbar: %s", exc)

    @app.event("message")
    def on_message(event, client):
        if (event.get("channel") != settings.work_channel or event.get("subtype") in IGNORED_SUBTYPES
                or event.get("bot_id") or (event.get("thread_ts") and event["thread_ts"] != event.get("ts"))):
            return
        group, links = worklinks.parse_message(event.get("text"))
        for url, label in links:
            try:
                with LOCK:
                    found = worklinks.existing(config_dir, url)
                    if found:
                        client.chat_postMessage(channel=event["channel"], thread_ts=event["ts"],
                                                text=f":information_source: <{url}> steht schon drin als "
                                                     f"*{found['name']}* (Gruppe *{found['top']}*)")
                        continue
                    entry = worklinks.build_entry(url, label, group, config_dir)
                    entry["name"] = worklinks.unique_name(config_dir, entry["group"], entry["name"])
                    entry["id"] = uuid.uuid4().hex[:12]
                    homepage.add_service(config_dir, backups, entry["group"], entry["name"], _cfg(entry))
                post(client, event["channel"], event["ts"], entry, ":white_check_mark: Eingetragen:")
            except Exception as exc:
                log.exception("Link nicht eingetragen")
                client.chat_postMessage(channel=event["channel"], thread_ts=event["ts"],
                                        text=f":x: <{url}> nicht eingetragen: {exc}")

    def load(entry_id):
        with LOCK:
            return store.load().get(entry_id)

    @app.action("wl_remove")
    def on_remove(ack, body, client):
        ack()
        entry = load(body["actions"][0]["value"])
        if not entry or entry.get("removed"):
            return
        try:
            with LOCK:
                homepage.remove_service(config_dir, backups, entry["group"], entry["name"])
                data = store.load()
                data[entry["id"]]["removed"] = True
                store.save(data)
            entry["removed"] = True
            refresh(client, entry, f":wastebasket: Entfernt (von <@{body['user']['id']}>):")
        except Exception as exc:
            log.exception("Entfernen fehlgeschlagen")
            client.chat_postMessage(channel=entry["channel"], thread_ts=entry["reply_ts"],
                                    text=f":x: Entfernen fehlgeschlagen: {exc}")

    @app.action("wl_edit")
    def on_edit(ack, body, client):
        ack()
        entry = load(body["actions"][0]["value"])
        if not entry or entry.get("removed"):
            return

        def field(block_id, label, value, optional=True, hint=None):
            element = {"type": "plain_text_input", "action_id": "v"}
            if value:
                element["initial_value"] = str(value)
            block = {"type": "input", "block_id": block_id, "optional": optional, "label": _pt(label),
                     "element": element}
            if hint:
                block["hint"] = {"type": "plain_text", "text": hint[:150]}
            return block

        existing_groups = ", ".join(worklinks.groups(config_dir))
        client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal", "callback_id": "wl_edit_submit", "private_metadata": entry["id"],
            "title": _pt("Link anpassen"), "submit": _pt("Speichern"), "close": _pt("Abbrechen"),
            "blocks": [
                field("name", "Name", entry["name"], optional=False),
                field("group", "Gruppe", entry["group"], optional=False, hint=f"Vorhanden: {existing_groups}"),
                field("href", "URL", entry["href"], optional=False),
                field("description", "Beschreibung", entry.get("description")),
                field("icon", "Icon (z. B. atlassian-jira.svg, mdi-… oder URL)", entry.get("icon")),
            ],
        })

    @app.view("wl_edit_submit")
    def on_edit_submit(ack, body, client, view):
        values = {k: (v["v"]["value"] or "").strip() for k, v in view["state"]["values"].items()}
        missing = {k: "Bitte ausfüllen" for k in ("name", "group", "href") if not values[k]}
        if missing:
            ack(response_action="errors", errors=missing)
            return
        ack()
        entry = load(view["private_metadata"])
        if not entry:
            return
        new = {**entry, **values}
        try:
            with LOCK:
                if (new["group"], new["name"]) != (entry["group"], entry["name"]):
                    new["name"] = worklinks.unique_name(config_dir, new["group"], new["name"])
                homepage.remove_service(config_dir, backups, entry["group"], entry["name"])
                try:
                    homepage.add_service(config_dir, backups, new["group"], new["name"], _cfg(new))
                except Exception:
                    homepage.add_service(config_dir, backups, entry["group"], entry["name"], _cfg(entry))
                    raise
                data = store.load()
                data[entry["id"]] = new
                store.save(data)
            refresh(client, new, f":pencil2: Angepasst (von <@{body['user']['id']}>):")
        except Exception as exc:
            log.exception("Anpassen fehlgeschlagen")
            client.chat_postMessage(channel=entry["channel"], thread_ts=entry["reply_ts"],
                                    text=f":x: Anpassen fehlgeschlagen: {exc}")
