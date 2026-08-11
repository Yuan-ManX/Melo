"""studio_ops tool — drive the whole studio from inside the agent loop.

One tool dispatching on an `action` argument — create a project, add a
track / clip, render audio, apply edits, inspect the sound library —
mapping each action onto `melo.services.studio_service` (or the ORM
models directly). Bound to a DB session + user; without them it raises
`ToolError`.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melo.agents.tools.registry import Tool, ToolError

logger = logging.getLogger(__name__)


class StudioOpsTool(Tool):
    """Perform studio operations scoped to a user + project.

    `run` dispatches on `action`; each supported action is implemented
    as a private `_action_<name>` coroutine. All results are plain,
    JSON-serialisable dicts.
    """

    name = "studio_ops"
    description = (
        "Operate on the user's studio. Dispatch on 'action'. Actions:\n"
        "  list_projects — list the user's projects\n"
        "  create_project (name, description?) — create a project\n"
        "  get_project (project_id) — project tree with tracks + clips\n"
        "  update_project (project_id, name?, description?) — rename or re-describe a project\n"
        "  delete_project (project_id) — remove a project\n"
        "  add_track (project_id, name, voice_id?) — create a track\n"
        "  update_track (track_id, name?, voice_id?) — edit a track\n"
        "  delete_track (track_id) — remove a track\n"
        "  reorder_tracks (project_id, track_ids) — set the track order\n"
        "  add_clip (track_id, text, start_time?) — create a clip\n"
        "  update_clip (clip_id, text?, start_time?, track_id?) — edit a clip\n"
        "  delete_clip (clip_id) — remove a clip\n"
        "  generate_clip (clip_id, voice_id?, speed?) — render clip audio\n"
        "  edit_clip (clip_id, instruction) — apply a natural-language edit\n"
        "  list_clip_versions (clip_id) — list a clip's historical renders\n"
        "  revert_clip (clip_id, version_index) — restore an older render\n"
        "  list_voices — list the user's voice library\n"
        "Returns a JSON object describing the outcome."
    )

    def __init__(
        self,
        *,
        db: AsyncSession | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._db = db
        self._user_id = user_id
        self._project_id = project_id

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs.get("action")
        if not action:
            raise ToolError("studio_ops requires an 'action'")
        if self._db is None or self._user_id is None:
            raise ToolError(
                "studio_ops requires a bound DB session + user_id; "
                "construct via StudioOpsTool(db=..., user_id=...)"
            )
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            raise ToolError(f"studio_ops: unknown action {action!r}")
        try:
            return await handler(**kwargs)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"studio_ops {action} failed: {exc}") from exc

    # -- actions -----------------------------------------------------------

    async def _action_list_projects(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        projects = await studio_service.list_projects(self._db, self._user_id)
        return {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "description": p.description,
                }
                for p in projects
            ]
        }

    async def _action_create_project(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import ProjectCreate
        from melo.services import studio_service

        name = kwargs.get("name")
        if not name:
            raise ToolError("create_project requires 'name'")
        data = ProjectCreate(name=name, description=kwargs.get("description"))
        project = await studio_service.create_project(self._db, self._user_id, data)
        return {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "description": project.description,
        }

    async def _action_get_project(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        project_id = kwargs.get("project_id") or self._project_id
        if not project_id:
            raise ToolError("get_project requires 'project_id'")
        project = await studio_service.get_project_tree(
            self._db, project_id, self._user_id
        )
        return self._serialize_project(project)

    async def _action_add_track(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import TrackCreate
        from melo.services import studio_service

        project_id = kwargs.get("project_id") or self._project_id
        name = kwargs.get("name")
        if not project_id or not name:
            raise ToolError("add_track requires 'project_id' and 'name'")
        data = TrackCreate(name=name, voice_id=kwargs.get("voice_id"))
        track = await studio_service.create_track(
            self._db, project_id, self._user_id, data
        )
        return {
            "id": track.id,
            "project_id": track.project_id,
            "name": track.name,
            "voice_id": track.voice_id,
            "order": track.order,
        }

    async def _action_add_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import ClipCreate
        from melo.services import studio_service

        track_id = kwargs.get("track_id")
        text = kwargs.get("text")
        if not track_id or not text:
            raise ToolError("add_clip requires 'track_id' and 'text'")
        start_time = float(kwargs.get("start_time", 0.0))
        data = ClipCreate(text=text, start_time=start_time)
        clip = await studio_service.create_clip(self._db, track_id, self._user_id, data)
        return {
            "id": clip.id,
            "track_id": clip.track_id,
            "text": clip.text,
            "start_time": clip.start_time,
            "status": clip.status,
        }

    async def _action_generate_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        if not clip_id:
            raise ToolError("generate_clip requires 'clip_id'")
        voice_id = kwargs.get("voice_id")
        speed = float(kwargs.get("speed", 1.0))
        clip = await studio_service.generate_clip_audio(
            self._db, clip_id, self._user_id, voice_id=voice_id, speed=speed
        )
        return {
            "id": clip.id,
            "status": clip.status,
            "audio_url": clip.audio_url,
            "duration": clip.duration,
        }

    async def _action_edit_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        instruction = kwargs.get("instruction")
        if not clip_id or not instruction:
            raise ToolError("edit_clip requires 'clip_id' and 'instruction'")
        result = await studio_service.apply_edit(
            self._db, clip_id, self._user_id, instruction
        )
        return result

    async def _action_update_project(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import ProjectUpdate
        from melo.services import studio_service

        project_id = kwargs.get("project_id")
        if not project_id:
            raise ToolError("update_project requires 'project_id'")
        fields = {k: v for k, v in {"name": kwargs.get("name"), "description": kwargs.get("description")}.items() if v is not None}
        if not fields:
            raise ToolError("update_project requires at least one of 'name' or 'description'")
        data = ProjectUpdate(**fields)
        project = await studio_service.update_project(
            self._db, project_id, self._user_id, data
        )
        return {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "description": project.description,
        }

    async def _action_delete_project(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        project_id = kwargs.get("project_id")
        if not project_id:
            raise ToolError("delete_project requires 'project_id'")
        await studio_service.delete_project(self._db, project_id, self._user_id)
        return {"deleted": project_id}

    async def _action_update_track(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import TrackUpdate
        from melo.services import studio_service

        track_id = kwargs.get("track_id")
        if not track_id:
            raise ToolError("update_track requires 'track_id'")
        fields = {k: v for k, v in {"name": kwargs.get("name"), "voice_id": kwargs.get("voice_id")}.items() if v is not None}
        if not fields:
            raise ToolError("update_track requires at least one of 'name' or 'voice_id'")
        data = TrackUpdate(**fields)
        track = await studio_service.update_track(
            self._db, track_id, self._user_id, data
        )
        return {
            "id": track.id,
            "name": track.name,
            "voice_id": track.voice_id,
            "order": track.order,
        }

    async def _action_delete_track(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        track_id = kwargs.get("track_id")
        if not track_id:
            raise ToolError("delete_track requires 'track_id'")
        await studio_service.delete_track(self._db, track_id, self._user_id)
        return {"deleted": track_id}

    async def _action_reorder_tracks(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        project_id = kwargs.get("project_id")
        track_ids = kwargs.get("track_ids")
        if not project_id or not track_ids:
            raise ToolError("reorder_tracks requires 'project_id' and a non-empty 'track_ids' list")
        await studio_service.reorder_tracks(
            self._db, project_id, self._user_id, list(track_ids)
        )
        return {"reordered": list(track_ids)}

    async def _action_update_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.schemas.studio import ClipUpdate
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        if not clip_id:
            raise ToolError("update_clip requires 'clip_id'")
        fields = {
            k: v
            for k, v in {
                "text": kwargs.get("text"),
                "start_time": kwargs.get("start_time"),
                "track_id": kwargs.get("track_id"),
            }.items()
            if v is not None
        }
        if not fields:
            raise ToolError("update_clip requires at least one of 'text', 'start_time' or 'track_id'")
        data = ClipUpdate(**fields)
        clip = await studio_service.update_clip(
            self._db, clip_id, self._user_id, data
        )
        return {
            "id": clip.id,
            "text": clip.text,
            "start_time": clip.start_time,
            "status": clip.status,
            "track_id": clip.track_id,
        }

    async def _action_delete_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        if not clip_id:
            raise ToolError("delete_clip requires 'clip_id'")
        await studio_service.delete_clip(self._db, clip_id, self._user_id)
        return {"deleted": clip_id}

    async def _action_list_clip_versions(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        if not clip_id:
            raise ToolError("list_clip_versions requires 'clip_id'")
        versions = await studio_service.list_clip_versions(
            self._db, clip_id, self._user_id
        )
        return {"clip_id": clip_id, "versions": versions}

    async def _action_revert_clip(self, **kwargs: Any) -> dict[str, Any]:
        from melo.services import studio_service

        clip_id = kwargs.get("clip_id")
        version_index = kwargs.get("version_index")
        if not clip_id or version_index is None:
            raise ToolError("revert_clip requires 'clip_id' and 'version_index'")
        clip = await studio_service.revert_clip_to_version(
            self._db, clip_id, self._user_id, int(version_index)
        )
        return {
            "id": clip.id,
            "audio_url": clip.audio_url,
            "status": clip.status,
            "duration": clip.duration,
        }

    async def _action_list_voices(self, **kwargs: Any) -> dict[str, Any]:
        from melo.models.db import Voice

        result = await self._db.execute(
            select(Voice).where(Voice.user_id == self._user_id)
        )
        voices = result.scalars().all()
        return {
            "voices": [
                {"id": v.id, "name": v.name, "provider": v.provider}
                for v in voices
            ]
        }

    # -- serialization -----------------------------------------------------

    @staticmethod
    def _serialize_project(project: Any) -> dict[str, Any]:
        """Flatten a project tree into a JSON-friendly dict."""
        tracks = []
        for tr in getattr(project, "tracks", None) or []:
            clips = []
            for c in getattr(tr, "clips", None) or []:
                clips.append(
                    {
                        "id": c.id,
                        "text": c.text,
                        "audio_url": c.audio_url,
                        "start_time": c.start_time,
                        "duration": c.duration,
                        "status": c.status,
                    }
                )
            tracks.append(
                {
                    "id": tr.id,
                    "name": tr.name,
                    "voice_id": tr.voice_id,
                    "order": tr.order,
                    "clips": clips,
                }
            )
        return {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "description": project.description,
            "tracks": tracks,
        }