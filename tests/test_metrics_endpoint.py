from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import metrics
from app.core.errors import AppError, ErrorCode
from app.schemas.auth import TokenData


class FakeQuery:
    def __init__(self, items):
        self._items = items

    async def to_list(self):
        return list(self._items)


@pytest.mark.asyncio
async def test_metrics_summary_returns_canonical_cards(monkeypatch):
    rows = [
        SimpleNamespace(metric_code="electricity_kwh_total", unit="kWh", value=1500.0, pillar="environmental", status="approved"),
        SimpleNamespace(metric_code="scope2_tco2e", unit="tCO2e", value=0.22, pillar="environmental", status="approved"),
        SimpleNamespace(metric_code="scope1_tco2e", unit="kgCO2e", value=300.0, pillar="environmental", status="approved"),
        SimpleNamespace(metric_code="headcount", unit="employees", value=25.0, pillar="social", status="approved"),
    ]

    monkeypatch.setattr(metrics.Metric, "find", lambda query: FakeQuery(rows))

    manager = TokenData(user_id="u-1", role="sustainability_manager", company_id="c-1")
    result = await metrics.metrics_summary(company_id="c-1", workspace_id="w-1", manager=manager)

    payload = result["data"]
    cards = {card.key: card for card in payload.cards}

    assert payload.company_id == "c-1"
    assert payload.workspace_id == "w-1"
    assert payload.environmental_count == 3
    assert payload.social_count == 1
    assert cards["electricity"].value == 1500.0
    assert cards["emissions"].value == 0.52


@pytest.mark.asyncio
async def test_metrics_summary_rejects_cross_tenant_access():
    manager = TokenData(user_id="u-1", role="sustainability_manager", company_id="c-2")

    with pytest.raises(AppError) as exc:
        await metrics.metrics_summary(company_id="c-1", workspace_id="w-1", manager=manager)

    assert exc.value.code == ErrorCode.FORBIDDEN
