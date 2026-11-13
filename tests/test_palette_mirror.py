"""The Tauri palette is documented as mirroring `config.py`. Nothing enforced it,
and `DANGER` had drifted to a different colour in each file (X1). These tests are
the enforcement, so the next edit to one side fails loudly instead of silently
splitting the two front-ends' idea of a colour.
"""

import re
from pathlib import Path

import pytest

import zugzwang.config as C

APP_CSS = Path(__file__).resolve().parent.parent / "desktop" / "src" / "app.css"

# CSS custom property → the `config.py` name holding the same colour, per theme.
DARK = {
    "--bg-deep": "BG_DEEP",
    "--bg-surface": "BG_SURFACE",
    "--bg-raised": "BG_RAISED",
    "--accent": "ACCENT",
    "--text": "TEXT",
    "--text-muted": "TEXT_MUTED",
    "--divider": "DIVIDER",
    "--danger": "DANGER",
    "--board-light": "BOARD_LIGHT",
    "--board-dark": "BOARD_DARK",
}
LIGHT = {
    "--bg-deep": "LIGHT_BG_DEEP",
    "--bg-surface": "LIGHT_BG_SURFACE",
    "--bg-raised": "LIGHT_BG_RAISED",
    "--accent": "LIGHT_ACCENT",
    "--text": "LIGHT_TEXT",
    "--text-muted": "LIGHT_TEXT_MUTED",
    "--divider": "LIGHT_DIVIDER",
    "--danger": "LIGHT_DANGER",
}


def _block(css: str, selector: str) -> dict[str, str]:
    """The custom properties declared directly in one selector's block.

    The selector has to be anchored to the start of a line: `[data-theme='light']`
    also appears in the file's header comment, and matching that silently returns
    `:root`'s declarations instead — which looks like a passing mirror.
    """
    m = re.search(rf"^{re.escape(selector)}\s*\{{", css, re.MULTILINE)
    assert m, f"no rule for {selector} in {APP_CSS.name}"
    body = css[m.end() : css.index("\n}", m.end())]
    return {
        m.group(1): m.group(2).strip().lower()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


@pytest.fixture(scope="module")
def css() -> str:
    return APP_CSS.read_text()


@pytest.mark.parametrize("prop,const", sorted(DARK.items()))
def test_dark_tokens_match_config(css, prop, const):
    assert _block(css, ":root")[prop] == getattr(C, const).lower(), (
        f"{prop} in app.css :root disagrees with config.{const}"
    )


@pytest.mark.parametrize("prop,const", sorted(LIGHT.items()))
def test_light_tokens_match_config(css, prop, const):
    assert _block(css, "[data-theme='light']")[prop] == getattr(C, const).lower(), (
        f"{prop} in app.css [data-theme='light'] disagrees with config.{const}"
    )


def test_board_is_constant_across_themes(css):
    # The wood board is the identity anchor and is deliberately *not* themed, so
    # a light-theme override would be a regression rather than a drift.
    light = _block(css, "[data-theme='light']")
    assert "--board-light" not in light
    assert "--board-dark" not in light
