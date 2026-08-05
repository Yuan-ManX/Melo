"""Voice library routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melo.api.deps import get_current_user
from melo.config import settings
from melo.models.database import get_db
from melo.models.db import User, Voice
from melo.models.schemas.voice import VoiceCreate, VoiceOut
from melo.voice.base import MeloVoiceError, VoiceProviderUnavailable
from melo.voice.manager import get_voice_manager

router = APIRouter(prefix="/voices", tags=["voices"])


@router.get("", response_model=list[VoiceOut])
async def list_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Voice).where(Voice.user_id == user.id).order_by(Voice.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=VoiceOut, status_code=201)
async def create(data: VoiceCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    voice = Voice(user_id=user.id, name=data.name, provider=data.provider, sample_url=data.sample_url, metadata_=data.metadata)
    db.add(voice)
    await db.commit()
    await db.refresh(voice)
    return voice


@router.delete("/{voice_id}", status_code=204)
async def delete(voice_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Voice).where(Voice.id == voice_id, Voice.user_id == user.id))
    voice = result.scalar_one_or_none()
    if voice:
        await db.delete(voice)
        await db.commit()


@router.get("/health")
async def health(user: User = Depends(get_current_user)) -> dict:
    """Report the status of each voice provider (ASR / TTS / Clone).

    Each entry is one of:
      * `available` — provider loaded + dependencies satisfied
      * `unavailable` — provider recognised but missing runtime / API key
      * `unknown`    — provider name not recognised

    The endpoint deliberately returns 200 even when providers are
    unavailable so the UI can render a useful diagnostic panel.
    """
    mgr = get_voice_manager()
    asr_status = _probe(lambda: mgr.get_asr(settings.asr_provider))
    tts_status = _probe(lambda: mgr.get_tts(settings.tts_provider))
    clone_status = _probe(lambda: mgr.get_clone(settings.clone_provider))
    return {
        "asr": {
            "configured": settings.asr_provider,
            "available": list(mgr.available_asr()),
            "status": asr_status,
        },
        "tts": {
            "configured": settings.tts_provider,
            "available": list(mgr.available_tts()),
            "status": tts_status,
        },
        "clone": {
            "configured": settings.clone_provider,
            "available": list(mgr.available_clone()),
            "status": clone_status,
        },
        "supported": {
            "asr": ["whisper_local", "openai", "deepgram", "stub"],
            "tts": ["piper_local", "openai", "elevenlabs", "stub"],
        },
    }


def _probe(builder) -> str:
    """Probe a provider; classify any error as unavailable / unknown."""
    try:
        provider = builder()
        return "available" if provider is not None else "unknown"
    except VoiceProviderUnavailable:
        return "unavailable"
    except MeloVoiceError:
        return "unknown"
    except Exception:
        # Lazy-build failures (import errors, missing model files) also
        # count as unavailable — the user can fix via .env.
        return "unavailable"
