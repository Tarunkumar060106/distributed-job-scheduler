import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import OrganizationMember, OrgRole, User

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret,
                             algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


# RBAC: role ranking used for "at least this role" checks.
ROLE_RANK = {OrgRole.VIEWER: 0, OrgRole.MEMBER: 1, OrgRole.ADMIN: 2, OrgRole.OWNER: 3}


def require_org_role(db: Session, user: User, org_id: uuid.UUID, minimum: OrgRole) -> OrganizationMember:
    member = (
        db.query(OrganizationMember)
        .filter_by(organization_id=org_id, user_id=user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organization")
    if ROLE_RANK[member.role] < ROLE_RANK[minimum]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Requires role {minimum.value} or higher (you are {member.role.value})",
        )
    return member
