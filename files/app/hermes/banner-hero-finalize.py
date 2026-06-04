#!/usr/bin/env python3
from pathlib import Path

path = Path('/opt/hermes-agent/src/hermes_cli/banner.py')
s = path.read_text()

s = s.replace('from rich.ansi import AnsiDecoder\n', '')
if 'import re\n' not in s:
    s = s.replace('import os\n', 'import os\nimport re\n', 1)
if 'from rich.segment import ControlType, Segment\n' not in s:
    s = s.replace('from rich.panel import Panel\n', 'from rich.panel import Panel\nfrom rich.segment import ControlType, Segment\n', 1)

raw_block = r'''_CSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class _RawAnsiHero:
    """Raw ANSI terminal art with Rich-compatible measurement.

    Direct terminal output for Joy's half-block mascot art is already correct.
    Rich's AnsiDecoder can preserve the glyph grid but re-emits truecolor
    through the surrounding console's color policy, which can corrupt the TUI
    rendering. Yield the original SGR bytes as zero-width control segments and
    the glyph/space cells as normal text segments, so Rich measures rows by
    terminal cells while the terminal receives the original ANSI stream.
    """

    def __init__(self, ansi: str):
        self.ansi = ansi

    def __rich_console__(self, console, options):
        for line in self.ansi.splitlines():
            pos = 0
            for match in _CSI_RE.finditer(line):
                if match.start() > pos:
                    yield Segment(line[pos:match.start()])
                # Mark escape/control bytes zero-width for Rich measurement,
                # while preserving the exact SGR stream in output.
                yield Segment(match.group(0), None, [(ControlType.CARRIAGE_RETURN,)])
                pos = match.end()
            if pos < len(line):
                yield Segment(line[pos:])
            yield Segment.line()


def _banner_hero_renderable(hero: str):
    """Render banner hero art without mixing it into surrounding markup."""
    if "\x1b" in hero:
        return _RawAnsiHero(hero)
    return Text.from_markup(hero)


def _banner_markup(markup: str) -> Text:
    """Parse regular one-line banner markup into a Rich Text renderable."""
    return Text.from_markup(markup)
'''

candidates = [
    idx for idx in [
        s.find('_CSI_RE = re.compile'),
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
    raise SystemExit('could not find banner helper region end')
s = s[:start] + raw_block + '\n' + s[end:]

rej = path.with_suffix(path.suffix + '.rej')
if rej.exists():
    rej.unlink()

path.write_text(s)
