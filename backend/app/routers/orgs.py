import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, OrganizationMember, OrgRole, Project, User
from app.schemas import (
    MemberAdd, MemberDetailOut, MemberOut, OrgCreate, OrgDetailOut, OrgOut,
    ProjectCreate, ProjectOut,
)
from app.security import get_current_user, require_org_role

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


@router.post("", response_model=OrgOut, status_code=201)
def create_org(body: OrgCreate, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    org = Organization(name=body.name)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.OWNER))
    db.commit()
    return org


@router.get("", response_model=list[OrgDetailOut])
def list_orgs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every organization the caller belongs to, with their role in each —
    the workspace switcher in the dashboard is built from this."""
    memberships = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .all()
    )
    result = []
    for membership in memberships:
        org = membership.organization
        result.append(OrgDetailOut(
            id=org.id, name=org.name, created_at=org.created_at,
            my_role=membership.role,
            member_count=db.query(OrganizationMember)
                .filter_by(organization_id=org.id).count(),
            project_count=db.query(Project)
                .filter_by(organization_id=org.id).count(),
        ))
    return result


@router.post("/{org_id}/members", response_model=MemberOut, status_code=201)
def add_member(org_id: uuid.UUID, body: MemberAdd,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_org_role(db, user, org_id, OrgRole.ADMIN)
    target = db.query(User).filter_by(email=body.email).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email")
    if db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=target.id).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    if body.role == OrgRole.OWNER:
        require_org_role(db, user, org_id, OrgRole.OWNER)
    member = OrganizationMember(organization_id=org_id, user_id=target.id, role=body.role)
    db.add(member)
    db.commit()
    return member


@router.get("/{org_id}/members", response_model=list[MemberDetailOut])
def list_members(org_id: uuid.UUID, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    require_org_role(db, user, org_id, OrgRole.VIEWER)
    members = db.query(OrganizationMember).filter_by(organization_id=org_id).all()
    return [MemberDetailOut(id=m.id, user_id=m.user_id, role=m.role,
                            email=m.user.email, name=m.user.name)
            for m in members]


@router.post("/{org_id}/projects", response_model=ProjectOut, status_code=201)
def create_project(org_id: uuid.UUID, body: ProjectCreate,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_org_role(db, user, org_id, OrgRole.ADMIN)
    if db.query(Project).filter_by(organization_id=org_id, name=body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Project name already exists in org")
    project = Project(organization_id=org_id, name=body.name, description=body.description)
    db.add(project)
    db.commit()
    return project


@router.get("/{org_id}/projects", response_model=list[ProjectOut])
def list_projects(org_id: uuid.UUID, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    require_org_role(db, user, org_id, OrgRole.VIEWER)
    return db.query(Project).filter_by(organization_id=org_id).all()
