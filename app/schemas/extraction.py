from datetime import datetime
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field, field_validator
from app.schemas.metric import MetricCreate, MetricRecommendationOut

class TemplateCreate(BaseModel):
    name: str
    workspace_id: Optional[str] = None
    schema_definition: Dict[str, Any]
    system_prompt: Optional[str] = None
    target_metrics_nlp: Optional[str] = None


class TemplateGenerationOut(BaseModel):
    filename: str
    document_preview: str
    template: Dict[str, Any]
    rules: Dict[str, Any] = Field(default_factory=dict)
    normalized_template: TemplateCreate
    validation_errors: list[str] = Field(default_factory=list)

class TemplateOut(BaseModel):
    id: str
    name: str
    company_id: str
    workspace_id: Optional[str] = None
    schema_definition: Dict[str, Any]
    system_prompt: str
    target_metrics_nlp: Optional[str] = None
    created_at: datetime
    
class ExtractedDataOut(BaseModel):
    id: str
    company_id: str
    workspace_id: str
    document_id: str
    template_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float
    exception_reason: Optional[str]
    status: str
    reviewer: Optional[str]
    document_filename: Optional[str] = None
    template_name: Optional[str] = None
    created_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, v: Any) -> Dict[str, Any]:
        if v is None:
            return {}
        return v


class DefaultTemplateLibraryItem(BaseModel):
    key: str
    name: str
    measurement_type: str
    output_unit: Optional[str] = None
    schema_definition: Dict[str, Any]
    target_metrics_nlp: str
    evidence_required: List[str] = Field(default_factory=list)
    standards_basis: List[str] = Field(default_factory=list)


class BootstrapDefaultTemplatesRequest(BaseModel):
    workspace_id: Optional[str] = None


class BootstrapDefaultTemplatesOut(BaseModel):
    created_count: int
    existing_count: int
    created_template_ids: List[str] = Field(default_factory=list)
    existing_template_names: List[str] = Field(default_factory=list)
    
class ExtractionRunRequest(BaseModel):
    document_id: str
    template_id: str


class ExtractionPreRunRequest(BaseModel):
    document_id: str
    template_id: str
    feedback_nlp: Optional[str] = None


class ExtractionPreRunOut(BaseModel):
    document_id: str
    template_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float
    exception_reason: Optional[str] = None
    status: str
    feedback_nlp_applied: Optional[str] = None
    metric_candidates: List[MetricCreate] = Field(default_factory=list)
    metric_recommendation: MetricRecommendationOut = Field(default_factory=MetricRecommendationOut)
    projected_metrics: List[Dict[str, Any]] = Field(default_factory=list)
    readiness_summary: Dict[str, Any] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    action: str  # approve, reject
    notes: Optional[str] = None
    overrides: Optional[Dict[str, Any]] = None # If the operator fixes some extracted numbers


class InsightAggregateOut(BaseModel):
    key: str
    label: str
    value: float
    unit: Optional[str] = None


class InsightIssueOut(BaseModel):
    extraction_id: str
    document_id: str
    document_filename: str
    field: str
    issue_type: str
    detail: str


class BlueprintInsightOut(BaseModel):
    template_id: str
    template_name: str
    documents_processed: int
    approved_count: int
    pending_count: int
    rejected_count: int
    average_confidence: float
    low_confidence_count: int
    missing_required_count: int
    aggregates: List[InsightAggregateOut] = Field(default_factory=list)
    top_issues: List[InsightIssueOut] = Field(default_factory=list)


class EvidenceDocumentOut(BaseModel):
    extraction_id: str
    document_id: str
    document_filename: str
    template_id: str
    template_name: str
    status: str
    confidence_score: float
    created_at: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


class ExtractionInsightsOut(BaseModel):
    workspace_id: str
    total_documents: int
    total_blueprints: int
    needs_review_count: int
    low_confidence_count: int
    blueprints: List[BlueprintInsightOut] = Field(default_factory=list)
    evidence_documents: List[EvidenceDocumentOut] = Field(default_factory=list)


class AuditEventOut(BaseModel):
    id: str
    event_type: str
    actor_user_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    company_id: Optional[str] = None
    workspace_id: Optional[str] = None
    entity_table: Optional[str] = None
    entity_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
