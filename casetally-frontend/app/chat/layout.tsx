import React from "react"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Chat - CaseTally",
  description: "AI-powered chat interface for legal code analysis and document review.",
}

export default function ChatLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <>{children}</>
}
