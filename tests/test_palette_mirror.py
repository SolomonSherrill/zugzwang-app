"""The palette is kept in three places that must agree: the redesign's tokens
(`desktop/src/lib/styles/tokens.css`, generated from `design/tokens.json`), the legacy names
the not-yet-rebuilt screens read in `desktop/src/app.css` (each now resolving to a token),
and `config.py`. Nothing enforced the first mirror and `DANGER` drifted (X1); these tests are
the enforcement. Dark only since the redesign (DESIGN.md): no light-theme block may return.
"""

import re
from pathlib import Path

import pytest

import zugzwang.config as C

DESKTOP = Path(__file__).resolve().parent.parent / "desktop" / "src"
APP_CSS = DESKTOP / "app.css"
TOKENS_CSS = DESKTOP / "lib" / "styles" / "tokens.css"

# legacy CSS name → (the token it resolves to, the config.py name holding the colour)
LEGACY = {
    "--bg-deep": ("--bg", "BG_DEEP"),
    "--bg-surface": ("--surface", "BG_SURFACE"),
    "--bg-raised": ("--raised", "BG_RAISED"),
    "--accent": ("--primary", "ACCENT"),
    "--text-muted": ("--text-3", "TEXT_MUTED"),
    "--danger": ("--loss", "DANGER"),
    "--board-light": ("--board-stone-light", "BOARD_LIGHT"),
    "--board-dark": ("--board-stone-dark", "BOARD_DARK"),
}


def _block(css: str, selector: str) -> dict[str, str]:
    """The custom properties declared directly in one selector's block (the selector
    anchored to the start of a line, so a mention in a comment cannot match)."""
    m = re.search(rf"^{re.escape(selector)}\s*\{{", css, re.MULTILINE)
    assert m, f"no rule for {selector}"
    body = css[m.end() : css.index("\n}", m.end())]
    return {
        m.group(1): m.group(2).strip().lower()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def test_divider_is_the_token_not_a_legacy_alias(app_css, tokens):
    """UI-BUILD-4 E: app.css once mapped the legacy --divider onto --border, overriding the token
    --divider (#1c1d21, the row divider). It must stay the token; config.DIVIDER mirrors --border,
    the colour the legacy controls' borders read."""
    assert "--divider" not in _block(app_css, ":root")
    assert "--divider" in tokens
    assert tokens["--border"].split("/*")[0].strip() == C.DIVIDER.lower()


@pytest.fixture(scope="module")
def app_css() -> str:
    return APP_CSS.read_text()


@pytest.fixture(scope="module")
def tokens() -> dict[str, str]:
    return _block(TOKENS_CSS.read_text(), ":root")


@pytest.mark.parametrize("legacy,token,const", sorted((k, *v) for k, v in LEGACY.items()))
def test_legacy_names_resolve_to_the_token_config_mirrors(app_css, tokens, legacy, token, const):
    assert _block(app_css, ":root")[legacy] == f"var({token})", f"{legacy} should read var({token})"
    value = tokens[token].split("/*")[0].strip()
    assert value == getattr(C, const).lower(), f"config.{const} disagrees with {token}"


def test_text_is_the_token_itself(app_css, tokens):
    # --text is a token name, so app.css must not redefine it (it once did, after the tokens).
    assert "--text" not in _block(app_css, ":root")
    assert tokens["--text"].split("/*")[0].strip() == C.TEXT.lower()


def test_dark_only(app_css):
    assert not re.search(r"^\[data-theme='light'\]", app_css, re.MULTILINE)
    assert not any(name.startswith("LIGHT_") for name in vars(C))
