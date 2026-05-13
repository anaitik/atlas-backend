from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from app.core.security import get_password_hash
from app.db.session import close_db, connect_db
from app.models.company import Company
from app.models.extraction import SchemaTemplate
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.company import CompanyCreate
from app.schemas.workspace import WorkspaceCreate
from app.services import tenant_service


@dataclass(frozen=True)
class DemoUserSpec:
    email: str
    full_name: str
    role: str


DEMO_COMPANY_NAME = "NovaTerra Manufacturing Ltd"
DEMO_WORKSPACE_NAME = "FY2025 CSRD Report"
DEMO_WORKSPACE_DESCRIPTION = "CSRD primary workspace with GRI + ISSB cross-mapping for investor demo."
DEMO_REPORTING_YEAR = 2025
DEMO_PASSWORD = "password123"

DEMO_ROLE_USERS = [
    DemoUserSpec("owner@novaterra.demo", "NovaTerra Owner", "company_owner"),
    DemoUserSpec("manager@novaterra.demo", "Sustainability Manager", "sustainability_manager"),
    DemoUserSpec("reviewer@novaterra.demo", "Data Reviewer", "data_reviewer"),
    DemoUserSpec("viewer@novaterra.demo", "Report Viewer", "report_viewer"),
]


async def upsert_user(
    *,
    email: str,
    full_name: str,
    role: str,
    status: str,
    company_id: str | None,
    password: str,
) -> User:
    normalized_email = email.strip().lower()
    user = await User.find_one({"email": normalized_email})
    if not user:
        user = User(
            email=normalized_email,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            role=role,
            status=status,
            company_id=company_id,
        )
        await user.insert()
        return user

    user.full_name = full_name
    user.role = role
    user.status = status
    user.company_id = company_id
    user.hashed_password = get_password_hash(password)
    await user.save()
    return user


async def ensure_company(admin_user_id: str, company_name: str) -> Company:
    company = await Company.find_one({"name": company_name})
    if company:
        if company.status != "active":
            company.status = "active"
            await company.save()
        return company
    return await tenant_service.create_company(CompanyCreate(name=company_name), admin_user_id)


async def reset_workspace(company_id: str, workspace_name: str, admin_user_id: str) -> int:
    existing = await Workspace.find({"company_id": company_id, "name": workspace_name}).to_list()
    for workspace in existing:
        await tenant_service.delete_workspace(company_id, workspace.id, admin_user_id)
    return len(existing)


async def ensure_workspace(company_id: str, admin_user_id: str) -> Workspace:
    workspace = await Workspace.find_one({"company_id": company_id, "name": DEMO_WORKSPACE_NAME})
    if workspace:
        return workspace

    return await tenant_service.create_workspace(
        company_id=company_id,
        data=WorkspaceCreate(
            name=DEMO_WORKSPACE_NAME,
            description=DEMO_WORKSPACE_DESCRIPTION,
            require_extraction_review=True,
            require_metric_approval=True,
            require_publish_approval=True,
            require_review_on_fallback_factor=True,
            region="EU",
            reporting_year=DEMO_REPORTING_YEAR,
            scope2_method="location_based",
        ),
        actor_id=admin_user_id,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed/reset Atlas investor demo data.")
    parser.add_argument("--admin-email", default="test@test.com", help="System admin login email.")
    parser.add_argument("--admin-name", default="Demo System Admin", help="System admin full name.")
    parser.add_argument("--password", default=DEMO_PASSWORD, help="Password used for seeded users.")
    parser.add_argument("--company-name", default=DEMO_COMPANY_NAME, help="Demo company name.")
    parser.add_argument(
        "--no-reset-workspace",
        action="store_true",
        help="Keep existing workspace if present instead of deleting and recreating.",
    )
    args = parser.parse_args()

    await connect_db()
    try:
        admin = await upsert_user(
            email=args.admin_email,
            full_name=args.admin_name,
            role="system_admin",
            status="active",
            company_id=None,
            password=args.password,
        )

        company = await ensure_company(admin.id, args.company_name)

        deleted_count = 0
        if not args.no_reset_workspace:
            deleted_count = await reset_workspace(company.id, DEMO_WORKSPACE_NAME, admin.id)

        workspace = await ensure_workspace(company.id, admin.id)

        seeded_users: list[str] = []
        for spec in DEMO_ROLE_USERS:
            user = await upsert_user(
                email=spec.email,
                full_name=spec.full_name,
                role=spec.role,
                status="active",
                company_id=company.id,
                password=args.password,
            )
            seeded_users.append(f"{user.email} ({user.role})")

        template_count = await SchemaTemplate.find({"company_id": company.id, "workspace_id": workspace.id}).count()

        print("Demo seed completed.")
        print(f"Admin: {admin.email} / {args.password}")
        print(f"Company: {company.name} ({company.id})")
        print(f"Workspace: {workspace.name} ({workspace.id})")
        print(f"Workspace reset: {'yes' if not args.no_reset_workspace else 'no'} (deleted: {deleted_count})")
        print(f"Templates provisioned: {template_count}")
        print("Role users:")
        for user_line in seeded_users:
            print(f" - {user_line}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
