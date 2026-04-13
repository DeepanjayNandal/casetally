"use client"

import { useState } from "react"

interface SampleQueryChipProps {
  query: string
  onClick: (query: string) => void
}

export function SampleQueryChip({ query, onClick }: SampleQueryChipProps) {
  const [hovered, setHovered] = useState(false)

  return (
    <button
      type="button"
      onClick={() => onClick(query)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: "6px 12px",
        border: `1px solid hsl(var(${hovered ? "--border-interactive" : "--border-subtle"}))`,
        borderRadius: "999px",
        background: hovered ? "hsl(var(--bg-surface))" : "transparent",
        color: "hsl(var(--text-secondary))",
        fontSize: "12px",
        fontWeight: 500,
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        cursor: "pointer",
        transform: hovered ? "scale(1.02)" : "scale(1)",
        transition: "background 0.15s ease, border-color 0.15s ease, transform 0.15s ease",
        whiteSpace: "nowrap",
      }}
    >
      {query}
    </button>
  )
}
