from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, UploadFile, File
from fastapi.responses import FileResponse

from app.core.errors import AppError, ErrorCode
from app.dependencies.auth import require_manager, TokenData
from app.models.document import Document
from app.schemas.document import (
    DocumentOut,
    DocumentVerificationOut,
    HashVerificationOut,
    HashVerificationRequest,
)
from app.services import storage_service, audit_service, blockchain_service

router = APIRouter()

from app.core.responses import SuccessResponse, api_response

@router.post("", response_model=SuccessResponse[DocumentOut])
async def upload_document(
    company_id: Annotated[str, Form()],
    workspace_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """Uploads a source document, computes its provenance hash, and saves to storage."""
    # Strict tenancy check
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    doc_id = str(uuid4())
    storage_path, file_hash, file_size = await storage_service.scan_and_save(file, company_id, doc_id)

    # Idempotent within the same workspace: reuse the existing document record
    # instead of failing the upload when the exact same file is retried.
    existing_doc = await Document.find_one(
        {
            "sha256_hash": file_hash,
            "company_id": company_id,
            "workspace_id": workspace_id,
        }
    )
    if existing_doc:
        path = storage_service.get_file_path(storage_path)
        if path.exists():
            path.unlink()
        return api_response(DocumentOut(**existing_doc.model_dump()))

    blockchain_tx_id = None
    try:
        blockchain_tx_id = await blockchain_service.anchor_document_hash(file_hash)
    except AppError as e:
        import structlog
        structlog.get_logger().warn("blockchain_anchoring_skipped_on_error", error=str(e))

    doc = Document(
        id=doc_id,
        company_id=company_id,
        workspace_id=workspace_id,
        uploaded_by_id=manager.user_id,
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        file_size_bytes=file_size,
        storage_path=storage_path,
        sha256_hash=file_hash,
        blockchain_tx_id=blockchain_tx_id,
    )
    await doc.insert()

    await audit_service.emit(
        event_type="DOCUMENT_ANCHORED",
        actor_user_id=manager.user_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="documents",
        entity_id=doc.id,
        payload={
            "filename": doc.filename,
            "sha256_hash": doc.sha256_hash,
            "blockchain_tx_id": doc.blockchain_tx_id,
        },
    )
    if blockchain_tx_id:
        await audit_service.emit(
            event_type="DOCUMENT_BLOCKCHAIN_ANCHORED",
            actor_user_id=manager.user_id,
            company_id=company_id,
            workspace_id=workspace_id,
            entity_table="documents",
            entity_id=doc.id,
            payload={
                "sha256_hash": doc.sha256_hash,
                "tx_hash": blockchain_tx_id,
            },
        )

    return api_response(DocumentOut(**doc.model_dump()))


@router.post("/verify-hash", response_model=SuccessResponse[HashVerificationOut])
async def verify_hash(
    data: HashVerificationRequest,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    verification = await blockchain_service.build_hash_verification(data.sha256_hash)
    return api_response(HashVerificationOut(**verification))


@router.get("/{document_id}/verification", response_model=SuccessResponse[DocumentVerificationOut])
async def verify_document(
    document_id: str,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    doc = await Document.get(document_id)
    if not doc:
        raise AppError(ErrorCode.NOT_FOUND, "Document not found")

    if manager.company_id and manager.company_id != doc.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    verification = await blockchain_service.build_hash_verification(doc.sha256_hash)
    return api_response(DocumentVerificationOut(
        document_id=doc.id,
        blockchain_tx_id=doc.blockchain_tx_id,
        **verification,
    ))

@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    doc = await Document.get(document_id)
    if not doc:
        raise AppError(ErrorCode.NOT_FOUND, "Document not found")
        
    if manager.company_id and manager.company_id != doc.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    path = storage_service.get_file_path(doc.storage_path)
    if not path.exists():
        raise AppError(ErrorCode.NOT_FOUND, "File missing from storage")
        
    return FileResponse(path, filename=doc.filename, media_type=doc.content_type)
