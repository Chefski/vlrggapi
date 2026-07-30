import asyncio

import pytest

from api.scrapers.match_detail import vlr_match_detail
from api.scrapers.match_detail.parsers import (
    _parse_economy,
    _parse_event_info,
    _parse_head_to_head,
    _parse_kill_matrix,
    _parse_maps,
    _parse_match_header,
    _parse_streams_vods,
)
from utils.cache_manager import cache_manager
from utils.html_parsers import parse_html

PLAYER_ROW = """
<tr>
  <td class="mod-player"><div class="text-of">TenZ</div></td>
  <td class="mod-agents"><img alt="Jett"></td>
  <td>1.20</td>
  <td>250</td>
  <td>20</td>
  <td>15</td>
  <td>5</td>
  <td>+5</td>
  <td>75%</td>
  <td>160</td>
  <td>30%</td>
  <td>3</td>
  <td>2</td>
  <td>+1</td>
</tr>
"""


BASE_MATCH_HTML = f"""
<html>
  <a class="match-header-link wf-link-hover mod-1" href="/team/100/team-one">
    <div class="match-header-link-name mod-1">
      <div class="wf-title-med">Team One</div>
      <div>ONE</div>
    </div>
  </a>
  <a class="match-header-link wf-link-hover mod-2" href="/team/200/team-two">
    <div class="match-header-link-name mod-2">
      <div class="wf-title-med">Team Two</div>
      <div>TWO</div>
    </div>
  </a>
  <div class="vm-stats-gamesnav-item" data-game-id="game-1"></div>
  <div class="vm-stats-gamesnav-item" data-game-id="game-2"></div>

  <div class="vm-stats-game" data-game-id="game-1">
    <div class="vm-stats-game-header">
      <div class="map">Ascent<div class="picked">Team One</div><div class="map-duration">30:00</div></div>
      <div class="team"><div class="score">13</div><div class="mod-ct">7</div><div class="mod-t">6</div></div>
      <div class="team"><div class="score">11</div><div class="mod-ct">5</div><div class="mod-t">6</div></div>
    </div>
    <table class="wf-table-inset mod-overview"><tbody>{PLAYER_ROW}</tbody></table>
    <table class="wf-table-inset mod-overview"><tbody>{PLAYER_ROW}</tbody></table>
  </div>

  <div class="vm-stats-game" data-game-id="game-2">
    <div class="vm-stats-game-header">
      <div class="map">Bind<div class="picked">Team Two</div><div class="map-duration">32:00</div></div>
      <div class="team"><div class="score">10</div><div class="mod-ct">4</div><div class="mod-t">6</div></div>
      <div class="team"><div class="score">13</div><div class="mod-ct">7</div><div class="mod-t">6</div></div>
    </div>
    <table class="wf-table-inset mod-overview"><tbody>{PLAYER_ROW}</tbody></table>
    <table class="wf-table-inset mod-overview"><tbody>{PLAYER_ROW}</tbody></table>
  </div>
</html>
"""

LIGHT_MATCH_HTML = BASE_MATCH_HTML.replace(
    "</html>",
    """
    <div class="match-header-event"><img src="//owcdn.net/img/event-light.png"></div>
    <div class="match-header-vs">
      <img src="//owcdn.net/img/team-one-light.png">
      <img src="//owcdn.net/img/team-two-light.png">
    </div>
    </html>
    """,
)
DARK_MATCH_HTML = LIGHT_MATCH_HTML.replace("-light.png", "-dark.png")


def performance_html(opponent_name: str) -> str:
    return f"""
    <html>
      <table class="wf-table-inset mod-matrix mod-normal">
        <thead><tr><th>Player</th><th>{opponent_name}</th></tr></thead>
        <tbody><tr><td>TenZ</td><td>5</td></tr></tbody>
      </table>
      <table class="wf-table-inset mod-adv-stats">
        <thead><tr><th>Player</th><th>2K</th></tr></thead>
        <tbody><tr><td>TenZ</td><td>3</td></tr></tbody>
      </table>
    </html>
    """


def economy_html(team_name: str) -> str:
    return f"""
    <html>
      <table class="wf-table-inset mod-econ">
        <thead><tr><th>Team</th><th>Pistol</th></tr></thead>
        <tbody><tr><td>{team_name}</td><td>50%</td></tr></tbody>
      </table>
    </html>
    """


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers: dict = {}


class FakeAsyncClient:
    def __init__(self, responses: dict[str, list[FakeResponse]]):
        self._responses = responses
        self.calls: list[tuple[str, int | None]] = []

    async def get(self, url: str, timeout=None, headers=None):
        self.calls.append((url, timeout))
        return self._responses[url].pop(0)


@pytest.mark.anyio
async def test_vlr_match_detail_fetches_performance_and_economy_for_all_games(monkeypatch):
    cache_manager.clear_all()
    client = FakeAsyncClient(
        {
            "https://www.vlr.gg/555": [
                FakeResponse(200, LIGHT_MATCH_HTML),
                FakeResponse(200, DARK_MATCH_HTML),
            ],
            "https://www.vlr.gg/555/?game=game-1&tab=performance": [FakeResponse(200, performance_html("Opponent A"))],
            "https://www.vlr.gg/555/?game=game-1&tab=economy": [FakeResponse(200, economy_html("Team One"))],
            "https://www.vlr.gg/555/?game=game-2&tab=performance": [FakeResponse(200, performance_html("Opponent B"))],
            "https://www.vlr.gg/555/?game=game-2&tab=economy": [FakeResponse(200, economy_html("Team Two"))],
        }
    )

    monkeypatch.setattr("api.scrapers.match_detail.crawler.get_http_client", lambda: client)

    data = await vlr_match_detail("555")
    segment = data["data"]["segments"][0]

    assert data["data"]["status"] == 200
    assert [team["id"] for team in segment["teams"]] == ["100", "200"]
    assert segment["teams"][0]["url"] == "https://www.vlr.gg/team/100/team-one"
    assert segment["teams"][0]["logo_light"] == "https://owcdn.net/img/team-one-light.png"
    assert segment["teams"][0]["logo_dark"] == "https://owcdn.net/img/team-one-dark.png"
    assert segment["event"]["logo"] == "https://owcdn.net/img/event-light.png"
    assert segment["event"]["logo_light"] == "https://owcdn.net/img/event-light.png"
    assert segment["event"]["logo_dark"] == "https://owcdn.net/img/event-dark.png"
    assert segment["performance"]["kill_matrix"][0]["kills_vs"] == {
        "Opponent A": "5"
    }
    assert segment["performance"]["kill_matrix"][0]["matchups"][0] == {
        "opponent": "Opponent A",
        "opponent_id": "",
        "opponent_url": "",
        "kills": "5",
        "deaths": "",
        "differential": "",
    }
    assert segment["performance"]["advanced_stats"][0]["2K"] == "3"
    assert segment["economy"] == [
        {"team_id": "100", "Team": "Team One", "Pistol": "50%"}
    ]
    assert [item["game_id"] for item in segment["performance"]["by_map"]] == [
        "game-1",
        "game-2",
    ]
    assert segment["performance"]["by_map"][1]["kill_matrix"][0]["kills_vs"] == {
        "Opponent B": "5"
    }
    assert segment["economy_by_map"][1]["rows"] == [
        {"team_id": "200", "Team": "Team Two", "Pistol": "50%"}
    ]
    assert segment["maps"][0]["performance"]["advanced_stats"][0]["2K"] == "3"
    assert segment["maps"][0]["economy"][0]["team_id"] == "100"
    assert segment["maps"][1]["performance"]["kill_matrix"][0]["kills_vs"] == {
        "Opponent B": "5"
    }
    assert segment["maps"][1]["economy"][0]["team_id"] == "200"
    assert len(client.calls) == 6
    cache_manager.clear_all()


@pytest.mark.anyio
async def test_vlr_match_detail_limits_tab_fetches_and_falls_back_on_tab_error(monkeypatch):
    cache_manager.clear_all()
    active_fetches = 0
    max_active_fetches = 0
    tab_timeouts: list[int | None] = []

    async def fake_fetch_with_retries(
        url,
        *,
        client=None,
        timeout=None,
        max_retries=3,
        request_delay=1.0,
    ):
        nonlocal active_fetches, max_active_fetches
        if url == "https://www.vlr.gg/888":
            return FakeResponse(200, BASE_MATCH_HTML)

        tab_timeouts.append(timeout)
        active_fetches += 1
        max_active_fetches = max(max_active_fetches, active_fetches)
        try:
            await asyncio.sleep(0)
            if url.endswith("game=game-2&tab=economy"):
                return FakeResponse(503, "<html></html>")
            if "tab=performance" in url:
                return FakeResponse(200, performance_html("Opponent"))
            return FakeResponse(200, economy_html("Team"))
        finally:
            active_fetches -= 1

    monkeypatch.setattr("api.scrapers.match_detail.crawler.get_http_client", lambda: object())

    async def fake_fetch_theme_variants(url, *, client=None):
        return FakeResponse(200, BASE_MATCH_HTML), FakeResponse(200, BASE_MATCH_HTML)

    monkeypatch.setattr(
        "api.scrapers.match_detail.crawler.fetch_theme_variants",
        fake_fetch_theme_variants,
    )
    monkeypatch.setattr("api.scrapers.match_detail.crawler.fetch_with_retries", fake_fetch_with_retries)
    monkeypatch.setattr("api.scrapers.match_detail.crawler.MATCH_DETAIL_TAB_FETCH_CONCURRENCY", 2)
    monkeypatch.setattr("api.scrapers.match_detail.crawler.MATCH_DETAIL_TAB_FETCH_TIMEOUT", 11)

    data = await vlr_match_detail("888")
    segment = data["data"]["segments"][0]

    assert max_active_fetches <= 2
    assert tab_timeouts == [11] * 4
    assert segment["economy_by_map"][1] == {"game_id": "game-2", "rows": []}
    assert segment["maps"][1]["economy"] == []
    cache_manager.clear_all()


@pytest.mark.anyio
async def test_vlr_match_detail_uses_empty_team_id_when_header_link_is_missing(monkeypatch):
    cache_manager.clear_all()
    client = FakeAsyncClient(
        {
            "https://www.vlr.gg/777": [
                FakeResponse(
                    200,
                    BASE_MATCH_HTML.replace(
                        '<a class="match-header-link wf-link-hover mod-2" href="/team/200/team-two">\n'
                        '    <div class="match-header-link-name mod-2">\n'
                        '      <div class="wf-title-med">Team Two</div>\n'
                        "      <div>TWO</div>\n"
                        "    </div>\n"
                        "  </a>\n",
                        '<div class="match-header-link-name mod-2">\n'
                        '  <div class="wf-title-med">Team Two</div>\n'
                        "  <div>TWO</div>\n"
                        "</div>\n",
                    ),
                )
            ],
            "https://www.vlr.gg/777/?game=game-1&tab=performance": [FakeResponse(200, performance_html("Opponent A"))],
            "https://www.vlr.gg/777/?game=game-1&tab=economy": [FakeResponse(200, economy_html("Team One"))],
            "https://www.vlr.gg/777/?game=game-2&tab=performance": [FakeResponse(200, performance_html("Opponent B"))],
            "https://www.vlr.gg/777/?game=game-2&tab=economy": [FakeResponse(200, economy_html("Team Two"))],
        }
    )

    monkeypatch.setattr("api.scrapers.match_detail.crawler.get_http_client", lambda: client)

    data = await vlr_match_detail("777")
    teams = data["data"]["segments"][0]["teams"]

    assert teams[0]["id"] == "100"
    assert teams[1]["id"] == ""
    cache_manager.clear_all()


@pytest.mark.anyio
async def test_vlr_match_detail_pairs_two_missing_team_ids_by_position(monkeypatch):
    cache_manager.clear_all()
    light_html = """
    <html>
      <div class="match-header-link-name mod-1"><div>Team One</div></div>
      <div class="match-header-link-name mod-2"><div>Team Two</div></div>
      <div class="match-header-vs">
        <img src="//owcdn.net/img/team-one-light.png">
        <img src="//owcdn.net/img/team-two-light.png">
      </div>
    </html>
    """
    dark_html = light_html.replace("-light.png", "-dark.png")

    async def fake_fetch_theme_variants(url, *, client=None):
        return FakeResponse(200, light_html), FakeResponse(200, dark_html)

    monkeypatch.setattr(
        "api.scrapers.match_detail.crawler.fetch_theme_variants",
        fake_fetch_theme_variants,
    )
    monkeypatch.setattr("api.scrapers.match_detail.crawler.get_http_client", lambda: object())

    data = await vlr_match_detail("999")
    teams = data["data"]["segments"][0]["teams"]

    assert [team["id"] for team in teams] == ["", ""]
    assert [team["logo_dark"] for team in teams] == [
        "https://owcdn.net/img/team-one-dark.png",
        "https://owcdn.net/img/team-two-dark.png",
    ]
    cache_manager.clear_all()


def test_current_header_event_and_stream_metadata():
    html = parse_html(
        """
        <a class="match-header-event"
           href="/event/2978/vct-2026-china-stage-2/group-stage">
          <div><div>VCT 2026: China Stage 2</div>
          <div class="match-header-event-series">Group Stage: Seeding</div></div>
          <img src="//owcdn.net/img/event.png">
        </a>
        <div class="match-header-date">
          <div class="moment-tz-convert" data-utc-ts="2026-07-26 07:30:00">3:30 PM</div>
          <div class="moment-tz-convert">in 2h</div>
          <div>Patch 12.02</div>
        </div>
        <div class="match-header-vs-note">completed</div>
        <div class="match-header-vs-note">Bo3</div>
        <div class="match-header-note">Match resumed the next day.</div>
        <div class="match-header-note">ONE ban Bind; TWO pick Haven; Lotus remains</div>
        <div class="match-streams-btn mod-embed">
          <div class="match-streams-btn-embed"><span>English</span></div>
          <div class="flag mod-us"></div>
          <button class="js-stream-embed-btn" data-site-id="vlr-test"></button>
          <a class="match-streams-btn-external" href="https://www.twitch.tv/valorant"></a>
        </div>
        <div class="match-vods">
          <a href="https://www.youtube.com/watch?v=test">Map 1</a>
        </div>
        """
    )

    assert _parse_event_info(html) == {
        "id": "2978",
        "name": "VCT 2026: China Stage 2",
        "series": "Group Stage: Seeding",
        "stage": "group-stage",
        "url": "https://www.vlr.gg/event/2978/vct-2026-china-stage-2/group-stage",
        "logo": "https://owcdn.net/img/event.png",
    }
    assert _parse_match_header(html) == {
        "date": "3:30 PM in 2h",
        "utc_timestamp": "2026-07-26 07:30:00",
        "scheduled_at": "2026-07-26T07:30:00Z",
        "patch": "12.02",
        "map_vetos": "ONE ban Bind; TWO pick Haven; Lotus remains",
        "notes": ["Match resumed the next day."],
        "status": "completed",
        "format": "Bo3",
    }
    streams, vods = _parse_streams_vods(html)
    assert streams == [
        {
            "name": "English",
            "url": "https://www.twitch.tv/valorant",
            "platform": "twitch",
            "country_code": "us",
            "is_embedded": True,
            "site_id": "vlr-test",
        }
    ]
    assert vods == [
        {
            "name": "Map 1",
            "url": "https://www.youtube.com/watch?v=test",
            "platform": "youtube",
            "map_number": 1,
        }
    ]


def test_current_map_identity_side_splits_and_round_methods():
    html = parse_html(
        """
        <div class="vm-stats-game" data-game-id="244645">
          <div class="vm-stats-game-header">
            <div class="map">Haven<div class="picked mod-1">PICK</div>
              <div class="map-duration">45:12</div></div>
            <div class="team"><div class="score">13</div><div class="mod-t">8</div>
              <div class="mod-ct">5</div></div>
            <div class="team"><div class="score">11</div><div class="mod-t">4</div>
              <div class="mod-ct">7</div></div>
          </div>
          <div class="ovw-cell mod-player">
            <a href="/player/1916/free1ng"><div class="ovw-player-name">free1ng</div></a>
            <div class="ovw-player-tag">KRX</div><div class="flag mod-kr"></div>
            <div class="ovw-agents"><img title="Tejo" src="/img/vlr/game/agents/tejo.png"></div>
          </div>
          <div class="ovw-cell" data-col="rating2"><span class="side mod-both">1.20</span>
            <span class="side mod-t">1.30</span><span class="side mod-ct">1.10</span></div>
          <div class="ovw-cell mod-kda" data-col="kills">
            <span class="ovw-kda-stat" data-col="kills"><span class="side mod-both">20</span>
              <span class="side mod-t">12</span><span class="side mod-ct">8</span></span>
            <span class="ovw-kda-stat" data-col="deaths"><span class="side mod-both">15</span>
              <span class="side mod-t">7</span><span class="side mod-ct">8</span></span>
            <span class="ovw-kda-stat" data-col="assists"><span class="side mod-both">6</span>
              <span class="side mod-t">4</span><span class="side mod-ct">2</span></span>
          </div>
          <div class="ovw-cell mod-player">
            <a href="/player/7378/jinggg"><div class="ovw-player-name">Jinggg</div></a>
            <div class="ovw-player-tag">PRX</div><div class="flag mod-sg"></div>
            <div class="ovw-agents"><img title="Raze" src="/img/vlr/game/agents/raze.png"></div>
          </div>
          <div class="ovw-cell" data-col="rating2"><span class="side mod-both">1.10</span>
            <span class="side mod-t">1.00</span><span class="side mod-ct">1.20</span></div>
          <div class="ovw-cell mod-kda" data-col="kills">
            <span class="ovw-kda-stat" data-col="kills"><span class="side mod-both">18</span></span>
            <span class="ovw-kda-stat" data-col="deaths"><span class="side mod-both">17</span></span>
            <span class="ovw-kda-stat" data-col="assists"><span class="side mod-both">5</span></span>
          </div>
          <div class="vlr-rounds"><div class="vlr-rounds-row">
            <div class="vlr-rounds-row-col" title="1-0"><div class="rnd-num">1</div>
              <div class="rnd-sq mod-win mod-t"><img src="/img/vlr/game/elim.webp"></div>
              <div class="rnd-sq"></div></div>
            <div class="vlr-rounds-row-col" title="1-0"><div class="rnd-num">2</div>
              <div class="rnd-sq"></div><div class="rnd-sq"></div></div>
          </div></div>
        </div>
        """
    )
    teams = [
        {"id": "8185", "name": "KIWOOM DRX", "url": "https://www.vlr.gg/team/8185"},
        {"id": "624", "name": "Paper Rex", "url": "https://www.vlr.gg/team/624"},
    ]

    game = _parse_maps(html, teams)[0]

    assert game["game_id"] == "244645"
    assert game["map_number"] == 1
    assert game["map_name"] == "Haven"
    assert game["picked_by"] == "KIWOOM DRX"
    assert game["picked_by_team_id"] == "8185"
    assert game["pick"]["slot"] == "team1"
    assert game["side_scores"]["team1"] == {
        "total": 13,
        "attack": "8",
        "defense": "5",
        "overtime": "",
    }
    assert game["players"]["team1"][0]["player_id"] == "1916"
    assert game["players"]["team1"][0]["agent_slug"] == "tejo"
    assert game["players"]["team1"][0]["attack"]["kills"] == "12"
    assert game["players"]["team1"][0]["defense"]["rating"] == "1.10"
    assert game["rounds"] == [
        {
            "round_num": 1,
            "winner": "team1",
            "side": "t",
            "side_name": "attack",
            "method": "elimination",
            "method_code": "elim",
            "method_icon": "https://www.vlr.gg/img/vlr/game/elim.webp",
            "score_after": {"team1": 1, "team2": 0},
        }
    ]


def test_empty_active_game_does_not_fall_back_to_aggregate_tabs():
    html = parse_html(
        """
        <div class="vm-stats-game" data-game-id="all">
          <table class="wf-table-inset mod-matrix mod-normal">
            <thead><tr><th>Player</th><th>Opponent</th></tr></thead>
            <tbody><tr><td>Aggregate</td><td>99</td></tr></tbody>
          </table>
          <table class="wf-table-inset mod-econ">
            <thead><tr><th>Team</th><th>Full</th></tr></thead>
            <tbody><tr><td>Aggregate</td><td>99%</td></tr></tbody>
          </table>
        </div>
        <div class="vm-stats-game mod-active" data-game-id="future"></div>
        """
    )

    assert _parse_kill_matrix(html) == []
    assert _parse_economy(html) == []


def test_map_with_rounds_but_no_winning_score_is_in_progress():
    html = parse_html(
        """
        <div class="vm-stats-game" data-game-id="live-map">
          <div class="vm-stats-game-header">
            <div class="map">Lotus</div>
            <div class="team"><div class="score">6</div></div>
            <div class="team"><div class="score">5</div></div>
          </div>
          <div class="vlr-rounds"><div class="vlr-rounds-row">
            <div class="vlr-rounds-row-col" title="1-0"><div class="rnd-num">1</div>
              <div class="rnd-sq mod-win mod-t"><img src="/img/vlr/game/elim.webp"></div>
              <div class="rnd-sq"></div></div>
          </div></div>
        </div>
        """
    )

    assert _parse_maps(html)[0]["status"] == "in_progress"


def test_legacy_event_and_date_markup_remain_supported():
    html = parse_html(
        """
        <div class="match-header-super">
          <div><a href="/event/123/legacy-event">Legacy Event</a></div>
          <div class="match-header-event-series">Upper Final</div>
        </div>
        <div class="match-header-date">April 23, 2024</div>
        """
    )

    event = _parse_event_info(html)
    assert event["id"] == "123"
    assert event["name"] == "Legacy Event"
    assert event["series"] == "Upper Final"
    assert _parse_match_header(html)["date"] == "April 23, 2024"


def test_head_to_head_prefers_dedicated_match_history():
    html = parse_html(
        """
        <a class="match-histories-item" href="/999/unrelated">
          <div class="match-histories-item-result mod-win"><span class="rf">2</span>
            <span class="ra">0</span></div>
        </a>
        <div class="match-h2h-matches">
          <a class="wf-module-item" href="/675342/bilibili-gaming-vs-nova">
            <img class="match-h2h-matches-team mod-loss" alt="Bilibili Gaming"
              src="//owcdn.net/img/historical-blg.png">
            <img class="match-h2h-matches-team mod-win" alt="Nova Esports"
              src="//owcdn.net/img/historical-nova.png">
            <div class="match-h2h-matches-score">1 2</div>
            <div class="match-h2h-matches-event-name">EWC 2026: China Qualifier</div>
            <div class="match-h2h-matches-event-series">UBF</div>
            <div class="match-h2h-matches-date">2026/05/13</div>
          </a>
        </div>
        """
    )
    teams = [
        {"id": "12010", "name": "Bilibili Gaming", "logo": "https://owcdn.net/img/blg.png"},
        {"id": "12064", "name": "Nova Esports", "logo": "https://owcdn.net/img/nova.png"},
    ]

    history = _parse_head_to_head(html, teams)

    assert len(history) == 1
    assert history[0]["match_id"] == "675342"
    assert history[0]["event_series"] == "UBF"
    assert [team["id"] for team in history[0]["teams"]] == ["12010", "12064"]


@pytest.mark.anyio
async def test_vlr_match_detail_skips_tabs_for_scheduled_games(monkeypatch):
    cache_manager.clear_all()
    scheduled_html = BASE_MATCH_HTML.replace(
        '<div class="team"><div class="score">10</div><div class="mod-ct">4</div><div class="mod-t">6</div></div>\n'
        '      <div class="team"><div class="score">13</div><div class="mod-ct">7</div><div class="mod-t">6</div></div>',
        '<div class="team"><div class="score"></div></div>\n'
        '      <div class="team"><div class="score"></div></div>',
    )
    client = FakeAsyncClient(
        {
            "https://www.vlr.gg/444": [
                FakeResponse(200, scheduled_html),
                FakeResponse(200, scheduled_html),
            ],
            "https://www.vlr.gg/444/?game=game-1&tab=performance": [
                FakeResponse(200, performance_html("Opponent"))
            ],
            "https://www.vlr.gg/444/?game=game-1&tab=economy": [
                FakeResponse(200, economy_html("Team One"))
            ],
        }
    )
    monkeypatch.setattr("api.scrapers.match_detail.crawler.get_http_client", lambda: client)

    segment = (await vlr_match_detail("444"))["data"]["segments"][0]

    assert segment["maps"][1]["status"] == "scheduled"
    assert segment["maps"][1]["performance"] == {
        "kill_matrix": [],
        "advanced_stats": [],
    }
    assert segment["maps"][1]["economy"] == []
    assert all("game=game-2" not in url for url, _ in client.calls)
    cache_manager.clear_all()
