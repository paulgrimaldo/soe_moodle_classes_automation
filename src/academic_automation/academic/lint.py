"""Local compatibility for plain-text examples in the installed academic lint."""

import re


def allow_text_examples(skill):
    original = skill.check_markdown

    def check_markdown(markdown, number, title):
        lines = []
        language = None
        for line in markdown.splitlines(keepends=True):
            fence = line.rstrip("\r\n")
            if fence.startswith("```"):
                if language is None:
                    language = fence[3:].strip()
                    if language == "text":
                        # Adapt only the lint input; exported Markdown stays byte-for-byte intact.
                        line = "```plaintext" + line[len(fence):]
                elif fence == "```":
                    language = None
            elif language == "text" and re.search(
                r"[\u2500-\u257f]|\[[^\n]+\]\s*(?:-->|->)\s*\[", line
            ):
                # Apply the installed lint's text-diagram check inside these examples too.
                raise skill.Failure("Se detectó un posible diagrama de texto fuera de Mermaid.")
            lines.append(line)
        return original("".join(lines), number, title)

    skill.check_markdown = check_markdown
