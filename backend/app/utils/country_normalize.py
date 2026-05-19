"""Normalize raw PMS country strings into ISO-3166-1 alpha-2 codes.

Cloudbeds returns country in mixed format depending on the source (OTA vs Web
vs Walk-in): full English names, ISO-2 codes, and junk values ("Unknown",
"00", "0", None) all coexist. To make booking-match country comparison
reliable, we normalize to ISO-2 once at sync time and store it on the
reservation. Downstream code can then compare ad-side ISO directly to
reservation-side ISO, no fuzzy substring matching needed.

The function is defensive on purpose: it must never raise, and any value it
can't confidently map returns None (the caller treats that as "country
unknown" and applies the appropriate fallback).
"""

from __future__ import annotations

import pycountry

# Strings Cloudbeds returns when no country is set. All map to None.
_JUNK_VALUES = {"", "unknown", "00", "0", "n/a", "na", "null", "none", "-"}

# Hand-curated overrides for PMS strings that pycountry either gets wrong or
# returns in a form that doesn't match common Cloudbeds output. Keep this list
# tight — only add an entry after seeing the string in production data.
_OVERRIDES: dict[str, str] = {
    # USA — Cloudbeds emits at least three variants
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "u.s.a": "US",
    "u.s.a.": "US",
    "america": "US",

    # UK — Cloudbeds uses "United Kingdom" (full) or "UK" (alias). pycountry
    # accepts "United Kingdom" but not bare "UK"; we add both for safety.
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",

    # Korea — explicit South/North split so we don't fuzzy-match "Korea" to
    # the wrong one. pycountry's "Korea, Republic of" / "Korea, Democratic
    # People's Republic of" are unwieldy; intercept the friendly forms first.
    "south korea": "KR",
    "korea": "KR",            # Cloudbeds defaults to ROK when ambiguous
    "republic of korea": "KR",
    "north korea": "KP",
    "dprk": "KP",

    # China/Taiwan/Hong Kong/Macau — disambiguate explicitly so substring
    # collisions like "Macau SAR China" → CN don't happen.
    "china": "CN",
    "people's republic of china": "CN",
    "mainland china": "CN",
    "taiwan": "TW",
    "taipei": "TW",
    "chinese taipei": "TW",
    "taiwan, province of china": "TW",
    "taiwan province of china": "TW",
    "republic of china": "TW",
    "hong kong": "HK",
    "hong kong sar": "HK",
    "hong kong sar china": "HK",
    "macau": "MO",
    "macao": "MO",
    "macau sar": "MO",
    "macau sar china": "MO",
    "macao sar china": "MO",

    # Other Asia commonly seen in PMS but worth pinning
    "vietnam": "VN",
    "viet nam": "VN",
    "việt nam": "VN",
    "japan": "JP",
    "nhật": "JP",
    "đài loan": "TW",
    "myanmar": "MM",
    "burma": "MM",
    "laos": "LA",
    "lao": "LA",
    "lao pdr": "LA",

    # Russia variants
    "russia": "RU",
    "russian federation": "RU",

    # Czech variants
    "czech republic": "CZ",
    "czechia": "CZ",

    # Turkey — renamed to "Türkiye" in ISO-3166 in 2022; pycountry stopped
    # recognising the plain English form, so map it explicitly.
    "turkey": "TR",
    "türkiye": "TR",
    "turkiye": "TR",

    # Misc historic variants we've seen on OTAs
    "ivory coast": "CI",
    "cape verde": "CV",
    "east timor": "TL",
    "timor-leste": "TL",
}


def _looks_like_iso2(s: str) -> bool:
    """True if the string is a plausible ISO-2 code (two ASCII letters)."""
    return len(s) == 2 and s.isalpha() and s.isascii()


def normalize_country_to_iso(raw: str | None) -> str | None:
    """Convert a raw PMS country value into an ISO-3166-1 alpha-2 code.

    Returns None if the input is empty/junk or can't be confidently mapped.
    """
    if not raw:
        return None

    cleaned = raw.strip()
    if not cleaned:
        return None

    lowered = cleaned.lower()
    if lowered in _JUNK_VALUES:
        return None

    # 1. Manual overrides take precedence — they cover the variants pycountry
    # doesn't handle correctly or doesn't see in production data.
    override = _OVERRIDES.get(lowered)
    if override:
        return override

    # 2. Plausible ISO-2 input — uppercase and validate via pycountry.
    if _looks_like_iso2(cleaned):
        upper = cleaned.upper()
        if pycountry.countries.get(alpha_2=upper) is not None:
            return upper
        # 2-letter but not a real ISO code ("AA", "ZZ", random initials)
        return None

    # 3. Try pycountry's name lookup. fuzzy_search picks up minor punctuation/
    # casing differences; we accept only the top hit when its score is high.
    try:
        country = pycountry.countries.lookup(cleaned)
        return country.alpha_2
    except LookupError:
        pass

    # 4. Last resort: fuzzy search. We only trust it when it returns exactly
    # one candidate — multiple matches mean the input was ambiguous and we'd
    # rather return None than guess wrong.
    try:
        candidates = pycountry.countries.search_fuzzy(cleaned)
    except LookupError:
        return None
    if len(candidates) == 1:
        return candidates[0].alpha_2

    return None
