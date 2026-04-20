from typing import Annotated, List
from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_manager, TokenData
from app.models.extraction import SchemaTemplate
from app.schemas.extraction import (
    BootstrapDefaultTemplatesOut,
    BootstrapDefaultTemplatesRequest,
    DefaultTemplateLibraryItem,
    TemplateCreate,
    TemplateGenerationOut,
    TemplateOut,
)
from app.services import template_generation_service
from app.services.default_esg_template_library import (
    build_template_create_payload,
    list_default_templates,
)

router = APIRouter()


@router.get("/default-library", response_model=SuccessResponse[List[DefaultTemplateLibraryItem]])
async def list_default_library(
    manager: Annotated[TokenData, Depends(require_manager)],
):
    _ = manager
    items = [DefaultTemplateLibraryItem(**item) for item in list_default_templates()]
    return api_response(items)


@router.post("/bootstrap-defaults", response_model=SuccessResponse[BootstrapDefaultTemplatesOut])
async def bootstrap_default_templates(
    data: BootstrapDefaultTemplatesRequest,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    company_id = manager.company_id or "platform"
    workspace_id = data.workspace_id

    existing_query: dict[str, object] = {"company_id": company_id}
    if workspace_id:
        existing_query["workspace_id"] = workspace_id
    else:
        existing_query["workspace_id"] = None

    existing_templates = await SchemaTemplate.find(existing_query).to_list()
    existing_names = {template.name.strip().lower() for template in existing_templates if template.name}

    created_template_ids: list[str] = []
    existing_template_names: list[str] = []

    for item in list_default_templates():
        template_name = str(item.get("name") or "").strip()
        if not template_name:
            continue
        if template_name.lower() in existing_names:
            existing_template_names.append(template_name)
            continue

        payload = build_template_create_payload(item, workspace_id)
        template = SchemaTemplate(
            name=str(payload["name"]),
            company_id=company_id,
            workspace_id=payload["workspace_id"],
            schema_definition=payload["schema_definition"],
            system_prompt=str(payload["system_prompt"]),
            target_metrics_nlp=str(payload["target_metrics_nlp"]),
        )
        await template.insert()
        created_template_ids.append(str(template.id))
        existing_names.add(template_name.lower())

    return api_response(
        BootstrapDefaultTemplatesOut(
            created_count=len(created_template_ids),
            existing_count=len(existing_template_names),
            created_template_ids=created_template_ids,
            existing_template_names=existing_template_names,
        )
    )

@router.post("/generate", response_model=SuccessResponse[TemplateGenerationOut])
async def generate_template(
    file: Annotated[UploadFile, File()],
    manager: Annotated[TokenData, Depends(require_manager)],
    workspace_id: Annotated[str | None, Form()] = None,
    user_hints: Annotated[str, Form()] = "",
):
    payload = await template_generation_service.generate_template_from_document(
        file_bytes=await file.read(),
        filename=file.filename or "sample.pdf",
        workspace_id=workspace_id,
        user_hints=user_hints,
    )
    return api_response(TemplateGenerationOut(**payload))


@router.post("", response_model=SuccessResponse[TemplateOut])
async def create_template(
    data: TemplateCreate,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """Create a new extraction template."""
    company_id = manager.company_id or "platform"

    prompt = (data.system_prompt or "").strip()
    if not prompt:
        prompt = template_generation_service.build_compact_system_prompt(
            template_name=data.name,
            schema_definition=data.schema_definition,
            target_metrics_nlp=data.target_metrics_nlp,
        )

    t = SchemaTemplate(
        name=data.name,
        company_id=company_id,
        workspace_id=data.workspace_id,
        schema_definition=data.schema_definition,
        system_prompt=prompt,
        target_metrics_nlp=data.target_metrics_nlp
    )
    await t.insert()
    return api_response(TemplateOut(**t.model_dump()))
    
@router.patch("/{template_id}", response_model=SuccessResponse[TemplateOut])
async def update_template(
    template_id: str,
    data: TemplateCreate,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """Update an existing extraction template."""
    comp_id = manager.company_id or "platform"
    t = await SchemaTemplate.find_one({"_id": template_id, "company_id": comp_id})
    if not t:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.NOT_FOUND, "Template not found or access denied")
        
    t.name = data.name
    t.workspace_id = data.workspace_id
    t.schema_definition = data.schema_definition
    prompt = (data.system_prompt or "").strip()
    if not prompt:
        prompt = template_generation_service.build_compact_system_prompt(
            template_name=data.name,
            schema_definition=data.schema_definition,
            target_metrics_nlp=data.target_metrics_nlp,
        )
    t.system_prompt = prompt
    t.target_metrics_nlp = data.target_metrics_nlp
    
    await t.save()
    return api_response(TemplateOut(**t.model_dump()))

@router.get("", response_model=SuccessResponse[List[TemplateOut]])
async def list_templates(
    manager: Annotated[TokenData, Depends(require_manager)],
    workspace_id: str | None = None,
    ensure_defaults: bool = True,
):
    comp_id = manager.company_id or "platform"
    if workspace_id and ensure_defaults:
        existing_workspace_templates = await SchemaTemplate.find(
            {"company_id": comp_id, "workspace_id": workspace_id}
        ).to_list()
        existing_names = {
            template.name.strip().lower()
            for template in existing_workspace_templates
            if template.name
        }
        for item in list_default_templates():
            template_name = str(item.get("name") or "").strip()
            if not template_name or template_name.lower() in existing_names:
                continue
            payload = build_template_create_payload(item, workspace_id)
            template = SchemaTemplate(
                name=str(payload["name"]),
                company_id=comp_id,
                workspace_id=workspace_id,
                schema_definition=payload["schema_definition"],
                system_prompt=str(payload["system_prompt"]),
                target_metrics_nlp=str(payload["target_metrics_nlp"]),
            )
            await template.insert()
            existing_names.add(template_name.lower())

    query: dict[str, object] = {"company_id": comp_id}
    if workspace_id:
        query = {
            "company_id": comp_id,
            "$or": [{"workspace_id": workspace_id}, {"workspace_id": None}],
        }
    items = await SchemaTemplate.find(query).to_list()
    return api_response([TemplateOut(**i.model_dump()) for i in items])
