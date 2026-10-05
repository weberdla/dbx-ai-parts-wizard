#!/usr/bin/env python3
"""Build ai-parts-wizard-spec.pdf from the governing Markdown.

Mirrors the fe-specialized-agents markdown-to-pdf skill (Databricks brand CSS +
WeasyPrint) but WITHOUT the `nl2br` markdown extension. The spec `.md` is hard-wrapped
at ~90 columns for readability; `nl2br` would turn every source line-wrap into a forced
<br>, producing ragged one-word-per-line breaks in the PDF. Dropping it lets paragraphs
reflow normally.

Usage:
    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 build_pdf.py
    # optional: python3 build_pdf.py <input.md> <output.pdf> <css>
"""
import os
import sys
import markdown
from weasyprint import HTML

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "ai-parts-wizard-spec.md")
OUTPUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "ai-parts-wizard-spec.pdf")
CSS = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "assets", "pdf.css")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="{css_path}">
</head>
<body>
{body}
</body>
</html>"""


def main() -> int:
    with open(INPUT, "r", encoding="utf-8") as f:
        md_text = f.read()
    # NOTE: no "nl2br" — single newlines stay soft (wrap), as normal Markdown.
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "codehilite", "toc"])
    html = HTML_TEMPLATE.format(css_path=os.path.abspath(CSS), body=body)
    HTML(string=html, base_url=os.path.dirname(os.path.abspath(INPUT))).write_pdf(OUTPUT)
    print(os.path.abspath(OUTPUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
