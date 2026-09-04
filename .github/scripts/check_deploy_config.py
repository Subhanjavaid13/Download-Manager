"""Guard rails for the deployment configuration. Run by CI, runnable by hand.

    python .github/scripts/check_deploy_config.py

Three jobs:

1. Every YAML and JSON file we deploy with actually parses. A typo in
   render.yaml is otherwise only discovered by Render, mid-deploy.
2. render.yaml never carries a literal secret. Secrets are declared by name
   with `sync: false` (Render prompts once) or `generateValue: true`.
3. No `.env*.example` file has a real value pasted into a secret-shaped key.
   That has happened once already, and a committed database password is a
   rotate-everything afternoon.

Exits non-zero with a specific message on the first real problem.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs it
    sys.exit("PyYAML is required: pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]

# Key names that should never hold a real value in a tracked file.
SECRET_KEY = re.compile(r"(SECRET|PASSWORD|TOKEN|_KEY|SALT|DSN)", re.IGNORECASE)

# Values that are obviously placeholders rather than credentials.
PLACEHOLDERS = {"", "change-me", "change-me-in-production", "changeme", "your-key-here"}

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


# --- 1. everything parses ----------------------------------------------------

yaml_files = [ROOT / "render.yaml", ROOT / "docker-compose.yml"]
yaml_files += sorted((ROOT / ".github" / "workflows").glob("*.yml"))
yaml_files += sorted((ROOT / ".github" / "workflows").glob("*.yaml"))

parsed: dict[Path, object] = {}
for path in yaml_files:
    if not path.exists():
        problems.append(f"{path.relative_to(ROOT)}: missing")
        continue
    try:
        parsed[path] = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problems.append(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")

for path in [ROOT / "frontend" / "vercel.json"]:
    if not path.exists():
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")

# --- 2. render.yaml declares secrets, never carries them ---------------------

render = parsed.get(ROOT / "render.yaml")
if isinstance(render, dict):
    services = render.get("services") or []
    check(bool(services), "render.yaml: no services defined")
    for service in services:
        name = service.get("name", "<unnamed>")
        check(
            service.get("healthCheckPath") == "/health",
            f"render.yaml: {name} should set healthCheckPath: /health",
        )
        check(
            service.get("runtime") == "docker",
            f"render.yaml: {name} should use runtime: docker",
        )
        for env in service.get("envVars") or []:
            key = env.get("key", "")
            if "value" not in env:
                continue  # declared by name only: sync: false / generateValue / fromGroup
            if SECRET_KEY.search(key):
                problems.append(
                    f"render.yaml: {key} has a literal value. Secrets must use "
                    f"`sync: false` so Render prompts for them instead."
                )
            if key.endswith("DATABASE_URL") and "@" in str(env["value"]):
                problems.append(f"render.yaml: {key} looks like it contains credentials.")

# --- 3. no real values in *.example files ------------------------------------

for path in sorted(ROOT.rglob("*.example")):
    if "node_modules" in path.parts or ".venv" in path.parts:
        continue
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split("#", 1)[0].strip().strip("\"'")
        where = f"{path.relative_to(ROOT)}:{lineno}"
        if SECRET_KEY.search(key) and value.lower() not in PLACEHOLDERS:
            problems.append(f"{where}: {key} has a real-looking value. Leave it empty.")
        if key.endswith("DATABASE_URL") and "@" in value:
            problems.append(f"{where}: {key} contains credentials. Leave it as the SQLite default.")

# --- report ------------------------------------------------------------------

if problems:
    print("Deployment config check failed:\n")
    for problem in problems:
        print(f"  - {problem}")
    sys.exit(1)

print(f"Deployment config OK ({len(parsed)} YAML files, vercel.json, *.example files clean).")
