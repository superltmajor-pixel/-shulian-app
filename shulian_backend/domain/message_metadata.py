"""Internal history labels are context metadata, never character dialogue."""
import re

_LABEL = re.compile(
    r"[【\[]\s*(?:消息时间\s*[:：]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}"
    r"(?:\s*[；;]\s*来源\s*[:：]\s*(?:主动消息|首页问候|新对话开场))?"
    r"|来源\s*[:：]\s*(?:主动消息|首页问候|新对话开场)"
    r"|消息编号\s*[:：]\s*\d+)\s*[】\]]"
)


def strip_history_labels(text: str) -> str:
    return _LABEL.sub("", str(text or "")).strip()


def has_history_labels(text: str) -> bool:
    return bool(_LABEL.search(str(text or "")))
