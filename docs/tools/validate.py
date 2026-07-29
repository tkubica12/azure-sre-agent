"""Static validation for docs/ (slides + guide): well-formed/semantic HTML,
internal link resolution, absence of CDN/hosted-asset references, absence of
Unicode emoji, WCAG contrast for the shared palette, and presence of the
accessibility/responsive/reduced-motion features AGENTS.md requires.

Dev-only checking script. Uses only the Python standard library (html.parser,
xml.dom.minidom, urllib.parse) - no new dependency is introduced. Run from
anywhere with:

    python docs/tools/validate.py

Exits 0 if every check passes, 1 otherwise, printing one PASS/FAIL line per
check plus a summary count (matching the style of labctl's own checks).
"""

from __future__ import annotations

import html.parser
import re
import sys
import unicodedata
import urllib.parse
import xml.dom.minidom
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"
HTML_FILES = [
    DOCS_ROOT / "slides" / "index.html",
    DOCS_ROOT / "guide" / "index.html",
]

FAILURES = 0
PASSES = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILURES, PASSES
    if condition:
        PASSES += 1
        print(f"PASS  {name}")
    else:
        FAILURES += 1
        suffix = f" - {detail}" if detail else ""
        print(f"FAIL  {name}{suffix}")


# --------------------------------------------------------------------------
# Well-formedness: every tag must open/close and nest correctly. We convert
# to strict XML rules using an XHTML-ish parse: html.parser tokenizes any
# soup, so we do our own stack-based balance check on start/end tags, which
# catches the class of error that matters here (typo'd or unclosed tags),
# without requiring a full XHTML self-closing dialect for void elements.
# --------------------------------------------------------------------------

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class BalanceChecker(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in VOID_ELEMENTS:
            return
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        # Self-closed tag (<foo />): does not push onto the stack.
        return

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"stray closing </{tag}> with nothing open")
            return
        if self.stack[-1] != tag:
            self.errors.append(
                f"mismatched close </{tag}>, expected </{self.stack[-1]}>"
            )
            # Best-effort recovery: pop until we find a match or empty out.
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
        else:
            self.stack.pop()


def check_well_formed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parser = BalanceChecker()
    parser.feed(text)
    parser.close()
    unclosed = [t for t in parser.stack if t not in {"html", "body"}]
    # html/body are allowed to be "closed" implicitly at EOF by the spec;
    # everything else left on the stack is a real bug.
    check(
        f"{path.relative_to(REPO_ROOT)}: tags are balanced and well-nested",
        not parser.errors and not unclosed,
        "; ".join(parser.errors + [f"unclosed: {unclosed}"] if unclosed else parser.errors),
    )


# --------------------------------------------------------------------------
# Semantic landmarks
# --------------------------------------------------------------------------


class LandmarkCollector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags_seen: set[str] = set()
        self.lang_attr: str | None = None
        self.has_meta_viewport = False
        self.has_title = False
        self.h1_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags_seen.add(tag)
        attr_dict = dict(attrs)
        if tag == "html" and "lang" in attr_dict:
            self.lang_attr = attr_dict["lang"]
        if tag == "meta" and attr_dict.get("name") == "viewport":
            self.has_meta_viewport = True
        if tag == "h1":
            self.h1_count += 1

    def handle_data(self, data: str) -> None:
        pass


def check_semantics(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parser = LandmarkCollector()
    parser.feed(text)
    rel = path.relative_to(REPO_ROOT)

    check(f"{rel}: declares lang on <html>", bool(parser.lang_attr), str(parser.lang_attr))
    check(f"{rel}: has a viewport meta tag", parser.has_meta_viewport)
    check(f"{rel}: has at least one <main>", "main" in parser.tags_seen)
    check(f"{rel}: has at least one <nav>", "nav" in parser.tags_seen)
    check(
        f"{rel}: uses sectioning elements (section)",
        "section" in parser.tags_seen,
    )
    check(f"{rel}: has exactly one <h1>", parser.h1_count == 1, f"found {parser.h1_count}")
    check(f"{rel}: has a <title>", "<title>" in text)


# --------------------------------------------------------------------------
# Internal link / asset resolution
# --------------------------------------------------------------------------


class LinkCollector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if "id" in attr_dict and attr_dict["id"]:
            self.ids.add(attr_dict["id"])
        if tag == "a" and attr_dict.get("href"):
            self.hrefs.append(attr_dict["href"])
        if tag in {"link"} and attr_dict.get("href"):
            self.srcs.append(attr_dict["href"])
        if tag in {"script", "img"} and attr_dict.get("src"):
            self.srcs.append(attr_dict["src"])


def check_links(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parser = LinkCollector()
    parser.feed(text)
    rel = path.relative_to(REPO_ROOT)

    for href in parser.hrefs:
        if href.startswith(("http://", "https://", "mailto:")):
            continue  # external citation links; not required to resolve offline
        parsed = urllib.parse.urlsplit(href)
        if parsed.path:
            target = (path.parent / urllib.parse.unquote(parsed.path)).resolve()
            check(f"{rel}: link target exists -> {href}", target.exists(), str(target))
        if parsed.fragment:
            if parsed.path:
                # Fragment into another document: verify that document has
                # a matching id (best-effort; only for local html targets).
                other = (path.parent / urllib.parse.unquote(parsed.path)).resolve()
                if other.exists() and other.suffix == ".html":
                    other_ids = LinkCollector()
                    other_ids.feed(other.read_text(encoding="utf-8"))
                    check(
                        f"{rel}: anchor #{parsed.fragment} exists in {href}",
                        parsed.fragment in other_ids.ids,
                    )
            else:
                check(
                    f"{rel}: same-document anchor #{parsed.fragment} resolves",
                    parsed.fragment in parser.ids,
                )

    for src in parser.srcs:
        if src.startswith(("http://", "https://")):
            check(f"{rel}: NO external/CDN resource reference ({src})", False, src)
            continue
        target = (path.parent / urllib.parse.unquote(src)).resolve()
        check(f"{rel}: local resource exists -> {src}", target.exists(), str(target))


def check_unique_ids(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT)
    ids = re.findall(r'\bid="([^"]+)"', text)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    check(f"{rel}: every id attribute is unique", not dupes, str(dupes))


def check_no_cdn_in_css(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT)
    matches = re.findall(r"url\(\s*['\"]?(https?://[^'\")]+)", text)
    check(f"{rel}: no external url() references in CSS", not matches, str(matches))


# --------------------------------------------------------------------------
# Emoji scan (Unicode emoji presentation / pictographic ranges)
# --------------------------------------------------------------------------

EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),  # misc symbols/pictographs through symbols & pictographs ext-A
    (0x2600, 0x27BF),  # misc symbols, dingbats
    (0x2190, 0x21FF),  # arrows (excludes plain punctuation but includes many emoji-ish arrows)
    (0x2B00, 0x2BFF),  # misc symbols and arrows
    (0xFE00, 0xFE0F),  # variation selectors
    (0x1F1E6, 0x1F1FF),  # regional indicators
]

# The deck intentionally uses a small set of plain typographic arrow glyphs
# for prev/next controls and inline "->" style notes; those are U+2190/2192
# etc. which fall in the arrows block above and would be a false positive
# for a genuine "no emoji" rule. Allow-list exactly the glyphs this deck
# uses for pure navigation/typography, not decorative emoji.
ALLOWED_CODEPOINTS = {0x2190, 0x2192, 0x2013, 0x2014}  # <- -> en/em dash


def check_no_emoji(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT)
    offenders = []
    for ch in text:
        cp = ord(ch)
        if cp in ALLOWED_CODEPOINTS:
            continue
        for lo, hi in EMOJI_RANGES:
            if lo <= cp <= hi:
                offenders.append((ch, hex(cp), unicodedata.name(ch, "UNKNOWN")))
                break
    check(f"{rel}: no Unicode emoji", not offenders, str(offenders[:10]))


# --------------------------------------------------------------------------
# CSS feature checks: focus-visible, reduced-motion, responsive breakpoints
# --------------------------------------------------------------------------


def check_css_features() -> None:
    css_files = list((DOCS_ROOT / "assets" / "css").glob("*.css"))
    css_files += list((DOCS_ROOT / "slides").glob("*.css"))
    css_files += list((DOCS_ROOT / "guide").glob("*.css"))
    combined = "\n".join(p.read_text(encoding="utf-8") for p in css_files)

    check(
        "CSS: :focus-visible style is defined (visible keyboard focus)",
        ":focus-visible" in combined,
    )
    check(
        "CSS: prefers-reduced-motion is respected",
        "prefers-reduced-motion" in combined,
    )
    check(
        "CSS: at least one narrower-than-16:9 responsive breakpoint exists",
        bool(re.search(r"@media[^{]*max-width", combined)),
    )
    check(
        "CSS: dark theme selector is defined",
        'data-theme="dark"' in combined,
    )

    # Focus visibility: an anti-pattern is removing the default outline
    # (`outline: none`/`outline: 0`) somewhere other than the one paired
    # `:focus { outline: none; }` + `:focus-visible { outline: ... }` combo
    # in base.css - that combo is fine (keyboard focus is restored via
    # :focus-visible), but a stray unconditional removal elsewhere would
    # silently break visible focus for that selector.
    combined_no_comments = re.sub(r"/\*.*?\*/", "", combined, flags=re.DOTALL)
    outline_none_selectors = re.findall(
        r"([^\{\}]+)\{[^\{\}]*outline\s*:\s*(?:none|0)\b[^\{\}]*\}", combined_no_comments
    )
    stray = [
        sel.strip()
        for sel in outline_none_selectors
        if ":focus-visible" not in sel and sel.strip() != ":focus"
    ]
    check(
        "CSS: no stray unconditional outline removal outside :focus/:focus-visible",
        not stray,
        str(stray),
    )

    # Overflow/viewport: the deck must not rely on fixed pixel widths large
    # enough to force horizontal scrolling at narrower-than-16:9 viewports.
    # Flag any block-level `width: <big>px` declaration that is not paired
    # with a `max-width` in the same rule.
    oversized_fixed_widths = []
    for rule_selector, rule_body in re.findall(r"([^\{\}]+)\{([^\{\}]*)\}", combined):
        widths = re.findall(r"(?<![-\w])width\s*:\s*(\d+)px", rule_body)
        if widths and "max-width" not in rule_body and int(widths[0]) > 700:
            oversized_fixed_widths.append((rule_selector.strip(), widths[0] + "px"))
    check(
        "CSS: no unguarded fixed pixel width > 700px without a max-width (overflow risk)",
        not oversized_fixed_widths,
        str(oversized_fixed_widths),
    )
    check(
        "CSS: slide surface manages overflow explicitly (no silent clipping/scrolling)",
        bool(re.search(r"\.slide\s*\{[^\}]*overflow\s*:\s*auto", combined)),
    )


def check_viewport_meta() -> None:
    for path in HTML_FILES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        match = re.search(r'<meta\s+name="viewport"\s+content="([^"]+)"', text)
        check(
            f"{rel}: viewport meta content includes width=device-width",
            bool(match and "width=device-width" in match.group(1)),
            match.group(1) if match else "no viewport meta found",
        )


# --------------------------------------------------------------------------
# Keyboard navigation and fragment accessibility (static source checks;
# behavioral/DOM checks for the same features live in validate.mjs)
# --------------------------------------------------------------------------

REQUIRED_NAV_KEYS = [
    "ArrowRight",
    "ArrowLeft",
    "ArrowUp",
    "ArrowDown",
    "PageUp",
    "PageDown",
    "Home",
    "End",
]


def check_required_nav_keys() -> None:
    slides_js = (DOCS_ROOT / "slides" / "slides.js").read_text(encoding="utf-8")
    missing = [key for key in REQUIRED_NAV_KEYS if f'"{key}"' not in slides_js]
    check(
        "slides.js: every AGENTS.md-required arrow/paging key is handled",
        not missing,
        f"missing: {missing}",
    )
    check(
        'slides.js: Space (" ") is handled for forward navigation',
        '" "' in slides_js or "' '" in slides_js,
    )
    check(
        "slides.js: F toggles full screen",
        bool(re.search(r'case\s+["\']f["\']', slides_js, re.IGNORECASE)),
    )


def check_fragment_accessibility() -> None:
    slides_js = (DOCS_ROOT / "slides" / "slides.js").read_text(encoding="utf-8")
    slides_css = (DOCS_ROOT / "slides" / "slides.css").read_text(encoding="utf-8")
    slides_html = (DOCS_ROOT / "slides" / "index.html").read_text(encoding="utf-8")
    sets_aria_hidden_on_fragments = bool(
        re.search(r'aria-hidden["\'],\s*String\(!revealed\)', slides_js)
    ) and "fragmentsIn" in slides_js
    check(
        "slides.js: fragments' aria-hidden is synchronized with reveal state",
        sets_aria_hidden_on_fragments,
    )
    check(
        "slides.js: newly revealed fragments are announced to assistive technology",
        "fragment-announcer" in slides_html and "fragmentAnnouncer" in slides_js,
    )
    check(
        "slides.css: .fragment visual reveal state is defined",
        ".fragment" in slides_css and "is-revealed" in slides_css,
    )


# --------------------------------------------------------------------------
# Offline / no-network guarantee: nothing in docs/ may depend on a live
# network fetch at runtime.
# --------------------------------------------------------------------------


def check_offline_no_network() -> None:
    js_files = list((DOCS_ROOT / "assets" / "js").glob("*.js")) + list(
        DOCS_ROOT.glob("*/*.js")
    )
    offenders = []
    for path in js_files:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"https?://[^\s\"'()]+", text):
            offenders.append((str(path.relative_to(REPO_ROOT)), match.group(0)))
        if re.search(r"\bfetch\s*\(|XMLHttpRequest|\bimport\s*\(", text):
            offenders.append((str(path.relative_to(REPO_ROOT)), "network/dynamic-import call"))
    check(
        "docs/*.js: no runtime network calls or hardcoded remote URLs",
        not offenders,
        str(offenders),
    )


# --------------------------------------------------------------------------
# Contrast (WCAG 2.1) for the declared token palette
# --------------------------------------------------------------------------


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    la, lb = max(la, lb), min(la, lb)
    return (la + 0.05) / (lb + 0.05)


def _parse_theme_tokens() -> dict[str, dict[str, str]]:
    """Parse actual custom-property values out of tokens.css instead of
    duplicating them as literal constants here - a contrast check against
    hardcoded copies of the palette cannot catch a real token edit that
    breaks contrast. Returns {"light": {token: hex}, "dark": {token: hex}}.
    """
    text = (DOCS_ROOT / "assets" / "css" / "tokens.css").read_text(encoding="utf-8")

    def block_for(selector_pattern: str) -> str:
        match = re.search(selector_pattern + r"\s*\{([^}]*)\}", text, re.DOTALL)
        return match.group(1) if match else ""

    light_block = block_for(r":root")
    dark_block = block_for(r'html\[data-theme="dark"\]')

    def tokens_in(block: str) -> dict[str, str]:
        return {
            name: value.strip()
            for name, value in re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", block)
        }

    return {"light": tokens_in(light_block), "dark": tokens_in(dark_block)}


def check_contrast() -> None:
    tokens = _parse_theme_tokens()
    # Light theme tokens are the base; dark-theme values fall back to the
    # light value for any token dark mode does not override, exactly like
    # the cascade the browser applies.
    resolved = {
        "light": tokens["light"],
        "dark": {**tokens["light"], **tokens["dark"]},
    }

    # (foreground token, background token, minimum ratio, why) - references
    # actual token *names*, resolved per theme above, not literal hex values.
    pairs = [
        ("--text", "--bg", 4.5, "body text on page background"),
        ("--text-muted", "--bg", 4.5, "muted text on page background"),
        ("--accent-strong", "--bg", 4.5, "accent-strong link text on page background"),
        ("--accent-contrast", "--accent", 4.5, "accent-contrast text on solid accent button"),
        ("--control-border", "--bg", 3.0, "control border on page background (UI component)"),
        ("--focus-ring", "--bg", 3.0, "focus ring on page background"),
    ]
    for theme in ("light", "dark"):
        palette = resolved[theme]
        for fg_token, bg_token, minimum, why in pairs:
            fg = palette.get(fg_token)
            bg = palette.get(bg_token)
            name = f"contrast {theme}: {why} ({fg_token} on {bg_token}, >= {minimum})"
            if not fg or not bg:
                check(name, False, f"token missing: fg={fg_token}={fg} bg={bg_token}={bg}")
                continue
            ratio = _contrast(fg, bg)
            check(name, ratio >= minimum, f"{ratio:.2f}:1 (need >= {minimum}); {fg} on {bg}")


# --------------------------------------------------------------------------
# XML strictness (extra check specifically for the vendored SVG asset)
# --------------------------------------------------------------------------


def check_svg_well_formed() -> None:
    svg_path = DOCS_ROOT / "assets" / "diagrams" / "architecture.svg"
    try:
        xml.dom.minidom.parse(str(svg_path))
        ok = True
        detail = ""
    except Exception as exc:  # noqa: BLE001 - report any parse failure as a check
        ok = False
        detail = str(exc)
    check(f"{svg_path.relative_to(REPO_ROOT)}: is well-formed XML", ok, detail)


def main() -> int:
    for path in HTML_FILES:
        check_well_formed(path)
        check_semantics(path)
        check_links(path)
        check_no_emoji(path)
        check_unique_ids(path)

    for css in (
        list((DOCS_ROOT / "assets" / "css").glob("*.css"))
        + list((DOCS_ROOT / "slides").glob("*.css"))
        + list((DOCS_ROOT / "guide").glob("*.css"))
    ):
        check_no_cdn_in_css(css)
        check_no_emoji(css)

    for js in list((DOCS_ROOT / "assets" / "js").glob("*.js")) + list(
        DOCS_ROOT.glob("*/*.js")
    ):
        check_no_emoji(js)

    check_css_features()
    check_viewport_meta()
    check_required_nav_keys()
    check_fragment_accessibility()
    check_offline_no_network()
    check_contrast()
    check_svg_well_formed()

    print(f"\n{PASSES} passed, {FAILURES} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
