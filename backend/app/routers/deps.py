"""Shared access-control helpers: resolve a resource and verify org membership."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import OrgRole, Project, Queue, User
from app.security import require_org_role


def get_project_checked(db: Session, user: User, project_id: uuid.UUID,
                        minimum: OrgRole = OrgRole.VIEWER) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    require_org_role(db, user, project.organization_id, minimum)
    return project


def get_queue_checked(db: Session, user: User, queue_id: uuid.UUID,
                      minimum: OrgRole = OrgRole.VIEWER) -> Queue:
    queue = db.get(Queue, queue_id)
    if queue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Queue not found")
    get_project_checked(db, user, queue.project_id, minimum)
    return queue
