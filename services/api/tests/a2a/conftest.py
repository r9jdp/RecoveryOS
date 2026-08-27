from __future__ import annotations

import sys
from pathlib import Path

CUSTOMER_AGENT_ROOT = Path(__file__).resolve().parents[3] / "customer-agent"
if str(CUSTOMER_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CUSTOMER_AGENT_ROOT))
