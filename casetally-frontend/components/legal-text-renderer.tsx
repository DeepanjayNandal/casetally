"use client"

interface LegalTextRendererProps {
  text: string
}

type SegmentKind = "chapter" | "top" | "nested" | "body"

interface Segment {
  kind: SegmentKind
  text: string
}

const CHAPTER_RE = /^(SUBCHAPTER|CHAPTER|PART|Sec\.|§)\s/i
const TOP_RE = /^\([a-z]\)\s/          // (a), (b), (c) ...
const NESTED_RE = /^\((\d+|[A-Z])\)\s/ // (1), (2), (A), (B) ...

// Split text into labeled segments based on legal subsection markers
function parseSegments(raw: string): Segment[] {
  // Split on subsection/chapter boundaries while keeping the delimiter
  const lines = raw.split(/\n/)
  const segments: Segment[] = []
  let current: string[] = []
  let currentKind: SegmentKind = "body"

  const flush = () => {
    const t = current.join(" ").trim()
    if (t) segments.push({ kind: currentKind, text: t })
    current = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    let kind: SegmentKind | null = null
    if (CHAPTER_RE.test(trimmed)) kind = "chapter"
    else if (TOP_RE.test(trimmed)) kind = "top"
    else if (NESTED_RE.test(trimmed)) kind = "nested"

    if (kind) {
      flush()
      currentKind = kind
      current.push(trimmed)
    } else {
      // Check if inline — text has a mid-sentence subsection marker
      // Split inline markers within a single long run-on paragraph
      const parts = trimmed.split(/(?=\([a-z]\)\s|\(\d+\)\s|\([A-Z]\)\s)/)
      if (parts.length > 1) {
        flush()
        for (const part of parts) {
          const p = part.trim()
          if (!p) continue
          if (TOP_RE.test(p)) segments.push({ kind: "top", text: p })
          else if (NESTED_RE.test(p)) segments.push({ kind: "nested", text: p })
          else segments.push({ kind: currentKind, text: p })
        }
        current = []
      } else {
        current.push(trimmed)
      }
    }
  }
  flush()
  return segments
}

export function LegalTextRenderer({ text }: LegalTextRendererProps) {
  const segments = parseSegments(text)

  return (
    <div
      style={{
        padding: "0",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        overflowY: "auto",
      }}
    >
      {segments.map((seg, i) => {
        if (seg.kind === "chapter") {
          return (
            <p
              key={i}
              style={{
                fontSize: "11px",
                fontWeight: 600,
                color: "hsl(var(--text-secondary))",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                marginBottom: "16px",
                marginTop: i === 0 ? 0 : "24px",
                lineHeight: 1.5,
              }}
            >
              {seg.text}
            </p>
          )
        }
        if (seg.kind === "top") {
          return (
            <p
              key={i}
              style={{
                fontSize: "15px",
                fontWeight: 400,
                color: "hsl(var(--text-primary))",
                lineHeight: 1.8,
                marginBottom: "12px",
              }}
            >
              {seg.text}
            </p>
          )
        }
        if (seg.kind === "nested") {
          return (
            <p
              key={i}
              style={{
                fontSize: "14px",
                fontWeight: 400,
                color: "hsl(var(--text-primary))",
                lineHeight: 1.75,
                marginBottom: "8px",
                paddingLeft: "24px",
              }}
            >
              {seg.text}
            </p>
          )
        }
        // body
        return (
          <p
            key={i}
            style={{
              fontSize: "15px",
              fontWeight: 400,
              color: "hsl(var(--text-secondary))",
              lineHeight: 1.8,
              marginBottom: "12px",
            }}
          >
            {seg.text}
          </p>
        )
      })}
    </div>
  )
}
