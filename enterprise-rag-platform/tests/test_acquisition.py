import pytest
from app.acquisition import validate_source_url

ALLOWED = {"www.faa.gov", "ntrs.nasa.gov"}


def test_accepts_allowlisted_https_url():
    assert validate_source_url("https://www.faa.gov/uas", ALLOWED) == "www.faa.gov"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.faa.gov/uas",
        "https://127.0.0.1/admin",
        "https://www.faa.gov@example.com/uas",
        "https://user:secret@www.faa.gov/uas",
    ],
)
def test_rejects_unsafe_or_unapproved_urls(url):
    with pytest.raises(ValueError):
        validate_source_url(url, ALLOWED)
