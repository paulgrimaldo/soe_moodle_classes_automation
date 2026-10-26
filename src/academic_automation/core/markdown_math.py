"""Math-aware Markdown parsing shared by publication, validation and preview."""

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

from academic_automation.core.errors import StageError


def _escaped(source: str, position: int) -> bool:
    backslashes = 0
    while position > 0 and source[position - 1] == "\\":
        backslashes += 1
        position -= 1
    return bool(backslashes % 2)


@dataclass(frozen=True)
class MathSpan:
    content: str
    end: int
    opening: str


def _span(source: str, position: int, *, strict=True) -> MathSpan | None:
    if _escaped(source, position):
        return None
    opening = next((marker for marker in (r"\[", r"\(", "$$", "$")
                    if source.startswith(marker, position)), None)
    if opening is None:
        return None
    start = position + len(opening)
    if opening == "$" and (start == len(source) or source[start].isspace()):
        return None
    closing = {r"\[": r"\]", r"\(": r"\)", "$$": "$$", "$": "$"}[opening]
    end = source.find(closing, start)
    while end >= 0 and _escaped(source, end):
        end = source.find(closing, end + len(closing))
    if end < 0:
        if strict and opening != "$":
            raise StageError("MATH_DELIMITER_UNCLOSED", review=True)
        return None
    after = end + len(closing)
    if opening == "$" and (end == start or source[end - 1].isspace()
                            or (after < len(source) and source[after].isdigit())):
        return None  # Currency such as "$5 ... $10" is ordinary text.
    return MathSpan(source[start:end], after, opening)


def checked_expression(expression: str) -> str:
    expression = expression.strip()
    if not expression:
        raise StageError("MATH_EXPRESSION_EMPTY", review=True)
    if len(expression) > 1000:
        raise StageError("NOTION_EQUATION_TOO_LONG", review=True)
    balance = 0
    for index, character in enumerate(expression):
        if not _escaped(expression, index):
            balance += (character == "{") - (character == "}")
            if balance < 0:
                break
    if balance != 0:
        raise StageError("MATH_BRACES_UNBALANCED", review=True)
    return expression


def _inline_math(state, silent):
    span = _span(state.src[:state.posMax], state.pos)
    if span is None:
        return False
    expression = checked_expression(span.content)
    if not silent:
        token = state.push("math_inline", "math", 0)
        token.content, token.markup = expression, span.opening
    state.pos = span.end
    return True


def _block_math(state, start_line, end_line, silent):
    start = state.bMarks[start_line] + state.tShift[start_line]
    if state.is_code_block(start_line) or not state.src.startswith((r"\[", "$$"), start):
        return False
    # Use the block parser's adjusted line boundaries, including inside lists/quotes.
    source = "\n".join(state.src[state.bMarks[line] + state.tShift[line]:state.eMarks[line]]
                       for line in range(start_line, end_line))
    span = _span(source, 0)
    if source[span.end:].split("\n", 1)[0].strip():
        return False  # Display delimiters inside prose are handled as inline equations.
    expression = checked_expression(span.content)
    if not silent:
        count = source[:span.end].count("\n") + 1
        token = state.push("math_block", "math", 0)
        token.content, token.markup, token.block = expression, span.opening, True
        token.map = [start_line, start_line + count]
        state.line = start_line + count
    return True


def academic_markdown_parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark").enable("table")
    parser.inline.ruler.before("escape", "math_inline", _inline_math)
    parser.block.ruler.before("blockquote", "math_block", _block_math,
                              {"alt": ["paragraph", "reference", "blockquote", "list"]})
    return parser


def _preview_prose(source: str) -> str:
    result, position = [], 0
    while position < len(source):
        if source[position] == "`" and not _escaped(source, position):
            run = re.match(r"`+", source[position:])[0]
            closing = next((match for match in re.finditer(r"`+", source[position + len(run):])
                            if match[0] == run), None)
            if closing:
                end = position + len(run) + closing.end()
                result.append(source[position:end])
                position = end
                continue
        span = _span(source, position, strict=False)
        if span:
            delimiter = "$$" if span.opening == r"\[" else "$"
            result.append(delimiter + span.content + delimiter if span.opening.startswith("\\")
                          else source[position:span.end])
            position = span.end
        else:
            result.append(source[position])
            position += 1
    return "".join(result)


def math_for_preview(markdown: str) -> str:
    """Normalize only presentation delimiters; preserve fenced and inline code."""
    offsets = [0]
    for line in markdown.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    protected = [(offsets[token.map[0]], offsets[token.map[1]])
                 for token in MarkdownIt("commonmark").parse(markdown)
                 if token.type in {"fence", "code_block"} and token.map]
    result, position = [], 0
    for start, end in protected:
        if start >= position:
            result.extend([_preview_prose(markdown[position:start]), markdown[start:end]])
            position = end
    result.append(_preview_prose(markdown[position:]))
    return "".join(result)
