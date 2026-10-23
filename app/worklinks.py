"""Links aus einem Slack-Channel in eine zweite Homepage-Instanz (z. B. Arbeitslinks) übernehmen.

Jede Zeile einer Nachricht mit einem Link wird ein Eintrag. Text in derselben Zeile wird zum Namen,
sonst wird er aus der URL (Confluence-Seite, Jira-Vorgang …) oder dem Seitentitel abgeleitet.
Mit „Gruppe: X“ (eigene Zeile) landen alle Links der Nachricht in Gruppe X.
"""
import html
import re
from urllib.parse import unquote_plus, urljoin, urlparse

import requests

from . import homepage

SLACK_LINK = re.compile(r"<(https?://[^>|]+)(?:\|([^>]*))?>")
GROUP_LINE = re.compile(r"^\s*(?:gruppe|group)\s*:\s*(.+?)\s*$", re.I)
LOGIN_TITLE = re.compile(r"sign in|log ?in|anmelden|redirect|just a moment|single sign|unavailable|error|forbidden|"
                         r"not found|denied|unauthori[sz]ed|\b[45]\d\d\b|^$", re.I)
FALLBACK_ICON = "mdi-web"
HEADERS = {"User-Agent": "Mozilla/5.0 (homepage-agent)"}
LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)

# (Muster für Host, Muster für Pfad oder None, Gruppe, Icon, Art)
KNOWN = [
    (r"(^|\.)(intune|endpoint)\.microsoft\.com$", None, "Microsoft", "microsoft-intune.svg", "Intune"),
    (r"(^|\.)entra\.microsoft\.com$", None, "Microsoft", "microsoft-azure.svg", "Entra"),
    (r"(^|\.)portal\.azure\.com$", None, "Microsoft", "microsoft-azure.svg", "Azure"),
    (r"(^|\.)admin\.microsoft\.com$", None, "Microsoft", "microsoft-365-admin-center.svg", "Microsoft 365"),
    (r"(^|\.)security\.microsoft\.com$", None, "Microsoft", "microsoft-defender.svg", "Defender"),
    (r"(^|\.)teams\.microsoft\.com$", None, "Microsoft", "microsoft-teams.svg", "Teams"),
    (r"\.sharepoint\.com$", None, "Microsoft", "microsoft-sharepoint.svg", "SharePoint"),
    (r"(^|\.)outlook\.(office|office365|live)\.com$", None, "Microsoft", "microsoft-outlook.svg", "Outlook"),
    (r"\.atlassian\.net$", r"^/wiki", "Confluence", "atlassian-confluence.svg", "Confluence"),
    (r"\.atlassian\.net$", None, "Jira", "atlassian-jira.svg", "Jira"),
    (r"\.service-now\.com$", None, "ServiceNow", "https://www.servicenow.com/favicon.ico", "ServiceNow"),
]


def classify(url, config_dir=None):
    parsed = urlparse(url)
    host, path = (parsed.hostname or "").lower(), parsed.path or "/"
    for host_re, path_re, group, icon, kind in KNOWN:
        if re.search(host_re, host) and (path_re is None or re.search(path_re, path)):
            return {"group": group, "icon": icon, "kind": kind}
    # Eigene Domains (z. B. ServiceNow unter Firmendomain): wie der vorhandene Eintrag mit demselben Host
    if config_dir is not None:
        for e in homepage.iter_services(homepage.load_yaml(config_dir / "services.yaml")):
            if homepage.host_of(e["cfg"].get("href")) == host:
                return {"group": e["top"], "icon": e["cfg"].get("icon"), "kind": e["name"]}
    return {"group": "Links", "icon": None, "kind": host}


def _from_url(url, kind):
    """Sprechender Name aus bekannten URL-Formen, sonst None."""
    parsed = urlparse(url)
    parts = [unquote_plus(p) for p in parsed.path.split("/") if p]
    if kind == "Confluence":
        if "pages" in parts:
            i = parts.index("pages")
            if len(parts) > i + 2:
                return parts[i + 2].replace("-", " ").strip()
        if "spaces" in parts and len(parts) > parts.index("spaces") + 1:
            return f"Space {parts[parts.index('spaces') + 1]}"
    if kind == "Jira":
        if "browse" in parts and len(parts) > parts.index("browse") + 1:
            return parts[parts.index("browse") + 1]
        if "projects" in parts and len(parts) > parts.index("projects") + 1:
            name = parts[parts.index("projects") + 1]
            return f"{name} Board" if "boards" in parts else name
        if "dashboards" in parts:
            return "Jira Dashboard"
    if kind == "ServiceNow":
        m = re.search(r"(?:^|[?&])sysparm_query=number%3D([A-Z]+\d+)|(\b[A-Z]{3,5}\d{6,}\b)", parsed.query or "")
        if m:
            return m.group(1) or m.group(2)
    return None


def _fetch(url):
    """Seite laden; None bei Fehler oder wenn sie auf einen anderen Host umleitet (Login/SSO)."""
    try:
        resp = requests.get(url, timeout=5, headers=HEADERS, allow_redirects=True)
    except requests.RequestException:
        return None
    return resp if urlparse(resp.url).hostname == urlparse(url).hostname else None


def _page_title(resp):
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text[:200_000], re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else ""
    if LOGIN_TITLE.search(title):
        return None  # Login- oder Fehlerseite, kein brauchbarer Titel
    title = re.sub(r"\s+", " ", title)
    if len(title) > 40:  # „Seite | Website“ → „Seite“
        title = re.split(r" [|·–—-] ", title)[0]
    return title[:60]


def _attr(tag, name):
    m = re.search(rf"""\b{name}\s*=\s*["']?([^"'>\s]+(?:\s+[^"'>=\s]+)*)""", tag, re.I)
    return m.group(1) if m else ""


def _is_image(url):
    try:
        resp = requests.get(url, timeout=5, headers=HEADERS, allow_redirects=True)
    except requests.RequestException:
        return False
    kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    return resp.ok and len(resp.content) > 0 and (kind.startswith("image/") or kind == "application/octet-stream")


def site_icon(url, resp=None):
    """Icon der Website: größtes <link rel=icon/apple-touch-icon>, sonst /favicon.ico – nur wenn es wirklich
    ein Bild liefert (sonst zeigt Homepage ein kaputtes Bild)."""
    candidates = []
    if resp is not None:
        for tag in LINK_TAG.findall(resp.text[:200_000]):
            rel, href = _attr(tag, "rel").lower(), _attr(tag, "href")
            if not href or "icon" not in rel or "mask-icon" in rel:
                continue
            sizes = [int(n) for n in re.findall(r"(\d+)x\d+", _attr(tag, "sizes"))]
            score = (2 if href.lower().endswith(".svg") else 1 if "apple-touch" in rel else 0, max(sizes or [0]))
            candidates.append((score, urljoin(resp.url, html.unescape(href))))
    candidates.sort(reverse=True)
    parsed = urlparse(url)
    fallback = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    for icon in [c[1] for c in candidates if c[1].startswith("http")] + [fallback]:
        if _is_image(icon):
            return icon
    return None


def parse_message(text):
    """Liefert (Gruppe oder None, [(url, label)]) aus einer Slack-Nachricht."""
    group, links = None, []
    for line in (text or "").splitlines():
        m = GROUP_LINE.match(SLACK_LINK.sub("", line))
        if m and not SLACK_LINK.search(line):
            group = m.group(1)
            continue
        found = SLACK_LINK.findall(line)
        rest = re.sub(r"[\s\-–:|•*_]+", " ", SLACK_LINK.sub(" ", line)).strip()
        for url, label in found:
            label = label if label and label != url and not label.startswith("http") else ""
            links.append((url, label or (rest if len(found) == 1 else "")))
    return group, links


def build_entry(url, label="", group=None, config_dir=None):
    info = classify(url, config_dir)
    kind = info["kind"]
    # Seite nur bei unbekannten Links laden – die bekannten Portale liefern ohne Login nur Fehlerseiten,
    # für sie gibt es passende Icons aus dashboard-icons
    resp = _fetch(url) if info["group"] == "Links" else None
    name = label or _from_url(url, kind) or (_page_title(resp) if resp is not None else None) or kind
    icon = info["icon"] or site_icon(url, resp) or FALLBACK_ICON
    host = urlparse(url).hostname or ""
    description = kind if kind != host else host
    if name == kind and kind != host:
        description = host
    return {"group": group or info["group"], "name": name, "href": url, "description": description,
            "icon": icon}


def existing(config_dir, href):
    """Eintrag mit derselben URL, falls schon vorhanden."""
    data = homepage.load_yaml(config_dir / "services.yaml")
    target = href.rstrip("/")
    for e in homepage.iter_services(data):
        if str(e["cfg"].get("href") or "").rstrip("/") == target:
            return e
    return None


def unique_name(config_dir, group, name):
    data = homepage.load_yaml(config_dir / "services.yaml")
    taken = {e["name"] for e in homepage.iter_services(data) if e["top"] == group}
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def groups(config_dir):
    return homepage.group_names(homepage.load_yaml(config_dir / "services.yaml"))
