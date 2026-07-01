"use client"

import { useEffect, useState } from "react"
import { usePathname } from "next/navigation"
import Link from "next/link"
import { Github, X } from "lucide-react"

function AboutModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "hsl(220 20% 4% / 0.8)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "relative",
          width: "100%",
          maxWidth: "560px",
          background: "hsl(220 18% 7%)",
          border: "1px solid hsl(220 15% 15%)",
          borderRadius: "16px",
          padding: "40px",
          fontFamily: "var(--font-inter), system-ui, sans-serif",
        }}
      >
        {/* Close */}
        <button
          type="button"
          onClick={onClose}
          style={{
            position: "absolute",
            top: "16px",
            right: "16px",
            background: "none",
            border: "none",
            color: "hsl(var(--text-muted))",
            cursor: "pointer",
            padding: "4px",
            display: "flex",
            alignItems: "center",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-muted))")}
        >
          <X size={18} />
        </button>

        {/* Title */}
        <h2 style={{ fontFamily: "var(--font-newsreader), Georgia, serif", fontSize: "22px", fontWeight: 600, color: "hsl(var(--text-primary))", marginBottom: "4px", letterSpacing: "-0.01em" }}>
          CaseTally
        </h2>
        <p style={{ fontSize: "13px", color: "hsl(var(--text-muted))", marginBottom: "20px" }}>
          AI Legal Research System
        </p>

        <p style={{ fontSize: "14px", color: "hsl(var(--text-secondary))", lineHeight: 1.7, marginBottom: "24px" }}>
          CaseTally lets you search the entire U.S. Code using natural language and get grounded, cited answers powered by AI.
        </p>

        {/* How it works */}
        <p style={{ fontSize: "13px", fontWeight: 500, color: "hsl(var(--text-primary))", marginBottom: "10px" }}>
          How it works:
        </p>
        <ul style={{ paddingLeft: "0", margin: "0 0 24px", listStyle: "none" }}>
          {[
            "Hybrid retrieval combining BM25 keyword search and vector similarity search across 53 U.S. Code titles and 47,207 sections",
            "Retrieved sections are passed as context to an LLM which generates a structured answer with exact statute citations",
            "All answers are grounded — the AI only uses retrieved legal text, never speculation",
          ].map((item, i) => (
            <li key={i} style={{ fontSize: "14px", color: "hsl(var(--text-secondary))", lineHeight: 1.7, marginBottom: "8px", paddingLeft: "16px", position: "relative" }}>
              <span style={{ position: "absolute", left: 0, color: "hsl(var(--accent))" }}>•</span>
              {item}
            </li>
          ))}
        </ul>

        {/* Tech stack */}
        <p style={{ fontSize: "13px", fontWeight: 500, color: "hsl(var(--text-primary))", marginBottom: "10px" }}>
          Tech stack:
        </p>
        <p style={{ fontSize: "14px", color: "hsl(var(--text-secondary))", marginBottom: "28px", lineHeight: 1.6 }}>
          Next.js · FastAPI · PostgreSQL · pgvector · Groq (Llama 3) · Docker
        </p>

        {/* Built by */}
        <div style={{ borderTop: "1px solid hsl(220 15% 15%)", paddingTop: "20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: "12px", color: "hsl(var(--text-muted))" }}>
            Built by Deepanjay Nandal
          </span>
          <div style={{ display: "flex", gap: "12px" }}>
            <a href="https://github.com/DeepanjayNandal" target="_blank" rel="noopener noreferrer" style={{ fontSize: "12px", color: "hsl(var(--accent))", textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.textDecoration = "underline")}
              onMouseLeave={(e) => (e.currentTarget.style.textDecoration = "none")}
            >GitHub</a>
            <a href="https://www.linkedin.com/in/deepanjay-nandal/" target="_blank" rel="noopener noreferrer" style={{ fontSize: "12px", color: "hsl(var(--accent))", textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.textDecoration = "underline")}
              onMouseLeave={(e) => (e.currentTarget.style.textDecoration = "none")}
            >LinkedIn</a>
          </div>
        </div>
      </div>
    </div>
  )
}

export function Nav() {
  const [scrolled, setScrolled] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const pathname = usePathname()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 50)
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <>
      <nav
        className={scrolled ? "nav-scrolled" : ""}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 100,
          height: "64px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 40px",
          background: "hsl(var(--bg-glass))",
          backdropFilter: "blur(var(--glass-blur))",
          WebkitBackdropFilter: "blur(var(--glass-blur))",
          borderBottom: `1px solid hsl(var(--border-subtle))`,
          transition: "background 0.2s ease, border-color 0.2s ease",
        }}
      >
        <Link
          href="/"
          style={{
            fontFamily: "var(--font-newsreader), Georgia, serif",
            fontSize: "20px",
            fontWeight: 600,
            color: "hsl(var(--text-primary))",
            letterSpacing: "-0.01em",
          }}
        >
          CaseTally
        </Link>

        <div style={{ display: "flex", alignItems: "center", gap: "28px" }}>
          <NavLink href="/code" active={pathname === "/code"}>
            <span className="hidden-mobile">Browse U.S. Code</span>
            <span className="show-mobile">Browse</span>
          </NavLink>
          <button
            type="button"
            onClick={() => setAboutOpen(true)}
            style={{
              fontSize: "14px",
              fontWeight: 500,
              color: "hsl(var(--text-secondary))",
              background: "none",
              border: "none",
              cursor: "pointer",
              fontFamily: "var(--font-inter), system-ui, sans-serif",
              padding: 0,
              transition: "color 0.15s ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-secondary))")}
          >
            About
          </button>
          <a
            href="https://github.com/DeepanjayNandal"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="GitHub"
            style={{
              color: "hsl(var(--text-muted))",
              display: "flex",
              alignItems: "center",
              transition: "color 0.15s ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-muted))")}
          >
            <Github size={18} />
          </a>
        </div>
      </nav>

      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}
    </>
  )
}

function NavLink({ href, children, active }: { href: string; children: React.ReactNode; active?: boolean }) {
  return (
    <Link
      href={href}
      style={{
        fontSize: "14px",
        fontWeight: 500,
        color: active ? "hsl(var(--text-primary))" : "hsl(var(--text-secondary))",
        transition: "color 0.15s ease",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        borderBottom: active ? "2px solid hsl(var(--accent))" : "2px solid transparent",
        paddingBottom: "2px",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
      onMouseLeave={(e) => (e.currentTarget.style.color = active ? "hsl(var(--text-primary))" : "hsl(var(--text-secondary))")}
    >
      {children}
    </Link>
  )
}
