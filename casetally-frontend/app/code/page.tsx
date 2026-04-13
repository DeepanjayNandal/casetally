"use client"

import { useState, useEffect } from "react"
import { ChevronRight, BookOpen } from "lucide-react"
import { Nav } from "@/components/nav"
import { Footer } from "@/components/footer"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:3001"

// 54 U.S. Code titles (static list — titles don't change)
const USC_TITLES = [
  { num: 1, name: "General Provisions" },
  { num: 2, name: "The Congress" },
  { num: 3, name: "The President" },
  { num: 4, name: "Flag and Seal, Seat of Government, and the States" },
  { num: 5, name: "Government Organization and Employees" },
  { num: 6, name: "Domestic Security" },
  { num: 7, name: "Agriculture" },
  { num: 8, name: "Aliens and Nationality" },
  { num: 9, name: "Arbitration" },
  { num: 10, name: "Armed Forces" },
  { num: 11, name: "Bankruptcy" },
  { num: 12, name: "Banks and Banking" },
  { num: 13, name: "Census" },
  { num: 14, name: "Coast Guard" },
  { num: 15, name: "Commerce and Trade" },
  { num: 16, name: "Conservation" },
  { num: 17, name: "Copyrights" },
  { num: 18, name: "Crimes and Criminal Procedure" },
  { num: 19, name: "Customs Duties" },
  { num: 20, name: "Education" },
  { num: 21, name: "Food and Drugs" },
  { num: 22, name: "Foreign Relations and Intercourse" },
  { num: 23, name: "Highways" },
  { num: 24, name: "Hospitals and Asylums" },
  { num: 25, name: "Indians" },
  { num: 26, name: "Internal Revenue Code" },
  { num: 27, name: "Intoxicating Liquors" },
  { num: 28, name: "Judiciary and Judicial Procedure" },
  { num: 29, name: "Labor" },
  { num: 30, name: "Mineral Lands and Mining" },
  { num: 31, name: "Money and Finance" },
  { num: 32, name: "National Guard" },
  { num: 33, name: "Navigation and Navigable Waters" },
  { num: 34, name: "Crime Control and Law Enforcement" },
  { num: 35, name: "Patents" },
  { num: 36, name: "Patriotic and National Observances, Ceremonies, and Organizations" },
  { num: 37, name: "Pay and Allowances of the Uniformed Services" },
  { num: 38, name: "Veterans' Benefits" },
  { num: 39, name: "Postal Service" },
  { num: 40, name: "Public Buildings, Property, and Works" },
  { num: 41, name: "Public Contracts" },
  { num: 42, name: "The Public Health and Welfare" },
  { num: 43, name: "Public Lands" },
  { num: 44, name: "Public Printing and Documents" },
  { num: 45, name: "Railroads" },
  { num: 46, name: "Shipping" },
  { num: 47, name: "Telecommunications" },
  { num: 48, name: "Territories and Insular Possessions" },
  { num: 49, name: "Transportation" },
  { num: 50, name: "War and National Defense" },
  { num: 51, name: "National and Commercial Space Programs" },
  { num: 52, name: "Voting and Elections" },
  { num: 53, name: "[Reserved]" },
  { num: 54, name: "National Park Service and Related Programs" },
]

interface SearchResult {
  chunk_id: number
  citation: string
  title: string
  snippet: string
  text_content: string
  hybrid_score: number
}

export default function CodePage() {
  const [selectedTitle, setSelectedTitle] = useState<number | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedChunk, setSelectedChunk] = useState<SearchResult | null>(null)

  const loadTitle = async (titleNum: number) => {
    setSelectedTitle(titleNum)
    setSelectedChunk(null)
    setLoading(true)
    try {
      const titleName = USC_TITLES.find((t) => t.num === titleNum)?.name ?? ""
      const res = await fetch(`${BACKEND_URL}/v1/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: titleName,
          top_k: 20,
          bm25_k: 50,
          vector_k: 50,
          weight_bm25: 0.5,
          weight_vector: 0.5,
        }),
      })
      if (!res.ok) throw new Error("Search failed")
      const data = await res.json()
      setResults(data.results || [])
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const selectedTitleObj = USC_TITLES.find((t) => t.num === selectedTitle)

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
          display: "grid",
          gridTemplateColumns: "320px 1fr",
          height: "calc(100vh - 64px)",
        }}
      >
        {/* Left — Title list */}
        <div
          style={{
            borderRight: `1px solid hsl(var(--border-subtle))`,
            overflowY: "auto",
            padding: "16px 0",
          }}
        >
          <div
            style={{
              padding: "0 16px 12px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              borderBottom: `1px solid hsl(var(--border-subtle))`,
              marginBottom: "8px",
            }}
          >
            <BookOpen size={14} style={{ color: "hsl(var(--accent))" }} />
            <span
              style={{
                fontSize: "12px",
                fontWeight: 600,
                color: "hsl(var(--text-muted))",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontFamily: "var(--font-inter), system-ui, sans-serif",
              }}
            >
              54 Titles
            </span>
          </div>

          {USC_TITLES.map((t) => (
            <button
              key={t.num}
              type="button"
              onClick={() => loadTitle(t.num)}
              style={{
                width: "100%",
                padding: "10px 16px",
                background:
                  selectedTitle === t.num
                    ? "hsl(var(--bg-surface))"
                    : "none",
                border: "none",
                borderLeft: `2px solid ${selectedTitle === t.num ? "hsl(var(--accent))" : "transparent"}`,
                textAlign: "left",
                cursor: "pointer",
                display: "flex",
                alignItems: "baseline",
                gap: "10px",
                transition: "background 0.1s ease",
              }}
              onMouseEnter={(e) => {
                if (selectedTitle !== t.num) {
                  e.currentTarget.style.background = "hsl(var(--bg-elevated))"
                }
              }}
              onMouseLeave={(e) => {
                if (selectedTitle !== t.num) {
                  e.currentTarget.style.background = "none"
                }
              }}
            >
              <span
                style={{
                  fontSize: "11px",
                  color: "hsl(var(--text-muted))",
                  fontFamily: "'Courier New', monospace",
                  flexShrink: 0,
                  width: "28px",
                }}
              >
                {t.num}
              </span>
              <span
                style={{
                  fontSize: "13px",
                  color:
                    selectedTitle === t.num
                      ? "hsl(var(--text-primary))"
                      : "hsl(var(--text-secondary))",
                  fontFamily: "var(--font-inter), system-ui, sans-serif",
                  lineHeight: 1.4,
                }}
              >
                {t.name}
              </span>
            </button>
          ))}
        </div>

        {/* Right — Sections or reading pane */}
        <div style={{ display: "grid", gridTemplateColumns: selectedChunk ? "1fr 1fr" : "1fr", height: "100%", overflow: "hidden" }}>
          {/* Sections list */}
          <div
            style={{
              overflowY: "auto",
              padding: "24px",
              borderRight: selectedChunk ? `1px solid hsl(var(--border-subtle))` : "none",
            }}
          >
            {!selectedTitle && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  gap: "12px",
                  color: "hsl(var(--text-muted))",
                }}
              >
                <BookOpen size={32} style={{ opacity: 0.3 }} />
                <p
                  style={{
                    fontSize: "15px",
                    fontFamily: "var(--font-inter), system-ui, sans-serif",
                  }}
                >
                  Select a title to browse sections
                </p>
              </div>
            )}

            {selectedTitle && (
              <>
                <div style={{ marginBottom: "20px" }}>
                  <p
                    style={{
                      fontSize: "11px",
                      color: "hsl(var(--text-muted))",
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      fontFamily: "var(--font-inter), system-ui, sans-serif",
                      marginBottom: "4px",
                    }}
                  >
                    Title {selectedTitle}
                  </p>
                  <h2
                    style={{
                      fontFamily: "var(--font-newsreader), Georgia, serif",
                      fontSize: "22px",
                      fontWeight: 500,
                      color: "hsl(var(--text-primary))",
                      letterSpacing: "-0.01em",
                    }}
                  >
                    {selectedTitleObj?.name}
                  </h2>
                </div>

                {loading && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {[...Array(6)].map((_, i) => (
                      <div
                        key={i}
                        className="skeleton"
                        style={{ height: "60px", borderRadius: "8px", animationDelay: `${i * 100}ms` }}
                      />
                    ))}
                  </div>
                )}

                {!loading && results.length === 0 && (
                  <p style={{ fontSize: "14px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
                    No sections found for this title in the database.
                  </p>
                )}

                {!loading && results.map((r) => (
                  <button
                    key={r.chunk_id}
                    type="button"
                    onClick={() => setSelectedChunk(r)}
                    style={{
                      width: "100%",
                      padding: "14px 16px",
                      background:
                        selectedChunk?.chunk_id === r.chunk_id
                          ? "hsl(var(--bg-surface))"
                          : "hsl(var(--bg-elevated))",
                      border: `1px solid hsl(var(--border-subtle))`,
                      borderLeft: `2px solid ${selectedChunk?.chunk_id === r.chunk_id ? "hsl(var(--accent))" : "hsl(var(--border-subtle))"}`,
                      borderRadius: "8px",
                      marginBottom: "8px",
                      textAlign: "left",
                      cursor: "pointer",
                      transition: "background 0.1s ease, border-left-color 0.15s ease",
                      display: "flex",
                      alignItems: "flex-start",
                      justifyContent: "space-between",
                      gap: "8px",
                    }}
                    onMouseEnter={(e) => {
                      if (selectedChunk?.chunk_id !== r.chunk_id) {
                        e.currentTarget.style.background = "hsl(var(--bg-surface))"
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (selectedChunk?.chunk_id !== r.chunk_id) {
                        e.currentTarget.style.background = "hsl(var(--bg-elevated))"
                      }
                    }}
                  >
                    <div>
                      <p
                        style={{
                          fontSize: "11px",
                          fontFamily: "'Courier New', monospace",
                          color: "hsl(var(--accent))",
                          marginBottom: "4px",
                        }}
                      >
                        {r.citation}
                      </p>
                      <p
                        style={{
                          fontSize: "13px",
                          fontWeight: 500,
                          color: "hsl(var(--text-primary))",
                          fontFamily: "var(--font-inter), system-ui, sans-serif",
                          marginBottom: "4px",
                        }}
                      >
                        {r.title}
                      </p>
                      <p
                        style={{
                          fontSize: "12px",
                          color: "hsl(var(--text-muted))",
                          fontFamily: "var(--font-inter), system-ui, sans-serif",
                          overflow: "hidden",
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                        } as React.CSSProperties}
                      >
                        {r.snippet}
                      </p>
                    </div>
                    <ChevronRight size={14} style={{ color: "hsl(var(--text-muted))", flexShrink: 0, marginTop: "2px" }} />
                  </button>
                ))}
              </>
            )}
          </div>

          {/* Reading pane */}
          {selectedChunk && (
            <div style={{ overflowY: "auto", padding: "28px 32px" }}>
              <p
                style={{
                  fontSize: "11px",
                  fontFamily: "'Courier New', monospace",
                  color: "hsl(var(--accent))",
                  marginBottom: "6px",
                }}
              >
                {selectedChunk.citation}
              </p>
              <h3
                style={{
                  fontFamily: "var(--font-newsreader), Georgia, serif",
                  fontSize: "20px",
                  fontWeight: 500,
                  color: "hsl(var(--text-primary))",
                  marginBottom: "24px",
                  letterSpacing: "-0.01em",
                  lineHeight: 1.3,
                }}
              >
                {selectedChunk.title}
              </h3>
              <div
                style={{
                  fontSize: "15px",
                  lineHeight: 1.8,
                  color: "hsl(var(--text-secondary))",
                  fontFamily: "var(--font-inter), system-ui, sans-serif",
                  whiteSpace: "pre-wrap",
                }}
              >
                {selectedChunk.text_content}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
