import { Search, Brain, FileCheck } from "lucide-react"

const STEPS = [
  {
    icon: Search,
    heading: "Search",
    description:
      "Ask any legal question in plain English — statutes, rights, procedures, or definitions.",
  },
  {
    icon: Brain,
    heading: "AI Analysis",
    description:
      "Our AI searches across 54 titles of federal law using hybrid BM25 + vector search.",
  },
  {
    icon: FileCheck,
    heading: "Cited Answer",
    description:
      "Get a clear answer with exact U.S. Code section citations you can verify and cite.",
  },
]

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      style={{
        padding: "80px 40px 112px",
        maxWidth: "1152px",
        margin: "0 auto",
      }}
    >
      <h2
        style={{
          fontFamily: "var(--font-newsreader), Georgia, serif",
          fontSize: "24px",
          fontWeight: 600,
          color: "hsl(var(--text-primary))",
          letterSpacing: "-0.01em",
          textAlign: "center",
          marginBottom: "48px",
        }}
      >
        How It Works
      </h2>

      <div className="how-it-works-grid">
        {STEPS.map((step, i) => {
          const Icon = step.icon
          return (
            <div
              key={step.heading}
              style={{
                backgroundColor: "hsl(var(--bg-elevated))",
                borderRadius: "12px",
                padding: "32px",
                borderTop: `2px solid hsl(215 50% 42%)`,
              }}
            >
              <div
                style={{
                  width: "40px",
                  height: "40px",
                  borderRadius: "8px",
                  background: `hsl(var(--bg-surface))`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: "20px",
                }}
              >
                <Icon size={18} style={{ color: "hsl(var(--accent))" }} />
              </div>

              <div
                style={{
                  fontSize: "11px",
                  fontWeight: 500,
                  color: "hsl(var(--text-muted))",
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  marginBottom: "8px",
                  fontFamily: "var(--font-inter), system-ui, sans-serif",
                }}
              >
                Step {i + 1}
              </div>

              <h3
                style={{
                  fontFamily: "var(--font-newsreader), Georgia, serif",
                  fontSize: "20px",
                  fontWeight: 500,
                  color: "hsl(var(--text-primary))",
                  marginBottom: "10px",
                }}
              >
                {step.heading}
              </h3>

              <p
                style={{
                  fontSize: "14px",
                  color: "hsl(var(--text-secondary))",
                  lineHeight: 1.7,
                  fontFamily: "var(--font-inter), system-ui, sans-serif",
                }}
              >
                {step.description}
              </p>
            </div>
          )
        })}
      </div>
    </section>
  )
}
