"""Auth endpoints: login / logout / me."""
from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import settings
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import (
    COOKIE_NAME,
    authenticate,
    create_token,
    get_current_user,
)
from app.models.schemas import LoginRequest, UserOut

router = APIRouter()


@router.post("/auth/login", response_model=UserOut)
async def login(body: LoginRequest, response: Response):
    user = await authenticate(body.username, body.password)
    if not user:
        await log_audit(
            AuditAction.LOGIN_FAILED,
            details={"username": body.username},
            risk_level="warn",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(user)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.token_ttl_days * 86400,
        path="/",
    )
    await log_audit(AuditAction.LOGIN, user_id=str(user["id"]), details={"username": user["username"]})
    return user


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return user