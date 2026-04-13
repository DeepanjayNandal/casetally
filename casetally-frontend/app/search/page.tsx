"use client"

import { useEffect, useState, useRef, useCallback, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Sparkles, BookOpen, AlertCircle, RefreshCcw, SearchX } from "lucide-react"
import { Nav } from "@/components/nav"
import { Footer } from "@/components/footer"
import { SearchInput } from "@/components/search-input"
import { SourceCard } from "@/components/source-card"
import { StreamingText } from "@/components/streaming-text"
import { SkeletonAnswer } from "@/components/skeleton-answer"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:3001"

interface SourceResult {
  chunk_id: number
  citation: string
  title: string
  snippet: string
  text_content: string
  hybrid_score: number
  tags: string[]
}

interface Turn {
  id: string
  query: string
  answer: string
  sources: SourceResult[]
  isLoading: boolean
  isStreaming: boolean
  error: string | null
  tookMs: number | null
}

function SearchResults() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialQuery = searchParams.get("q") || ""

  const [turns, setTurns] = useState<Turn[]>([])
  const [topInput, setTopInput] = useState(initialQuery)
  const [followUp, setFollowUp] = useState("")
  const [highlightedRef, setHighlightedRef] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastTurnIdRef = useRef<string | null>(null)

  const handleStop = () => {
    abortRef.current?.abort()
    if (lastTurnIdRef.current) {
      updateTurn(lastTurnIdRef.current, { isLoading: false, isStreaming: false })
    }
  }

  const updateTurn = (id: string, patch: Partial<Turn>) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }

  const fetchSources = async (q: string, turnId: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/v1/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: q,
          top_k: 10,
          bm25_k: 50,
          vector_k: 50,
          weight_bm25: 0.5,
          weight_vector: 0.5,
        }),
      })
      if (!res.ok) return
      const data = await res.json()
      updateTurn(turnId, {
        sources: data.results || [],
        tookMs: data.took_ms,
      })
    } catch {
      // best-effort
    }
  }

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) return

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    const turnId = `${Date.now()}`
    const newTurn: Turn = {
      id: turnId,
      query: q,
      answer: "",
      sources: [],
      isLoading: true,
      isStreaming: false,
      error: null,
      tookMs: null,
    }

    setTurns((prev) => [...prev, newTurn])
    setFollowUp("")
    lastTurnIdRef.current = turnId

    // Scroll to new turn after it renders
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50)

    const startMs = Date.now()

    try {
      const response = await fetch(`${BACKEND_URL}/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q, history: [] }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(
          response.status === 429
            ? "Rate limited. Please wait a moment and try again."
            : `Server error (${response.status}). Please try again.`
        )
      }

      if (!response.body) throw new Error("No response body")

      // Keep isLoading until first token so the pulsing animation stays visible
      let firstToken = true
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const data = line.slice(6).trim()
          if (data === "[DONE]") break
          try {
            const json = JSON.parse(data)
            if (json.type === "text" && json.chunk) {
              if (firstToken) {
                firstToken = false
                updateTurn(turnId, { isLoading: false, isStreaming: true })
              }
              setTurns((prev) =>
                prev.map((t) =>
                  t.id === turnId ? { ...t, answer: t.answer + json.chunk } : t
                )
              )
            }
          } catch {
            // ignore
          }
        }
      }

      updateTurn(turnId, {
        isStreaming: false,
        tookMs: Date.now() - startMs,
      })

      fetchSources(q, turnId)
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") {
        // Always clean up state on abort so spinner doesn't hang
        updateTurn(turnId, { isLoading: false, isStreaming: false })
        return
      }
      updateTurn(turnId, {
        isLoading: false,
        isStreaming: false,
        error: (err as Error).message || "Something went wrong. Please try again.",
      })
    }
  }, [])

  // Run search when initialQuery changes.
  // Using a ref (not local var) to deduplicate StrictMode's double-invoke —
  // the ref persists across both invocations so the second one skips.
  const lastSearchedRef = useRef<string>("")
  useEffect(() => {
    if (!initialQuery || lastSearchedRef.current === initialQuery) return
    lastSearchedRef.current = initialQuery
    runSearch(initialQuery)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery])

  // Listen for citation clicks
  useEffect(() => {
    const handler = (e: Event) => {
      const ref = (e as CustomEvent<{ ref: string }>).detail.ref
      setHighlightedRef(ref)
      setTimeout(() => setHighlightedRef(null), 2500)
    }
    window.addEventListener("cite-click", handler)
    return () => window.removeEventListener("cite-click", handler)
  }, [])

  // Top search bar — fresh search, navigate to new URL
  const handleTopSearch = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    router.push(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  // Follow-up — append to conversation, update URL without navigation
  const handleFollowUp = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    setTopInput(trimmed)
    // Mark as already searched so the useEffect doesn't fire a duplicate
    lastSearchedRef.current = trimmed
    router.replace(`/search?q=${encodeURIComponent(trimmed)}`)
    runSearch(trimmed)
  }

  const lastTurn = turns[turns.length - 1]
  const isActive = !!lastTurn && (lastTurn.isLoading || lastTurn.isStreaming)

  // Latest sources for right panel (always show last turn's sources)
  const latestSources = lastTurn?.sources ?? []

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

      <main
        id="main-content"
        style={{
          flex: 1,
          paddingTop: "64px",
          maxWidth: "1152px",
          margin: "0 auto",
          width: "100%",
          padding: "64px 24px 48px",
        }}
      >
        {/* Two-column layout */}
        <div
          className="search-two-col"
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.9fr) minmax(0, 1fr)",
            gap: "32px",
            alignItems: "start",
          }}
        >
          {/* LEFT — Conversation turns */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "24px" }}>
              <Sparkles size={16} style={{ color: "hsl(var(--accent))" }} />
              <h1
                style={{
                  fontFamily: "var(--font-newsreader), Georgia, serif",
                  fontSize: "24px",
                  fontWeight: 600,
                  color: "hsl(var(--text-primary))",
                  letterSpacing: "-0.01em",
                }}
              >
                Answer
              </h1>
            </div>

            {/* All turns rendered in sequence */}
            {turns.map((turn, i) => (
              <div key={turn.id} style={{ marginBottom: i < turns.length - 1 ? "40px" : "0" }}>
                {/* Question */}
                <p
                  style={{
                    fontFamily: "var(--font-inter), system-ui, sans-serif",
                    fontSize: "16px",
                    fontWeight: 500,
                    color: "hsl(var(--text-primary))",
                    marginBottom: "16px",
                    borderLeft: "3px solid hsl(var(--accent))",
                    paddingLeft: "12px",
                    lineHeight: 1.5,
                  }}
                >
                  {turn.query}
                </p>

                {/* Answer card */}
                <div
                  className="glass"
                  style={{ padding: "28px 32px", borderRadius: "12px", minHeight: "120px" }}
                >
                  {turn.error ? (
                    <ErrorCard message={turn.error} onRetry={() => runSearch(turn.query)} />
                  ) : turn.isLoading ? (
                    <SkeletonAnswer />
                  ) : !turn.isStreaming && !turn.answer.trim() ? (
                    <NoResultsCard />
                  ) : (
                    <StreamingText text={turn.answer} isStreaming={turn.isStreaming} />
                  )}
                </div>

                {/* Relevant laws for this turn */}
                {!turn.isLoading && !turn.isStreaming && turn.sources.length > 0 && (
                  <div style={{ marginTop: "14px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                    {turn.sources.slice(0, 6).map((src) => (
                      <span
                        key={src.chunk_id}
                        style={{
                          padding: "4px 10px",
                          backgroundColor: "hsl(var(--bg-elevated))",
                          border: `1px solid hsl(var(--border-subtle))`,
                          borderRadius: "6px",
                          fontSize: "12px",
                          fontFamily: "'Courier New', monospace",
                          color: "hsl(var(--text-primary))",
                        }}
                      >
                        {src.citation}
                      </span>
                    ))}
                  </div>
                )}

                {/* Divider between turns */}
                {i < turns.length - 1 && (
                  <div
                    style={{
                      height: "1px",
                      background: "hsl(var(--border-subtle))",
                      marginTop: "32px",
                    }}
                  />
                )}
              </div>
            ))}

            <div ref={bottomRef} />

            {/* Follow-up input */}
            {turns.length > 0 && (
              <div style={{ marginTop: "28px" }}>
                <SearchInput
                  size="md"
                  value={followUp}
                  onChange={setFollowUp}
                  onSubmit={handleFollowUp}
                  onStop={handleStop}
                  placeholder="Ask a follow-up question..."
                  isLoading={isActive}
                />
              </div>
            )}
          </div>

          {/* RIGHT — Sources (always latest turn) */}
          <div className="sources-panel" style={{ position: "sticky", top: "80px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <BookOpen size={16} style={{ color: "hsl(var(--accent))" }} />
              <h2
                style={{
                  fontFamily: "var(--font-newsreader), Georgia, serif",
                  fontSize: "24px",
                  fontWeight: 600,
                  color: "hsl(var(--text-primary))",
                  letterSpacing: "-0.01em",
                }}
              >
                Sources
              </h2>
              {latestSources.length > 0 && (
                <span
                  style={{
                    fontSize: "12px",
                    fontWeight: 500,
                    color: "hsl(var(--text-muted))",
                    background: "hsl(var(--bg-surface))",
                    border: `1px solid hsl(var(--border-subtle))`,
                    borderRadius: "999px",
                    padding: "2px 8px",
                    fontFamily: "var(--font-inter), system-ui, sans-serif",
                  }}
                >
                  {latestSources.length} sections
                </span>
              )}
            </div>

            {latestSources.length > 0 && (
              <p
                style={{
                  fontSize: "12px",
                  color: "hsl(var(--text-muted))",
                  fontFamily: "var(--font-inter), system-ui, sans-serif",
                  marginBottom: "16px",
                  fontWeight: 500,
                }}
              >
                Retrieved {latestSources.length} sources · Hybrid search (BM25 + vector)
              </p>
            )}

            {isActive && latestSources.length === 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "16px 0" }}>
                <span style={{ fontSize: "13px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
                  Searching federal law
                </span>
                <span className="dot-loader" aria-hidden="true">
                  <span /><span /><span />
                </span>
              </div>
            )}

            {latestSources.map((src, i) => {
              const isHighlighted = highlightedRef
                ? src.citation.includes(highlightedRef.trim()) || highlightedRef.includes(src.citation)
                : false
              return (
                <SourceCard
                  key={src.chunk_id}
                  index={i + 1}
                  citation={src.citation}
                  title={src.title}
                  snippet={src.snippet}
                  text={src.text_content}
                  score={src.hybrid_score}
                  staggerDelay={i * 80}
                  isHighlighted={isHighlighted}
                />
              )
            })}
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "16px", padding: "24px 0", textAlign: "center" }}>
      <AlertCircle size={48} style={{ color: "hsl(0 65% 55%)", opacity: 0.9 }} />
      <div>
        <h3 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "18px", fontWeight: 500, color: "hsl(var(--text-primary))", marginBottom: "6px" }}>
          Something went wrong
        </h3>
        <p style={{ fontSize: "14px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
          {message || "Unable to connect to the search service. Please try again."}
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        style={{
          display: "inline-flex", alignItems: "center", gap: "6px",
          padding: "8px 20px", border: `1px solid hsl(var(--accent))`,
          borderRadius: "8px", background: "none", color: "hsl(var(--accent))",
          fontSize: "13px", fontFamily: "var(--font-inter), system-ui, sans-serif",
          cursor: "pointer", transition: "background 0.15s ease",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "hsl(var(--accent) / 0.1)" }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "none" }}
      >
        <RefreshCcw size={13} />
        Try again
      </button>
    </div>
  )
}

function NoResultsCard() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "16px", padding: "24px 0", textAlign: "center" }}>
      <SearchX size={48} style={{ color: "hsl(var(--text-muted))", opacity: 0.7 }} />
      <div>
        <h3 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "18px", fontWeight: 500, color: "hsl(var(--text-secondary))", marginBottom: "6px" }}>
          No matching sections found
        </h3>
        <p style={{ fontSize: "14px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
          Try rephrasing your query or using different legal terms.
        </p>
      </div>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
        {["Try broader terms", "Check spelling", "Use legal terminology"].map((s) => (
          <span key={s} style={{ fontSize: "12px", padding: "4px 12px", border: "1px solid hsl(var(--border-subtle))", borderRadius: "999px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
            {s}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchResults />
    </Suspense>
  )
}
