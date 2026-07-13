from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("voiceops.audit")


def audit(event: str, call_id: str, **fields: Any) -> dict[str, object]:
    record: dict[str, object] = {
        "event": event,
        "call_id": call_id,
        "at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logger.info(json.dumps(record, default=str, sort_keys=True))
    return record
