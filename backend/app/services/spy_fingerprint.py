"""Group near-duplicate competitor ads into one creative concept.

Ad-ID longevity alone understates a competitor: they routinely relaunch the
same creative under new ad IDs, so five 10-day ads can be one concept they
have trusted for months. Grouping recovers that.

No embedding provider is involved (the platform has none). Two deterministic
signals do the work:

- **Asset identity.** Meta CDN URLs carry a stable asset id in the filename
  and a volatile signature in the query string. Strip the query and two ads
  built on the same photo or video collapse together - the strongest signal
  we have, and free.
- **Copy similarity.** Token Jaccard over normalized body text catches
  re-shot creatives that keep the script, and price/date swaps of one promo.

Both feed a union-find so grouping is order-independent: whichever ad we
happen to process first, the same partition comes out.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

# Facebook CDN filenames look like `<id>_<id>_<id>_n.jpg`; the leading numeric
# run is the asset id and is what stays constant across reuses.
_CDN_ASSET_RE = re.compile(r"(\d{6,})")
_URL_RE = re.compile(r"https?://\S+")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_DIGIT_RUN_RE = re.compile(r"\d+")

# Copy boilerplate that is identical across unrelated hotel ads; leaving it in
# inflates Jaccard and glues distinct concepts together.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "your", "you", "our", "we", "is", "are", "be", "book", "now", "here",
    "va", "cua", "cho", "voi", "ban", "tai", "co", "la", "den", "duoc",
}

TEXT_SIMILARITY_THRESHOLD = 0.72
_MIN_TOKENS_FOR_TEXT_MATCH = 6


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def normalize_text(text: str) -> str:
    """Lowercase, de-accent, drop urls/punctuation, and blank out numbers.

    Numbers go because a promo relaunched at a new price or new dates is the
    same concept - which is exactly what we want grouped.
    """
    if not text:
        return ""
    out = _URL_RE.sub(" ", text.lower())
    out = _strip_accents(out)
    out = _DIGIT_RUN_RE.sub(" ", out)
    out = _NON_WORD_RE.sub(" ", out)
    return _WS_RE.sub(" ", out).strip()


def text_tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) > 2 and t not in _STOPWORDS}


def asset_key(url: str) -> str | None:
    """Reduce a CDN url to the asset it points at, or None if it has no id.

    The query string carries a per-request signature and expiry, so it must be
    dropped; the numeric run in the path is what identifies the asset.
    """
    if not url:
        return None
    path = urlparse(url).path
    ids = _CDN_ASSET_RE.findall(path)
    if not ids:
        return None
    # The longest numeric run is the asset id; the shorter ones are size and
    # revision markers that can differ between two renders of one asset.
    return max(ids, key=len)


def ad_asset_keys(image_urls, video_urls) -> set[str]:
    keys = set()
    for url in list(image_urls or []) + list(video_urls or []):
        key = asset_key(url)
        if key:
            keys.add(key)
    return keys


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def fingerprint(bodies, titles, image_urls, video_urls) -> str:
    """A stable per-ad hash.

    Prefers asset identity - two ads on the same photo get the same
    fingerprint even if the copy was rewritten. Falls back to normalized copy
    when the actor returned no media urls.
    """
    keys = sorted(ad_asset_keys(image_urls, video_urls))
    if keys:
        seed = "asset:" + "|".join(keys)
    else:
        text = " ".join(list(bodies or []) + list(titles or []))
        seed = "text:" + " ".join(sorted(text_tokens(text)))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


class _UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, k):
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def group_ads(ads: list[dict]) -> dict[str, list[str]]:
    """Partition ads into creative concepts.

    `ads` items need: id, ad_creative_bodies, ad_creative_link_titles,
    image_urls, video_urls. Returns {group_key: [ad_id, ...]}, where the group
    key is derived from its members so it survives re-runs.
    """
    if not ads:
        return {}

    ids = [a["id"] for a in ads]
    uf = _UnionFind(ids)

    assets: dict[str, set[str]] = {}
    tokens: dict[str, set[str]] = {}
    for ad in ads:
        ad_id = ad["id"]
        assets[ad_id] = ad_asset_keys(ad.get("image_urls"), ad.get("video_urls"))
        text = " ".join(
            list(ad.get("ad_creative_bodies") or [])
            + list(ad.get("ad_creative_link_titles") or [])
        )
        tokens[ad_id] = text_tokens(text)

    # Pass 1: shared asset. An inverted index keeps this linear instead of
    # comparing every pair.
    by_asset: dict[str, list[str]] = {}
    for ad_id, keys in assets.items():
        for key in keys:
            by_asset.setdefault(key, []).append(ad_id)
    for members in by_asset.values():
        for other in members[1:]:
            uf.union(members[0], other)

    # Pass 2: copy similarity, only for the pairs asset identity did not
    # already settle. Ad counts here are in the hundreds, so O(n^2) is fine.
    comparable = [i for i in ids if len(tokens[i]) >= _MIN_TOKENS_FOR_TEXT_MATCH]
    for idx, a_id in enumerate(comparable):
        for b_id in comparable[idx + 1:]:
            if uf.find(a_id) == uf.find(b_id):
                continue
            if jaccard(tokens[a_id], tokens[b_id]) >= TEXT_SIMILARITY_THRESHOLD:
                uf.union(a_id, b_id)

    clusters: dict[str, list[str]] = {}
    for ad_id in ids:
        clusters.setdefault(uf.find(ad_id), []).append(ad_id)

    # Key on the member set, not on whichever ad happened to become root, so a
    # re-run over the same ads reproduces the same group keys.
    out: dict[str, list[str]] = {}
    for members in clusters.values():
        members.sort()
        key = hashlib.sha256("|".join(members).encode("utf-8")).hexdigest()[:32]
        out[key] = members
    return out
