"""Studio routes — projects, tracks, clips.

All route handlers are thin wrappers around `melo.services.studio_service`
so business logic (ownership checks, TTS generation, edit dispatch)
lives in one testable place.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from melo.api.deps import get_current_user
from melo.models.database import get_db
from melo.models.db import User
from melo.models.schemas.studio import (
    ClipCreate,
    ClipEditRequest,
    ClipGenerateRequest,
    ClipOut,
    ClipUpdate,
    ClipVersion,
    ProjectCreate,
    ProjectOut,
    ProjectTreeOut,
    ProjectUpdate,
    ReorderTracksRequest,
    TrackCreate,
    TrackOut,
    TrackUpdate,
)
from melo.services import studio_service
from melo.voice.base import VoiceProviderUnavailable

router = APIRouter(prefix="/studio", tags=["studio"])


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await studio_service.list_projects(db, user.id)


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await studio_service.create_project(db, user.id, data)


@router.get("/projects/{project_id}", response_model=ProjectTreeOut)
async def get_project(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Return a project with nested tracks + clips (full studio snapshot)."""
    return await studio_service.get_project_tree(db, project_id, user.id)


@router.put("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.update_project(db, project_id, user.id, data)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await studio_service.delete_project(db, project_id, user.id)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/tracks", response_model=list[TrackOut])
async def list_tracks(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await studio_service.list_tracks(db, project_id, user.id)


@router.post("/projects/{project_id}/tracks", response_model=TrackOut, status_code=201)
async def create_track(
    project_id: str,
    data: TrackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.create_track(db, project_id, user.id, data)


@router.put("/projects/{project_id}/tracks/reorder", response_model=list[TrackOut])
async def reorder_tracks(
    project_id: str,
    data: ReorderTracksRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.reorder_tracks(db, project_id, user.id, data.track_ids)


@router.put("/tracks/{track_id}", response_model=TrackOut)
async def update_track(
    track_id: str,
    data: TrackUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.update_track(db, track_id, user.id, data)


@router.delete("/tracks/{track_id}", status_code=204)
async def delete_track(
    track_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await studio_service.delete_track(db, track_id, user.id)


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------


@router.get("/tracks/{track_id}/clips", response_model=list[ClipOut])
async def list_clips(
    track_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await studio_service.list_clips(db, track_id, user.id)


@router.post("/tracks/{track_id}/clips", response_model=ClipOut, status_code=201)
async def create_clip(
    track_id: str,
    data: ClipCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.create_clip(db, track_id, user.id, data)


@router.put("/clips/{clip_id}", response_model=ClipOut)
async def update_clip(
    clip_id: str,
    data: ClipUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await studio_service.update_clip(db, clip_id, user.id, data)


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip(
    clip_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await studio_service.delete_clip(db, clip_id, user.id)


@router.post("/clips/{clip_id}/generate", response_model=ClipOut)
async def generate_clip_audio(
    clip_id: str,
    data: ClipGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger TTS synthesis for a clip and persist the resulting audio.

    Returns 503 when no TTS provider is available (e.g. piper_local
    is configured but the piper package isn't installed). The clip's
    status is flipped to `error` in either case so the UI can react.
    """
    try:
        return await studio_service.generate_clip_audio(
            db, clip_id, user.id, voice_id=data.voice_id, speed=data.speed
        )
    except VoiceProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"TTS provider unavailable: {exc}",
        ) from exc


@router.post("/clips/{clip_id}/edit")
async def edit_clip(
    clip_id: str,
    data: ClipEditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a natural-language edit instruction to a clip."""
    return await studio_service.apply_edit(db, clip_id, user.id, data.instruction)


@router.get("/clips/{clip_id}/versions", response_model=list[ClipVersion])
async def list_clip_versions(
    clip_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List historical render versions of a clip's audio.

    Each version corresponds to one `generate` call. Use the `index`
    with `POST /clips/{clip_id}/revert/{version_index}` to switch back.
    """
    return await studio_service.list_clip_versions(db, clip_id, user.id)


@router.post("/clips/{clip_id}/revert/{version_index}", response_model=ClipOut)
async def revert_clip_to_version(
    clip_id: str,
    version_index: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch a clip's audio back to a previously rendered version.

    Audio files are never deleted from disk, so reverting just flips
    `audio_url` / `status` to point at the chosen version's URL.
    """
    return await studio_service.revert_clip_to_version(
        db, clip_id, user.id, version_index
    )
