from pathlib import Path

from app.services import extraction_agent, storage_service


def test_ensure_local_dir_uses_local_storage_path(tmp_path):
    original_path = storage_service.settings.LOCAL_STORAGE_PATH
    storage_service.settings.LOCAL_STORAGE_PATH = str(tmp_path)
    try:
        company_dir = storage_service._ensure_local_dir("tenant-a")
        assert company_dir == Path(tmp_path) / "tenant-a"
        assert company_dir.exists()
    finally:
        storage_service.settings.LOCAL_STORAGE_PATH = original_path


def test_fallback_value_uses_schema_hints():
    assert extraction_agent._fallback_value("float") == 0.0
    assert extraction_agent._fallback_value("integer") == 0
    assert extraction_agent._fallback_value("boolean") is False
    assert extraction_agent._fallback_value("date")
    assert extraction_agent._fallback_value({"nested": "string"}) == {"nested": ""}
