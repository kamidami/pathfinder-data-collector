import re

_SPACE = re.compile(r"\s+")


def clean_text(value: str | None, maximum: int = 2000) -> str:
    if not value:
        return ""
    return _SPACE.sub(" ", value).strip()[:maximum]


def evidence_excerpt(label: str, value: str) -> str:
    return clean_text(f"{label}: {value}", 500)
