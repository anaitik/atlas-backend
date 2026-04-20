from pathlib import Path
from types import SimpleNamespace
from datetime import UTC, datetime

import pytest

from app.api.v1.endpoints import documents
from app.schemas.auth import TokenData
from app.schemas.document import HashVerificationRequest


def test_upload_document_reuses_existing_file_in_same_workspace(monkeypatch, tmp_path):
    temp_file = tmp_path / "duplicate.pdf"
    temp_file.write_bytes(b"duplicate")

    async def fake_scan_and_save(file, company_id, document_id):
        return f"local://{temp_file}", "same-hash", temp_file.stat().st_size

    async def fake_find_one(query):
        return SimpleNamespace(
            id="existing-doc",
            filename="duplicate.pdf",
            content_type="application/pdf",
            file_size_bytes=123,
            sha256_hash="same-hash",
            status="uploaded",
            blockchain_tx_id=None,
            uploaded_by_id="user-1",
            created_at="2025-01-01T00:00:00Z",
            model_dump=lambda: {
                "id": "existing-doc",
                "filename": "duplicate.pdf",
                "content_type": "application/pdf",
                "file_size_bytes": 123,
                "sha256_hash": "same-hash",
                "status": "uploaded",
                "blockchain_tx_id": None,
                "uploaded_by_id": "user-1",
                "created_at": "2025-01-01T00:00:00Z",
            },
        )

    monkeypatch.setattr(documents.storage_service, "scan_and_save", fake_scan_and_save)
    monkeypatch.setattr(documents.storage_service, "get_file_path", lambda _: Path(temp_file))
    monkeypatch.setattr(documents.Document, "find_one", fake_find_one)

    manager = TokenData(user_id="user-1", role="sustainability_manager", company_id="company-1")
    file = SimpleNamespace(filename="duplicate.pdf", content_type="application/pdf")

    response = documents.upload_document(
        company_id="company-1",
        workspace_id="workspace-1",
        file=file,
        manager=manager,
    )

    import asyncio

    result = asyncio.run(response)

    assert result["data"].id == "existing-doc"
    assert not temp_file.exists()


@pytest.mark.asyncio
async def test_upload_document_persists_blockchain_tx_id(monkeypatch):
    inserted = []
    audit_calls = []

    class FakeDocument:
        def __init__(self, **kwargs):
            self.status = "uploaded"
            self.created_at = datetime(2025, 1, 1, tzinfo=UTC)
            for key, value in kwargs.items():
                setattr(self, key, value)

        @classmethod
        async def find_one(cls, query):
            return None

        async def insert(self):
            inserted.append(self)

        def model_dump(self):
            return {
                "id": self.id,
                "filename": self.filename,
                "content_type": self.content_type,
                "file_size_bytes": self.file_size_bytes,
                "sha256_hash": self.sha256_hash,
                "status": self.status,
                "blockchain_tx_id": self.blockchain_tx_id,
                "uploaded_by_id": self.uploaded_by_id,
                "created_at": self.created_at,
            }

    async def fake_scan_and_save(file, company_id, document_id):
        return "local://C:/tmp/utility.pdf", "a" * 64, 2048

    async def fake_emit(**kwargs):
        audit_calls.append(kwargs)

    async def fake_anchor_document_hash(file_hash):
        assert file_hash == "a" * 64
        return "0xabc123"

    monkeypatch.setattr(documents.storage_service, "scan_and_save", fake_scan_and_save)
    monkeypatch.setattr(documents, "Document", FakeDocument)
    monkeypatch.setattr(documents.audit_service, "emit", fake_emit)
    monkeypatch.setattr(documents.blockchain_service, "anchor_document_hash", fake_anchor_document_hash)

    manager = TokenData(user_id="user-1", role="sustainability_manager", company_id="company-1")
    file = SimpleNamespace(filename="utility.pdf", content_type="application/pdf")

    result = await documents.upload_document(
        company_id="company-1",
        workspace_id="workspace-1",
        file=file,
        manager=manager,
    )

    assert inserted[0].blockchain_tx_id == "0xabc123"
    assert result["data"].blockchain_tx_id == "0xabc123"
    assert [call["event_type"] for call in audit_calls] == [
        "DOCUMENT_ANCHORED",
        "DOCUMENT_BLOCKCHAIN_ANCHORED",
    ]


@pytest.mark.asyncio
async def test_upload_document_allows_missing_blockchain_config(monkeypatch):
    inserted = []
    audit_calls = []

    class FakeDocument:
        def __init__(self, **kwargs):
            self.status = "uploaded"
            self.created_at = datetime(2025, 1, 1, tzinfo=UTC)
            for key, value in kwargs.items():
                setattr(self, key, value)

        @classmethod
        async def find_one(cls, query):
            return None

        async def insert(self):
            inserted.append(self)

        def model_dump(self):
            return {
                "id": self.id,
                "filename": self.filename,
                "content_type": self.content_type,
                "file_size_bytes": self.file_size_bytes,
                "sha256_hash": self.sha256_hash,
                "status": self.status,
                "blockchain_tx_id": self.blockchain_tx_id,
                "uploaded_by_id": self.uploaded_by_id,
                "created_at": self.created_at,
            }

    async def fake_scan_and_save(file, company_id, document_id):
        return "local://C:/tmp/local-only.pdf", "b" * 64, 1024

    async def fake_emit(**kwargs):
        audit_calls.append(kwargs)

    async def fake_anchor_document_hash(file_hash):
        return None

    monkeypatch.setattr(documents.storage_service, "scan_and_save", fake_scan_and_save)
    monkeypatch.setattr(documents, "Document", FakeDocument)
    monkeypatch.setattr(documents.audit_service, "emit", fake_emit)
    monkeypatch.setattr(documents.blockchain_service, "anchor_document_hash", fake_anchor_document_hash)

    manager = TokenData(user_id="user-1", role="sustainability_manager", company_id="company-1")
    file = SimpleNamespace(filename="local-only.pdf", content_type="application/pdf")

    result = await documents.upload_document(
        company_id="company-1",
        workspace_id="workspace-1",
        file=file,
        manager=manager,
    )

    assert inserted[0].blockchain_tx_id is None
    assert result["data"].blockchain_tx_id is None
    assert [call["event_type"] for call in audit_calls] == ["DOCUMENT_ANCHORED"]


@pytest.mark.asyncio
async def test_verify_hash_endpoint_returns_chain_status(monkeypatch):
    async def fake_build_hash_verification(file_hash):
        assert file_hash == "c" * 64
        return {
            "sha256_hash": file_hash,
            "blockchain_enabled": True,
            "chain_id": 80002,
            "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
            "verified_on_chain": True,
            "verification_status": "verified",
        }

    monkeypatch.setattr(documents.blockchain_service, "build_hash_verification", fake_build_hash_verification)

    manager = TokenData(user_id="user-1", role="sustainability_manager", company_id="company-1")
    result = await documents.verify_hash(
        data=HashVerificationRequest(sha256_hash="c" * 64),
        manager=manager,
    )

    assert result["data"].verified_on_chain is True
    assert result["data"].verification_status == "verified"


@pytest.mark.asyncio
async def test_verify_document_returns_stored_hash_metadata(monkeypatch):
    async def fake_get(document_id):
        return SimpleNamespace(
            id=document_id,
            company_id="company-1",
            sha256_hash="d" * 64,
            blockchain_tx_id="0xfeedbeef",
        )

    async def fake_build_hash_verification(file_hash):
        assert file_hash == "d" * 64
        return {
            "sha256_hash": file_hash,
            "blockchain_enabled": True,
            "chain_id": 80002,
            "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
            "verified_on_chain": False,
            "verification_status": "not_found",
        }

    monkeypatch.setattr(documents.Document, "get", fake_get)
    monkeypatch.setattr(documents.blockchain_service, "build_hash_verification", fake_build_hash_verification)

    manager = TokenData(user_id="user-1", role="sustainability_manager", company_id="company-1")
    result = await documents.verify_document("doc-1", manager=manager)

    assert result["data"].document_id == "doc-1"
    assert result["data"].blockchain_tx_id == "0xfeedbeef"
    assert result["data"].verification_status == "not_found"
