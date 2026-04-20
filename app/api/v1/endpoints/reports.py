from typing import Annotated, List
from fastapi import APIRouter, Depends, Query, Response

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_manager, require_role, TokenData
from app.schemas.report import (
    InterviewQuestionOut,
    ReportGenerateRequest,
    ReportOut,
    ReportPublicVerificationOut,
    ReportSectionRegenerateRequest,
    ReportRejectRequest,
)
from app.services import report_service, report_export_service
from app.services import blockchain_service, verification_service
from app.core.errors import AppError, ErrorCode

router = APIRouter()

@router.get("/questions", response_model=SuccessResponse[List[InterviewQuestionOut]])
async def list_interview_questions(
    _user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    questions = [
        InterviewQuestionOut(
            id=q["id"],
            pillar=q["pillar"],
            category=q.get("category", ""),
            text=q["text"],
            hint=q.get("hint", ""),
        )
        for q in report_service.list_interview_questions()
    ]
    return api_response(questions)


@router.get("", response_model=SuccessResponse[List[ReportOut]])
async def list_reports(
    company_id: str,
    workspace_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    reports = await report_service.list_reports(company_id, workspace_id, user.company_id)
    return api_response([ReportOut(**r.model_dump()) for r in reports])


@router.get("/{report_id}", response_model=SuccessResponse[ReportOut])
async def get_report(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    report = await report_service.get_report(report_id, user.company_id)
    return api_response(ReportOut(**report.model_dump()))


@router.post("/generate", response_model=SuccessResponse[ReportOut])
async def generate_report(
    company_id: str,
    workspace_id: str,
    data: ReportGenerateRequest,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    report = await report_service.generate_report(
        company_id,
        workspace_id,
        manager.user_id,
        manager.company_id,
        data.output_format,
        data.reporting_year,
        data.interview_answers,
    )
    return api_response(ReportOut(**report.model_dump()))


@router.post("/{report_id}/regenerate-section", response_model=SuccessResponse[ReportOut])
async def regenerate_report_section(
    report_id: str,
    data: ReportSectionRegenerateRequest,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    report = await report_service.regenerate_section(
        report_id,
        data.pillar,
        manager.user_id,
        manager.company_id,
        data.output_format,
        data.interview_answers,
    )
    return api_response(ReportOut(**report.model_dump()))


@router.post("/{report_id}/submit-for-review", response_model=SuccessResponse[ReportOut])
async def submit_report_for_review(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("sustainability_manager"))],
):
    report = await report_service.submit_for_review(report_id, user.user_id, user.company_id)
    return api_response(ReportOut(**report.model_dump()))


@router.post("/{report_id}/approve", response_model=SuccessResponse[ReportOut])
async def approve_report(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("sustainability_manager"))],
):
    report = await report_service.approve_report(report_id, user.user_id, user.company_id)
    return api_response(ReportOut(**report.model_dump()))


@router.post("/{report_id}/reject", response_model=SuccessResponse[ReportOut])
async def reject_report(
    report_id: str,
    data: ReportRejectRequest,
    user: Annotated[TokenData, Depends(require_role("sustainability_manager"))],
):
    report = await report_service.reject_report(report_id, user.user_id, data.reason, user.company_id)
    return api_response(ReportOut(**report.model_dump()))


@router.post("/{report_id}/publish", response_model=SuccessResponse[ReportOut])
async def publish_report(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("sustainability_manager"))],
):
    report = await report_service.publish_report(report_id, user.user_id, user.company_id)
    return api_response(ReportOut(**report.model_dump()))


from app.schemas.document import DocumentVerificationOut
@router.get("/{report_id}/verification", response_model=SuccessResponse[DocumentVerificationOut])
async def verify_report(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    report = await report_service.get_report(report_id, user.company_id)
    if not report.sha256_hash:
        raise AppError(ErrorCode.NOT_FOUND, "Report has not been anchored to the blockchain.")
        
    from app.services import blockchain_service
    verification = await blockchain_service.build_hash_verification(report.sha256_hash)
    return api_response(DocumentVerificationOut(
        document_id=report.id,
        blockchain_tx_id=report.blockchain_tx_id,
        **verification,
    ))



@router.get("/{report_id}/export")
async def export_report(
    report_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
    format: report_export_service.ReportExportFormat = Query(..., alias="format"),
):
    report = await report_service.get_report(report_id, user.company_id)
    if report.status not in ["approved", "published"]:
        raise AppError(ErrorCode.CONFLICT, "Only approved or published reports can be exported.")
        
    content = await report_export_service.export_report(report, format)
    
    media_types = {
        "xhtml": "application/xhtml+xml",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
    
    ext = format if format != "xhtml" else "html"
    filename = f"report_{report.reporting_year}_v{report.version}.{ext}"
    
    return Response(
        content=content,
        media_type=media_types.get(format, "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/public/verify/{report_id}", response_model=SuccessResponse[ReportPublicVerificationOut])
async def public_verify_report(
    report_id: str,
    sig: str = Query(..., description="Verification signature"),
):
    report = await report_service.get_report(report_id, actor_company_id=None)
    if not report.sha256_hash:
        raise AppError(ErrorCode.NOT_FOUND, "Report hash not available for verification.")

    stored_signature = report.verification_signature or ""
    signature_valid = verification_service.verify_report_signature(report, sig) and sig == stored_signature
    verification = await blockchain_service.build_hash_verification(report.sha256_hash)

    payload = ReportPublicVerificationOut(
        report_id=str(report.id),
        company_id=report.company_id,
        workspace_id=report.workspace_id,
        reporting_year=report.reporting_year,
        version=report.version,
        status=report.status,
        sha256_hash=report.sha256_hash,
        blockchain_tx_id=report.blockchain_tx_id,
        verified_on_chain=verification["verified_on_chain"],
        verification_status=verification["verification_status"],
        signature_valid=signature_valid,
        verification_url=report.verification_url,
        superseded_by_report_id=report.superseded_by_report_id,
        high_assurance_mode=report.high_assurance_mode,
        raw_document_anchor_count=report.raw_document_anchor_count,
    )
    return api_response(payload)
