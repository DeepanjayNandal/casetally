import { Scale } from "lucide-react"

export function TrustBadge() {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "4px 12px",
        border: `1px solid hsl(var(--border-subtle))`,
        borderRadius: "999px",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
      }}
    >
      <Scale size={11} style={{ color: "hsl(var(--text-muted) / 0.5)" }} />
      <span
        style={{
          fontSize: "11px",
          fontWeight: 500,
          color: "hsl(var(--text-muted) / 0.5)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
        }}
      >
        U.S. Code · 54 Titles · govinfo.gov
      </span>
    </div>
  )
}
