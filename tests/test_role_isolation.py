"""The system_audit_officer must reach ONLY blueprint endpoints."""

import pytest

from app.dependencies.auth import (
    require_app_user, require_audit_officer, require_role, AUDIT_OFFICER_ROLE,
)
from app.schemas.auth import TokenData
from app.core.errors import AppError


def _td(role: str) -> TokenData:
    return TokenData(user_id="u1", role=role, company_id="c1")


def test_officer_denied_app_user_endpoints():
    with pytest.raises(AppError):
        require_app_user(_td(AUDIT_OFFICER_ROLE))


def test_tenant_user_allowed_app_user_endpoints():
    assert require_app_user(_td("sustainability_manager")).role == "sustainability_manager"


def test_officer_allowed_audit_endpoints():
    assert require_audit_officer(_td(AUDIT_OFFICER_ROLE)).role == AUDIT_OFFICER_ROLE


def test_non_officer_denied_audit_endpoints():
    with pytest.raises(AppError):
        require_audit_officer(_td("company_owner"))


def test_officer_denied_hierarchy_roles():
    # role absent from hierarchy → level 0 → denied every role-gated route
    checker = require_role("report_viewer")
    with pytest.raises(AppError):
        checker(_td(AUDIT_OFFICER_ROLE))
