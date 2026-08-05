"""Agent lifecycle service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melo.core.exceptions import not_found
from melo.models.db import Agent
from melo.models.schemas.agent import AgentCreate, AgentUpdate


async def list_agents(db: AsyncSession, user_id: str) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.user_id == user_id).order_by(Agent.created_at.desc()))
    return list(result.scalars().all())


async def create_agent(db: AsyncSession, user_id: str, data: AgentCreate) -> Agent:
    agent = Agent(user_id=user_id, **data.model_dump())
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def get_agent(db: AsyncSession, agent_id: str, user_id: str) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found("Agent not found")
    return agent


async def update_agent(db: AsyncSession, agent_id: str, user_id: str, data: AgentUpdate) -> Agent:
    agent = await get_agent(db, agent_id, user_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(agent, k, v)
    await db.commit()
    await db.refresh(agent)
    return agent


async def delete_agent(db: AsyncSession, agent_id: str, user_id: str) -> None:
    agent = await get_agent(db, agent_id, user_id)
    await db.delete(agent)
    await db.commit()
