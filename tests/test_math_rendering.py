import pytest

from academic_automation.core.errors import StageError
from academic_automation.notion.markdown import markdown_blocks


@pytest.mark.parametrize("source", [r"\[M = \mathcal{T}(C, D, H, E, S)\]",
                                     "\\[\nM = \\mathcal{T}(C, D, H, E, S)\n\\]",
                                     r"$$M = \mathcal{T}(C, D, H, E, S)$$"])
def test_display_equations_are_native_notion_blocks(source):
    blocks = markdown_blocks(source)
    assert len(blocks) == 1 and blocks[0]["type"] == "equation"
    assert blocks[0]["equation"]["expression"] == r"M = \mathcal{T}(C, D, H, E, S)"


@pytest.mark.parametrize("source", [r"donde \(M\) es el modelo y \(C\) el código.",
                                     r"donde $M$ es el modelo y $C$ el código."])
def test_inline_variables_are_native_equations(source):
    items = markdown_blocks(source)[0]["paragraph"]["rich_text"]
    assert [item["equation"]["expression"] for item in items if item["type"] == "equation"] == ["M", "C"]


def test_math_in_tables_and_bold_text_preserves_formatting():
    blocks = markdown_blocks("**\\(x_i\\)**\n\n| Variable | Definición |\n|---|---|\n| $x_i$ | Entrada |")
    equation = next(item for item in blocks[0]["paragraph"]["rich_text"] if item["type"] == "equation")
    assert equation["annotations"]["bold"] is True
    cell = blocks[1]["table"]["children"][1]["table_row"]["cells"][0]
    assert cell == [{"type": "equation", "equation": {"expression": "x_i"}}]


def test_code_and_currency_are_not_reinterpreted_as_math():
    source = r"Ejemplo `\(x\)` y costo $5 seguido de $10." + "\n\n```python\nx = '$x$'\n```\n"
    blocks = markdown_blocks(source)
    assert all(item["type"] != "equation" for item in blocks[0]["paragraph"]["rich_text"])
    assert blocks[1]["code"]["rich_text"][0]["text"]["content"] == "x = '$x$'\n"


@pytest.mark.parametrize("source", [r"\[x", r"\(x", r"$$x^{2$$", "$$" + "x" * 1001 + "$$"])
def test_invalid_or_oversized_math_stops_publication(source):
    with pytest.raises(StageError) as error:
        markdown_blocks(source)
    assert error.value.review


def test_preview_normalizes_math_without_changing_code():
    from academic_automation.core.markdown_math import math_for_preview
    source = "\\[\nx^2\n\\]\n\ndonde \\(x\\) es real y `\\(x\\)` es código.\n\n```latex\n\\[x\\]\n```\n"
    expected = "$$\nx^2\n$$\n\ndonde $x$ es real y `\\(x\\)` es código.\n\n```latex\n\\[x\\]\n```\n"
    assert math_for_preview(source) == expected
    assert math_for_preview(expected) == expected


def test_display_math_precedes_setext_heading_interpretation():
    blocks = markdown_blocks("$$x^2$$\n---\n")
    assert [item["type"] for item in blocks] == ["equation", "divider"]


def test_nested_math_and_escaped_delimiters():
    source = "> \\[\n> \\frac{x_i}{n}\n> \\]\n\nLiteral \\\\(x\\\\) y `$$x$$`."
    blocks = markdown_blocks(source)
    assert blocks[0]["type"] == "equation"
    assert blocks[0]["equation"]["expression"] == r"\frac{x_i}{n}"
    assert not any(item["type"] == "equation" for item in blocks[1]["paragraph"]["rich_text"])
