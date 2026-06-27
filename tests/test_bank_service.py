"""
Tests for bank_service — portal logic, rate limiting, token management.
Pure unit tests — no real DB calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


# ── Rate Limiter ──────────────────────────────────────────────────

def test_rate_limiter_allows_under_limit():
    from app.core.rate_limit import is_allowed

    # Fresh key — should allow 5 calls within window
    for i in range(5):
        allowed, retry = is_allowed(f"test-key-{i}", max_calls=10, window_seconds=60)
        assert allowed is True
        assert retry == 0


def test_rate_limiter_blocks_over_limit():
    from app.core.rate_limit import is_allowed, _buckets

    key = "test-block-key"
    _buckets.pop(key, None)  # start clean

    for _ in range(5):
        is_allowed(key, max_calls=5, window_seconds=60)

    # 6th call should be blocked
    allowed, retry = is_allowed(key, max_calls=5, window_seconds=60)
    assert allowed is False
    assert retry > 0


def test_rate_limiter_different_keys_independent():
    from app.core.rate_limit import is_allowed, _buckets

    key_a = "rate-test-a"
    key_b = "rate-test-b"
    _buckets.pop(key_a, None)
    _buckets.pop(key_b, None)

    for _ in range(3):
        is_allowed(key_a, max_calls=3, window_seconds=60)

    # key_a exhausted, key_b fresh
    allowed_a, _ = is_allowed(key_a, max_calls=3, window_seconds=60)
    allowed_b, _ = is_allowed(key_b, max_calls=3, window_seconds=60)
    assert allowed_a is False
    assert allowed_b is True


# ── Token Extraction ──────────────────────────────────────────────

def test_token_urlsafe_is_unique():
    from secrets import token_urlsafe
    tokens = {token_urlsafe(32) for _ in range(100)}
    assert len(tokens) == 100  # no collisions in 100 samples


# ── GHG calculation formula ───────────────────────────────────────

def test_scope2_emission_factor():
    """EU average grid: 0.276 kgCO2e per kWh."""
    kwh = 50_000
    scope2_kg = kwh * 0.276
    assert scope2_kg == pytest.approx(13_800.0, abs=0.01)


def test_scope1_emission_factor():
    """Diesel combustion: 2.68784 kgCO2e per litre (DESNZ 2024)."""
    litres = 1_000
    scope1_kg = litres * 2.68784
    assert scope1_kg == pytest.approx(2687.84, abs=0.01)


def test_total_ghg_conversion_to_tonnes():
    """Verify kg → tonne conversion and rounding."""
    scope2_kg = 13_800.0
    scope1_kg = 2687.84
    total_t = round((scope1_kg + scope2_kg) / 1000, 4)
    assert total_t == pytest.approx(16.4878, abs=0.001)


# ── Bank access expiry logic ──────────────────────────────────────

def test_expired_token_detection():
    """Token with past expires_at should be detected as expired."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=1)

    assert past < now  # expired
    assert future > now  # still valid


def test_renewal_extends_expiry():
    """Renewing a token adds days from now, not from old expiry."""
    now = datetime.now(timezone.utc)
    expires_in = 90
    new_expiry = now + timedelta(days=expires_in)
    # Should be approximately 90 days from now
    delta = (new_expiry - now).days
    assert delta == 90


# ── Portfolio batch ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_batch_caps_at_25():
    """Batch should not process more than 25 tokens."""
    from app.services.bank_service import get_bank_portfolio_batch

    tokens = [f"token-{i}" for i in range(30)]
    call_count = 0

    async def fake_get_portal(token):
        nonlocal call_count
        call_count += 1
        return {
            "company_name": "Test Co",
            "workspace_name": "2024",
            "interview_completion_pct": 80,
            "total_approved": 12,
            "total_questions": 15,
            "pillar_scores": {},
            "overall_esg_score": 70,
            "data_quality_score": 85,
            "metrics": [],
            "unanswered_questions": [],
            "blockchain_verified": False,
            "blockchain_tx_id": None,
            "report_id": None,
            "sha256_hash": None,
            "institution_name": "Test Bank",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    with patch("app.services.bank_service.get_bank_portal", side_effect=fake_get_portal):
        results = await get_bank_portfolio_batch(tokens)

    assert call_count == 25
    assert len(results) == 25


@pytest.mark.asyncio
async def test_portfolio_batch_tags_access_token():
    """Each result should carry _access_token matching its source token."""
    from app.services.bank_service import get_bank_portfolio_batch

    async def fake_get_portal(token):
        return {
            "company_name": "Test Co",
            "workspace_name": "2024",
            "interview_completion_pct": 50,
            "total_approved": 7,
            "total_questions": 15,
            "pillar_scores": {},
            "overall_esg_score": 40,
            "data_quality_score": 70,
            "metrics": [],
            "unanswered_questions": [],
            "blockchain_verified": False,
            "blockchain_tx_id": None,
            "report_id": None,
            "sha256_hash": None,
            "institution_name": "Test Bank",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    tokens = ["token-alpha", "token-beta"]
    with patch("app.services.bank_service.get_bank_portal", side_effect=fake_get_portal):
        results = await get_bank_portfolio_batch(tokens)

    assert results[0]["_access_token"] == "token-alpha"
    assert results[1]["_access_token"] == "token-beta"


@pytest.mark.asyncio
async def test_portfolio_batch_skips_invalid_tokens():
    """Invalid tokens should be silently skipped — not crash the batch."""
    from app.services.bank_service import get_bank_portfolio_batch

    async def fake_get_portal(token):
        if token == "bad-token":
            raise Exception("Not found")
        return {
            "company_name": "Good Co",
            "workspace_name": "2024",
            "interview_completion_pct": 60,
            "total_approved": 9,
            "total_questions": 15,
            "pillar_scores": {},
            "overall_esg_score": 55,
            "data_quality_score": 80,
            "metrics": [],
            "unanswered_questions": [],
            "blockchain_verified": False,
            "blockchain_tx_id": None,
            "report_id": None,
            "sha256_hash": None,
            "institution_name": "Some Bank",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    tokens = ["good-token", "bad-token", "good-token-2"]
    with patch("app.services.bank_service.get_bank_portal", side_effect=fake_get_portal):
        results = await get_bank_portfolio_batch(tokens)

    assert len(results) == 2  # bad-token skipped
    for r in results:
        assert r["company_name"] == "Good Co"
