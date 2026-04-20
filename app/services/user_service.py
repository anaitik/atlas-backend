from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserUpdate
from app.services import audit_service

user_repo = UserRepository()

async def get_user(user_id: str) -> User:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise AppError(ErrorCode.NOT_FOUND, "User not found")
    return user

async def update_user(user_id: str, data: UserUpdate, actor_id: str) -> User:
    user = await get_user(user_id)
    
    old_status = user.status
    if data.full_name: user.full_name = data.full_name
    if data.role: user.role = data.role
    if data.status: user.status = data.status
    if data.company_id is not None: user.company_id = data.company_id
    
    await user_repo.update(user)
    
    if old_status != user.status and user.status == "active":
        await audit_service.emit(
            event_type="USER_APPROVED",
            actor_user_id=actor_id,
            entity_table="users",
            entity_id=user.id
        )
        
    return user
