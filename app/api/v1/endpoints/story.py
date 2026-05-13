from typing import Annotated, List
from datetime import datetime, timezone
import hashlib

from fastapi import APIRouter, Depends
from app.dependencies.auth import get_current_user
from app.core.responses import SuccessResponse, api_response
from app.schemas.auth import TokenData
from app.schemas.story import PipelineStoryOut, StoryEventOut
from app.models.audit_event import AuditEvent
from app.services import blockchain_service

router = APIRouter()

@router.get("/{workspace_id}", response_model=SuccessResponse[PipelineStoryOut])
async def get_pipeline_story(
    workspace_id: str,
    _user: Annotated[TokenData, Depends(get_current_user)],
):
    """
    Get the narrative 'story' of the document pipeline for a workspace.
    """
    events_raw = await AuditEvent.find({"workspace_id": workspace_id}).sort("-created_at").to_list()
    
    events_out = []
    # Build a stable string for hashing the entire workspace audit trail
    audit_hash_source = []
    for ev in events_raw:
        headline = ev.event_type.replace("_", " ").title()
        detail = f"Entity: {ev.entity_table} ({ev.entity_id})" if ev.entity_table else "System Event"
        events_out.append(StoryEventOut(
            id=ev.id,
            event_type=ev.event_type,
            created_at=ev.created_at,
            headline=headline,
            detail=detail,
            payload=ev.payload,
        ))
        audit_hash_source.append(f"{ev.id}:{ev.event_type}:{ev.created_at.isoformat()}")
    
    story_text = "No tracked workspace activity has been recorded yet."
    workspace_hash = None
    verification = {
        **blockchain_service.blockchain_metadata(),
        "verified_on_chain": False,
        "verification_status": "not_configured",
    }
    tx_id = None
    
    if events_raw:
        count = len(events_raw)
        story_text = (
            f"The pipeline sequence has successfully tracked {count} distinct events within this reporting workspace. "
            "All events are hashed for replayable audit history."
        )
        # Hash the audit trail
        hash_str = "|".join(audit_hash_source)
        workspace_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        try:
            verification = await blockchain_service.build_hash_verification(workspace_hash)
        except Exception:
            verification = {
                **blockchain_service.blockchain_metadata(),
                "sha256_hash": workspace_hash,
                "verified_on_chain": False,
                "verification_status": "not_found",
            }

        if verification.get("verification_status") == "verified":
            story_text += " The workspace fingerprint is verified on-chain."
        elif verification.get("verification_status") == "not_found":
            story_text += " The workspace fingerprint is recorded off-chain and awaiting on-chain anchoring."
        else:
            story_text += " Blockchain verification is not configured in this environment."

    audit_story = PipelineStoryOut(
        workspace_id=workspace_id,
        story=story_text,
        events=events_out,
        generated_at=datetime.now(timezone.utc),
        sha256_hash=workspace_hash,
        blockchain_enabled=bool(verification.get("blockchain_enabled")),
        chain_id=verification.get("chain_id"),
        contract_address=verification.get("contract_address"),
        verified_on_chain=bool(verification.get("verified_on_chain")),
        verification_status=verification.get("verification_status", "not_configured"),
        blockchain_tx_id=tx_id,
    )
    return api_response(audit_story)

@router.get("/{workspace_id}/events", response_model=SuccessResponse[List[StoryEventOut]])
async def get_pipeline_events(
    workspace_id: str,
    _user: Annotated[TokenData, Depends(get_current_user)],
    limit: int = 20,
):
    """
    Get recent pipeline events.
    """
    events_raw = await AuditEvent.find({"workspace_id": workspace_id}).sort("-created_at").limit(limit).to_list()
    events_out = []
    for ev in events_raw:
        headline = ev.event_type.replace("_", " ").title()
        detail = f"Entity: {ev.entity_table} ({ev.entity_id})" if ev.entity_table else "System Event"
        events_out.append(StoryEventOut(
            id=ev.id,
            event_type=ev.event_type,
            created_at=ev.created_at,
            headline=headline,
            detail=detail,
            payload=ev.payload,
        ))
    return api_response(events_out)
