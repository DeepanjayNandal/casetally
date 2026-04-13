"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Github } from "lucide-react"

export function Nav() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 50)
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  return (
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
        <NavLink href="/code">Browse U.S. Code</NavLink>
        <NavLink href="/#how-it-works">About</NavLink>
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
          onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-muted))")}
        >
          <Github size={18} />
        </a>
      </div>
    </nav>
  )
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      style={{
        fontSize: "14px",
        fontWeight: 500,
        color: "hsl(var(--text-secondary))",
        transition: "color 0.15s ease",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.color = "hsl(var(--text-primary))")}
      onMouseLeave={(e) => (e.currentTarget.style.color = "hsl(var(--text-secondary))")}
    >
      {children}
    </Link>
  )
}
