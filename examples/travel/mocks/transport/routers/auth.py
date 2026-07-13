"""Auth routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..db import connect
from ..schemas import LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (body.username,),
        ).fetchone()
    if row is None or row["password"] != body.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    user = UserOut(
        user_id=row["user_id"],
        username=row["username"],
        display_name=row["display_name"],
        phone=row["phone"],
        email=row["email"],
    )
    return LoginResponse(token=row["token"], user=user)
