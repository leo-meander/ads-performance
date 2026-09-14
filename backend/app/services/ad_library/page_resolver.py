"""Turn whatever a user pastes into a numeric Meta Page ID.

The Ad Library is indexed by Facebook **Page**, and its `view_all_page_id`
parameter only understands the numeric id. A vanity slug pasted there does not
error -- Meta simply returns nothing, which on our side is indistinguishable
from a competitor who stopped advertising. That silent failure is the whole
reason this module exists: resolve up front, or refuse with a message.

Three ways in, cheapest first:

1. The input already carries the id (`view_all_page_id=`, `profile.php?id=`,
   `/pages/Name/<id>`, or a bare number) -- free, no request at all.
2. The Page's public HTML embeds its id as `fb://profile/<id>` -- free. Note
   the User-Agent below: Facebook answers a browser UA without cookies with
   HTTP 400 and serves the public link-preview markup to declared crawlers.
3. An Ad Library keyword search, reading the page id off the competitor's own
   ads -- costs money (the provider bills per ad), so it runs last, with a
   small ceiling, and it never guesses: the match must actually look like the
   name searched for, otherwise the candidates go back for a human to pick.

Instagram has no id of its own here -- ads on Instagram are bought by a
Facebook Page, and that Page is always what gets tracked. An IG handle tries
facebook.com/<same handle> first (brands nearly always reuse the slug, and it
is free), then the paid search. Either way the caller is told which Facebook
Page the Instagram profile resolved to, because that mapping is a guess a
human should confirm.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

import requests

from app.config import settings
from app.services.ad_library.base import AdLibraryError

logger = logging.getLogger(__name__)

FACEBOOK_HOSTS = {"facebook.com", "fb.com", "fb.me"}
INSTAGRAM_HOSTS = {"instagram.com", "instagr.am", "ig.me"}
HOST_PREFIXES = ("www.", "m.", "mbasic.", "web.", "touch.", "l.", "free.")

# Path segments that are Facebook's own surfaces, never a Page handle.
FB_RESERVED = {
    "ads", "groups", "group", "marketplace", "watch", "events", "event",
    "gaming", "photo", "photos", "video", "videos", "story.php", "stories",
    "permalink.php", "sharer", "sharer.php", "share", "login", "help",
    "settings", "messages", "notes", "reel", "reels", "hashtag", "search",
    "public", "bookmarks", "media", "home.php", "business", "profile.php",
}
IG_RESERVED = {
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct",
    "about", "developer", "legal", "challenge",
}

# Anything shorter is a false positive far more often than a real page id.
_ID_RE = re.compile(r"^\d{5,}$")

# The id as it survives in public Page HTML. Ordered by how specific each
# pattern is -- "userID" is last because logged out it is often "0".
_HTML_ID_PATTERNS = [
    re.compile(r'"delegate_page"\s*:\s*\{\s*"id"\s*:\s*"(\d{5,})"'),
    re.compile(r'"pageID"\s*:\s*"(\d{5,})"'),
    re.compile(r'"page_id"\s*:\s*"?(\d{5,})"?'),
    re.compile(r"fb://page/\?id=(\d{5,})"),
    # New-style Pages expose their id only as a profile deep link.
    re.compile(r"fb://profile/(\d{5,})"),
    re.compile(r'"entity_id"\s*:\s*"(\d{5,})"'),
    re.compile(r"profile_id=(\d{5,})"),
    re.compile(r'"userID"\s*:\s*"(\d{5,})"'),
]
_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_HTML_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
# Titles that mean "you are looking at a login wall", not at a page.
_GENERIC_TITLES = {
    "facebook", "instagram", "log in to facebook", "log into facebook",
    "login • instagram", "log in • instagram", "content not available",
}

# Identify honestly as a bot. Not politeness theatre: Facebook answers a
# browser User-Agent without cookies with HTTP 400, and serves the public
# link-preview markup (which carries the page id) to self-declared crawlers.
_BOT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MeanderAdsBot/1.0; +https://staymeander.com)",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class PageCandidate:
    page_id: str
    page_name: str
    ad_count: int = 0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "page_name": self.page_name,
            "ad_count": self.ad_count,
            "score": round(self.score, 3),
        }


@dataclass
class ParsedTarget:
    """What the pasted text turned out to be."""

    kind: str  # "page_id" | "facebook" | "instagram" | "handle"
    value: str  # numeric id, or the handle
    page_name_hint: str = ""


@dataclass
class ResolvedPage:
    page_id: str
    page_name: str
    # numeric | url_param | page_html | ad_library_search
    method: str
    platform: str = "facebook"
    handle: str = ""
    note: str | None = None
    candidates: list[PageCandidate] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.page_id)

    def to_dict(self) -> dict:
        return {
            "resolved": self.resolved,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "method": self.method,
            "platform": self.platform,
            "handle": self.handle,
            "note": self.note,
            "candidates": [c.to_dict() for c in self.candidates],
        }


# -- Parsing ------------------------------------------------------------


def _normalize_host(host: str) -> str:
    host = (host or "").lower().split(":")[0]
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def _clean_handle(value: str) -> str:
    return value.strip().strip("@/").split("?")[0].split("#")[0]


def parse_target(raw: str) -> ParsedTarget:
    """Classify the pasted text. Raises with a usable message when it can't."""
    text = (raw or "").strip()
    if not text:
        raise AdLibraryError("Paste a Facebook page URL, an Instagram URL, or a Page ID.")

    if _ID_RE.match(text):
        return ParsedTarget(kind="page_id", value=text)

    if text.startswith("@"):
        return ParsedTarget(kind="handle", value=_clean_handle(text))

    if "/" not in text and "." not in text:
        # A bare word: treat it as a handle or an advertiser name.
        return ParsedTarget(kind="handle", value=_clean_handle(text))

    url = text if "://" in text else f"https://{text}"
    parsed = urlparse(url)
    host = _normalize_host(parsed.netloc)
    query = parse_qs(parsed.query or "")
    segments = [s for s in (parsed.path or "").split("/") if s]

    if host in INSTAGRAM_HOSTS:
        if not segments:
            raise AdLibraryError("That Instagram link has no profile in it.")
        handle = _clean_handle(segments[0])
        if handle.lower() in IG_RESERVED:
            raise AdLibraryError(
                "That is an Instagram post/reel link, not a profile. Paste the "
                "profile URL instead (instagram.com/their_handle)."
            )
        return ParsedTarget(kind="instagram", value=handle)

    if host not in FACEBOOK_HOSTS:
        raise AdLibraryError(
            f"'{host}' is not a Facebook or Instagram address. Paste the "
            "competitor's Facebook page URL, their Instagram profile URL, or "
            "their numeric Meta Page ID."
        )

    # The id is sometimes already in the URL -- free, exact, no lookup.
    for key in ("view_all_page_id", "page_id", "id"):
        for value in query.get(key, []):
            if _ID_RE.match(value.strip()):
                return ParsedTarget(kind="page_id", value=value.strip())

    if not segments:
        raise AdLibraryError("That Facebook link has no page in it.")

    head = segments[0].lower()
    if head in ("pages", "people", "pg"):
        # /pages/Some-Hotel/123456789 -- id last, display name before it.
        for index, seg in enumerate(segments):
            if index and _ID_RE.match(seg):
                previous = segments[index - 1]
                hint = "" if _ID_RE.match(previous) else previous.replace("-", " ").strip()
                return ParsedTarget(kind="page_id", value=seg, page_name_hint=hint)
        if head == "pg" and len(segments) > 1:
            return ParsedTarget(kind="facebook", value=_clean_handle(segments[1]))
        raise AdLibraryError("Could not find a Page ID in that Facebook link.")

    if head in ("groups", "group"):
        raise AdLibraryError(
            "That is a Facebook Group. Groups do not run ads -- paste the "
            "competitor's Page URL instead."
        )
    if head in FB_RESERVED:
        raise AdLibraryError(
            "That link does not point at a Facebook Page. Open the "
            "competitor's page and copy the URL from the address bar."
        )

    return ParsedTarget(kind="facebook", value=_clean_handle(segments[0]))


# -- Route 2: the Page's own HTML ---------------------------------------


def _fetch_html(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers=_BOT_HEADERS,
            timeout=settings.SPY_RESOLVE_HTTP_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as e:
        logger.info("[spy-resolve] %s unreachable: %s", url, e)
        return ""
    if resp.status_code >= 400:
        logger.info("[spy-resolve] %s returned %s", url, resp.status_code)
        return ""
    return resp.text or ""


# Two public surfaces for the same Page. www is tried first because its
# markup carries the id in more shapes; mbasic is the fallback for when www
# answers a datacenter IP with a login wall that has no id in it at all --
# mbasic is the stripped-down surface Facebook still serves in that case.
_PAGE_HTML_SURFACES = ("https://www.facebook.com/{h}", "https://mbasic.facebook.com/{h}")


def _title_of(html: str) -> str:
    match = _HTML_OG_TITLE_RE.search(html) or _HTML_TITLE_RE.search(html)
    if not match:
        return ""
    # Facebook escapes the title, so a Vietnamese page name arrives as
    # "Kh&#xe1;ch S&#x1ea1;n ..." -- unescape before it is stored and before
    # it is used as an Ad Library search query, where entities match nothing.
    title = re.sub(r"\s+", " ", html_lib.unescape(match.group(1))).strip()
    for suffix in (" | Facebook", " - Facebook", " | Instagram"):
        if title.lower().endswith(suffix.lower()):
            title = title[: -len(suffix)].strip()
    if title.lower() in _GENERIC_TITLES:
        return ""
    # Facebook renders page titles as "<Page name> | <City>"; keep the name.
    if "|" in title:
        head, _, tail = title.rpartition("|")
        if head.strip() and len(tail.split()) <= 4:
            title = head.strip()
    return title


def probe_facebook_page(handle: str) -> tuple[str, str]:
    """(page_id, display_name) from the public Page HTML; either may be empty.

    The name is worth keeping even when the id is not there: Facebook's login
    wall still renders the Page title often enough, and a real name searches
    the Ad Library far better than a run-together handle does.
    """
    name = ""
    for surface in _PAGE_HTML_SURFACES:
        markup = _fetch_html(surface.format(h=handle))
        if not markup:
            continue
        name = name or _title_of(markup)
        for pattern in _HTML_ID_PATTERNS:
            match = pattern.search(markup)
            if match and match.group(1) != "0":
                return match.group(1), name
    return "", name


def instagram_display_name(handle: str) -> str:
    """The human name behind an IG handle, e.g. 'Icon Lifestyle Hotel'.

    Instagram serves logged-out crawlers an og:title shaped
    "Name (@handle) • Instagram photos and videos". Searching the Ad Library
    for the name finds the advertiser; searching for 'iconlifestylehotel'
    usually finds nobody, because no page is named that.
    """
    html = _fetch_html(f"https://www.instagram.com/{handle}/")
    if not html:
        return ""
    title = _title_of(html)
    if not title:
        return ""
    name = title.split("(@")[0].split("•")[0].strip(" -–—|")
    # "Icon Lifestyle Hotel" and "iconlifestylehotel" normalize the same, and
    # the spaced one is exactly what makes the Ad Library search work -- so
    # compare raw, and only drop a name that adds literally nothing.
    if not name or name.lower() == handle.lower() or name.lower() == "instagram":
        return ""
    return name


# -- Route 3: read the id off the competitor's own ads ------------------


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _match_score(handle: str, page_name: str) -> float:
    a, b = _normalize_name(handle), _normalize_name(page_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        # Containment is strong, but "hotel" inside "grandhotelsaigon" is not
        # -- scale by how much of the longer name the match actually covers.
        return 0.75 + 0.2 * (min(len(a), len(b)) / max(len(a), len(b)))
    return SequenceMatcher(None, a, b).ratio()


def _search_candidates(
    query: str,
    aliases: list[str],
    country: str,
    provider: str | None,
) -> list[PageCandidate]:
    # Imported here because app.services.ad_library re-exports this module's
    # resolve_page; a module-level import would be circular.
    from app.services.ad_library import search_ads

    page = search_ads(
        provider=provider,
        query=query,
        country=country or "ALL",
        active_status="ALL",
        limit=settings.SPY_RESOLVE_SEARCH_LIMIT,
    )

    buckets: dict[str, PageCandidate] = {}
    for ad in page.ads:
        if not ad.page_id:
            continue
        candidate = buckets.get(ad.page_id)
        if candidate is None:
            candidate = PageCandidate(page_id=ad.page_id, page_name=ad.page_name or handle)
            buckets[ad.page_id] = candidate
        candidate.ad_count += 1
        if ad.page_name and not candidate.page_name:
            candidate.page_name = ad.page_name

    # Score against every name we know the competitor by -- the handle, and
    # the display name when a profile page gave one up.
    names = [a for a in aliases if a] or [query]
    for candidate in buckets.values():
        candidate.score = max(_match_score(name, candidate.page_name) for name in names)

    return sorted(buckets.values(), key=lambda c: (c.score, c.ad_count), reverse=True)


# -- Public entry point -------------------------------------------------


def resolve_page(
    raw: str,
    country: str = "ALL",
    provider: str | None = None,
    allow_search: bool = True,
) -> ResolvedPage:
    """Resolve pasted text to a numeric Page ID, or say what to do next.

    An unconfident match comes back with `page_id` empty and `candidates`
    filled rather than as a silent best guess -- tracking the wrong page is
    the expensive mistake here, not asking one extra question.
    """
    target = parse_target(raw)

    if target.kind == "page_id":
        return ResolvedPage(
            page_id=target.value,
            page_name=target.page_name_hint,
            method="numeric" if (raw or "").strip() == target.value else "url_param",
        )

    handle = target.value
    platform = "instagram" if target.kind == "instagram" else "facebook"
    display_name = ""

    # Instagram has no Page ID of its own, but a brand almost always uses the
    # same slug on both -- and that check is free, where the ad search is not.
    page_id, display_name = probe_facebook_page(handle)
    if page_id:
        note = None
        if platform == "instagram":
            note = (
                f"Matched facebook.com/{handle}, the Facebook Page with the same "
                "handle. Instagram ads are bought by a Facebook Page, so that is "
                "what gets tracked -- check the name above is really them."
            )
        return ResolvedPage(
            page_id=page_id,
            page_name=display_name or handle,
            method="page_html",
            platform=platform,
            handle=handle,
            note=note,
        )

    if platform == "instagram":
        # Falling through to the paid search: the profile's display name finds
        # the advertiser where a run-together handle finds nobody.
        display_name = instagram_display_name(handle) or display_name

    if not allow_search:
        raise AdLibraryError(
            f"Could not read the Page ID for '{handle}' from Facebook directly."
        )

    query = display_name or handle.replace("_", " ").replace(".", " ").strip() or handle
    candidates = _search_candidates(query, [handle, display_name], country, provider)
    if not candidates:
        raise AdLibraryError(
            f"No ads found for '{handle}' in the Ad Library, so there is no "
            "Page ID to read. Either they are not advertising in this country, "
            "or their page name differs from the handle -- try the Search tab "
            "with their brand name, then use Track page on a result."
        )

    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    confident = best.score >= 0.72 and (best.score - runner_up) >= 0.1

    if not confident:
        return ResolvedPage(
            page_id="",
            page_name="",
            method="ad_library_search",
            platform=platform,
            handle=handle,
            note=(
                f"Found {len(candidates)} advertiser(s) for '{handle}' but none "
                "clearly matches it. Pick the right page."
            ),
            candidates=candidates[:8],
        )

    note = None
    if platform == "instagram":
        note = (
            f"Instagram @{handle} advertises through the Facebook Page "
            f"'{best.page_name}' -- the Ad Library only indexes Pages."
        )

    return ResolvedPage(
        page_id=best.page_id,
        page_name=best.page_name,
        method="ad_library_search",
        platform=platform,
        handle=handle,
        note=note,
        candidates=candidates[:8],
    )


def looks_like_page_id(value: str) -> bool:
    return bool(_ID_RE.match((value or "").strip()))
