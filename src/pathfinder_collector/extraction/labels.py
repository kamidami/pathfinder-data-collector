from collections.abc import Iterator
from dataclasses import dataclass

from lxml.html import HtmlElement

from pathfinder_collector.extraction.text import clean_text


@dataclass(frozen=True)
class LabelledValue:
    label: str
    value: str
    locator: str


def labelled_values(document: HtmlElement) -> Iterator[LabelledValue]:
    for term in document.xpath("//dt")[:500]:
        following = term.xpath("following-sibling::dd[1]")
        if following:
            label = clean_text(term.text_content(), 200)
            value = _value(following[0])
            if label and value:
                yield LabelledValue(label, value, f"definition-list:{label}")
    for row in document.xpath("//tr")[:1000]:
        cells = row.xpath("./th|./td")
        if len(cells) >= 2:
            label = clean_text(cells[0].text_content(), 200)
            value = _value(cells[1])
            if label and value:
                yield LabelledValue(label, value, f"table:{label}")
    for container in document.xpath("//*[br]")[:1000]:
        for line in _break_lines(container):
            if ":" in line:
                label, value = line.split(":", 1)
                label = clean_text(label, 200)
                value = clean_text(value)
                if label and value:
                    yield LabelledValue(label, value, f"labelled-lines:{label}")
    card_xpath = (
        "//*[self::strong or self::h2 or self::h3 or self::h4 or self::h5 or self::h6]"
        "[parent::*[contains(@class,'card') or contains(@class,'spec') or "
        "contains(@class,'box') or contains(@class,'flex__')]]"
    )
    for label_node in document.xpath(card_xpath)[:1000]:
        label = clean_text(label_node.text_content(), 200)
        parent = label_node.getparent()
        value = clean_text(" ".join(parent.xpath("./*[not(self::strong)]//text()")))
        if label and value and value != label:
            yield LabelledValue(label, value, f"labelled-card:{label}")
    for label_node in document.xpath("//p/strong")[:500]:
        label = clean_text(label_node.text_content(), 200).rstrip(":")
        inline_value = clean_text("".join(label_node.xpath("following-sibling::text()"))).lstrip(
            ": "
        )
        if label and inline_value:
            yield LabelledValue(label, inline_value, f"labelled-inline:{label}")
        following = label_node.getparent().xpath("following-sibling::*[1]")
        if label and following:
            value = clean_text(following[0].text_content())
            if value:
                yield LabelledValue(label, value, f"labelled-paragraph:{label}")


def _value(element: HtmlElement) -> str:
    links = element.xpath(".//a[@href]")
    if links and any(
        word in clean_text(element.text_content()).lower() for word in ("apply", "application")
    ):
        return clean_text(links[0].get("href"))
    return clean_text(element.text_content())


def _break_lines(element: HtmlElement) -> Iterator[str]:
    parts: list[str] = [element.text or ""]
    for child in element:
        if child.tag.lower() == "br":
            line = clean_text("".join(parts))
            if line:
                yield line
            parts = []
        else:
            parts.append(child.text_content())
        parts.append(child.tail or "")
    line = clean_text("".join(parts))
    if line:
        yield line
