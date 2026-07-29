"""Small, safe Markdown renderer for Ameath's compact Qt chat surface."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_ORDERED = re.compile(r"^\d+[.)]\s+(.+)$")
_UNORDERED = re.compile(r"^[-*+]\s+(.+)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def is_safe_link(url: str) -> bool:
    return urlparse(url).scheme.lower() in _SAFE_LINK_SCHEMES


def render_markdown(source: str) -> str:
    """Render the supported Markdown subset after escaping all model-provided HTML."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag = ""
    code_lines: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items, list_tag
        if list_items:
            blocks.append(f"<{list_tag}>" + "".join(f"<li>{_inline(item)}</li>" for item in list_items) + f"</{list_tag}>")
            list_items = []
            list_tag = ""

    for raw_line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            if code_lines is None:
                code_lines = []
            else:
                blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = None
            continue
        if code_lines is not None:
            code_lines.append(raw_line)
            continue
        if not raw_line.strip():
            flush_paragraph()
            flush_list()
            continue
        heading = _HEADING.match(raw_line)
        if heading:
            flush_paragraph()
            flush_list()
            level = min(3, len(heading.group(1)))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if raw_line.startswith("> "):
            flush_paragraph()
            flush_list()
            blocks.append("<blockquote>" + _inline(raw_line[2:]) + "</blockquote>")
            continue
        unordered = _UNORDERED.match(raw_line)
        ordered = _ORDERED.match(raw_line)
        if unordered or ordered:
            tag = "ul" if unordered else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            flush_paragraph()
            list_tag = tag
            list_items.append((unordered or ordered).group(1))
            continue
        flush_list()
        paragraph.append(raw_line)

    if code_lines is not None:
        blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    flush_paragraph()
    flush_list()
    return "".join(blocks) or "<p></p>"


def markdown_to_plain(source: str) -> str:
    text = source.replace("```", "").replace("`", "")
    text = _LINK.sub(lambda match: match.group(1), text)
    text = re.sub(r"(^|\s)[#>*_-]+\s?", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__|\*|_)", "", text)
    return " ".join(text.split())


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), html.unescape(match.group(2))
        if not is_safe_link(url):
            return _inline_without_links(label, already_escaped=True)
        return f'<a href="{html.escape(url, quote=True)}">{_inline_without_links(label, already_escaped=True)}</a>'

    escaped = _LINK.sub(link, escaped)
    return _inline_without_links(escaped, already_escaped=True)


def _inline_without_links(text: str, *, already_escaped: bool = False) -> str:
    value = text if already_escaped else html.escape(text, quote=False)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)", lambda m: f"<i>{m.group(1) or m.group(2)}</i>", value)
    return value
