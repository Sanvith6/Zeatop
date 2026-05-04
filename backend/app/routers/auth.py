from fastapi import APIRouter, HTTPException, status

from app.security import LoginRequest, TokenResponse, authenticate, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def issue_token(payload: LoginRequest) -> TokenResponse:
    if not authenticate(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return create_access_token(payload.username)
