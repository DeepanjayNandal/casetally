"use client"

import { Github } from "lucide-react"

const TECH_STACK = ["Next.js", "FastAPI", "pgvector", "Groq"]

export function Footer() {
  return (
    <footer
      style={{
        borderTop: `1px solid hsl(var(--border-subtle))`,
        padding: "24px 40px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        gap: "16px",
        flexWrap: "wrap",
      }}
    >
      {/* Left */}
      <span style={{ fontSize: "12px", color: "hsl(var(--text-muted))" }}>
        CaseTally · AI Legal Research System
      </span>

      {/* Right — tech badges + github */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
        {TECH_STACK.map((tech) => (
          <span
            key={tech}
            style={{
              fontSize: "11px",
              fontFamily: "var(--font-inter), system-ui, sans-serif",
              color: "hsl(var(--text-secondary))",
              background: "hsl(220 16% 10%)",
              border: "1px solid hsl(220 15% 20%)",
              borderRadius: "999px",
              padding: "2px 10px",
            }}
          >
            {tech}
          </span>
        ))}

        <a
          href="https://github.com/DeepanjayNandal"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub"
          style={{
            color: "hsl(var(--text-muted))",
            display: "flex",
            alignItems: "center",
            marginLeft: "4px",
            transition: "color 0.15s ease",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-secondary))")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-muted))")}
        >
          <Github size={14} />
        </a>
      </div>
    </footer>
  )
}
