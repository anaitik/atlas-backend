"""
Document provenance tracking. Part of Pack 04.
"""

from __future__ import annotations

from typing import Optional
from pymongo import IndexModel

from app.models.base import BaseDocument

class Document(BaseDocument):
    """
    Tracks uploaded raw sources (e.g., invoices, CSR reports).
    Maps virtual paths to actual storage paths.
    """
    company_id: str
    workspace_id: str
    uploaded_by_id: str
    
    filename: str
    content_type: str
    file_size_bytes: int
    storage_path: str                 # URI (e.g., local://uploads/... or s3://...)
    
    # Blockchain/Provenance Hash
    sha256_hash: str
    blockchain_tx_id: Optional[str] = None
    
    status: str = "uploaded"          # uploaded, processing, archived
    
    class Settings:
        name = "documents"
        indexes = [
            IndexModel([("company_id", 1), ("workspace_id", 1)]),
            IndexModel([("sha256_hash", 1)]),
        ]
