"""The Apify actor's input contract, which is narrower than our own UI's.

`activeStatus` on the actor accepts ONLY "", "active" or "inactive". Our UI
(and page_resolver, which searches for a competitor's ads regardless of
whether they are still running) says "ALL", and "all" is rejected with HTTP
400 before a single ad is fetched — the run fails, nothing is billed, and the
user sees a raw provider error. So the mapping is tested, not assumed.
"""
from unittest.mock import patch

from app.services.ad_library.apify import (
    actor_active_status,
    build_library_url,
    search,
)

# What the actor's own schema allows. Anything else is a 400.
ALLOWED = {"", "active", "inactive"}


def test_every_status_our_code_passes_is_one_the_actor_allows():
    for value in ["ALL", "all", "ACTIVE", "active", "INACTIVE", "inactive", "", None]:
        assert actor_active_status(value) in ALLOWED


def test_all_means_do_not_filter_rather_than_the_literal_word():
    assert actor_active_status("ALL") == ""
    assert actor_active_status("ACTIVE") == "active"
    assert actor_active_status("INACTIVE") == "inactive"


def test_search_sends_the_actor_an_allowed_status():
    with patch("app.services.ad_library.apify._run_actor", return_value=[]) as run:
        search(query="cupid love hotel", country="VN", active_status="ALL", limit=8)

    assert run.call_args.args[0]["activeStatus"] in ALLOWED


def test_the_ad_library_url_keeps_all_which_meta_itself_understands():
    # Only the actor input is this narrow — the web surface we point it at
    # takes active_status=all, and narrowing that too would silently drop
    # every competitor ad that has stopped running.
    assert "active_status=all" in build_library_url(query="x", country="VN", active_status="ALL")
