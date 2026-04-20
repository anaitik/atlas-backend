from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import reports
from app.services import verification_service


def test_verification_signature_roundtrip():
    report = SimpleNamespace(
        id="r-1",
        sha256_hash="a" * 64,
        version=2,
        reporting_year=2026,
    )
    sig = verification_service.build_verification_signature(report)
    assert verification_service.verify_report_signature(report, sig) is True
    assert verification_service.verify_report_signature(report, "bad-signature") is False


def test_report_content_hash_is_deterministic():
    report = SimpleNamespace(
        id="r-1",
        company_id="c-1",
        workspace_id="w-1",
        reporting_year=2026,
        version=1,
        output_format="csrd",
        exec_summary="Summary",
        sections={"environmental": {"title": "E", "content": "C"}},
        data_lineage=[{"metric_code": "scope2_tco2e", "value": 10}],
        interview_answers=[{"question_id": "q1", "answer": "a1"}],
    )
    first = verification_service.build_report_content_hash(report)
    second = verification_service.build_report_content_hash(report)
    assert first == second


def test_qr_data_url_generation():
    data_url = verification_service.build_qr_data_url("https://example.com/verify")
    assert data_url.startswith("data:image/png;base64,")
    assert len(data_url) > 100


@pytest.mark.asyncio
async def test_public_verify_report(monkeypatch):
    report_obj = SimpleNamespace(
        id="r-1",
        company_id="c-1",
        workspace_id="w-1",
        reporting_year=2026,
        version=1,
        status="approved",
        sha256_hash="b" * 64,
        blockchain_tx_id="0xabc",
        verification_signature="sig-1",
        verification_url="http://localhost:8000/api/v1/reports/public/verify/r-1?sig=sig-1",
        superseded_by_report_id=None,
        high_assurance_mode=True,
        raw_document_anchor_count=3,
    )

    async def fake_get_report(report_id, actor_company_id=None):
        assert report_id == "r-1"
        return report_obj

    async def fake_hash_verification(file_hash):
        assert file_hash == "b" * 64
        return {
            "sha256_hash": file_hash,
            "blockchain_enabled": True,
            "chain_id": 80002,
            "contract_address": "0x123",
            "verified_on_chain": True,
            "verification_status": "verified",
        }

    monkeypatch.setattr(reports.report_service, "get_report", fake_get_report)
    monkeypatch.setattr(reports.blockchain_service, "build_hash_verification", fake_hash_verification)
    monkeypatch.setattr(reports.verification_service, "verify_report_signature", lambda report, sig: sig == "sig-1")

    result = await reports.public_verify_report("r-1", sig="sig-1")
    assert result["data"].signature_valid is True
    assert result["data"].verification_status == "verified"
