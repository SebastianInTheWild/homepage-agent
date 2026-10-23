"""Portainer-API: Homepage-Labels in die Compose-Datei eines Stacks schreiben und neu ausrollen."""
import io
from collections import Counter

import requests
from ruamel.yaml import YAML

TIMEOUT = 120  # Neu ausrollen inkl. Container-Neustart kann dauern
STACK_TYPE_COMPOSE = 2
PROTECTED_STACKS = {"homepage-agent"}  # würde sich beim Ausrollen selbst beenden


class Portainer:
    def __init__(self, url, api_key, endpoint_id):
        self.url = url.rstrip("/")
        self.endpoint_id = endpoint_id
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers["X-API-Key"] = api_key

    def _request(self, method, path, **kwargs):
        r = self.session.request(method, f"{self.url}/api{path}", timeout=TIMEOUT, **kwargs)
        if not r.ok:
            raise RuntimeError(f"Portainer {method} {path}: {r.status_code} {r.text[:150]}")
        return r.json() if r.content else None

    def editable_stacks(self):
        """Stack-Name → Id für Stacks, deren Compose-Datei in Portainer liegt (nicht Git, Name eindeutig)."""
        stacks = [s for s in self._request("GET", "/stacks") if s.get("EndpointId") == self.endpoint_id]
        names = Counter(s["Name"] for s in stacks)
        return {
            s["Name"]: s["Id"] for s in stacks
            if names[s["Name"]] == 1 and not s.get("GitConfig") and s.get("Type") == STACK_TYPE_COMPOSE
            and s["Name"] not in PROTECTED_STACKS
        }

    def set_labels(self, stack_id, service, labels):
        stack = self._request("GET", f"/stacks/{stack_id}")
        content = self._request("GET", f"/stacks/{stack_id}/file")["StackFileContent"]
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.width = 4096
        yaml.indent(mapping=2, sequence=4, offset=2)
        doc = yaml.load(content)
        try:
            svc = doc["services"][service]
        except (KeyError, TypeError):
            raise RuntimeError(f"Service „{service}“ nicht in der Compose-Datei von Stack {stack['Name']}") from None

        current = svc.get("labels")
        if current is None:
            svc["labels"] = dict(labels)
        elif isinstance(current, list):
            current[:] = [item for item in current if str(item).split("=", 1)[0] not in labels]
            current.extend(f"{key}={value}" for key, value in labels.items())
        else:
            for key, value in labels.items():
                current[key] = value

        out = io.StringIO()
        yaml.dump(doc, out)
        self._request("PUT", f"/stacks/{stack_id}", params={"endpointId": stack["EndpointId"]}, json={
            "stackFileContent": out.getvalue(),
            "env": stack.get("Env") or [],
            "prune": False,
            "pullImage": False,
        })
        return stack["Name"]
