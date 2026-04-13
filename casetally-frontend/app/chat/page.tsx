"use client"

import React from "react"
import { useRouter } from "next/navigation"
import { ChatInterface } from "@/components/chat/chat-interface"
import { Button } from "@/components/ui/button"
import { ArrowLeft } from "lucide-react"

export default function ChatPage() {
  const router = useRouter()
  return (
    <div className="h-screen w-full bg-background flex flex-col">
      <div className="border-b border-glass-border bg-glass/50 px-4 py-3 backdrop-blur-xl">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => router.back()}
          className="h-9 w-9"
          title="Go back"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
      </div>
      <ChatInterface />
    </div>
  )
}