from lxml import etree, html
from lxml.html import HtmlElement

from pathfinder_collector.extraction.exceptions import ExtractionError

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_NODES = 50_000


def parse_html(content: bytes) -> HtmlElement:
    if len(content) > MAX_HTML_BYTES:
        raise ExtractionError("cached HTML exceeds extraction size limit")
    parser = html.HTMLParser(encoding="utf-8", recover=True, no_network=True)
    try:
        document = html.fromstring(content, parser=parser)
    except (etree.ParserError, ValueError) as exc:
        raise ExtractionError("cached HTML could not be parsed") from exc
    if sum(1 for _ in document.iter()) > MAX_NODES:
        raise ExtractionError("cached HTML has too many nodes")
    return document


def remove_non_content(document: HtmlElement) -> None:
    for element in document.xpath(
        "//script|//style|//noscript|//nav|//footer|//header|//form|//aside|"
        "//*[@hidden]|//*[@aria-hidden='true']"
    ):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
