"""Regenerate API artifacts in temporary paths and fail on contract drift."""

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    local = Path.home() / ".local" / "bin" / name
    if local.exists():
        return str(local)
    raise RuntimeError(f"required executable not found: {name}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="repomedic-contract-") as raw_temp:
        temp = Path(raw_temp)
        openapi = temp / "openapi.json"
        generated = temp / "generated.ts"
        subprocess.run(
            [
                executable("uv"),
                "run",
                "--project",
                "apps/api",
                "python",
                "-m",
                "repomedic.cli.contract",
                "--output",
                str(openapi),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                executable("bun"),
                "x",
                "openapi-typescript",
                str(openapi),
                "-o",
                str(generated),
            ],
            cwd=ROOT,
            check=True,
        )
        expected = {
            ROOT / "apps/api/openapi.json": openapi,
            ROOT / "apps/web/src/lib/api/generated.ts": generated,
        }
        drifted = [
            str(target.relative_to(ROOT))
            for target, fresh in expected.items()
            if target.read_bytes() != fresh.read_bytes()
        ]
        if drifted:
            raise SystemExit(
                f"OpenAPI contract drift: {', '.join(drifted)}. Run bun run contract:generate"
            )


if __name__ == "__main__":
    main()
