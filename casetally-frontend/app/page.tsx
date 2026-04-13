"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Nav } from "@/components/nav"
import { Footer } from "@/components/footer"
import { SearchInput } from "@/components/search-input"
import { TrustBadge } from "@/components/trust-badge"
import { SampleQueryChip } from "@/components/sample-query-chip"
import { HowItWorks } from "@/components/how-it-works"
import { StatsBar } from "@/components/stats-bar"

const SAMPLE_QUERIES = [
  "Patent eligibility requirements",
  "First Amendment protections",
  "Federal tax brackets",
]

export default function HomePage() {
  const router = useRouter()
  const [query, setQuery] = useState("")

  const handleSubmit = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    router.push(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  const handleChipClick = (q: string) => {
    setQuery(q)
    handleSubmit(q)
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "hsl(var(--bg-primary))",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Nav />

      {/* Hero — true center, no excess top padding */}
      <main
        id="main-content"
        className="hero-main"
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 20px 48px",
          minHeight: "calc(100vh - 64px)", /* overridden on mobile via CSS */
        }}
      >
        {/* Trust badge */}
        <div className="fade-up fade-up-1" style={{ marginBottom: "28px" }}>
          <TrustBadge />
        </div>

        {/* Headline */}
        <h1
          className="fade-up fade-up-2"
          style={{
            fontFamily: "var(--font-newsreader), Georgia, serif",
            fontSize: "clamp(36px, 5vw, 48px)",
            fontWeight: 500,
            color: "hsl(var(--text-primary))",
            textAlign: "center",
            letterSpacing: "-0.02em",
            lineHeight: 1.15,
            maxWidth: "680px",
            marginBottom: "16px",
          }}
        >
          Research U.S. Federal Law with{" "}
          <span
            style={{
              background: `linear-gradient(135deg, hsl(var(--accent)), hsl(var(--accent-glow)))`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            AI
          </span>
        </h1>

        {/* Subtitle */}
        <p
          className="fade-up fade-up-3"
          style={{
            fontFamily: "var(--font-inter), system-ui, sans-serif",
            fontSize: "18px",
            fontWeight: 400,
            color: "hsl(var(--text-secondary))",
            textAlign: "center",
            letterSpacing: "0.01em",
            maxWidth: "520px",
            marginBottom: "44px",
            lineHeight: 1.6,
          }}
        >
          Search the entire U.S. Code using natural language. Get answers with
          exact citations.
        </p>

        {/* Search bar + hint */}
        <div
          className="fade-up fade-up-4"
          style={{ width: "100%", maxWidth: "680px", marginBottom: "20px" }}
        >
          <SearchInput
            size="lg"
            value={query}
            onChange={setQuery}
            onSubmit={handleSubmit}
            placeholder="e.g., What are the requirements for patent eligibility?"
            autoFocus
          />
          {/* Press / hint — visually attached to bar, desktop only */}
          <div style={{ textAlign: "right", marginTop: "6px" }}>
            <span
              className="hidden-mobile"
              style={{
                fontSize: "12px",
                color: "hsl(var(--text-muted))",
                fontFamily: "var(--font-inter), system-ui, sans-serif",
              }}
            >
              Press <kbd style={{ fontFamily: "monospace", background: "hsl(var(--bg-surface))", border: "1px solid hsl(var(--border-subtle))", borderRadius: "4px", padding: "1px 5px", fontSize: "11px" }}>/</kbd> to search
            </span>
          </div>
        </div>

        {/* Sample query chips */}
        <div
          className="fade-up fade-up-5"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "8px",
            justifyContent: "center",
            maxWidth: "680px",
          }}
        >
          {SAMPLE_QUERIES.map((q) => (
            <SampleQueryChip key={q} query={q} onClick={handleChipClick} />
          ))}
        </div>
      </main>

      {/* Stats bar */}
      <StatsBar />

      {/* How it works */}
      <HowItWorks />

      <Footer />
    </div>
  )
}
