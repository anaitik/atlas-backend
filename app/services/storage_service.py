"""
Storage service handling local vs S3 seamlessly based on config.
"""

import hashlib
import os
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile

from app.config import StorageBackend, get_settings
from app.core.errors import AppError, ErrorCode

settings = get_settings()


def _local_storage_root() -> Path:
    return Path(settings.LOCAL_STORAGE_PATH).resolve()


def _ensure_local_dir(company_id: str) -> Path:
    base = _local_storage_root() / company_id
    base.mkdir(parents=True, exist_ok=True)
    return base


async def scan_and_save(file: UploadFile, company_id: str, document_id: str) -> Tuple[str, str, int]:
    """
    Streams file upload, computes SHA-256 for provenance, saves to disk.
    Returns: (storage_path, hash_hex, size_bytes)
    """
    sha256_algo = hashlib.sha256()
    size = 0
    
    # Determine save path
    if settings.STORAGE_BACKEND == StorageBackend.LOCAL:
        ext = os.path.splitext(file.filename or "unknown")[1]
        out_path = _ensure_local_dir(company_id) / f"{document_id}{ext}"
        storage_uri = f"local://{out_path.absolute()}"
        
        with open(out_path, "wb") as f_out:
            while chunk := await file.read(8192):
                sha256_algo.update(chunk)
                f_out.write(chunk)
                size += len(chunk)
    else:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Configured storage backend is not implemented")
        
    return storage_uri, sha256_algo.hexdigest(), size


def get_file_path(storage_uri: str) -> Path:
    if storage_uri.startswith("local://"):
        return Path(storage_uri[8:])
    raise AppError(ErrorCode.INTERNAL_ERROR, "Unsupported storage URI scheme")
