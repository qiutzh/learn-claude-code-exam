"""String helper utilities.

Provides :func:`slugify` to turn arbitrary text into a URL-friendly slug,
e.g. ``slugify("Hello, World!") -> "hello-world"``.
"""

import re
import unicodedata


def slugify(text: str) -> str:
    """Convert *text* into a URL-friendly slug string.

    The conversion follows these rules:

    - Unicode is normalized to NFKD and diacritics are stripped, so
      ``"Café Möller"`` becomes ``"cafe-moller"``; characters that cannot
      be mapped to ASCII (e.g. CJK) are removed, so ``"你好 world"``
      becomes ``"world"``.
    - The text is lowercased, then every run of characters other than
      lowercase letters and digits (whitespace, underscores, punctuation,
      ...) is collapsed into a single hyphen.
    - Leading/trailing hyphens are stripped; empty input (or input made
      only of special characters) yields ``""``.

    Examples:
        >>> slugify("Hello World")
        'hello-world'
        >>> slugify("hello   world_foo")
        'hello-world-foo'
        >>> slugify("Hello, World!")
        'hello-world'
        >>> slugify("Café Möller")
        'cafe-moller'
        >>> slugify("你好 world")
        'world'
        >>> slugify(" Hello ")
        'hello'
        >>> slugify("!!!")
        ''
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    # Collapse every run of non-alphanumeric characters into one hyphen,
    # then drop any hyphens at the ends.
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")