import json
from collections.abc import Iterator

from lxml.html import HtmlElement

from pathfinder_collector.enums import ConfidenceLevel
from pathfinder_collector.extraction.evidence import suggestion
from pathfinder_collector.extraction.results import FieldSuggestion
from pathfinder_collector.extraction.text import clean_text


def metadata_suggestions(document: HtmlElement) -> tuple[list[FieldSuggestion], list[str], bool]:
    values: list[FieldSuggestion] = []
    warnings: list[str] = []
    programme_context = False
    for index, script in enumerate(document.xpath("//script[@type='application/ld+json']")[:20]):
        raw = script.text or ""
        if len(raw) > 200_000:
            warnings.append("JSON-LD block skipped because it was too large")
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            warnings.append("Invalid JSON-LD was ignored")
            continue
        for item in _objects(payload):
            item_type = item.get("@type", "")
            types = {
                str(value).lower()
                for value in (item_type if isinstance(item_type, list) else [item_type])
            }
            if types & {"course", "educationaloccupationalprogram", "courseinstance"}:
                programme_context = True
                _add(values, "program_name", item.get("name"), f"JSON-LD[{index}].name")
                provider = item.get("provider")
                if isinstance(provider, dict):
                    _add(
                        values,
                        "university_name",
                        provider.get("name"),
                        f"JSON-LD[{index}].provider.name",
                    )
                _add(
                    values,
                    "teaching_language",
                    item.get("inLanguage"),
                    f"JSON-LD[{index}].inLanguage",
                )
                _add(
                    values,
                    "duration",
                    item.get("timeToComplete"),
                    f"JSON-LD[{index}].timeToComplete",
                )
            if types & {
                "collegeoruniversity",
                "educationalorganization",
                "researchorganization",
            }:
                _add(values, "university_name", item.get("name"), f"JSON-LD[{index}].name")
                address = item.get("address")
                if isinstance(address, dict):
                    _add(
                        values,
                        "country_code",
                        address.get("addressCountry"),
                        f"JSON-LD[{index}].address.addressCountry",
                    )
    site_name = _meta(document, "property", "og:site_name")
    if site_name:
        item = suggestion(
            "university_name",
            site_name,
            site_name,
            "meta[property='og:site_name']",
            ConfidenceLevel.MEDIUM,
        )
        if item:
            values.append(item)
    institution = _institution_metadata(document)
    if institution:
        value, locator = institution
        item = suggestion("university_name", value, value, locator, ConfidenceLevel.MEDIUM)
        if item:
            values.append(item)
    return values, warnings, programme_context


def canonical_url(document: HtmlElement) -> str | None:
    links = document.xpath(
        "//link[contains(concat(' ', normalize-space(@rel), ' '), ' canonical ')]/@href"
    )
    return clean_text(links[0]) if links else None


def metadata_title(document: HtmlElement) -> str | None:
    value = _meta(document, "property", "og:title")
    if value:
        return value
    titles = document.xpath("//title/text()")
    return clean_text(titles[0]) if titles else None


def _meta(document: HtmlElement, attribute: str, name: str) -> str | None:
    uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lowercase = "abcdefghijklmnopqrstuvwxyz"
    values = document.xpath(
        f"//meta[translate(@{attribute}, '{uppercase}', '{lowercase}')='{name.lower()}']/@content"
    )
    return clean_text(values[0]) if values else None


def _institution_metadata(document: HtmlElement) -> tuple[str, str] | None:
    author = _meta(document, "name", "author")
    if author and _looks_like_institution(author):
        return author, "meta[name='author']"
    title = metadata_title(document)
    if title:
        for segment in reversed([clean_text(item) for item in title.split("|")]):
            if _looks_like_institution(segment):
                return segment, "metadata:title:institution-segment"
    publisher = _meta(document, "name", "publisher")
    if publisher and _looks_like_institution(publisher):
        return publisher, "meta[name='publisher']"
    return None


def _looks_like_institution(value: str) -> bool:
    lowered = value.casefold()
    return any(token in lowered for token in ("university", "universität", "universitaet"))


def _objects(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for child in graph:
                yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _add(values: list[FieldSuggestion], field: str, value: object, locator: str) -> None:
    if isinstance(value, str):
        item = suggestion(field, value, value, locator, ConfidenceLevel.HIGH)
        if item:
            values.append(item)
