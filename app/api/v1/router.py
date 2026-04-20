from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, companies, documents, templates, extraction, metrics, admin, reports, story, settings

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["Platform Admin"])
api_router.include_router(users.router, prefix="/users", tags=["Users (Admin)"])
api_router.include_router(companies.router, prefix="/companies", tags=["Tenancy"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents & Provenance"])
api_router.include_router(templates.router, prefix="/templates", tags=["Extraction Templates"])
api_router.include_router(extraction.router, prefix="/extraction", tags=["Extraction Agent"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["Computed Metrics"])
api_router.include_router(reports.router, prefix="/reports", tags=["Report Studio"])
api_router.include_router(story.router, prefix="/story", tags=["Pipeline Story"])
api_router.include_router(settings.router, prefix="/settings", tags=["Tenant Settings"])
