from typing import Dict, Any
from app.models.workspace import Workspace
from app.core.errors import AppError, ErrorCode

class WorkflowPolicy:
    def __init__(self, workspace: Workspace):
        self.require_extraction_review = workspace.require_extraction_review
        self.require_metric_approval = workspace.require_metric_approval
        self.require_publish_approval = workspace.require_publish_approval
        self.require_review_on_fallback_factor = workspace.require_review_on_fallback_factor

async def get_workflow_policy(workspace_id: str) -> WorkflowPolicy:
    workspace = await Workspace.get(workspace_id)
    if not workspace:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found")
    return WorkflowPolicy(workspace)
