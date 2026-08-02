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


def _value(element: HtmlElement) -> str:
    links = element.xpath(".//a[@href]")
    if links and any(
        word in clean_text(element.text_content()).lower() for word in ("apply", "application")
    ):
        return clean_text(links[0].get("href"))
    return clean_text(element.text_content())
