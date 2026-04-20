from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class InterviewQuestionOut(BaseModel):
    id: str
    pillar: str
    category: str = ""
    text: str
    hint: str = ""


class InterviewAnswerIn(BaseModel):
    question_id: str
    answer: Optional[str] = None


class ReportSectionOut(BaseModel):
    pillar: str
    title: str
    content: str
    data_caveats: List[str] = Field(default_factory=list)
    model_used: str = ""
    framework_tags: List[str] = Field(default_factory=list)
    # generated_at is optional to avoid serialisation failures on legacy records
    generated_at: Optional[datetime] = None


ReportOutputFormat = Literal["csrd", "gri", "tcfd", "integrated"]


class ReportGenerateRequest(BaseModel):
    output_format: ReportOutputFormat = "csrd"
    reporting_year: Optional[int] = None
    materiality_topics: List[str] = Field(default_factory=list)
    interview_answers: List[InterviewAnswerIn] = Field(default_factory=list)


class ReportSectionRegenerateRequest(BaseModel):
    pillar: str
    output_format: Optional[str] = None
    interview_answers: List[InterviewAnswerIn] = Field(default_factory=list)


class ReportRejectRequest(BaseModel):
    reason: str


class ReportOut(BaseModel):
    id: str
    company_id: str
    workspace_id: str
    reporting_year: int
    version: int
    output_format: str
    status: str
    exec_summary: str
    sections: Dict[str, Any]  # kept as Any to avoid strict nested validation on legacy docs
    data_lineage: List[Dict[str, Any]] = Field(default_factory=list)
    interview_answers: List[Dict[str, Any]] = Field(default_factory=list)
    generated_by_id: Optional[str] = None

    submitted_at: Optional[datetime] = None
    submitted_by_id: Optional[str] = None

    approved_at: Optional[datetime] = None
    approved_by_id: Optional[str] = None

    rejected_at: Optional[datetime] = None
    rejected_by_id: Optional[str] = None
    rejection_reason: Optional[str] = None

    published_at: Optional[datetime] = None
    published_by_id: Optional[str] = None

    canonical_xhtml: Optional[str] = None
    export_formats_generated: List[str] = Field(default_factory=list)

    sha256_hash: Optional[str] = None
    blockchain_tx_id: Optional[str] = None
    verification_signature: Optional[str] = None
    verification_url: Optional[str] = None
    verification_qr_data_url: Optional[str] = None
    superseded_by_report_id: Optional[str] = None
    raw_document_anchor_count: int = 0
    high_assurance_mode: bool = False

    created_at: datetime
    updated_at: datetime


class ReportPublicVerificationOut(BaseModel):
    report_id: str
    company_id: str
    workspace_id: str
    reporting_year: int
    version: int
    status: str
    sha256_hash: str
    blockchain_tx_id: Optional[str] = None
    verified_on_chain: bool = False
    verification_status: str
    signature_valid: bool
    verification_url: Optional[str] = None
    superseded_by_report_id: Optional[str] = None
    high_assurance_mode: bool = False
    raw_document_anchor_count: int = 0
