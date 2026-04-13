"use client"

import { useState, useEffect, useRef } from "react"
import { ChevronDown } from "lucide-react"

interface SourceCardProps {
  index: number
  citation: string
  title: string
  snippet: string
  text: string
  score: number
  staggerDelay?: number
  isHighlighted?: boolean
}

export function SourceCard({
  index,
  citation,
  title,
  snippet,
  text,
  score,
  staggerDelay = 0,
  isHighlighted = false,
}: SourceCardProps) {
  const [expanded, setExpanded] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Scroll into view and briefly highlight when cited
  useEffect(() => {
    if (isHighlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
  }, [isHighlighted])

  const scorePercent = Math.round(Math.min(score * 100, 100))

  function getRelevanceLabel(score: number): string {
    if (score >= 0.75) return "Directly relevant"
    if (score >= 0.55) return "Supporting context"
    if (score >= 0.40) return "Related provision"
    return "Weak match"
  }

  return (
    <div
      ref={ref}
      className="source-card-in glass"
      style={{
        animationDelay: `${staggerDelay}ms`,
        borderLeft: `2px solid ${isHighlighted ? "hsl(var(--accent))" : "hsl(var(--accent-muted))"}`,
        borderRadius: "10px",
        padding: "16px",
        transition: "border-left-color 0.3s ease",
        cursor: "pointer",
        marginBottom: "10px",
      }}
    >
      {/* Header row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        style={{
          width: "100%",
          background: "none",
          border: "none",
          padding: 0,
          textAlign: "left",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "8px" }}>
          <div style={{ flex: 1 }}>
            <span
              style={{
                fontFamily: "'Courier New', monospace",
                fontSize: "12px",
                color: "hsl(var(--accent))",
                fontWeight: 500,
              }}
            >
              [{index}] {citation}
            </span>
            <p
              style={{
                fontSize: "13px",
                fontWeight: 500,
                color: "hsl(var(--text-primary))",
                marginTop: "4px",
                fontFamily: "var(--font-inter), system-ui, sans-serif",
                lineHeight: 1.4,
                display: "-webkit-box",
                WebkitLineClamp: expanded ? "unset" : 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              } as React.CSSProperties}
            >
              {title}
            </p>
          </div>
          <ChevronDown
            size={14}
            style={{
              color: "hsl(var(--text-muted))",
              flexShrink: 0,
              marginTop: "2px",
              transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.25s ease",
            }}
          />
        </div>

        {/* Relevance bar */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              flex: 1,
              height: "2px",
              background: "hsl(var(--bg-surface))",
              borderRadius: "2px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${scorePercent}%`,
                background: "hsl(var(--accent))",
                borderRadius: "2px",
              }}
            />
          </div>
          <span
            style={{
              fontSize: "10px",
              color: "hsl(var(--text-muted))",
              fontFamily: "var(--font-inter), system-ui, sans-serif",
              flexShrink: 0,
            }}
          >
            {getRelevanceLabel(score)}
          </span>
        </div>
      </button>

      {/* Expanded body */}
      <div className={`source-body ${expanded ? "expanded" : ""}`}>
        <div
          style={{
            paddingTop: "14px",
            borderTop: `1px solid hsl(var(--border-subtle))`,
            marginTop: "14px",
          }}
        >
          <p
            style={{
              fontSize: "13px",
              color: "hsl(var(--text-secondary))",
              lineHeight: 1.7,
              fontFamily: "var(--font-inter), system-ui, sans-serif",
              whiteSpace: "pre-wrap",
            }}
          >
            {text || snippet}
          </p>
        </div>
      </div>
    </div>
  )
}
