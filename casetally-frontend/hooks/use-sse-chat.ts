import { useState, useCallback } from 'react'
import type { Message, Artifact } from '@/types/chat'

interface SSEMessage {
  type: 'text' | 'artifact'
  chunk?: string
  id?: string
  title?: string
  url?: string
}

export function useSSEChat(backendUrl: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null)

  const sendMessage = useCallback(
    async (userMessage: string) => {
      if (!userMessage.trim()) return

      // Add user message
      const userMsg: Message = {
        id: Date.now().toString(),
        role: 'user',
        content: userMessage,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, userMsg])
      setInput('')
      setIsLoading(true)

      // Create assistant message placeholder
      const assistantMsgId = (Date.now() + 1).toString()
      const assistantMsg: Message = {
        id: assistantMsgId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])

      try {
        // Call backend SSE endpoint
        const response = await fetch(`${backendUrl}/v1/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: userMessage,
            history: messages,
          }),
        })

        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (!response.body) throw new Error('No response body')

        // Parse SSE stream
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6)
              if (data === '[DONE]') break

              try {
                const json: SSEMessage = JSON.parse(data)

                if (json.type === 'text' && json.chunk) {
                  // Append text chunk to assistant message
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsgId
                        ? { ...m, content: m.content + json.chunk }
                        : m
                    )
                  )
                } else if (json.type === 'artifact' && json.id && json.url) {
                  // Attach artifact metadata to assistant message
                  const artifact: Artifact = {
                    id: json.id,
                    type: 'pdf',
                    title: json.title || 'Document',
                    content: '', // Not needed for Option 1 (file is on backend)
                    highlights: [],
                  }

                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsgId
                        ? { ...m, artifact }
                        : m
                    )
                  )
                }
              } catch {
                // Ignore parse errors
              }
            }
          }
        }
      } catch (error) {
        console.error('SSE error:', error)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? {
                  ...m,
                  content: '[Error streaming response]',
                }
              : m
          )
        )
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId && m.content === ''
              ? { ...m, content: 'No relevant results found for your query. Try rephrasing or using specific legal terms.' }
              : m
          )
        )
        setIsLoading(false)
      }
    },
    [messages, backendUrl]
  )

  const downloadArtifact = (artifactUrl: string) => {
    window.location.href = artifactUrl
  }

  return {
    messages,
    input,
    setInput,
    sendMessage,
    isLoading,
    selectedArtifact,
    setSelectedArtifact,
    downloadArtifact,
  }
}
