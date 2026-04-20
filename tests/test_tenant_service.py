from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import AppError, ErrorCode
from app.services import tenant_service


class FakeRecord:
    def __init__(self, **attrs):
        self.deleted = False
        for key, value in attrs.items():
            setattr(self, key, value)

    async def delete(self):
        self.deleted = True


class FakeQuery:
    def __init__(self, records):
        self.records = records

    async def to_list(self):
        return list(self.records)


@pytest.mark.asyncio
async def test_delete_workspace_removes_workspace_scoped_records(monkeypatch, tmp_path):
    evidence_file = tmp_path / "evidence.pdf"
    evidence_file.write_text("proof")

    workspace = FakeRecord(id="workspace-1", company_id="company-1", name="FY2026")
    document = FakeRecord(storage_path=f"local://{evidence_file}")
    extraction = FakeRecord()
    metric = FakeRecord()
    report = FakeRecord()
    template = FakeRecord()
    audit_calls = []

    async def fake_get_company(company_id):
        return SimpleNamespace(id=company_id)

    async def fake_get_workspace(workspace_id):
        assert workspace_id == "workspace-1"
        return workspace

    async def fake_emit(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(tenant_service, "get_company", fake_get_company)
    monkeypatch.setattr(tenant_service.Workspace, "get", fake_get_workspace)
    monkeypatch.setattr(tenant_service.Document, "find", lambda filters: FakeQuery([document]))
    monkeypatch.setattr(tenant_service.ExtractedData, "find", lambda filters: FakeQuery([extraction]))
    monkeypatch.setattr(tenant_service.Metric, "find", lambda filters: FakeQuery([metric]))
    monkeypatch.setattr(tenant_service.Report, "find", lambda filters: FakeQuery([report]))
    monkeypatch.setattr(tenant_service.SchemaTemplate, "find", lambda filters: FakeQuery([template]))
    monkeypatch.setattr(tenant_service.storage_service, "get_file_path", lambda storage_uri: Path(storage_uri[8:]))
    monkeypatch.setattr(tenant_service.audit_service, "emit", fake_emit)

    result = await tenant_service.delete_workspace("company-1", "workspace-1", "user-1")

    assert result["deleted"] is True
    assert result["workspace_id"] == "workspace-1"
    assert result["workspace_name"] == "FY2026"
    assert result["documents_deleted"] == 1
    assert result["files_deleted"] == 1
    assert result["extractions_deleted"] == 1
    assert result["metrics_deleted"] == 1
    assert result["reports_deleted"] == 1
    assert result["templates_deleted"] == 1
    assert not evidence_file.exists()
    assert workspace.deleted is True
    assert document.deleted is True
    assert extraction.deleted is True
    assert metric.deleted is True
    assert report.deleted is True
    assert template.deleted is True
    assert audit_calls[0]["event_type"] == "WORKSPACE_DELETED"


@pytest.mark.asyncio
async def test_delete_workspace_raises_not_found_for_missing_workspace(monkeypatch):
    async def fake_get_company(company_id):
        return SimpleNamespace(id=company_id)

    async def fake_get_workspace(workspace_id):
        return None

    monkeypatch.setattr(tenant_service, "get_company", fake_get_company)
    monkeypatch.setattr(tenant_service.Workspace, "get", fake_get_workspace)

    with pytest.raises(AppError) as exc_info:
        await tenant_service.delete_workspace("company-1", "workspace-404", "user-1")

    assert exc_info.value.code == ErrorCode.NOT_FOUND
    assert exc_info.value.message == "Workspace not found"
