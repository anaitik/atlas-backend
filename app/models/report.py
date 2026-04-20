"""
Generated report model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from datetime import datetime

from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument

ReportStatus = Literal["draft", "review", "approved", "rejected", "published"]

class Report(BaseDocument):
    company_id: str
    workspace_id: str
    reporting_year: int
    version: int = 1
    output_format: str = "csrd"
    status: ReportStatus = "draft"
    exec_summary: str = ""
    sections: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    data_lineage: List[Dict[str, Any]] = Field(default_factory=list)
    interview_answers: List[Dict[str, Any]] = Field(default_factory=list)
    generated_by_id: Optional[str] = None
    
    # Workflow Audit
    submitted_at: Optional[datetime] = None
    submitted_by_id: Optional[str] = None
    
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[str] = None
    
    rejected_at: Optional[datetime] = None
    rejected_by_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    published_at: Optional[datetime] = None
    published_by_id: Optional[str] = None
    
    # Artifacts
    canonical_xhtml: Optional[str] = None
    export_formats_generated: List[str] = Field(default_factory=list)

    # Blockchain
    sha256_hash: Optional[str] = None
    blockchain_tx_id: Optional[str] = None
    verification_signature: Optional[str] = None
    verification_url: Optional[str] = None
    verification_qr_data_url: Optional[str] = None
    superseded_by_report_id: Optional[str] = None
    raw_document_anchor_count: int = 0
    high_assurance_mode: bool = False

    class Settings:
        name = "reports"
        indexes = [
            IndexModel([("company_id", 1), ("workspace_id", 1), ("created_at", -1)]),
            IndexModel([("workspace_id", 1), ("reporting_year", 1), ("version", -1)]),
            IndexModel([("company_id", 1), ("workspace_id", 1), ("status", 1)]),
        ]
