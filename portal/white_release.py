"""White presentation only; preserve the existing race handlers and execution logic."""
from pathlib import Path
import race_release as race

portal = race.portal
original_page_html = race.page_html


def page_html():
    html = original_page_html()
    anchor = '<section id="race-stage"'
    assert html.count(anchor) == 1
    css = Path(__file__).with_name("race_white.css").read_text()
    return html.replace(anchor, '<style id="race-white-theme">\n' + css + '\n</style>\n' + anchor, 1)


race.page_html = page_html

if __name__ == "__main__":
    portal.main()