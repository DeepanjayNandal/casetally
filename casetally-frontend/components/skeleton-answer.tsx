export function SkeletonAnswer() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: "8px 0",
      }}
    >
      {/* Pulsing ring */}
      <span
        style={{
          display: "inline-block",
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: "hsl(var(--accent))",
          flexShrink: 0,
          animation: "thinking-pulse 1.4s ease-in-out infinite",
        }}
        aria-hidden="true"
      />

      <span
        style={{
          fontSize: "13px",
          color: "hsl(var(--text-muted))",
          fontFamily: "var(--font-inter), system-ui, sans-serif",
        }}
      >
        Searching federal law
      </span>

      <span className="dot-loader" aria-hidden="true">
        <span /><span /><span />
      </span>
    </div>
  )
}
