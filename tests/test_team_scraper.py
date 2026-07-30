import pytest
from fastapi import HTTPException

from api.scrapers.teams import (
    vlr_team,
    vlr_team_matches,
    vlr_team_transactions,
)
from api.scrapers.teams.parsers import _extract_prize_from_text
from utils.cache_manager import cache_manager


class FakeResponse:
    def __init__(self, status_code: int, text: str = "<html></html>"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers: dict = {}


class FakeAsyncClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[tuple[str, int | None]] = []

    async def get(self, url: str, timeout=None, headers=None):
        self.calls.append((url, timeout))
        return self.response


@pytest.mark.anyio
async def test_team_profile_returns_light_and_dark_logo_variants(monkeypatch):
    cache_manager.clear_all()
    light_html = """
    <html><div class="team-header">
      <div class="team-header-logo"><img src="//owcdn.net/img/team-light.png"></div>
      <div class="team-header-name"><h1>Example</h1><h2>EX</h2></div>
    </div></html>
    """
    dark_html = light_html.replace("team-light.png", "team-dark.png")

    async def fake_fetch_theme_variants(url, *, client=None):
        assert url == "https://www.vlr.gg/team/77"
        return FakeResponse(200, light_html), FakeResponse(200, dark_html)

    monkeypatch.setattr(
        "api.scrapers.teams.crawlers.fetch_theme_variants",
        fake_fetch_theme_variants,
    )
    monkeypatch.setattr("api.scrapers.teams.crawlers.get_http_client", lambda: object())

    result = await vlr_team("77")
    team = result["data"]["segments"][0]

    assert team["logo"] == "https://owcdn.net/img/team-light.png"
    assert team["logo_light"] == "https://owcdn.net/img/team-light.png"
    assert team["logo_dark"] == "https://owcdn.net/img/team-dark.png"
    cache_manager.clear_all()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1st $50,0002024", "$50,000"),
        ("2nd $2,024", "$2,024"),
        ("special prize $2024", "$2024"),
        ("winner $100K 2024", "$100K"),
        ("no prize here", ""),
        ("", ""),
    ],
)
def test_extract_prize_from_text_handles_concatenated_years(text, expected):
    assert _extract_prize_from_text(text) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scraper", "args", "expected_status", "expected_detail"),
    [
        (vlr_team, ("77",), 404, "VLR.GG returned status 404 for team 77"),
        (
            vlr_team_matches,
            ("77", 3),
            503,
            "VLR.GG returned status 503 for team matches 77 page 3",
        ),
        (
            vlr_team_transactions,
            ("77",),
            429,
            "VLR.GG returned status 429 for team transactions 77",
        ),
    ],
)
async def test_team_scrapers_raise_http_errors_for_upstream_failures(
    monkeypatch, scraper, args, expected_status, expected_detail
):
    client = FakeAsyncClient(FakeResponse(expected_status))

    monkeypatch.setattr("api.scrapers.teams.crawlers.get_http_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await scraper(*args)

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
