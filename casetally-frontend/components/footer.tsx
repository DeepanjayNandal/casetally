import { Github } from "lucide-react"

export function Footer() {
  return (
    <footer
      style={{
        borderTop: `1px solid hsl(var(--border-subtle))`,
        padding: "24px 40px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "12px",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
      }}
    >
      <span
        style={{
          fontSize: "12px",
          color: "hsl(var(--text-muted))",
        }}
      >
        CaseTally — Open-source legal research
      </span>
      <a
        href="https://github.com"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="GitHub"
        style={{
          color: "hsl(var(--text-muted))",
          display: "flex",
          alignItems: "center",
          transition: "color 0.15s ease",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-secondary))")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-muted))")}
      >
        <Github size={14} />
      </a>
    </footer>
  )
}
