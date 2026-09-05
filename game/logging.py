"""Small JSON logging helpers shared by Django and the Telegram runtime."""

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    context_fields = ("game_id", "chat_id", "player_id", "transaction_id", "update_id")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.context_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
