"""Agent tool registry.

A `Tool` is an async callable with a declared argument schema; the
registry maps names → `Tool` instances and exposes `execute()` for
dispatch by name. Built-in tools:

  * `generate_speech` / `clone_voice` / `transcribe_audio` / `preview_voice`
    — voice stack via the plugin managers
  * `edit_audio` / `export_mixdown` — studio audio operations
  * `call_mcp` — generic MCP server connector

Tools are thin wrappers around existing services, reused by both the
conversational runtime and the studio agent.
"""

from melo.agents.tools.asr_tool import TranscribeAudioTool
from melo.agents.tools.clone_tool import CloneVoiceTool
from melo.agents.tools.edit_tool import EditAudioTool
from melo.agents.tools.mcp_tool import CallMCPTool
from melo.agents.tools.mixdown_tool import ExportMixdownTool
from melo.agents.tools.preview_voice_tool import PreviewVoiceTool
from melo.agents.tools.registry import Tool, ToolError, ToolRegistry, default_registry
from melo.agents.tools.studio_tool import StudioOpsTool
from melo.agents.tools.tts_tool import GenerateSpeechTool
from melo.agents.tools.voice_control_tool import VoiceControlTool

__all__ = [
    "CallMCPTool",
    "CloneVoiceTool",
    "EditAudioTool",
    "ExportMixdownTool",
    "GenerateSpeechTool",
    "PreviewVoiceTool",
    "StudioOpsTool",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "TranscribeAudioTool",
    "VoiceControlTool",
    "default_registry",
]
