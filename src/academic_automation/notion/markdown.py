import json
import re

from academic_automation.core.errors import StageError
from academic_automation.core.markdown_math import academic_markdown_parser


def rich(text: str, *, annotations=None, link=None):
    result = []
    for index in range(0, len(text), 1900):
        item = {"type": "text", "text": {"content": text[index:index + 1900]}}
        if link and re.match(r"^https?://", link):
            item["text"]["link"] = {"url": link}
        if annotations:
            item["annotations"] = dict(annotations)
        result.append(item)
    return result or [{"type": "text", "text": {"content": ""}}]


def block(kind, content="", **extra):
    return {"object": "block", "type": kind, kind: {"rich_text": rich(content), **extra}}


def inline(token):
    result, annotations, link = [], {}, None
    for child in token.children or []:
        if child.type in {"strong_open", "em_open", "s_open"}:
            annotations[{"strong_open": "bold", "em_open": "italic", "s_open": "strikethrough"}[child.type]] = True
        elif child.type in {"strong_close", "em_close", "s_close"}:
            annotations.pop({"strong_close": "bold", "em_close": "italic", "s_close": "strikethrough"}[child.type], None)
        elif child.type == "link_open":
            link = child.attrGet("href")
        elif child.type == "link_close":
            link = None
        elif child.type == "code_inline":
            result.extend(rich(child.content, annotations={**annotations, "code": True}, link=link))
        elif child.type == "math_inline":
            equation = {"type": "equation", "equation": {"expression": child.content}}
            if annotations:
                equation["annotations"] = dict(annotations)
            result.append(equation)
        elif child.type in {"softbreak", "hardbreak"}:
            result.extend(rich("\n"))
        elif child.type == "image":
            result.extend(rich(f"{child.content} ({child.attrGet('src')})"))
        elif child.content:
            result.extend(rich(child.content, annotations=annotations, link=link))
    return result or rich(token.content)


LANGUAGES = {"python", "javascript", "typescript", "sql", "bash", "shell", "json", "yaml", "r", "java", "c", "c++", "html", "css", "latex", "docker", "markdown", "plain text"}


def markdown_blocks(markdown: str) -> list[dict]:
    """Unsupported rich formats keep their literal source. Mermaid is an explicit code fallback."""
    parser = academic_markdown_parser()
    tokens = parser.parse(markdown)
    blocks, lists = [], []
    quote, index = False, 0
    while index < len(tokens):
        token = tokens[index]
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            lists.append("bulleted_list_item" if token.type == "bullet_list_open" else "numbered_list_item")
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif token.type == "blockquote_open":
            quote = True
        elif token.type == "blockquote_close":
            quote = False
        elif token.type == "heading_open":
            index += 1
            heading = tokens[index]
            level = int(token.tag[1:])
            item = block(f"heading_{min(level, 3)}")
            item[item["type"]]["rich_text"] = inline(heading)
            blocks.append(item)
        elif token.type == "paragraph_open":
            index += 1
            content = tokens[index]
            kind = lists[-1] if lists else ("callout" if quote else "paragraph")
            item = block(kind)
            item[kind]["rich_text"] = inline(content)
            if kind == "callout":
                item[kind]["color"] = "blue_background"
            blocks.append(item)
        elif token.type == "math_block":
            blocks.append({"object": "block", "type": "equation", "equation": {"expression": token.content}})
        elif token.type in {"fence", "code_block"}:
            language = token.info.split()[0] if token.info.strip() else "plain text"
            if language == "mermaid":
                # API code language does not reliably render Mermaid. Preserve exact source and caption.
                blocks.append(block("code", token.content, language="plain text", caption=rich("Mermaid")))
            else:
                blocks.append(block("code", token.content, language=language if language in LANGUAGES else "plain text"))
        elif token.type == "hr":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif token.type == "table_open":
            rows = []
            index += 1
            while tokens[index].type != "table_close":
                current = tokens[index]
                if current.type == "tr_open":
                    rows.append([])
                elif current.type == "inline":
                    rows[-1].append(inline(current))
                index += 1
            if rows:
                # Keep request nesting under 100 children; split long tables with a repeated header.
                for offset in range(1, max(len(rows), 2), 90):
                    group = [rows[0]] + rows[offset:offset + 90]
                    blocks.append({"object": "block", "type": "table", "table": {
                        "table_width": len(rows[0]), "has_column_header": True, "has_row_header": False,
                        "children": [{"object": "block", "type": "table_row", "table_row": {"cells": row}} for row in group]}})
        elif token.type == "html_block":
            blocks.append(block("code", token.content, language="html"))
        index += 1
    return blocks


def batches(blocks: list[dict]):
    def elements(item):
        return 1 + sum(elements(child) for child in item[item["type"]].get("children", []))
    current, size, count = [], 0, 0
    for item in blocks:
        encoded = len(json.dumps(item, ensure_ascii=False).encode())
        if encoded > 450_000:
            raise StageError("NOTION_BLOCK_TOO_LARGE", review=True)
        block_count = elements(item)
        if block_count > 900:
            raise StageError("NOTION_BLOCK_TOO_DEEP", review=True)
        if current and (len(current) >= 50 or size + encoded > 450_000 or count + block_count > 900):
            yield current
            current, size, count = [], 0, 0
        current.append(item)
        size += encoded
        count += block_count
    if current:
        yield current
