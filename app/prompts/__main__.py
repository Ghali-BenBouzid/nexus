"""Update versions.lock: ``python -m app.prompts``. Refuses a prompt whose text
changed while its version did not."""

import json
import sys

from app.prompts import LOCK, PROMPTS, fingerprint, version


def main() -> int:
    locked = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    new, unbumped = {}, []
    for name, prompt in PROMPTS.items():
        entry = {"version": version(prompt), "sha256": fingerprint(prompt)}
        old = locked.get(name)
        if (
            old
            and old["version"] == entry["version"]
            and old["sha256"] != entry["sha256"]
        ):
            unbumped.append(name)
        elif old != entry:
            print(f"{name}: v{entry['version']}")
        new[name] = entry
    if unbumped:
        print(f"Text changed without a version bump: {', '.join(unbumped)}")
        return 1
    LOCK.write_text(json.dumps(new, indent=2) + "\n")
    return 0


sys.exit(main())
