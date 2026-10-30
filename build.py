"""Build index.html from guide.md.

Usage:
    pip install markdown pygments
    python build.py

Edit the CONFIG block to change the title, subtitle or GitHub link.
Edit guide.md to change content. Edit the :root block in template.html to change colours and fonts.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
CONFIG = {
    "TITLE": "RS6240 Radar Occupancy Detection",
    "SHORT_TITLE": "RS6240 occupancy guide",
    "SUBTITLE": "How the RS6240 SDK and its parameters work, why the current model fails in real rooms, "
                "and how to fix the radar setup, data and ML pipeline.",
    # Set to your repository URL to show an "Edit on GitHub" link, e.g.
    # "https://github.com/your-org/rs6240-guide/edit/main/guide.md"
    "EDIT_URL": "https://github.com/akiimi/rs6240-info/edit/main/guide.md",
}
LIGHT_CODE_STYLE = "friendly"
DARK_CODE_STYLE = "github-dark"
# ----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent


def pygments_css() -> str:
    light = HtmlFormatter(style=LIGHT_CODE_STYLE).get_style_defs(".codehilite")
    dark = HtmlFormatter(style=DARK_CODE_STYLE).get_style_defs(".codehilite")
    # Backgrounds come from the theme variables, not from Pygments.
    strip_bg = lambda css: re.sub(r"\.codehilite\s*\{[^}]*\}", "", css)
    light, dark = strip_bg(light), strip_bg(dark)
    scoped_dark = "\n".join(
        f':root[data-theme="dark"] {line}' for line in dark.splitlines() if line.startswith(".codehilite")
    )
    auto_dark = "\n".join(
        f':root:not([data-theme="light"]) {line}' for line in dark.splitlines() if line.startswith(".codehilite")
    )
    return f"{light}\n{scoped_dark}\n@media (prefers-color-scheme: dark) {{\n{auto_dark}\n}}\n.codehilite {{ background: none; }}"


def build_toc(tokens) -> str:
    def walk(items, depth):
        if not items or depth > 3:
            return ""
        out = ["<ul>"]
        for t in items:
            out.append(f'<li><a href="#{t["id"]}">{html.escape(t["name"])}</a>')
            out.append(walk(t.get("children", []), depth + 1))
            out.append("</li>")
        out.append("</ul>")
        return "".join(out)
    return walk(tokens, 2)


def task_lists(body: str) -> str:
    counter = {"n": 0}

    def repl(m):
        counter["n"] += 1
        checked = m.group(1).lower() == "x"
        return (f'<li><input type="checkbox" data-id="{counter["n"]}" aria-label="Mark as done"'
                f'{" checked" if checked else ""}><span>')

    body = re.sub(r"<li>\s*(?:<p>)?\s*\[([ xX])\]\s*", repl, body)
    # close the span opened above, at the end of each task item
    body = re.sub(r"(<li><input type=\"checkbox\"[^>]*><span>.*?)(</li>)", r"\1</span>\2", body, flags=re.S)
    body = re.sub(r"<ul>(\s*<li><input type=\"checkbox\")", r'<ul class="task-list">\1', body)
    return body


def main() -> None:
    source = (ROOT / "guide.md").read_text(encoding="utf-8")
    md = markdown.Markdown(
        extensions=["extra", "admonition", "sane_lists", "codehilite", "toc"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "toc": {"permalink": "#", "permalink_class": "anchor", "permalink_title": "Link to this section",
                    "toc_depth": "2-3"},
        },
    )
    body = md.convert(source)
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)
    body = task_lists(body)

    edit = ""
    if CONFIG["EDIT_URL"]:
        edit = f'<div><dt>Source</dt><dd><a href="{html.escape(CONFIG["EDIT_URL"])}">Edit on GitHub</a></dd></div>'

    page = (ROOT / "template.html").read_text(encoding="utf-8")
    replacements = {
        "{{TITLE}}": html.escape(CONFIG["TITLE"]),
        "{{SHORT_TITLE}}": html.escape(CONFIG["SHORT_TITLE"]),
        "{{SUBTITLE}}": html.escape(CONFIG["SUBTITLE"]),
        "{{UPDATED}}": dt.date.today().strftime("%d %b %Y"),
        "{{EDIT_LINK}}": edit,
        "{{TOC}}": build_toc(md.toc_tokens),
        "{{PYGMENTS_CSS}}": pygments_css(),
        "{{CONTENT}}": body,
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    (ROOT / "index.html").write_text(page, encoding="utf-8")
    print(f"Wrote index.html ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
