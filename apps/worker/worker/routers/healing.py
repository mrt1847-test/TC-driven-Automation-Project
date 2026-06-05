from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.database import get_session
from worker.models.db import HealingProposal, Project
from worker.services.healing_proposals import (
    accept_healing_proposal,
    apply_healing_proposal,
    healing_proposal_payload,
    reject_healing_proposal,
)
from worker.services.project_generator import GenerationConflictError

router = APIRouter(prefix="/projects/{project_id}/healing-proposals", tags=["healing"])


@router.get("")
def list_healing_proposals(
    project_id: str,
    automation_key: str | None = None,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    statement = select(HealingProposal).where(HealingProposal.project_id == project_id)
    if automation_key:
        statement = statement.where(HealingProposal.automation_key == automation_key)
    proposals = session.exec(statement.order_by(HealingProposal.created_at)).all()
    return [healing_proposal_payload(proposal) for proposal in proposals]


@router.get("/{proposal_id}")
def get_healing_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
):
    proposal = session.get(HealingProposal, proposal_id)
    if not proposal or proposal.project_id != project_id:
        raise HTTPException(404, "Healing proposal not found")
    return healing_proposal_payload(proposal)


@router.post("/{proposal_id}/accept")
def accept_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    proposal = session.get(HealingProposal, proposal_id)
    if not proposal or proposal.project_id != project_id:
        raise HTTPException(404, "Healing proposal not found")
    try:
        return accept_healing_proposal(session, project, proposal)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{proposal_id}/reject")
def reject_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    proposal = session.get(HealingProposal, proposal_id)
    if not proposal or proposal.project_id != project_id:
        raise HTTPException(404, "Healing proposal not found")
    try:
        return reject_healing_proposal(session, project, proposal)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{proposal_id}/apply")
def apply_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    proposal = session.get(HealingProposal, proposal_id)
    if not proposal or proposal.project_id != project_id:
        raise HTTPException(404, "Healing proposal not found")
    try:
        return apply_healing_proposal(session, project, proposal)
    except GenerationConflictError as exc:
        raise HTTPException(409, {"message": str(exc), **exc.summary()}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
