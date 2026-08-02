import re
from urllib.parse import urljoin

from pathfinder_collector.enums import ConfidenceLevel, StudyMode
from pathfinder_collector.extraction.evidence import suggestion
from pathfinder_collector.extraction.html import parse_html, remove_non_content
from pathfinder_collector.extraction.labels import labelled_values
from pathfinder_collector.extraction.metadata import (
    canonical_url,
    metadata_suggestions,
    metadata_title,
)
from pathfinder_collector.extraction.results import ExtractorOutput, FieldSuggestion
from pathfinder_collector.extraction.text import clean_text

_DEGREES = (
    (re.compile(r"\b(?:b\.?\s*sc\.?|bachelor(?: of science)?)\b", re.I), "bachelor"),
    (re.compile(r"\b(?:m\.?\s*sc\.?|master(?: of science)?)\b", re.I), "master"),
    (re.compile(r"\b(?:ph\.?d\.?|doctorate|dr\.?-?ing\.?)\b", re.I), "phd"),
)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COUNTRIES = {
    "germany": "DE",
    "deutschland": "DE",
    "netherlands": "NL",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "united kingdom": "GB",
    "austria": "AT",
    "switzerland": "CH",
}

_LABEL_FIELDS = {
    "programme": "program_name",
    "program": "program_name",
    "programme name": "program_name",
    "program name": "program_name",
    "university": "university_name",
    "institution": "university_name",
    "provider": "university_name",
    "degree": "degree_level",
    "degree awarded": "degree_level",
    "qualification": "degree_level",
    "language of instruction": "teaching_language",
    "teaching language": "teaching_language",
    "language": "teaching_language",
    "duration": "duration",
    "standard period of study": "duration",
    "location": "city",
    "campus": "city",
    "city": "city",
    "country": "country_code",
    "country code": "country_code",
    "study mode": "study_mode",
    "mode of study": "study_mode",
    "start semester": "intake",
    "intake": "intake",
    "field of study": "field_category",
    "subject area": "field_category",
    "application": "application_url",
    "application url": "application_url",
    "apply": "application_url",
}


class ProgrammeExtractor:
    def extract(self, content: bytes, source_url: str) -> ExtractorOutput:
        document = parse_html(content)
        metadata, warnings, structured_context = metadata_suggestions(document)
        canonical = canonical_url(document)
        title = metadata_title(document)
        remove_non_content(document)
        labelled = list(labelled_values(document))
        known_labels = [item for item in labelled if _label_key(item.label) in _LABEL_FIELDS]
        headings = [clean_text(item.text_content()) for item in document.xpath("//h1")[:5]]
        headings = [item for item in headings if item]
        heading = headings[0] if headings else ""
        programme_context = (
            structured_context or bool(known_labels) or bool(normalize_degree(heading))
        )
        if not programme_context:
            return ExtractorOutput(
                warnings=warnings + ["Page did not contain conservative programme indicators"],
                programme_context=False,
            )

        suggestions: list[FieldSuggestion] = []
        suggestions.extend(_normalize_suggestions(metadata, source_url))
        if heading:
            _append(
                suggestions,
                suggestion(
                    "program_name",
                    heading,
                    heading,
                    "h1[1]",
                    ConfidenceLevel.HIGH,
                    label="programme heading",
                ),
            )
            degree = normalize_degree(heading)
            if degree:
                _append(
                    suggestions,
                    suggestion(
                        "degree_level",
                        heading,
                        degree,
                        "h1[1]:controlled-degree-token",
                        ConfidenceLevel.MEDIUM,
                        label="degree in programme heading",
                    ),
                )
        elif title:
            _append(
                suggestions,
                suggestion(
                    "program_name",
                    _clean_metadata_title(title),
                    _clean_metadata_title(title),
                    "metadata:title",
                    ConfidenceLevel.MEDIUM,
                ),
            )

        for item in known_labels:
            field = _LABEL_FIELDS[_label_key(item.label)]
            suggestions.extend(_label_suggestions(field, item.value, item.locator, source_url))

        candidate_source = urljoin(source_url, canonical) if canonical else source_url
        effective_source = (
            candidate_source if candidate_source.startswith(("http://", "https://")) else source_url
        )
        _append(
            suggestions,
            suggestion(
                "source_url",
                effective_source,
                effective_source,
                "link[rel='canonical']" if canonical else "source-page-record",
                ConfidenceLevel.HIGH,
            ),
        )
        return ExtractorOutput(
            suggestions=_deduplicate(suggestions), warnings=warnings, programme_context=True
        )


def normalize_degree(value: str) -> str | None:
    for pattern, normalized in _DEGREES:
        if pattern.search(value):
            return normalized
    return None


def normalize_language(value: str) -> str | None:
    lowered = clean_text(value).lower()
    english = "english" in lowered or "englisch" in lowered
    german = "german" in lowered or "deutsch" in lowered
    if english and german:
        return "English and German"
    if "bilingual" in lowered or "bilingual" in lowered:
        return "bilingual"
    if english:
        return "English"
    if german:
        return "German"
    return None


def normalize_study_mode(value: str) -> StudyMode:
    lowered = clean_text(value).lower().replace("-", " ")
    if "hybrid" in lowered or "blended" in lowered:
        return StudyMode.HYBRID
    if "online" in lowered or "distance" in lowered:
        return StudyMode.ONLINE
    if "part time" in lowered:
        return StudyMode.PART_TIME
    if "full time" in lowered:
        return StudyMode.FULL_TIME
    return StudyMode.UNKNOWN


def normalize_duration(value: str) -> tuple[int, str, int | None] | None:
    lowered = clean_text(value).lower()
    iso = re.fullmatch(r"p(\d+)([ym])", lowered)
    if iso:
        number = int(iso.group(1))
        unit = "years" if iso.group(2) == "y" else "months"
        return number, unit, number * 2 if unit == "years" else None
    match = re.search(
        r"\b(\d+|one|two|three|four|five|six)\s+(semester|semesters|year|years|month|months)\b",
        lowered,
    )
    if not match:
        return None
    token, unit = match.groups()
    number = int(token) if token.isdigit() else _NUMBER_WORDS[token]
    unit = unit.removesuffix("s") + "s"
    semesters = number if unit == "semesters" else number * 2 if unit == "years" else None
    return number, unit, semesters


def _label_suggestions(
    field: str, value: str, locator: str, source_url: str
) -> list[FieldSuggestion]:
    if field == "duration":
        duration = normalize_duration(value)
        if not duration:
            return []
        number, unit, semesters = duration
        results: list[FieldSuggestion] = []
        for name, normalized in (
            ("duration_value", str(number)),
            ("duration_unit", unit),
            ("duration_semesters", str(semesters) if semesters is not None else None),
        ):
            if normalized:
                _append(results, suggestion(name, value, normalized, locator, ConfidenceLevel.HIGH))
        return results
    normalized: str | None = value
    if field == "degree_level":
        normalized = normalize_degree(value)
    elif field == "teaching_language":
        normalized = normalize_language(value)
    elif field == "study_mode":
        normalized = normalize_study_mode(value).value
    elif field == "country_code":
        lowered = value.lower().strip()
        normalized = (
            value.upper()
            if re.fullmatch(r"[A-Za-z]{2}", value.strip())
            else _COUNTRIES.get(lowered)
        )
    elif field == "application_url":
        normalized = urljoin(source_url, value)
        if not normalized.startswith(("http://", "https://")):
            normalized = None
    if normalized is None:
        return []
    item = suggestion(field, value, normalized, locator, ConfidenceLevel.HIGH)
    return [item] if item else []


def _normalize_suggestions(items: list[FieldSuggestion], source_url: str) -> list[FieldSuggestion]:
    normalized: list[FieldSuggestion] = []
    for item in items:
        replacements = _label_suggestions(
            item.field_name, item.extracted_value, item.evidence_locator, source_url
        )
        if replacements:
            for replacement in replacements:
                replacement.confidence = item.confidence
                replacement.priority = item.priority
            normalized.extend(replacements)
        elif item.field_name not in {"teaching_language", "duration"}:
            normalized.append(item)
    return normalized


def _label_key(value: str) -> str:
    return clean_text(value).lower().rstrip(":")


def _clean_metadata_title(value: str) -> str:
    return clean_text(re.split(r"\s+[|–—]\s+", value, maxsplit=1)[0])


def _append(items: list[FieldSuggestion], item: FieldSuggestion | None) -> None:
    if item:
        items.append(item)


def _deduplicate(items: list[FieldSuggestion]) -> list[FieldSuggestion]:
    seen: set[tuple[str, str, str]] = set()
    result: list[FieldSuggestion] = []
    for item in items:
        key = (
            item.field_name,
            (item.normalized_value or item.extracted_value).casefold(),
            item.evidence_locator,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
