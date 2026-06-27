from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class MetricDefinitionOut(BaseModel):
    key: str
    description: str
    pillar: str
    unit: str
    suggested_tool: Optional[str] = None
    tags: List[str] = []


class MetricRecommendationReasonOut(BaseModel):
    metric_key: str
    reason: str


class MetricRecommendationSignalOut(BaseModel):
    key: str
    unit: Optional[str] = None
    records: List[str] = []
    paths: List[str] = []


class MetricRecommendationOut(BaseModel):
    metric_targets: List[str] = []
    structure_signals: List[MetricRecommendationSignalOut] = []
    explanation: str = ""
    rationale: List[MetricRecommendationReasonOut] = []


class MetricAgentRunRequest(BaseModel):
    metric_targets: Optional[List[str]] = None


class MetricCreate(BaseModel):
    metric_code: str
    name: str
    unit: str
    pillar: str = "environmental"
    value: float
    metadata: Dict[str, Any] = {}
    source_extracted_data_ids: List[str] = []

class MetricOut(BaseModel):
    id: str
    company_id: str
    workspace_id: str
    metric_code: str
    name: str
    unit: str
    pillar: str
    value: float
    metadata: Dict[str, Any]
    source_extracted_data_ids: List[str]
    status: str
    reviewer: Optional[str]
    created_at: datetime
    updated_at: datetime
    
class MetricReview(BaseModel):
    action: str  # "approve" or "reject"
    override_value: Optional[float] = None
    override_rationale: Optional[str] = None


class ManualMetricEntry(BaseModel):
    company_id: str
    workspace_id: str
    metric_code: str
    name: str
    value: float
    unit: str
    pillar: str = "environmental"
    evidence_note: Optional[str] = None
    evidence_document_id: Optional[str] = None


class MetricSummaryCardOut(BaseModel):
    key: str
    label: str
    unit: str
    value: float


class MetricSummaryOut(BaseModel):
    company_id: str
    workspace_id: str
    total_metrics: int
    environmental_count: int
    social_count: int
    governance_count: int
    cards: List[MetricSummaryCardOut] = Field(default_factory=list)
