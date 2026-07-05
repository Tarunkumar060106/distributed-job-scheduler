"""Idempotent demo data seed.

Creates one account per RBAC role, all members of a shared demo organization,
so reviewers can experience each permission level with one click on the login
page. Runs at identity-service (and monolith) startup; every step is
check-before-insert, so restarts and replicas are safe.
"""
import logging

from sqlalchemy.orm import Session

from app.models import (
    Organization, OrganizationMember, OrgRole, Project, Queue, User,
)
from app.security import hash_password

logger = logging.getLogger("scheduler.seed")

DEMO_PASSWORD = "demo1234"
DEMO_ORG = "Acme Logistics (Demo)"
DEMO_USERS = [
    ("owner@demo.io", "Olivia Owner", OrgRole.OWNER),
    ("admin@demo.io", "Adam Admin", OrgRole.ADMIN),
    ("member@demo.io", "Mia Member", OrgRole.MEMBER),
    ("viewer@demo.io", "Victor Viewer", OrgRole.VIEWER),
]


def seed_demo_data(db: Session) -> None:
    org = db.query(Organization).filter_by(name=DEMO_ORG).first()
    if org is None:
        org = Organization(name=DEMO_ORG)
        db.add(org)
        db.flush()

    password_hash = hash_password(DEMO_PASSWORD)
    for email, name, role in DEMO_USERS:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = User(email=email, name=name, password_hash=password_hash)
            db.add(user)
            db.flush()
        membership = (db.query(OrganizationMember)
                      .filter_by(organization_id=org.id, user_id=user.id).first())
        if membership is None:
            db.add(OrganizationMember(organization_id=org.id,
                                      user_id=user.id, role=role))

    project = db.query(Project).filter_by(organization_id=org.id,
                                          name="logistics-core").first()
    if project is None:
        project = Project(organization_id=org.id, name="logistics-core",
                          description="Demo project seeded for reviewers")
        db.add(project)
        db.flush()
        db.add(Queue(project_id=project.id, name="notifications",
                     max_concurrency=5))

    db.commit()
    logger.info("Demo data ensured (org '%s', %d demo users)", DEMO_ORG,
                len(DEMO_USERS))
