"""Pydantic models for auth request/response payloads."""
from __future__ import annotations
from pydantic import BaseModel


class VerifyInviteRequest(BaseModel):
    invite_code: str


class VerifyInviteResponse(BaseModel):
    valid: bool
    message: str = ""


class RegisterRequest(BaseModel):
    invite_code: str
    username: str
    password: str
    confirm_password: str
    exam_region: str
    grade: str = ""
    school: str = ""


class RegisterResponse(BaseModel):
    user_id: str
    username: str
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    login_id: str  # username, phone, or email
    password: str


class LoginResponse(BaseModel):
    user_id: str
    username: str
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: str
    role: str = "user"
