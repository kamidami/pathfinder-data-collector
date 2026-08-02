from pathfinder_collector.enums import ConfidenceLevel
from pathfinder_collector.extraction.confidence import priority_for
from pathfinder_collector.extraction.results import FieldSuggestion
from pathfinder_collector.extraction.text import clean_text, evidence_excerpt


def suggestion(
    field_name: str,
    value: str,
    normalized: str | None,
    locator: str,
    confidence: ConfidenceLevel,
    *,
    label: str | None = None,
) -> FieldSuggestion | None:
    value = clean_text(value)
    if not value:
        return None
    return FieldSuggestion(
        field_name=field_name,
        extracted_value=value,
        normalized_value=clean_text(normalized) if normalized else None,
        evidence_locator=clean_text(locator, 500),
        short_evidence_text=evidence_excerpt(label or field_name, value),
        confidence=confidence,
        priority=priority_for(confidence),
    )
