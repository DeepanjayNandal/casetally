const STATS = [
  { label: "U.S. Code titles", value: "53" },
  { label: "Sections indexed", value: "47,207" },
  { label: "Search", value: "Hybrid BM25 + Vector" },
  { label: "Response time", value: "Sub-second" },
]

export function StatsBar() {
  return (
    <div
      style={{
        padding: "16px 40px",
        borderTop: `1px solid hsl(var(--border-subtle))`,
        borderBottom: `1px solid hsl(var(--border-subtle))`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "0",
        flexWrap: "wrap",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
      }}
    >
      {STATS.map((stat, i) => (
        <span
          key={stat.label}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            fontSize: "13px",
            color: "hsl(var(--text-muted))",
            padding: "4px 20px",
          }}
        >
          <span style={{ fontWeight: 600, color: "hsl(var(--text-secondary))" }}>
            {stat.value}
          </span>
          <span>{stat.label}</span>
          {i < STATS.length - 1 && (
            <span
              style={{
                marginLeft: "20px",
                color: "hsl(var(--border-interactive))",
              }}
            >
              ·
            </span>
          )}
        </span>
      ))}
    </div>
  )
}
