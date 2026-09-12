import pytest
from fastapi.testclient import TestClient

import backend


def _fake_stocktwits(universe):
    return {
        t: {
            "sentiment_score": 0.2,
            "confidence": 0.6,
            "bull_ratio": 0.6,
            "message_volume": 10,
            "top_messages": [],
        }
        for t in universe
    }


def _fake_reddit(universe):
    return {
        t: {
            "mention_momentum": 0.1,
            "spike_detected": False,
            "mentions_24h": 5,
            "mentions_7d": 15,
            "avg_post_score": 50.0,
            "top_posts": [],
            "subreddit_breakdown": {},
        }
        for t in universe
    }


def _fake_fundamentals(universe):
    return {
        t: {
            "rsi": 50.0,
            "volatility": 0.30,
            "fundamental_score": 55.0,
            "current_price": 100.0,
            "daily_change_pct": 1.5,
            "momentum_30d": 0.05,
            "volume_ratio": 1.0,
            "market_cap": 1_000_000_000,
            "pe_ratio": 20.0,
            "sector": "Technology",
            "price_chart": [{"date": "2026-01-01", "price": 100.0}],
        }
        for t in universe
    }


def _fake_run_sentiment_graph(scored_tickers):
    # Pass through unchanged — exercises risk_classifier on real
    # score_all_tickers() output without needing a live Groq API key.
    return scored_tickers


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(backend, "fetch_all_stocktwits", _fake_stocktwits)
    monkeypatch.setattr(backend, "fetch_reddit_sentiment_via_search", _fake_reddit)
    monkeypatch.setattr(backend, "fetch_all_fundamentals", _fake_fundamentals)
    monkeypatch.setattr(backend, "run_sentiment_graph", _fake_run_sentiment_graph)
    return TestClient(backend.app)


def test_run_pipeline_success_shape(client):
    response = client.get("/api/run_pipeline")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "success"
    assert "classified" in data
    assert "trending" in data
    assert "scored_flat" in data
    assert "run_time" in data
    assert len(data["scored_flat"]) == len(backend.STOCK_UNIVERSE)


def test_run_pipeline_failure_returns_502_with_detail(client, monkeypatch):
    def boom(universe):
        raise RuntimeError("StockTwits data collection failed for 20/24 tickers")

    monkeypatch.setattr(backend, "fetch_all_stocktwits", boom)

    response = client.get("/api/run_pipeline")
    assert response.status_code == 502
    assert "StockTwits data collection failed" in response.json()["detail"]


def test_cors_rejects_disallowed_origin(client):
    response = client.get(
        "/api/run_pipeline", headers={"Origin": "https://not-allowed.example.com"}
    )
    # The request still executes (CORS is enforced by the browser, not the
    # server), but the disallowed origin must not be echoed back — a
    # missing header is what makes the browser block the response.
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origin(client):
    allowed_origin = backend.CORS_ORIGINS[0]
    response = client.get("/api/run_pipeline", headers={"Origin": allowed_origin})
    assert response.headers.get("access-control-allow-origin") == allowed_origin
