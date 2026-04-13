"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { useSSEChat } from "@/hooks/use-sse-chat"
import { Button } from "@/components/ui/button"
import { GlassCard } from "@/components/glass/glass-card"
import { ArtifactPanel } from "@/components/chat/artifact-panel"
import {
  Send,
  Copy,
  ThumbsUp,
  ThumbsDown,
  RotateCcw,
  User,
  Bot,
  FileText,
  Download,
  PanelRightOpen,
  PanelRightClose,
} from "lucide-react"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:3001"

// TODO: Replace with real backend data once connected
const MOCK_MESSAGES = [
  {
    id: "1",
    role: "user" as const,
    content: "What are the key provisions of the First Amendment?",
    artifact: null,
  },
  {
    id: "2",
    role: "assistant" as const,
    content: "The First Amendment protects five fundamental freedoms:\n\n1. **Freedom of Speech** - The right to express beliefs without government interference\n\n2. **Freedom of Religion** - Both the right to practice any religion and freedom from government-imposed religious requirements\n\n3. **Freedom of the Press** - Protection for journalism and media organizations\n\n4. **Freedom of Assembly** - The right to gather peacefully with others\n\n5. **Right to Petition** - The ability to appeal to the government for grievance redress\n\nThese protections apply to federal, state, and local governments through the 14th Amendment's incorporation doctrine.",
    artifact: {
      id: "first-amendment",
      type: "document" as const,
      title: "First Amendment Analysis",
      content: "The First Amendment to the United States Constitution protects several fundamental freedoms and rights. It is part of the Bill of Rights and is considered one of the most important amendments to the Constitution.",
    },
  },
]

interface ChatInterfaceProps {
  className?: string
}

export function ChatInterface({ className }: ChatInterfaceProps) {
  const {
    messages: hookMessages,
    input,
    setInput,
    sendMessage,
    isLoading,
    selectedArtifact,
    setSelectedArtifact,
    downloadArtifact,
  } = useSSEChat(BACKEND_URL)

  // TODO: Remove mock data once backend is connected
  const messages = hookMessages.length === 0 ? MOCK_MESSAGES : hookMessages

  const messagesEndRef = React.useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  React.useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    sendMessage(input)
  }

  const [showArtifact, setShowArtifact] = React.useState(true)

  return (
    <div className={cn("flex h-screen flex-col lg:flex-row overflow-hidden", className)}>
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "flex gap-4",
                  message.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                {message.role === "assistant" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                    <Bot className="h-4 w-4" />
                  </div>
                )}
                <div
                  className={cn(
                    "max-w-[80%] space-y-3",
                    message.role === "user" ? "order-first" : ""
                  )}
                >
                  <GlassCard
                    variant={message.role === "user" ? "prominent" : "default"}
                    className={cn(
                      "px-4 py-3",
                      message.role === "user"
                        ? "bg-foreground text-background"
                        : ""
                    )}
                  >
                    <div className={cn(
                      "prose prose-sm max-w-none",
                      message.role === "user" ? "prose-invert" : "dark:prose-invert"
                    )}>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">
                        {message.content}
                      </p>
                    </div>
                  </GlassCard>

                  {/* Artifact Button */}
                  {message.artifact && (
                    <button
                      onClick={() => {
                        setSelectedArtifact(message.artifact!)
                        setShowArtifact(true)
                      }}
                      className="flex items-center gap-2 rounded-lg border border-glass-border bg-glass/50 px-3 py-2 text-sm transition-all hover:bg-glass hover:shadow-md"
                    >
                      <FileText className="h-4 w-4 text-accent" />
                      <span className="font-medium">{message.artifact.title}</span>
                      <Download className="h-3.5 w-3.5 ml-auto text-muted-foreground" />
                    </button>
                  )}

                  {/* Message Actions */}
                  {message.role === "assistant" && (
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
                {message.role === "user" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <User className="h-4 w-4" />
                  </div>
                )}
              </div>
            ))}

            {isLoading && (
              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                  <Bot className="h-4 w-4" />
                </div>
                <GlassCard className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground" />
                    <div className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
                    <div className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
                  </div>
                </GlassCard>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-glass-border bg-glass/50 p-4 backdrop-blur-xl">
          <form onSubmit={handleSubmit} className="mx-auto max-w-3xl">
            <div className="relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about legal codes, regulations, or case law..."
                className="w-full rounded-xl border border-glass-border bg-background/50 py-4 pl-4 pr-24 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                disabled={isLoading}
              />
              <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
                <Button
                  type="submit"
                  size="icon"
                  className="h-8 w-8"
                  disabled={!input.trim() || isLoading}
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <p className="mt-2 text-center text-xs text-muted-foreground">
              CaseTally provides legal information for educational purposes only.
            </p>
          </form>
        </div>
      </div>

      {/* Artifact Panel */}
      {selectedArtifact && (
        <div className={cn(
          "border-l border-glass-border transition-all duration-300",
          showArtifact ? "w-1/2" : "w-0 overflow-hidden"
        )}>
          <div className="sticky top-0 flex items-center justify-between border-b border-glass-border bg-glass/50 px-4 py-3 backdrop-blur-xl">
            <h3 className="font-medium">{selectedArtifact.title}</h3>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  const artifactUrl = `/v1/artifacts/${selectedArtifact.id}/file`
                  downloadArtifact(artifactUrl)
                }}
                className="h-8 w-8"
                title="Download artifact"
              >
                <Download className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowArtifact(!showArtifact)}
                className="h-8 w-8"
              >
                {showArtifact ? (
                  <PanelRightClose className="h-4 w-4" />
                ) : (
                  <PanelRightOpen className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <ArtifactPanel artifact={selectedArtifact} />
        </div>
      )}

      {/* Toggle Artifact Button when hidden */}
      {selectedArtifact && !showArtifact && (
        <Button
          variant="outline"
          size="icon"
          onClick={() => setShowArtifact(true)}
          className="fixed right-4 top-24 z-50 h-10 w-10 rounded-full shadow-lg"
        >
          <PanelRightOpen className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}
