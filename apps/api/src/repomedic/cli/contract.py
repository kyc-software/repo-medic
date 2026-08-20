"""Export authoritative OpenAPI without starting paid or live adapters."""

import json
import sys
from pathlib import Path

from repomedic.transport.app import app


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--output":
        destination = Path(sys.argv[2])
    else:
        destination = Path(__file__).parents[3] / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
