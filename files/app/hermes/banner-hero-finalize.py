#!/usr/bin/env python3
from pathlib import Path

path = Path('/opt/hermes-agent/src/hermes_cli/banner.py')
s = path.read_text()

s = s.replace('import re\n', '')
s = s.replace('from rich.segment import ControlType, Segment\n', '')

helper = """def _banner_hero_renderable(hero: str) -> Text:
    \"\"\"Render banner hero art as fixed-width, non-wrapping Rich markup.

    The accepted Talon/Star source art is the safe 39-column half-block ANSI
    artifact. Hiera stores a faithful Rich-markup conversion of that artifact
    because the banner path is a Rich renderer. Keep the hero isolated and
    non-wrapping so Rich table measurement may not squeeze sparse rows down to
    their minimum width and scatter cells across columns.
    \"\"\"
    text = Text.from_markup(hero, emoji=False, overflow=\"ignore\")
    text.no_wrap = True
    return text


def _banner_markup(markup: str) -> Text:
    \"\"\"Parse regular one-line banner markup into a Rich Text renderable.\"\"\"
    return Text.from_markup(markup)
"""

candidates = [
    idx for idx in [
        s.find('_CSI_RE = re.compile'),
        s.find('class _RawAnsiHero'),
        s.find('def _banner_hero_renderable'),
    ]
    if idx != -1
]
if not candidates:
    raise SystemExit('could not find banner helper insertion point')
start = min(candidates)
marker = '# =========================================================================\n# ASCII Art & Branding'
end = s.find(marker, start)
if end == -1:
    raise SystemExit('could not find ASCII art marker')
s = s[:start] + helper + '\n' + s[end:]

s = s.replace(
    '    layout_table.add_column("left", justify="center")\n'
    '    layout_table.add_column("right", justify="left")\n',
    '    layout_table.add_column("left", justify="left", width=39, min_width=39, max_width=39, no_wrap=True, overflow="ignore")\n'
    '    layout_table.add_column("right", justify="left")\n',
)
s = s.replace(
    '    layout_table.add_column("left", justify="left")\n'
    '    layout_table.add_column("right", justify="left")\n',
    '    layout_table.add_column("left", justify="left", width=39, min_width=39, max_width=39, no_wrap=True, overflow="ignore")\n'
    '    layout_table.add_column("right", justify="left")\n',
)

path.write_text(s)
rej = path.with_suffix(path.suffix + '.rej')
if rej.exists():
    rej.unlink()
