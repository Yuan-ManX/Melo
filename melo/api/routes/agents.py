"""Agent CRUD routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from melo.api.deps import get_current_user
from melo.models.database import get_db
from melo.models.db import User
from melo.models.schemas.agent import AgentCreate, AgentOut, AgentUpdate
from melo.services.agent_service import (
    create_agent, delete_agent, get_agent, list_agents, update_agent,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await list_agents(db, user.id)


@router.post("", response_model=AgentOut, status_code=201)
async def create(data: AgentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await create_agent(db, user.id, data)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_one(agent_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_agent(db, agent_id, user.id)


@router.put("/{agent_id}", response_model=AgentOut)
async def update(agent_id: str, data: AgentUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await update_agent(db, agent_id, user.id, data)


@router.delete("/{agent_id}", status_code=204)
async def delete(agent_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await delete_agent(db, agent_id, user.id)
