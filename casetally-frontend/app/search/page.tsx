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

// ?? rather than ||: an empty string is a MEANINGFUL value here. Built with
// NEXT_PUBLIC_BACKEND_URL="" the requests become relative ("/v1/search"), so the
// bundle is same-origin on whatever host serves it and works behind any ingress
// hostname without a rebuild. With || an empty string is falsy and would silently
// fall back to the dev default below, hard-coding localhost into the bundle.
// The fallback still applies when the variable is genuinely unset, which is what
// `npm run dev` relies on.
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:3001"

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
  // Section numbers the answer cited that were NOT in the retrieved excerpts.
  // A fabricated citation is indistinguishable from a real one to a reader, so it
  // has to be surfaced rather than trusted.
  unverifiedCitations: string[]
}

function SearchResults() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialQuery = searchParams.get("q") || ""

  const [turns, setTurns] = useState<Turn[]>([])
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

  // The sources panel is no longer fetched separately. /v1/chat/stream emits a
  // "sources" event carrying the retrieval it actually used, so the panel and the
  // answer are the same result set by construction. Previously this component
  // called /v1/search with the RAW question while the answer searched the
  // REWRITTEN one, at a different depth, so the panel could show the right
  // statute while the answer said it had no relevant information.

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
      unverifiedCitations: [],
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
            // The retrieval the answer is actually built from. Arrives before the
            // first token, so the panel fills while the answer is still
            // streaming, and it is populated even when the LLM call fails.
            if (json.type === "sources" && Array.isArray(json.results)) {
              updateTurn(turnId, { sources: json.results })
            }
            if (json.type === "citation_check") {
              updateTurn(turnId, { unverifiedCitations: json.unverified || [] })
            }
            // The backend reports failures that happen after the response
            // headers are already sent, so they arrive as an event rather than a
            // status code. Clear the loading state here too: this is a terminal
            // outcome for the turn, and leaving isLoading set was what left the
            // spinner running forever with no answer.
            if (json.type === "error") {
              firstToken = false
              updateTurn(turnId, {
                isLoading: false,
                isStreaming: false,
                error: json.message || "Something went wrong. Please try again.",
              })
            }
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

      // isLoading must be cleared here as well as on the first token. It used to
      // be cleared ONLY when a token arrived, so a stream that completed without
      // any text left isLoading true forever: the skeleton kept pulsing, and
      // because the composer is disabled while the turn is active, the whole page
      // became unusable until a reload. A finished stream is never still loading,
      // whether or not it produced anything.
      updateTurn(turnId, {
        isLoading: false,
        isStreaming: false,
        tookMs: Date.now() - startMs,
      })

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Follow-up — append to conversation, update URL without navigation
  const handleFollowUp = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
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
                    <>
                    <StreamingText text={turn.answer} isStreaming={turn.isStreaming} />
                    {turn.unverifiedCitations.length > 0 && (
                      <div
                        role="alert"
                        className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
                      >
                        <span className="font-medium">Unverified citation{turn.unverifiedCitations.length > 1 ? "s" : ""}:</span>{" "}
                        {turn.unverifiedCitations
                          .map((c) => {
                            const [title, section] = c.split(":")
                            return `${title} U.S.C. § ${section}`
                          })
                          .join(", ")}
                        . {turn.unverifiedCitations.length > 1 ? "These were" : "This was"} not among the
                        retrieved sections, so {turn.unverifiedCitations.length > 1 ? "they" : "it"} could not be
                        checked against the corpus. Treat with caution.
                      </div>
                    )}
                    </>
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
                Retrieved {latestSources.length} sources · Hybrid search (full-text + vector)
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
