/**
 * HomeRoute — voice conversation interface.
 *
 * Thin wrapper around `VoiceConversation`. Loads the agent list via the
 * shared `useAgentStore` and renders the orchestrator.
 */

import { useEffect } from 'react'

import { VoiceConversation } from '../components/voice/VoiceConversation'
import { useAgentStore } from '../stores/agentStore'

export function HomeRoute() {
  const { agents, currentAgentId, isLoading, fetchAgents, selectAgent } =
    useAgentStore()

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  return (
    <VoiceConversation
      agents={agents}
      agentsLoading={isLoading}
      selectedAgentId={currentAgentId}
      onSelectAgent={selectAgent}
    />
  )
}
