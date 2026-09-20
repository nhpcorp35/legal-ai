#!/usr/bin/env python3
"""Install declared Python dependencies when a fresh workspace needs them."""

from __future__ import annotations

import importlib.util
import importlib
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = REPOSITORY_ROOT / "requirements.txt"
REQUIRED_IMPORTS = ("flask", "gunicorn", "pandas", "pypdf", "reportlab", "boto3")


def missing_imports() -> list[str]:
    return [
        module_name
        for module_name in REQUIRED_IMPORTS
        if importlib.util.find_spec(module_name) is None
    ]


def main() -> int:
    missing = missing_imports()
    if not missing:
        print("LegalAI workspace dependencies are ready.")
        return 0

    print("Installing missing LegalAI workspace dependencies: " + ", ".join(missing))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    # The running interpreter may have cached a failed lookup before pip
    # created the package directories. Refresh import discovery before the
    # post-install verification in this same process.
    importlib.invalidate_caches()
    still_missing = missing_imports()
    if still_missing:
        print(
            "Dependency bootstrap incomplete: " + ", ".join(still_missing),
            file=sys.stderr,
        )
        return 1
    print("LegalAI workspace dependencies are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
