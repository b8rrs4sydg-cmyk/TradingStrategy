"""A browser page without prices is a failure to read unless Google says there is no flight."""

from app.providers.google_flights import classify_page


def test_loading_page_is_slow_not_empty():
    assert classify_page("Flight search | Multi-city | Loading results | Filters") == "timeout"


def test_google_error_page_is_an_error():
    assert classify_page("Search results | No results returned. | Oops, something went wrong. | Reload") == "error"


def test_unknown_page_is_never_proof_of_no_flight():
    assert classify_page("some other page") == "timeout"


def test_explicit_empty_state_is_no_result():
    assert classify_page("Search results | No flights found for these dates") == "no_result"
