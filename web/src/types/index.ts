export interface User {
  id: string
  email: string
  username: string
}

export interface Token {
  access_token: string
  token_type: string
  user: User
}

export interface Agent {
  id: string
  name: string
  persona: string | null
  system_prompt: string | null
  voice_id: string | null
  llm_config: Record<string, unknown>
  created_at: string
}

export interface Conversation {
  id: string
  agent_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  audio_url: string | null
  metadata_: Record<string, unknown>
  created_at: string
}

export interface Voice {
  id: string
  name: string
  provider: string
  provider_voice_id: string | null
  sample_url: string | null
  metadata_: Record<string, unknown>
  created_at: string
}

export interface Project {
  id: string
  name: string
  description: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface Track {
  id: string
  project_id: string
  name: string
  voice_id: string | null
  order: number
}

export interface Clip {
  id: string
  track_id: string
  text: string
  audio_url: string | null
  start_time: number
  duration: number
  status: string
  metadata_: Record<string, unknown>
  created_at: string
}

export interface ClipVersion {
  /** Position in `Clip.metadata_.versions` — used as the revert path param. */
  index: number
  audio_url: string | null
  bytes: number | null
  voice_id: string | null
  speed: number | null
  created_at: string | null
}

export interface TrackWithClips extends Track {
  clips: Clip[]
}

export interface ProjectTree extends Project {
  tracks: TrackWithClips[]
}

export interface ServerSettings {
  llm: {
    provider: string
    openai: { base_url: string; default_model: string; has_api_key: boolean }
    anthropic: { base_url: string; default_model: string; has_api_key: boolean }
  }
  voice: {
    asr_provider: string
    tts_provider: string
    clone_provider: string
    whisper_model_size: string
    piper_default_voice: string | null
    has_elevenlabs_key: boolean
    has_deepgram_key: boolean
  }
  websocket: { sample_rate: number; vad_threshold: number; silence_pad_ms: number }
  app: { name: string; version: string; backend_port: number }
}
