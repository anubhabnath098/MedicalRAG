"""
api/auth_routes.py
------------------
Authentication endpoints.

POST /api/auth/register      Create account → sends OTP email
POST /api/auth/verify-otp    Verify OTP → activates account
POST /api/auth/login         Exchange credentials → JWT
POST /api/auth/resend-otp    Request a fresh OTP (pre-verification only)
GET  /api/auth/me            Return current user info (requires JWT)
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from models.schemas import (
    AuthMessageResponse,
    LoginRequest,
    RegisterRequest,
    ResendOTPRequest,
    TokenResponse,
    UserOut,
    VerifyOTPRequest,
)
from services.auth_service import AuthService, get_current_user

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])

_auth_service = AuthService()


@auth_router.post(
    "/register",
    response_model=AuthMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(body: RegisterRequest) -> AuthMessageResponse:
    """
    Create a new user account.
    A 6-digit OTP is sent to the provided email address.
    The account cannot be used until the OTP is verified.
    """
    print(body.email, body.password)
    result = _auth_service.register(email=body.email, password=body.password)
    return AuthMessageResponse(**result)


@auth_router.post(
    "/verify-otp",
    response_model=AuthMessageResponse,
    summary="Verify email with OTP",
)
def verify_otp(body: VerifyOTPRequest) -> AuthMessageResponse:
    """
    Submit the 6-digit OTP received by email to activate the account.
    OTPs expire after 10 minutes.
    """
    result = _auth_service.verify_otp(email=body.email, otp=body.otp)
    return AuthMessageResponse(**result)


@auth_router.post(
    "/resend-otp",
    response_model=AuthMessageResponse,
    summary="Resend OTP to email",
)
def resend_otp(body: ResendOTPRequest) -> AuthMessageResponse:
    """
    Request a new OTP if the previous one expired.
    Only works for unverified accounts.
    """
    result = _auth_service.resend_otp(email=body.email)
    return AuthMessageResponse(**result)


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive a JWT",
)
def login(body: LoginRequest) -> TokenResponse:
    """
    Exchange verified email + password for a JWT Bearer token.
    Include the token in the `Authorization: Bearer <token>` header for all
    subsequent API calls. The token expires after 24 hours (configurable via
    JWT_EXPIRE_MINUTES in .env).
    """
    result = _auth_service.login(email=body.email, password=body.password)
    return TokenResponse(**result)


@auth_router.get(
    "/me",
    response_model=UserOut,
    summary="Get current user info",
)
def me(current_user: Annotated[dict, Depends(get_current_user)]) -> UserOut:
    """Return the user_id and email of the currently authenticated user."""
    return UserOut(user_id=current_user["user_id"], email=current_user["email"])