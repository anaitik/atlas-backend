from app.core.errors import AppError, ErrorCode
from app.models.company import Company
from app.models.document import Document
from app.models.extraction import ExtractedData, SchemaTemplate
from app.models.metric import Metric
from app.models.report import Report
from app.models.workspace import Workspace
from app.schemas.company import CompanyCreate
from app.schemas.workspace import WorkspaceCreate
from app.services import audit_service
from app.services.default_esg_template_library import build_template_create_payload, list_default_templates
from app.services import storage_service

async def create_company(data: CompanyCreate, actor_id: str) -> Company:
    if await Company.find_one({"name": data.name}):
        raise AppError(ErrorCode.CONFLICT, "Company name already exists")
        
    company = Company(name=data.name)
    await company.insert()
    
    await audit_service.emit(
        event_type="COMPANY_CREATED", 
        actor_user_id=actor_id,
        company_id=company.id,
        entity_table="companies",
        entity_id=company.id
    )
    return company

async def get_company(company_id: str) -> Company:
    company = await Company.get(company_id)
    if not company:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found")
    return company

async def create_workspace(company_id: str, data: WorkspaceCreate, actor_id: str) -> Workspace:
    await get_company(company_id) # Verify company exists
    
    if await Workspace.find_one({"company_id": company_id, "name": data.name}):
        raise AppError(ErrorCode.CONFLICT, "Workspace name exists in company")
        
    workspace = Workspace(
        name=data.name,
        description=data.description,
        company_id=company_id,
        require_extraction_review=data.require_extraction_review,
        require_metric_approval=data.require_metric_approval,
        require_publish_approval=data.require_publish_approval,
        require_review_on_fallback_factor=data.require_review_on_fallback_factor,
        region=(data.region or "EU").upper(),
        reporting_year=data.reporting_year,
        scope2_method=(data.scope2_method or "location_based").lower(),
        nace_sector=data.nace_sector,
        employee_count_range=data.employee_count_range,
        turnover_range_eur=data.turnover_range_eur,
        is_listed=data.is_listed,
        is_first_time_reporter=data.is_first_time_reporter,
        material_topics=data.material_topics or [],
    )
    await workspace.insert()

    # Auto-provision default ESG evidence templates for each new workspace.
    default_templates = list_default_templates()
    for item in default_templates:
        payload = build_template_create_payload(item, workspace.id)
        template = SchemaTemplate(
            name=str(payload["name"]),
            company_id=company_id,
            workspace_id=workspace.id,
            schema_definition=payload["schema_definition"],
            system_prompt=str(payload["system_prompt"]),
            target_metrics_nlp=str(payload["target_metrics_nlp"]),
        )
        await template.insert()
    
    await audit_service.emit(
        event_type="WORKSPACE_CREATED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace.id,
        entity_table="workspaces",
        entity_id=workspace.id,
        payload={"default_templates_bootstrapped": len(default_templates)},
    )
    return workspace


async def _delete_model_records(model, filters: dict) -> int:
    records = await model.find(filters).to_list()
    for record in records:
        await record.delete()
    return len(records)


async def _delete_workspace_documents(company_id: str, workspace_id: str) -> tuple[int, int]:
    documents = await Document.find({"company_id": company_id, "workspace_id": workspace_id}).to_list()
    deleted_files = 0

    for document in documents:
        try:
            file_path = storage_service.get_file_path(document.storage_path)
            if file_path.exists():
                file_path.unlink()
                deleted_files += 1
        except (AppError, OSError):
            pass
        await document.delete()

    return len(documents), deleted_files


async def delete_workspace(company_id: str, workspace_id: str, actor_id: str) -> dict:
    await get_company(company_id)

    workspace = await Workspace.get(workspace_id)
    if not workspace or workspace.company_id != company_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found")

    extracted_records_deleted = await _delete_model_records(
        ExtractedData,
        {"company_id": company_id, "workspace_id": workspace_id},
    )
    metrics_deleted = await _delete_model_records(
        Metric,
        {"company_id": company_id, "workspace_id": workspace_id},
    )
    reports_deleted = await _delete_model_records(
        Report,
        {"company_id": company_id, "workspace_id": workspace_id},
    )
    templates_deleted = await _delete_model_records(
        SchemaTemplate,
        {"company_id": company_id, "workspace_id": workspace_id},
    )
    documents_deleted, files_deleted = await _delete_workspace_documents(company_id, workspace_id)

    workspace_name = workspace.name
    await workspace.delete()

    summary = {
        "deleted": True,
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "documents_deleted": documents_deleted,
        "files_deleted": files_deleted,
        "extractions_deleted": extracted_records_deleted,
        "metrics_deleted": metrics_deleted,
        "reports_deleted": reports_deleted,
        "templates_deleted": templates_deleted,
    }

    await audit_service.emit(
        event_type="WORKSPACE_DELETED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="workspaces",
        entity_id=workspace_id,
        payload=summary,
    )
    return summary
