from fastapi import APIRouter
from app.core.responses import SuccessResponse, api_response
from app.schemas.auth import LoginRequest, RegisterRequest, AuthLoginData
from app.schemas.user import UserOut
from app.services import auth_service

router = APIRouter()

@router.post("/login", response_model=SuccessResponse[AuthLoginData])
async def login(data: LoginRequest):
    user, token = await auth_service.authenticate(data)
    return api_response(AuthLoginData(
        user=UserOut(**user.model_dump()),
        access_token=token,
        token_type="bearer"
    ))

@router.post("/register", response_model=SuccessResponse[UserOut])
async def register(data: RegisterRequest):
    user = await auth_service.register(data)
    return api_response(UserOut(**user.model_dump()))
