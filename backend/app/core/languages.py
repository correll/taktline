"""The languages the product speaks — one allowlist, used by every door.

The set is chosen for who actually works on the shop floors this product
serves (Spanish, Haitian Creole and Burmese are the languages of Indiana
manufacturing workforces, not a marketing wishlist), and it is deliberately a
**data file**: adding a language is one line here plus a dictionary column in
`frontend/src/i18n/strings.ts`. Codes are BCP 47.

Three doors read this list, differently:

- **Signup** (a brand-new account) may pick any language here.
- **A company** declares which subset it supports (Settings → Global,
  `global_settings.supportedLanguages`) — the admin is promising that lot
  cards, station names and instructions will make sense in these languages.
- **An invited operator** picks from the company's subset, not from the whole
  list: offering a language the company does not run in would hand them a UI
  their supervisor cannot read over their shoulder.

The user's choice lives in `users.preferences["language"]` — the existing
cross-device personal blob — so there is no schema change and no migration on
the user side, and it travels with the account to every device.
"""

from __future__ import annotations

#: code → endonym (the language's own name for itself — a picker that says
#: "Burmese" to someone looking for မြန်မာ has failed at its one job).
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Español",
    "fr-CA": "Français (Canada)",
    "my": "မြန်မာ",
    "ht": "Kreyòl ayisyen",
}

DEFAULT_LANGUAGE = "en"


def valid(code: str | None) -> bool:
    return code in LANGUAGES


def clean_supported(codes: list[str]) -> list[str]:
    """Validate a company's supported set: known codes, deduped in the order
    given, never empty. Raises ValueError with a sentence someone can act on."""
    seen: list[str] = []
    for code in codes:
        if code not in LANGUAGES:
            raise ValueError(f"Unknown language '{code}' — supported: "
                             f"{', '.join(LANGUAGES)}")
        if code not in seen:
            seen.append(code)
    if not seen:
        raise ValueError("A company must support at least one language")
    return seen
