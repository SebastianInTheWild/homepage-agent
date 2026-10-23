"""Slack: Bericht posten, Buttons und Dialoge verarbeiten.

Jeder Dienst bekommt eine eigene Nachricht im Channel (= eigener Thread); was per Button passiert,
landet als Antwort in diesem Thread. Die Zusammenfassung ist eine separate Nachricht.
"""
import datetime
import json
import logging
from dataclasses import asdict

from . import cleanup, health, homepage, provision
from .portainer import Portainer
from .state import LOCK, State

log = logging.getLogger(__name__)
MAX_TEXT = 2900  # Slack erlaubt 3000 Zeichen pro Abschnitt


def _pt(text):
    return {"type": "plain_text", "text": text[:75]}


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:MAX_TEXT]}}


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:MAX_TEXT]}]}


def _option(group):
    return {"text": _pt(group), "value": group[:150]}


def _button(action, text, item_id, style=None):
    button = {"type": "button", "action_id": action, "text": _pt(text), "value": item_id}
    if style:
        button["style"] = style
    return button


def entry_cfg(c):
    cfg = {"href": c.get("href"), "description": c.get("description"), "icon": c.get("icon")}
    if c.get("container"):
        cfg.update(server=c["server"], container=c["container"])
    cfg.update(c.get("proxmox") or {})
    return cfg


def entry_labels(c):
    labels = {"homepage.group": c.get("group"), "homepage.name": c.get("name"), "homepage.href": c.get("href"),
              "homepage.icon": c.get("icon"), "homepage.description": c.get("description")}
    return {key: value for key, value in labels.items() if value}


def target_text(c):
    t = c.get("target") or {}
    if t:
        return f"Ziel: Docker-Label an `{t['service']}` im Stack `{t['stack']}` (Container startet dabei neu)"
    return "Ziel: services.yaml"


def candidate_blocks(c, groups=None, status=None):
    verdict = (c.get("health") or {}).get("verdict")
    title = (f":broom: Proxy-Host `{c['hosts'][0]}` für *{c['name']}* funktioniert nicht "
             f"(ein Eintrag „{c['name']}“ steht bereits in Homepage)" if c.get("in_homepage")
             else f"*{c['name']}*  ·  {c['href'] or '_keine URL gefunden – über „Anpassen“ ergänzen_'}")
    lines = [title]
    if c.get("description") and not c.get("in_homepage"):
        lines.append(f"_{c['description']}_")
    lines += [f"• {s}" for s in c["sources"]]
    blocks = [_section("\n".join(lines))]
    if verdict:
        reasons = " · ".join(c["health"]["reasons"])
        blocks.append(_section(f"{health.TEXT[verdict]}\n{reasons}"))
    if not c.get("in_homepage"):
        blocks.append(_context(f"Vorschlag: Gruppe *{c['group']}* · Icon `{c['icon']}` · {target_text(c)}"))
    if status:
        return blocks + [_context(status)]

    leftover = verdict == health.LEFTOVER
    elements = []
    if not c.get("in_homepage"):
        options = [_option(g) for g in dict.fromkeys([*(groups or []), c["group"]])][:100]
        elements += [
            {"type": "static_select", "action_id": "group", "options": options, "initial_option": _option(c["group"])},
            _button("add", "Eintragen", c["id"], None if leftover else "primary"),
            _button("edit", "Anpassen …", c["id"]),
        ]
    if c.get("hosts"):
        elements.append(_button("delete", "Löschen …", c["id"], "danger"))
    elements += [_button("ignore", "Ignorieren", c["id"]), _button("later", "Später", c["id"])]
    blocks.append({"type": "actions", "block_id": f"act|{c['id']}"[:255], "elements": elements})
    return blocks


def provision_blocks(p, status=None):
    lines = [f":sparkles: *Neuer Dienst: {p['name']}*  ·  `{p['domain']}`",
             f"Container `{p['container']}` auf `{p['server']}` hat das Label `{provision.LABEL}`. Das fehlt noch:"]
    lines += provision.describe(p)
    blocks = [_section("\n".join(lines))]
    if p["problems"]:
        blocks.append(_context(":warning: " + " · ".join(p["problems"])))
    if status:
        return blocks + [_context(status)]
    elements = [_button("ignore", "Ignorieren", p["id"]), _button("later", "Später", p["id"])]
    if not p["problems"]:
        elements.insert(0, _button("provision", "Anlegen", p["id"], "primary"))
    blocks.append({"type": "actions", "block_id": f"act|{p['id']}"[:255], "elements": elements})
    return blocks


FIELD_NAMES = {"name": "Name", "description": "Beschreibung", "group": "Gruppe"}


def revision_blocks(r, status=None):
    where = r["where"] + (f" im Stack `{r['target']['stack']}`" if r.get("target") else "")
    lines = [f":pencil: *{r['name']}* überarbeiten  ·  {where}"]
    lines += [f"• {FIELD_NAMES[f]}: {('_' + old + '_') if old else '–'}  →  *{new}*"
              for f, (old, new) in r["changes"].items()]
    blocks = [_section("\n".join(lines))]
    changeable = r["where"] == "services.yaml" or r.get("target")
    if not changeable:
        blocks.append(_context(":information_source: Labels in diesem Stack kann ich nicht ändern (Git-Stack oder "
                               "anderer Server) – bitte im Compose selbst anpassen."))
    if r.get("target"):
        blocks.append(_context("Beim Übernehmen startet der Container neu."))
    if status:
        return blocks + [_context(status)]
    elements = [_button("ignore", "Ignorieren", r["id"]), _button("later", "Später", r["id"])]
    if changeable:
        elements.insert(0, _button("revise", "Übernehmen", r["id"], "primary"))
    blocks.append({"type": "actions", "block_id": f"act|{r['id']}"[:255], "elements": elements})
    return blocks


def render(item, status=None):
    if item.get("kind") == "provision":
        return provision_blocks(item["candidate"], status)
    if item.get("kind") == "revision":
        return revision_blocks(item["candidate"], status)
    return candidate_blocks(item["candidate"], item.get("groups"), status)


def _bullets(title, items, limit=15):
    more = f"\n… und {len(items) - limit} weitere" if len(items) > limit else ""
    return _section(f"{title}\n" + "\n".join(f"• {i}" for i in items[:limit]) + more)


def post_report(client, settings, report, force=False):
    """Zusammenfassung in den Channel, danach jeder offene Dienst als eigene Nachricht mit Buttons."""
    store = State(settings.data_dir)
    current = {c.id: ("candidate", asdict(c)) for c in report.missing}
    current.update({p["id"]: ("provision", p) for p in report.provisions})
    current.update({r["id"]: ("revision", r) for r in report.revisions})
    with LOCK:
        st = store.load()

        # Erledigtes abschließen; ohne Fehler beim Abfragen, sonst fehlen vielleicht nur Daten
        for item_id, item in list(st["items"].items()):
            if item_id in current:
                continue
            if item["status"] in ("pending", "later") and not report.errors:
                _update(client, item, ":white_check_mark: Erledigt – taucht beim Abgleich nicht mehr als offen auf")
                del st["items"][item_id]
            elif item["status"] in ("added", "deleted"):
                del st["items"][item_id]

        # Offene Nachrichten mit neuen Erkenntnissen (Container, Label-Ziel …) auffrischen
        for item_id, (kind, data) in current.items():
            item = st["items"].get(item_id)
            if item and item["status"] == "pending":
                if kind == "candidate":
                    data = {**data, "group": item["candidate"]["group"]}
                if data != item["candidate"]:
                    item.update(candidate=data, groups=report.groups, kind=kind)
                    _refresh(client, item)

        new = [i for i in current if i not in st["items"] or st["items"][i]["status"] == "later"]
        waiting = [current[i][1]["name"] for i in current if i in st["items"] and st["items"][i]["status"] == "pending"]
        issues = sorted(report.stale + report.lint + report.labels + report.errors)
        if not force and not new and issues == st["last_issues"]:
            log.info("Keine Änderungen – kein Bericht")
            return

        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        not_in_homepage = [c for c in report.missing if not c.in_homepage]
        known = report.total - len(not_in_homepage)
        blocks = [_section(f"*Homepage-Check* · {now}\n{report.total} Dienste in NPM gefunden, "
                           f"{known} davon in Homepage oder ignoriert.")]
        n_new_prov = sum(1 for i in new if current[i][0] == "provision")
        if n_new_prov:
            blocks.append(_section(f":sparkles: *{n_new_prov} neue Dienste per Label* zum Anlegen – je eigene Nachricht"))
        new_ids = set(new)
        verdicts = {v: sum(1 for c in report.missing if c.id in new_ids and c.health.get("verdict") == v
                           and not c.in_homepage) for v in (health.ACTIVE, health.CHECK, health.LEFTOVER)}
        if sum(verdicts.values()):
            blocks.append(_section(
                f":new: *{sum(verdicts.values())} fehlen in Homepage* – je eigene Nachricht\n"
                f":large_green_circle: {verdicts[health.ACTIVE]} eintragen · :large_yellow_circle: "
                f"{verdicts[health.CHECK]} prüfen · :red_circle: {verdicts[health.LEFTOVER]} vermutlich Reste"))
        n_rest = sum(1 for c in report.missing if c.id in new_ids and c.in_homepage)
        if n_rest:
            blocks.append(_section(f":broom: *{n_rest} Proxy-Hosts funktionieren nicht*, obwohl der Dienst in "
                                   "Homepage steht – Löschen oder Reparieren empfohlen"))
        n_rev = sum(1 for i in new if current[i][0] == "revision")
        if n_rev:
            blocks.append(_section(f":pencil: *{n_rev} bestehende Einträge überarbeiten* (Name, Beschreibung, "
                                   "Gruppe) – je eigene Nachricht"))
        if waiting:
            blocks.append(_section(f":hourglass_flowing_sand: {len(waiting)} warten noch auf deine Entscheidung: "
                                   + ", ".join(waiting)))
        if report.stale:
            blocks.append(_bullets(":wastebasket: *Veraltete Einträge*", report.stale))
        if report.lint:
            blocks.append(_bullets(":pencil2: *Auffälligkeiten in services.yaml*", report.lint))
        if report.labels:
            blocks.append(_bullets(":label: *Docker-Labels ohne Proxy/DNS*", report.labels))
        if report.errors:
            blocks.append(_bullets(":warning: *Nicht abgefragt*", report.errors))
        if not (new or waiting or issues):
            blocks.append(_section(":white_check_mark: Alles eingetragen."))
        client.chat_postMessage(channel=settings.slack_channel, blocks=blocks[:50],
                                text=f"Homepage-Check: {len(new)} offen")

        for item_id in new:
            kind, data = current[item_id]
            item = {"status": "pending", "kind": kind, "candidate": data, "groups": report.groups}
            prefix = ("Neuer Dienst" if kind == "provision" else "Überarbeiten" if kind == "revision" else
                      "Rest in Homepage" if data.get("in_homepage") else "Fehlt in Homepage")
            msg = client.chat_postMessage(channel=settings.slack_channel, blocks=render(item),
                                          text=f"{prefix}: {data['name']}")
            item.update(channel=msg["channel"], ts=msg["ts"])
            st["items"][item_id] = item
        st["last_issues"] = issues
        store.save(st)


def reset(client, settings):
    """Alle eigenen Nachrichten im Channel löschen und den Status zurücksetzen (Sicherung bleibt)."""
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    from slack_sdk.errors import SlackApiError

    me = client.auth_test()
    mine = lambda m: m.get("user") == me["user_id"] or (m.get("bot_id") and m.get("bot_id") == me.get("bot_id"))
    deleted = skipped = 0

    def delete(msg):
        nonlocal deleted, skipped
        if not mine(msg):
            return
        try:
            client.chat_delete(channel=settings.slack_channel, ts=msg["ts"])
            deleted += 1
        except SlackApiError as exc:  # z. B. „ist dem Channel beigetreten“ lässt sich nicht löschen
            skipped += 1
            log.info("Nicht löschbar (%s): %s", exc.response.get("error"), msg.get("subtype") or msg["ts"])

    cursor = None
    while True:
        page = client.conversations_history(channel=settings.slack_channel, limit=200, cursor=cursor)
        for msg in page["messages"]:
            if msg.get("reply_count"):
                for reply in client.conversations_replies(channel=settings.slack_channel, ts=msg["ts"],
                                                          limit=200)["messages"][1:]:
                    delete(reply)
            delete(msg)
        cursor = (page.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    store = State(settings.data_dir)
    with LOCK:
        if store.path.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            store.path.replace(store.path.with_name(f"state-vor-reset-{stamp}.json"))
        store.save(store.load())
    log.info("Reset: %d Nachrichten gelöscht, %d nicht löschbar, Status zurückgesetzt", deleted, skipped)
    return deleted


def _refresh(client, item):
    try:
        client.chat_update(channel=item["channel"], ts=item["ts"], text=item["candidate"]["name"],
                           blocks=render(item))
    except Exception as exc:
        log.warning("Nachricht nicht aktualisierbar: %s", exc)


def _update(client, item, status):
    try:
        client.chat_update(channel=item["channel"], ts=item["ts"], text=status, blocks=render(item, status))
    except Exception as exc:  # alte Nachricht gelöscht o. Ä. – nicht schlimm
        log.warning("Nachricht nicht aktualisierbar: %s", exc)


def _reply(client, item, text):
    """Antwort in den Thread des Dienstes."""
    try:
        client.chat_postMessage(channel=item["channel"], thread_ts=item["ts"], text=text)
    except Exception as exc:
        log.warning("Thread-Antwort fehlgeschlagen: %s", exc)


def register(app, settings):
    store = State(settings.data_dir)

    def load_item(item_id):
        with LOCK:
            return store.load()["items"].get(item_id)

    def set_status(item_id, status, **changes):
        with LOCK:
            st = store.load()
            item = st["items"].get(item_id)
            if item:
                item.update(status=status, **changes)
                store.save(st)
            return item

    def add(client, item_id, user, overrides):
        item = load_item(item_id)
        if not item:
            return
        c = {**item["candidate"], **{k: v for k, v in overrides.items() if v is not None}}
        target = c.get("target") or {}
        _reply(client, item, f":hourglass_flowing_sand: <@{user}> trägt *{c['name']}* ein …")
        try:
            with LOCK:
                if target and settings.portainer_url and settings.portainer_api_key:
                    portainer = Portainer(settings.portainer_url, settings.portainer_api_key,
                                          settings.portainer_endpoint_id)
                    portainer.set_labels(target["stack_id"], target["service"], entry_labels(c))
                    done = (f"Als Docker-Label an `{target['service']}` im Stack `{target['stack']}` gesetzt, "
                            f"Gruppe *{c['group']}*")
                else:
                    homepage.add_service(settings.config_dir, settings.data_dir / "backups", c["group"], c["name"],
                                         entry_cfg(c))
                    done = f"In services.yaml eingetragen, Gruppe *{c['group']}*"
        except Exception as exc:
            log.exception("Eintragen fehlgeschlagen")
            _reply(client, item, f":x: Eintragen fehlgeschlagen: {exc}")
            return
        item = set_status(item_id, "added", candidate=c)
        _update(client, item, f":white_check_mark: {done} (von <@{user}>)")
        _reply(client, item, f":white_check_mark: {done}.")

    def finish(client, body, status, message):
        item_id, user = body["actions"][0]["value"], body["user"]["id"]
        with LOCK:
            st = store.load()
            item = st["items"].get(item_id)
            if not item:
                return
            if status == "ignored":
                st["ignored"][item_id] = {"name": item["candidate"]["name"], "by": user,
                                          "at": datetime.datetime.now().isoformat(timespec="seconds")}
                del st["items"][item_id]
            else:
                item["status"] = status
            store.save(st)
        _update(client, item, message.format(user=user))

    @app.action("group")
    def on_group(ack):
        ack()

    @app.action("add")
    def on_add(ack, body, client):
        ack()
        block_id = body["actions"][0]["block_id"]
        selected = (body.get("state", {}).get("values", {}).get(block_id, {}).get("group", {})
                    .get("selected_option") or {}).get("value")
        add(client, body["actions"][0]["value"], body["user"]["id"], {"group": selected})

    @app.action("ignore")
    def on_ignore(ack, body, client):
        ack()
        finish(client, body, "ignored", ":no_entry_sign: Wird ignoriert (von <@{user}>)")

    @app.action("later")
    def on_later(ack, body, client):
        ack()
        finish(client, body, "later", ":zzz: Kommt beim nächsten Lauf wieder (<@{user}>)")

    @app.action("provision")
    def on_provision(ack, body, client):
        ack()
        item_id, user = body["actions"][0]["value"], body["user"]["id"]
        item = load_item(item_id)
        if not item:
            return
        _reply(client, item, f":hourglass_flowing_sand: <@{user}> legt *{item['candidate']['domain']}* an …")
        with LOCK:
            done, errors = provision.execute(settings, item["candidate"])
        text = ":white_check_mark: Angelegt: " + (", ".join(done) or "nichts")
        if errors:
            text += "\n:x: Fehler: " + "; ".join(errors) + "\nBeim nächsten Lauf kommt der Rest erneut zur Auswahl."
        _reply(client, item, text)
        if not errors:
            item = set_status(item_id, "added")
            _update(client, item, f":white_check_mark: Angelegt von <@{user}>")

    @app.action("revise")
    def on_revise(ack, body, client):
        ack()
        item_id, user = body["actions"][0]["value"], body["user"]["id"]
        item = load_item(item_id)
        if not item:
            return
        r = item["candidate"]
        new = {f: change[1] for f, change in r["changes"].items()}
        _reply(client, item, f":hourglass_flowing_sand: <@{user}> übernimmt die Änderungen an *{r['name']}* …")
        try:
            with LOCK:
                if r.get("target"):
                    labels = {f"homepage.{f}": v for f, v in new.items()}
                    Portainer(settings.portainer_url, settings.portainer_api_key, settings.portainer_endpoint_id) \
                        .set_labels(r["target"]["stack_id"], r["target"]["service"], labels)
                else:
                    homepage.update_service(settings.config_dir, settings.data_dir / "backups", r["group"], r["name"],
                                            new_name=new.get("name"), description=new.get("description"),
                                            new_group=new.get("group"))
        except Exception as exc:
            log.exception("Überarbeiten fehlgeschlagen")
            _reply(client, item, f":x: Übernehmen fehlgeschlagen: {exc}")
            return
        item = set_status(item_id, "added")
        _update(client, item, f":white_check_mark: Übernommen von <@{user}>")
        _reply(client, item, ":white_check_mark: Übernommen: " + ", ".join(FIELD_NAMES[f] for f in new))

    @app.action("edit")
    def on_edit(ack, body, client):
        ack()
        item_id = body["actions"][0]["value"]
        item = load_item(item_id)
        if not item:
            return
        c = item["candidate"]
        groups = list(dict.fromkeys([*item.get("groups", []), c["group"]]))

        def field(block_id, label, value, optional=True):
            element = {"type": "plain_text_input", "action_id": "v"}
            if value:
                element["initial_value"] = str(value)
            return {"type": "input", "block_id": block_id, "optional": optional, "label": _pt(label),
                    "element": element}

        client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal",
            "callback_id": "edit_submit",
            "private_metadata": json.dumps({"id": item_id}),
            "title": _pt("Dienst eintragen"),
            "submit": _pt("Eintragen"),
            "close": _pt("Abbrechen"),
            "blocks": [
                field("name", "Name", c["name"], optional=False),
                {"type": "input", "block_id": "group", "label": _pt("Gruppe"),
                 "element": {"type": "static_select", "action_id": "v", "initial_option": _option(c["group"]),
                             "options": [_option(g) for g in groups][:100]}},
                field("href", "URL", c["href"]),
                field("description", "Beschreibung", c["description"]),
                field("icon", "Icon (z. B. plex.png oder mdi-…)", c["icon"]),
            ],
        })

    @app.view("edit_submit")
    def on_edit_submit(ack, body, client, view):
        values = view["state"]["values"]
        name = (values["name"]["v"]["value"] or "").strip()
        if not name:
            ack(response_action="errors", errors={"name": "Bitte einen Namen angeben"})
            return
        ack()
        overrides = {
            "name": name,
            "group": values["group"]["v"]["selected_option"]["value"],
            "href": (values["href"]["v"]["value"] or "").strip(),
            "description": (values["description"]["v"]["value"] or "").strip(),
            "icon": (values["icon"]["v"]["value"] or "").strip(),
        }
        add(client, json.loads(view["private_metadata"])["id"], body["user"]["id"], overrides)

    def delete_view(item_id, text, can_submit):
        view = {"type": "modal", "callback_id": "delete_submit", "private_metadata": json.dumps({"id": item_id}),
                "title": _pt("Dienst löschen"), "close": _pt("Abbrechen"), "blocks": [_section(text)]}
        if can_submit:
            view["submit"] = _pt("Endgültig löschen")
        return view

    @app.action("delete")
    def on_delete(ack, body, client):
        ack()
        item_id = body["actions"][0]["value"]
        item = load_item(item_id)
        if not item:
            return
        # Dialog sofort öffnen (Slack erlaubt nur 3 s), Inhalt nach der Abfrage nachladen
        opened = client.views_open(trigger_id=body["trigger_id"],
                                   view=delete_view(item_id, ":hourglass_flowing_sand: Frage NPM und DNS ab …", False))
        p = cleanup.plan(settings, item["candidate"]["hosts"])
        lines = cleanup.describe(p)
        if lines:
            text = (f"*{item['candidate']['name']}* – das wird gelöscht:\n" + "\n".join(lines)
                    + "\n\nVorher wird alles als JSON in `data/deleted/` gesichert.")
        else:
            text = "Weder in NPM noch im DNS gibt es dazu noch Einträge."
        if p["errors"]:
            text += "\n\n:warning: Nicht abfragbar: " + "; ".join(p["errors"])
        with LOCK:
            st = store.load()
            if item_id in st["items"]:
                st["items"][item_id]["delete_plan"] = p
                store.save(st)
        client.views_update(view_id=opened["view"]["id"], view=delete_view(item_id, text[:2900], bool(lines)))

    @app.view("delete_submit")
    def on_delete_submit(ack, body, client, view):
        ack()
        item_id, user = json.loads(view["private_metadata"])["id"], body["user"]["id"]
        with LOCK:
            st = store.load()
            item = st["items"].get(item_id)
            if not item or not item.get("delete_plan"):
                return
            done, errors = cleanup.execute(settings, item.pop("delete_plan"), item["candidate"]["name"])
            if done and not errors:
                item["status"] = "deleted"
            store.save(st)
        text = f":wastebasket: <@{user}> hat gelöscht: " + (", ".join(done) or "nichts")
        if errors:
            text += "\n:x: Fehler: " + "; ".join(errors)
        _reply(client, item, text)
        if item["status"] == "deleted":
            _update(client, item, f":wastebasket: Gelöscht von <@{user}>")
