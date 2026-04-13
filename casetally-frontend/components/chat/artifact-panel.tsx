"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { Artifact, TextHighlight } from "@/types/chat"
import {
  Download,
  Copy,
  ZoomIn,
  ZoomOut,
  Highlighter,
  MessageSquare,
  FileText,
  Code,
  Table,
} from "lucide-react"

interface ArtifactPanelProps {
  artifact: Artifact
  className?: string
}

const highlightColors: Record<TextHighlight["color"], string> = {
  yellow: "bg-yellow-300/40 dark:bg-yellow-500/30",
  blue: "bg-blue-300/40 dark:bg-blue-500/30",
  green: "bg-green-300/40 dark:bg-green-500/30",
  pink: "bg-pink-300/40 dark:bg-pink-500/30",
}

const typeIcons = {
  pdf: FileText,
  code: Code,
  document: FileText,
  table: Table,
}

export function ArtifactPanel({ artifact, className }: ArtifactPanelProps) {
  const [zoom, setZoom] = React.useState(100)
  const [activeHighlight, setActiveHighlight] = React.useState<string | null>(null)

  const TypeIcon = typeIcons[artifact.type]

  const renderContentWithHighlights = () => {
    if (!artifact.highlights || artifact.highlights.length === 0) {
      return <p className="whitespace-pre-wrap">{artifact.content}</p>
    }

    // Sort highlights by start index
    const sortedHighlights = [...artifact.highlights].sort(
      (a, b) => a.startIndex - b.startIndex
    )

    const parts: React.ReactNode[] = []
    let lastIndex = 0

    sortedHighlights.forEach((highlight, index) => {
      // Add text before this highlight
      if (highlight.startIndex > lastIndex) {
        parts.push(
          <span key={`text-${index}`}>
            {artifact.content.slice(lastIndex, highlight.startIndex)}
          </span>
        )
      }

      // Add highlighted text
      parts.push(
        <span
          key={`highlight-${highlight.id}`}
          className={cn(
            "cursor-pointer rounded px-0.5 transition-all",
            highlightColors[highlight.color],
            activeHighlight === highlight.id && "ring-2 ring-accent"
          )}
          onClick={() => setActiveHighlight(
            activeHighlight === highlight.id ? null : highlight.id
          )}
        >
          {artifact.content.slice(highlight.startIndex, highlight.endIndex)}
          {highlight.note && activeHighlight === highlight.id && (
            <span className="ml-2 inline-flex items-center gap-1 rounded bg-popover px-2 py-1 text-xs text-popover-foreground shadow-lg">
              <MessageSquare className="h-3 w-3" />
              {highlight.note}
            </span>
          )}
        </span>
      )

      lastIndex = highlight.endIndex
    })

    // Add remaining text
    if (lastIndex < artifact.content.length) {
      parts.push(
        <span key="text-end">{artifact.content.slice(lastIndex)}</span>
      )
    }

    return <p className="whitespace-pre-wrap leading-relaxed">{parts}</p>
  }

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-glass-border bg-muted/30 px-4 py-2">
        <div className="flex items-center gap-2">
          <TypeIcon className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs font-medium uppercase text-muted-foreground">
            {artifact.type}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setZoom(Math.max(50, zoom - 10))}
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
          <span className="min-w-[3rem] text-center text-xs text-muted-foreground">
            {zoom}%
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setZoom(Math.min(200, zoom + 10))}
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
          <div className="mx-2 h-4 w-px bg-border" />
          <Button variant="ghost" size="icon" className="h-7 w-7">
            <Highlighter className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7">
            <Copy className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7">
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Highlights Legend */}
      {artifact.highlights && artifact.highlights.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-glass-border bg-muted/20 px-4 py-2">
          <span className="text-xs text-muted-foreground">Highlights:</span>
          {artifact.highlights.map((highlight) => (
            <button
              key={highlight.id}
              onClick={() => setActiveHighlight(
                activeHighlight === highlight.id ? null : highlight.id
              )}
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs transition-all",
                highlightColors[highlight.color],
                activeHighlight === highlight.id && "ring-2 ring-accent"
              )}
            >
              <span className="max-w-[100px] truncate">{highlight.text}</span>
              {highlight.note && (
                <MessageSquare className="h-3 w-3 text-muted-foreground" />
              )}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div
          className="mx-auto max-w-2xl rounded-lg border border-glass-border bg-card p-8 shadow-sm transition-transform"
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
        >
          {/* Document Header */}
          <div className="mb-6 border-b border-border pb-4">
            <h1 className="text-lg font-semibold">{artifact.title}</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              Legal Document • Last updated: {new Date().toLocaleDateString()}
            </p>
          </div>

          {/* Document Content */}
          <div className="prose prose-sm max-w-none dark:prose-invert">
            {renderContentWithHighlights()}
          </div>
        </div>
      </div>
    </div>
  )
}
