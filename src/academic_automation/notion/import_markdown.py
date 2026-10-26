"""Deterministic conversion of captured academic blocks; no generation or remote writes."""

import html
import re
from collections import Counter
from urllib.parse import urlsplit
from uuid import UUID

from academic_automation.core.errors import StageError
from academic_automation.core.security import digest

CONVERTER_VERSION = "notion-blocks-v1"
CLASS_HEADING = re.compile(r"Clase\s+(\d+)\s*:\s*(.+)", re.I | re.S)


def plain(items):
    return "".join(t.get("text", {}).get("content", t.get("plain_text", ""))
                   if t["type"] == "text" else t.get("equation", {}).get("expression", "") for t in items)


def text(value):
    # Escape Markdown and Vue syntax, leaving only converter-created markup active.
    value = html.escape(value, quote=False).replace("{", "&#123;").replace("}", "&#125;")
    value = re.sub(r"([\\`*_\[\]$|#~])", r"\\\1", value)
    value = re.sub(r"(?m)^(\s*)(\d+)([.)])(?=\s)", r"\1\2\\\3", value)
    value = re.sub(r"(?m)^(\s*)([-+])(?=\s)", r"\1\\\2", value)
    value = re.sub(r"(?m)^(\s*)([-=_])(?=[-=_ \t]{2,}$)", r"\1\\\2", value)
    return value.replace("\n", "<br>\n")


class BlockConverter:
    def __init__(self, corrections):
        self.corrections = {}
        for correction in corrections:
            self.corrections.setdefault(str(correction.block_id), []).append(correction)
        self.applied = []
        self.metrics = Counter()
        self.seen = set()

    def validate_tree(self, blocks, depth=0):
        if depth > 32:
            raise StageError("NOTION_IMPORT_TREE_TOO_DEEP")
        for block in blocks:
            try:
                identifier = str(UUID(block["id"]))
                if identifier in self.seen or len(self.seen) >= 20_000:
                    raise ValueError()
                self.seen.add(identifier)
                kind = block["type"]
                if not isinstance(block[kind], dict) or block.get("archived") or block.get("in_trash"):
                    raise ValueError()
                if block.get("has_children") and "_children" not in block:
                    raise ValueError()
                children = block.get("_children", [])
                if not isinstance(children, list):
                    raise ValueError()
                self.validate_tree(children, depth + 1)
            except (KeyError, TypeError, ValueError):
                raise StageError("NOTION_IMPORT_TREE_INVALID") from None

    def rich(self, items):
        output = []
        for item in items:
            kind = item["type"]
            if kind == "equation":
                self.metrics["equations"] += 1
                output.append("$" + item["equation"]["expression"] + "$")
                continue
            if kind != "text":
                raise StageError("NOTION_IMPORT_RICH_TEXT_UNSUPPORTED")
            value = item["text"]["content"]
            annotations = item.get("annotations", {})
            if annotations.get("code"):
                fence = "`" * max(1, max((len(m[0]) + 1 for m in re.finditer(r"`+", value)), default=1))
                value = fence + " " + value + " " + fence
            else:
                value = text(value)
                for enabled, marker in (("bold", "**"), ("italic", "*"), ("strikethrough", "~~")):
                    if annotations.get(enabled) and value.strip():
                        start = value[:len(value) - len(value.lstrip())]
                        end = value[len(value.rstrip()):]
                        value = start + marker + value.strip() + marker + end
                if annotations.get("underline"):
                    value = "<u>" + value + "</u>"
            link = item["text"].get("link")
            if link:
                url = link["url"]
                if urlsplit(url).scheme not in {"http", "https", "mailto"}:
                    raise StageError("NOTION_IMPORT_LINK_UNSUPPORTED")
                url = url.replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A")
                value = f"[{value}](<{url}>)"
            output.append(value)
        return "".join(output)

    def render(self, blocks):
        return "\n\n".join(self.block(block) for block in blocks).strip() + "\n"

    def block(self, block):
        kind = block["type"]
        body = block[kind]
        children = block.get("_children", [])
        if kind == "code":
            value = plain(body["rich_text"])
            if re.search(r"<!--\s*@include\s*:", value, re.I):
                raise StageError("NOTION_IMPORT_BUILD_DIRECTIVE_UNSUPPORTED")
            original_hash = digest(value)
            for correction in self.corrections.get(block["id"], []):
                if (body["language"] != "mermaid" or original_hash != correction.expected_sha256
                        or value.count(correction.find) != 1):
                    raise StageError("NOTION_IMPORT_CORRECTION_STALE")
                value = value.replace(correction.find, correction.replace, 1)
                self.applied.append({"block_id": block["id"], "source_sha256": original_hash,
                                     "find": correction.find, "replace": correction.replace})
            fence = "`" * max(3, max((len(m[0]) + 1 for m in re.finditer(r"`+", value)), default=3))
            language = body["language"] if re.fullmatch(r"[\w+-]+", body["language"]) else "text"
            self.metrics["code_blocks"] += 1
            caption = self.rich(body.get("caption", []))
            return f"{fence}{language}\n{value}" + ("" if value.endswith("\n") else "\n") + fence + (
                "\n\n" + caption if caption else "")
        if kind == "equation":
            self.metrics["equations"] += 1
            return "$$\n" + body["expression"] + "\n$$"
        if kind == "table":
            if any(row["type"] != "table_row" for row in children) or not children:
                raise StageError("NOTION_IMPORT_TABLE_INVALID")
            width = body["table_width"]
            rows = []
            for row in children:
                if len(row["table_row"]["cells"]) != width:
                    raise StageError("NOTION_IMPORT_TABLE_INVALID")
                cells = [re.sub(r"(?<!\\)\|", r"\\|", self.rich(cell)).replace("\n", " ")
                         for cell in row["table_row"]["cells"]]
                rows.append("| " + " | ".join(cells) + " |")
                self.metrics["table_cells"] += width
            if not body.get("has_column_header"):
                rows.insert(0, "| " + " | ".join([""] * width) + " |")
            rows.insert(1, "| " + " | ".join(["---"] * width) + " |")
            self.metrics["tables"] += 1
            self.metrics["source_table_rows"] += len(children)
            return "\n".join(rows)
        if kind == "divider":
            return "---"
        if re.fullmatch(r"heading_[1-6]", kind):
            if children:
                raise StageError("NOTION_IMPORT_HEADING_CHILDREN_UNSUPPORTED")
            return "#" * int(kind[-1]) + " " + self.rich(body["rich_text"])
        if kind in {"paragraph", "bulleted_list_item", "numbered_list_item", "quote", "callout"}:
            value = self.rich(body.get("rich_text", []))
            nested = self.render(children).strip() if children else ""
            if kind in {"quote", "callout"}:
                if kind == "callout":
                    self.metrics["callouts"] += 1
                return "\n".join("> " + line for line in (value + ("\n\n" + nested if nested else "")).splitlines())
            if kind.endswith("list_item"):
                marker = "- " if kind == "bulleted_list_item" else "1. "
                continuation = " " * len(marker)
                lines = value.splitlines() or [""]
                return marker + ("\n" + continuation).join(lines) + (
                    "\n\n" + "\n".join(continuation + line for line in nested.splitlines()) if nested else "")
            return value + ("\n\n" + nested if nested else "")
        raise StageError("NOTION_IMPORT_BLOCK_UNSUPPORTED")


def convert_week(week, corrections):
    converter = BlockConverter(corrections)
    blocks = week["blocks"]
    converter.validate_tree(blocks)
    headings = []
    for index, block in enumerate(blocks):
        if block["type"] == "heading_1":
            match = CLASS_HEADING.fullmatch(plain(block["heading_1"]["rich_text"]).strip())
            if match is None:
                raise StageError("NOTION_IMPORT_CLASS_AMBIGUOUS")
            headings.append((index, int(match[1]), match[2]))
    if not 1 <= len(headings) <= 2:
        raise StageError("NOTION_IMPORT_CLASS_AMBIGUOUS")
    number = week["week"]
    positions = []
    starts = []
    for index, label, title in headings:
        part = label if label in {1, 2} else label - (number - 1) * 2
        if part not in {1, 2} or part in positions:
            raise StageError("NOTION_IMPORT_CLASS_AMBIGUOUS")
        positions.append(part)
        start = index
        # Historical class objectives can precede their own heading, after the previous class.
        cursor = index - 1
        while cursor >= 0 and blocks[cursor]["type"] == "divider":
            cursor -= 1
        if cursor >= 0 and blocks[cursor]["type"] == "callout":
            label_text = plain(blocks[cursor]["callout"].get("rich_text", [])).casefold()
            if re.search(r"objetivo.*sesi[oó]n", label_text):
                start = cursor
        starts.append(start)
    if positions != sorted(positions):
        raise StageError("NOTION_IMPORT_CLASS_AMBIGUOUS")
    context = converter.render(blocks[:starts[0]])
    if not context.replace("---", "").strip():
        context = ""
    classes = []
    for offset, ((index, _, title), part, start) in enumerate(zip(headings, positions, starts)):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(blocks)
        # Position labels are normalized independently of the preserved capture.
        content = converter.render(blocks[start:index]) if start < index else ""
        content += f"# Clase {(number - 1) * 2 + part}: {text(title)}\n\n"
        content += converter.render(blocks[index + 1:end])
        classes.append({"part": part, "number": (number - 1) * 2 + part,
                        "title": title, "markdown": content,
                        "block_ids": [block["id"] for block in blocks[start:end]],
                        "source_heading": plain(blocks[index]["heading_1"]["rich_text"])})
    return {"classes": classes, "context": context, "metrics": dict(converter.metrics),
            "corrections": converter.applied, "converter_version": CONVERTER_VERSION}
