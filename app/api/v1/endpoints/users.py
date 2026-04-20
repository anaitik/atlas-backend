from typing import Annotated, List
from fastapi import APIRouter, Depends
from app.core.pagination import PaginationParams
from app.core.responses import SuccessResponse, PaginatedSuccessResponse, api_response, paginated_response
from app.dependencies.auth import require_admin, TokenData
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserOut, UserUpdate
from app.services import user_service

router = APIRouter()
user_repo = UserRepository()

@router.get("", response_model=PaginatedSuccessResponse[UserOut])
async def list_users(
    _admin: Annotated[TokenData, Depends(require_admin)],
    pagination: Annotated[PaginationParams, Depends()]
):
    users, total = await user_repo.paginated(
        page=pagination.page, 
        page_size=pagination.page_size
    )
    return paginated_response(
        [UserOut(**u.model_dump()) for u in users],
        total,
        pagination.page,
        pagination.page_size
    )

@router.patch("/{user_id}", response_model=SuccessResponse[UserOut])
async def update_user(
    user_id: str,
    data: UserUpdate,
    admin: Annotated[TokenData, Depends(require_admin)]
):
    user = await user_service.update_user(user_id, data, actor_id=admin.user_id)
    return api_response(UserOut(**user.model_dump()))
