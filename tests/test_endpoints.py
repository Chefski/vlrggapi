"""Endpoint smoke tests for original and v2 routers."""
import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_version_endpoint(client):
    resp = await client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "3.0.0"
    assert data["default_api"] == "v3"
    assert data["compatibility_api"] == "v2"


@pytest.mark.anyio
async def test_v2_health(client):
    resp = await client.get("/v2/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "data" in data


@pytest.mark.anyio
async def test_v2_invalid_region_returns_400(client):
    resp = await client.get("/v2/rankings?region=invalid_xyz")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_invalid_match_query_returns_400(client):
    resp = await client.get("/v2/match?q=bad_query")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_invalid_timespan_returns_400(client):
    resp = await client.get("/v2/stats?region=na&timespan=45")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_stats_requires_timespan_or_span(client):
    resp = await client.get("/v2/stats?region=americas")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_stats_forwards_current_filters(client, monkeypatch):
    captured = {}

    async def fake_stats(region, timespan=None, **filters):
        captured.update({"region": region, "timespan": timespan, **filters})
        return {
            "data": {
                "status": 200,
                "filters": {"region": region, "span": filters["span"]},
                "segments": [],
            }
        }

    monkeypatch.setattr("routers.v2_router.get_stats_data", fake_stats)
    resp = await client.get(
        "/v2/stats?region=emea&span=custom&from=2026-01-01&to=2026-06-30"
        "&tier=vct&side=ct&role=sentinel&agent=killjoy&map_id=12"
        "&min_rounds=100&min_rating=0&sort=kmax&dir=asc"
    )

    assert resp.status_code == 200
    assert captured == {
        "region": "emea",
        "timespan": None,
        "span": "custom",
        "from_date": "2026-01-01",
        "to_date": "2026-06-30",
        "tier": "vct",
        "side": "ct",
        "role": "sentinel",
        "agent": "killjoy",
        "map_id": "12",
        "min_rounds": 100,
        "min_rating": 0,
        "sort": "kmax",
        "direction": "asc",
    }


@pytest.mark.anyio
async def test_v2_invalid_event_query_returns_400(client):
    resp = await client.get("/v2/events?q=bad_query")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_event_detail_forwards_stage(client, monkeypatch):
    captured = {}

    async def fake_detail(event_id, stage=None):
        captured.update({"event_id": event_id, "stage": stage})
        return {"data": {"status": 200, "segments": {"groups": []}}}

    monkeypatch.setattr("routers.v2_router.get_event_detail_data", fake_detail)
    resp = await client.get("/v2/event/2978?stage=group-stage")

    assert resp.status_code == 200
    assert captured == {"event_id": "2978", "stage": "group-stage"}


@pytest.mark.anyio
async def test_v2_event_detail_rejects_unsafe_stage(client):
    resp = await client.get("/v2/event/2978?stage=../stats")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_event_stats_forwards_filters(client, monkeypatch):
    captured = {}

    async def fake_stats(event_id, **filters):
        captured.update({"event_id": event_id, **filters})
        return {"data": {"status": 200, "segments": []}}

    monkeypatch.setattr("routers.v2_router.get_event_stats_data", fake_stats)
    resp = await client.get(
        "/v2/event/2978/stats?sort=kmax&dir=asc&side=ct&role=sentinel"
        "&agent=killjoy&map_id=12&min_rounds=100&exclude=551.552"
    )

    assert resp.status_code == 200
    assert captured == {
        "event_id": "2978",
        "sort": "kmax",
        "direction": "asc",
        "side": "ct",
        "role": "sentinel",
        "agent": "killjoy",
        "map_id": "12",
        "min_rounds": 100,
        "exclude": "551.552",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("resource", ["stats", "agents", "news", "pickem"])
async def test_v2_event_resources_reject_invalid_id(client, resource):
    resp = await client.get(f"/v2/event/not-an-id/{resource}")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_event_agents_rejects_invalid_exclude(client):
    resp = await client.get("/v2/event/2978/agents?exclude=551,552")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_original_event_detail_forwards_stage(client, monkeypatch):
    captured = {}

    async def fake_detail(event_id, stage=None):
        captured.update({"event_id": event_id, "stage": stage})
        return {"data": {"status": 200, "segments": {"groups": []}}}

    monkeypatch.setattr("routers.vlr_router.get_event_detail_data", fake_detail)
    resp = await client.get("/event/2978?stage=playoffs")

    assert resp.status_code == 200
    assert captured == {"event_id": "2978", "stage": "playoffs"}


@pytest.mark.anyio
async def test_original_news_not_redirect(client):
    """Original /news endpoint should respond directly (not redirect)."""
    resp = await client.get("/news", follow_redirects=False)
    # Should not be a 301 redirect — it serves directly
    assert resp.status_code != 301


@pytest.mark.anyio
async def test_original_invalid_match_returns_error(client):
    """Original /match with bad q should return error dict, not 400."""
    resp = await client.get("/match?q=bad_query", follow_redirects=False)
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


@pytest.mark.anyio
async def test_original_player_rejects_invalid_id(client):
    resp = await client.get("/player?id=abc")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_original_player_rejects_invalid_timespan(client):
    resp = await client.get("/player?id=9&timespan=45d")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_original_match_detail_rejects_invalid_id(client):
    resp = await client.get("/match/details?match_id=abc")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_match_detail_exposes_team_ids(client, monkeypatch):
    async def fake_match_detail(match_id):
        return {
            "data": {
                "status": 200,
                "segments": [
                    {
                        "match_id": match_id,
                        "teams": [
                            {"id": "100", "name": "Team One"},
                            {"id": "200", "name": "Team Two"},
                        ],
                    }
                ],
            }
        }

    monkeypatch.setattr("routers.v2_router.get_match_detail_data", fake_match_detail)

    resp = await client.get("/v2/match/details?match_id=123")
    assert resp.status_code == 200
    assert resp.json()["data"]["segments"][0]["teams"] == [
        {"id": "100", "name": "Team One"},
        {"id": "200", "name": "Team Two"},
    ]


@pytest.mark.anyio
async def test_original_match_detail_strips_team_ids(client, monkeypatch):
    async def fake_match_detail(match_id):
        return {
            "data": {
                "status": 200,
                "segments": [
                    {
                        "match_id": match_id,
                        "teams": [
                            {"id": "100", "name": "Team One"},
                            {"id": "200", "name": "Team Two"},
                        ],
                    }
                ],
            }
        }

    monkeypatch.setattr("routers.vlr_router.get_match_detail_data", fake_match_detail)

    resp = await client.get("/match/details?match_id=123")
    assert resp.status_code == 200
    assert resp.json()["data"]["segments"][0]["teams"] == [
        {"name": "Team One"},
        {"name": "Team Two"},
    ]


@pytest.mark.anyio
async def test_v2_wrap_propagates_scraper_error_status(client, monkeypatch):
    async def fake_news(page=1):
        return {"data": {"status": 502, "error": "upstream failure", "segments": []}}

    monkeypatch.setattr("routers.v2_router.get_news_data", fake_news)
    resp = await client.get("/v2/news")
    assert resp.status_code == 502
    assert "detail" in resp.json()


@pytest.mark.anyio
async def test_v2_news_forwards_page_and_article_id(client, monkeypatch):
    captured = {}

    async def fake_news(page=1):
        captured["page"] = page
        return {"data": {"status": 200, "segments": [], "meta": {"page": page}}}

    async def fake_article(article_id):
        captured["article_id"] = article_id
        return {
            "data": {
                "status": 200,
                "segments": [{"article_id": article_id}],
            }
        }

    monkeypatch.setattr("routers.v2_router.get_news_data", fake_news)
    monkeypatch.setattr("routers.v2_router.get_news_article_data", fake_article)

    archive = await client.get("/v2/news?page=126")
    article = await client.get("/v2/news/725612")

    assert archive.status_code == 200
    assert archive.json()["data"]["meta"] == {"page": 126}
    assert article.status_code == 200
    assert article.json()["data"]["segments"][0]["article_id"] == "725612"
    assert captured == {"page": 126, "article_id": "725612"}


@pytest.mark.anyio
async def test_v2_news_validates_archive_page_and_article_id(client):
    assert (await client.get("/v2/news?page=501")).status_code == 422
    assert (await client.get("/v2/news/not-a-number")).status_code == 400


@pytest.mark.anyio
async def test_original_news_article_propagates_embedded_error_status(
    client,
    monkeypatch,
):
    async def fake_article(article_id):
        return {
            "data": {
                "status": 404,
                "error": f"news article {article_id} not found",
                "segments": [],
            }
        }

    monkeypatch.setattr("routers.vlr_router.get_news_article_data", fake_article)

    response = await client.get("/news/725612")

    assert response.status_code == 404
    assert response.json()["detail"] == "news article 725612 not found"


@pytest.mark.anyio
async def test_v2_events_propagates_scraper_error_status(client, monkeypatch):
    async def fake_events(q, page):
        return {"data": {"status": 503, "error": "events unavailable", "segments": []}}

    monkeypatch.setattr("routers.v2_router.get_events_data", fake_events)

    resp = await client.get("/v2/events")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "events unavailable"


@pytest.mark.anyio
async def test_v2_player_propagates_scraper_error_status(client, monkeypatch):
    async def fake_player(player_id, timespan):
        return {
            "data": {
                "status": 404,
                "error": f"player {player_id} not found",
                "segments": [],
            }
        }

    monkeypatch.setattr("routers.v2_router.get_player_data", fake_player)

    resp = await client.get("/v2/player?id=9")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "player 9 not found"


@pytest.mark.anyio
async def test_v2_match_rejects_oversized_workload(client):
    resp = await client.get("/v2/match?q=results&num_pages=21")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_v2_match_rejects_pagination_for_upcoming_query(client):
    resp = await client.get("/v2/match?q=upcoming&num_pages=2")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_original_match_rejects_pagination_for_live_score_query(client):
    resp = await client.get("/match?q=live_score&from_page=2")
    assert resp.status_code == 400
