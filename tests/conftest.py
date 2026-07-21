import json
from pathlib import Path
from typing import Any

import pytest

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def tailscale_status() -> dict[str, Any]:
    """A realistic `tailscale status --json` payload (Self + peers)."""
    return json.loads((DATA_DIR / "tailscale_status.json").read_text())
