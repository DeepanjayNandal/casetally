"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface StreamingTextProps {
  text: string
  isStreaming: boolean
}

export function StreamingText({ text, isStreaming }: StreamingTextProps) {
  const handleCitationClick = (ref: string) => {
    window.dispatchEvent(new CustomEvent("cite-click", { detail: { ref } }))
  }

  // Append cursor placeholder while streaming so markdown parser sees clean text
  const displayText = isStreaming ? text + "\u200B" : text

  return (
    <div
      aria-live="polite"
      aria-label="AI answer"
      style={{
        fontSize: "15px",
        lineHeight: 1.75,
        color: "hsl(var(--text-primary))",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings → Newsreader serif
          h1: ({ children }) => (
            <h1 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "20px", fontWeight: 600, color: "hsl(var(--text-primary))", margin: "20px 0 8px", letterSpacing: "-0.01em" }}>{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "18px", fontWeight: 600, color: "hsl(var(--text-primary))", margin: "18px 0 6px", letterSpacing: "-0.01em" }}>{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "16px", fontWeight: 600, color: "hsl(var(--text-primary))", margin: "14px 0 4px" }}>{children}</h3>
          ),
          // Paragraphs
          p: ({ children }) => (
            <p style={{ margin: "0 0 12px", lineHeight: 1.75, color: "hsl(var(--text-primary))" }}>{children}</p>
          ),
          // Bold — section headings like **Short Answer**
          strong: ({ children }) => (
            <strong style={{ fontWeight: 600, color: "hsl(var(--text-primary))" }}>{children}</strong>
          ),
          // Blockquote — Key Statutory Language
          blockquote: ({ children }) => (
            <blockquote style={{
              borderLeft: "3px solid hsl(var(--accent-muted))",
              paddingLeft: "16px",
              margin: "12px 0",
              color: "hsl(var(--text-secondary))",
              fontStyle: "italic",
              fontSize: "14px",
              lineHeight: 1.7,
            }}>
              {children}
            </blockquote>
          ),
          // Lists — Relevant Statutes
          ul: ({ children }) => (
            <ul style={{ paddingLeft: "20px", margin: "8px 0 12px", listStyleType: "disc" }}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol style={{ paddingLeft: "20px", margin: "8px 0 12px" }}>{children}</ol>
          ),
          li: ({ children }) => {
            // Extract plain text from children to check for USC citation pattern
            const extractText = (node: React.ReactNode): string => {
              if (typeof node === "string") return node
              if (Array.isArray(node)) return node.map(extractText).join("")
              if (node && typeof node === "object" && "props" in (node as object)) {
                return extractText((node as React.ReactElement).props.children)
              }
              return ""
            }
            const raw = extractText(children).trim()
            const match = raw.match(/^(\d+)\s+U\.S\.C\.\s+§\s+(\S+?)([\s—\-–].+)?$/)
            if (match) {
              const [, title, section, rest] = match
              const cleanSection = section.replace(/\.$/, "")
              const url = `https://www.govinfo.gov/link/uscode/${title}/${cleanSection}`
              return (
                <li style={{ margin: "4px 0", color: "hsl(var(--text-primary))" }}>
                  <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: "hsl(var(--accent))", textDecoration: "underline", textUnderlineOffset: "3px" }}>
                    {title} U.S.C. § {section}
                  </a>
                  {rest || ""}
                </li>
              )
            }
            return <li style={{ margin: "4px 0", color: "hsl(var(--text-primary))" }}>{children}</li>
          },
          // Inline code — legal citations like `18 U.S.C. § 2709`
          code: ({ children, className }) => {
            const isBlock = !!className
            if (isBlock) {
              return (
                <pre style={{ background: "hsl(var(--bg-surface))", borderRadius: "6px", padding: "12px 16px", fontSize: "13px", overflowX: "auto", margin: "12px 0" }}>
                  <code>{children}</code>
                </pre>
              )
            }
            // Inline citation — clickable
            const text = String(children)
            return (
              <span
                className="citation-badge"
                role="button"
                tabIndex={0}
                onClick={() => handleCitationClick(text)}
                onKeyDown={(e) => e.key === "Enter" && handleCitationClick(text)}
              >
                {children}
              </span>
            )
          },
          // Horizontal rule — section divider
          hr: () => (
            <hr style={{ border: "none", borderTop: "1px solid hsl(var(--border-subtle))", margin: "16px 0" }} />
          ),
          // Links — pass through (statute links injected by li renderer above)
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: "hsl(var(--accent))", textDecoration: "underline", textUnderlineOffset: "3px" }}>
              {children}
            </a>
          ),
        }}
      >
        {displayText}
      </ReactMarkdown>

      {/* Streaming cursor after last content */}
      {isStreaming && (
        <span className="streaming-cursor" aria-hidden="true" />
      )}
    </div>
  )
}
