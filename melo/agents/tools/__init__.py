"""Agent tool registry.

A `Tool` is an async callable with a declared argument schema. The
registry maps tool names → `Tool` instances and exposes `execute()`
so the agent / planner can dispatch by name without knowing the
concrete implementation.

Built-in tools:
  * `generate_speech`  — TTS via the voice plugin manager.
  * `clone_voice`       — voice cloning via the voice plugin manager.
  * `edit_audio`        — studio audio editing.
  * `call_mcp`          — generic MCP server connector.
  * `transcribe_audio`  — ASR via the voice plugin manager.
  * `preview_voice`     — render a short TTS sample for a voice.
  * `export_mixdown`    — concatenate a project's clips into one WAV.

Tools are intentionally thin wrappers around existing services so
they can be reused by both the conversational runtime and the studio
agent without duplicating business logic.
"""

from melo.agents.tools.asr_tool import TranscribeAudioTool
from melo.agents.tools.clone_tool import CloneVoiceTool
from melo.agents.tools.edit_tool import EditAudioTool
from melo.agents.tools.mcp_tool import CallMCPTool
from melo.agents.tools.mixdown_tool import ExportMixdownTool
from melo.agents.tools.preview_voice_tool import PreviewVoiceTool
from melo.agents.tools.registry import Tool, ToolError, ToolRegistry, default_registry
from melo.agents.tools.tts_tool import GenerateSpeechTool

__all__ = [
    "CallMCPTool",
    "CloneVoiceTool",
    "EditAudioTool",
    "ExportMixdownTool",
    "GenerateSpeechTool",
    "PreviewVoiceTool",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "TranscribeAudioTool",
    "default_registry",
]
