from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Interview Questions ──────────────────────────────────────────

class ValueSchemaOut(BaseModel):
    unit: str
    label: str


class InterviewQuestionOut(BaseModel):
    id: str
    question_number: int
    disclosure_id: str
    pillar: str
    category: str
    question_text: str
    help_text: str
    answer_modes: List[str]
    value_schema: Optional[ValueSchemaOut]
    metric_code: str
    metric_name: str
    bank_relevance: str


# ── Submit + Interpret ───────────────────────────────────────────

class InterviewAnswerSubmit(BaseModel):
    answer_mode: str                   # "upload" | "value" | "text" | "skipped"
    document_id: Optional[str] = None
    raw_value: Optional[float] = None
    raw_unit: Optional[str] = None
    raw_text: Optional[str] = None
    skipped_reason: Optional[str] = None


class InterpretTextRequest(BaseModel):
    raw_text: str


class InterpretedValueOut(BaseModel):
    value: Optional[float]
    unit: Optional[str]
    confidence: float
    reasoning: str


class ApproveAnswerRequest(BaseModel):
    override_value: Optional[float] = None
    override_unit: Optional[str] = None
    override_reason: Optional[str] = None   # required when changing an auto-filled/AI value


# ── Atlas ESG Score (v2) ─────────────────────────────────────────

class ScoreFlagOut(BaseModel):
    severity: str          # "critical" | "warn" | "info"
    code: str
    message: str


class SubScoreOut(BaseModel):
    key: str
    label: str
    score: Optional[int]
    weight: float
    detail: str
    value: Any = None
    scored: bool


class CarbonBenchmarkOut(BaseModel):
    intensity_tco2e_per_eur_m: float
    sector_median: float
    ratio_to_peers: float
    sector_label: Optional[str] = None
    confidence: Optional[str] = None
    turnover_basis: str


class AtlasScoreOut(BaseModel):
    performance_score: Optional[int]
    grade: str
    completeness_score: int
    data_trust_score: int
    provisional: bool
    pillar_performance: Dict[str, Optional[int]] = Field(default_factory=dict)
    pillar_completeness: Dict[str, int] = Field(default_factory=dict)
    carbon_benchmark: Optional[CarbonBenchmarkOut] = None
    flags: List[ScoreFlagOut] = Field(default_factory=list)
    breakdown: Dict[str, List[SubScoreOut]] = Field(default_factory=dict)
    trust_components: Dict[str, int] = Field(default_factory=dict)
    methodology: Dict[str, Any] = Field(default_factory=dict)


# ── Response / Progress ──────────────────────────────────────────

class InterviewResponseOut(BaseModel):
    id: str
    question_id: str
    answer_mode: str
    document_id: Optional[str]
    raw_value: Optional[float]
    raw_unit: Optional[str]
    raw_text: Optional[str]
    interpreted_metric_code: Optional[str]
    interpreted_value: Optional[float]
    interpreted_unit: Optional[str]
    interpretation_confidence: float
    interpretation_reasoning: Optional[str]
    status: str
    approved_metric_id: Optional[str]
    autofill_source: Optional[Dict[str, Any]] = None
    override_reason: Optional[str] = None


class InterviewProgressOut(BaseModel):
    workspace_id: str
    total_questions: int
    answered: int
    approved: int
    skipped: int
    completion_pct: int
    pillar_scores: Dict[str, int] = Field(default_factory=dict)
    overall_esg_score: int = 0
    data_quality_score: int = 0
    atlas_score: Optional[AtlasScoreOut] = None
    responses: List[InterviewResponseOut]


# ── Bank Access ──────────────────────────────────────────────────

class BankAccessCreate(BaseModel):
    institution_name: str
    allowed_pillars: List[str] = ["environmental", "social", "governance"]
    allow_document_access: bool = False
    expires_days: Optional[int] = 90   # None = no expiry


class BankAccessOut(BaseModel):
    id: str
    institution_name: str
    access_token: str
    access_url: str
    allowed_pillars: List[str]
    allow_document_access: bool
    expires_at: Optional[datetime]
    is_active: bool
    access_count: int
    created_at: datetime


# ── Bank Access Renewal ──────────────────────────────────────────

class RenewBankAccessRequest(BaseModel):
    expires_days: int = 90


# ── Bank Portal (public) ─────────────────────────────────────────

class UnansweredQuestionOut(BaseModel):
    id: str
    category: str
    metric_name: str
    pillar: str
    bank_relevance: str


class BankMetricOut(BaseModel):
    metric_code: str
    metric_name: str
    pillar: str
    value: float
    unit: str
    status: str


class BankPortalOut(BaseModel):
    company_name: str
    workspace_name: str
    reporting_year: Optional[int]
    nace_sector: Optional[str]
    employee_count_range: Optional[str]
    turnover_range_eur: Optional[str]

    # Interview completion
    interview_completion_pct: int
    total_approved: int
    total_questions: int

    # ESG Scores — overall_esg_score is now the real performance score (v2);
    # pillar_scores carry pillar performance. atlas_score holds the full,
    # self-explaining breakdown (benchmark, flags, completeness, trust).
    pillar_scores: Dict[str, int] = Field(default_factory=dict)
    overall_esg_score: int = 0
    data_quality_score: int = 0
    atlas_score: Optional[AtlasScoreOut] = None  # full self-explaining breakdown

    # Metrics
    metrics: List[BankMetricOut]
    unanswered_questions: List[UnansweredQuestionOut] = Field(default_factory=list)

    # Verification
    blockchain_verified: bool
    blockchain_tx_id: Optional[str]
    report_id: Optional[str]
    sha256_hash: Optional[str]

    # Meta
    institution_name: str
    generated_at: str
    atlas_verified: bool = True
