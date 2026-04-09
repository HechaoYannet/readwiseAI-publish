"""Authentication API routes."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_user
from app.auth.jwt_handler import create_access_token, should_refresh
from app.auth.models import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    RefreshResponse,
    VerifyInviteRequest,
    VerifyInviteResponse,
)
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/verify-invite", response_model=VerifyInviteResponse)
async def verify_invite(body: VerifyInviteRequest) -> VerifyInviteResponse:
    """Validate an invite code before registration."""
    valid, message = user_service.verify_invite_code(body.invite_code)
    return VerifyInviteResponse(valid=valid, message=message)


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request) -> RegisterResponse:
    """Register a new user with an invite code."""
    client_ip = request.client.host if request.client else ""
    user, error = user_service.register_user(
        invite_code=body.invite_code,
        username=body.username,
        exam_region=body.exam_region,
        password=body.password,
        confirm_password=body.confirm_password,
        grade=body.grade,
        school=body.school,
        client_ip=client_ip,
    )
    if user is None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": error},
        )
    token = create_access_token(user_id=user.id, role=user.role.value)
    return RegisterResponse(
        user_id=user.id,
        username=user.username,
        access_token=token,
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Login with username / phone / email and password."""
    user, error = user_service.login_user(body.login_id, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error,
        )
    token = create_access_token(user_id=user.id, role=user.role.value)
    return LoginResponse(
        user_id=user.id,
        username=user.username,
        access_token=token,
    )


@router.post("/logout")
async def logout() -> dict:
    """Logout endpoint – client should discard the token."""
    return {"message": "已退出登录"}


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
        token_data=Depends(get_current_user),
) -> RefreshResponse:
    """Issue a new token if the current one is close to expiry."""
    new_token = create_access_token(
        user_id=token_data.user_id, role=token_data.role
    )
    return RefreshResponse(access_token=new_token)
