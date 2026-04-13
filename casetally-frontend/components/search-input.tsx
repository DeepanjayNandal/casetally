"use client"

import { useRef } from "react"
import { Search, ArrowRight, Square } from "lucide-react"

interface SearchInputProps {
  size?: "lg" | "md"
  value: string
  onChange: (value: string) => void
  onSubmit: (value: string) => void
  onStop?: () => void
  placeholder?: string
  isLoading?: boolean
  autoFocus?: boolean
}

export function SearchInput({
  size = "lg",
  value,
  onChange,
  onSubmit,
  onStop,
  placeholder = "e.g., What are the requirements for patent eligibility?",
  isLoading = false,
  autoFocus = false,
}: SearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const height = size === "lg" ? 56 : 48
  const fontSize = size === "lg" ? 16 : 15

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      if (isLoading && onStop) onStop()
      else onChange("")
    }
    if (e.key === "Enter" && !isLoading) onSubmit(value)
  }

  const handleButtonClick = () => {
    if (isLoading) {
      onStop?.()
    } else if (value.trim()) {
      onSubmit(value)
    }
  }

  const showStop = isLoading
  const canSubmit = !isLoading && !!value.trim()

  return (
    <div
      className="search-wrapper"
      style={{
        display: "flex",
        alignItems: "center",
        padding: "0 16px",
        height: `${height}px`,
        border: `1px solid hsl(215 30% 30%)`,
        borderRadius: "12px",
        gap: "12px",
        transition: "border-color 0.2s ease, box-shadow 0.2s ease",
        background: "hsl(220 18% 8%)",
        boxShadow: "inset 0 1px 3px hsl(220 30% 2% / 0.5)",
        backdropFilter: "blur(var(--glass-blur))",
        WebkitBackdropFilter: "blur(var(--glass-blur))",
      }}
    >
      <Search size={18} style={{ color: "hsl(var(--text-muted))", flexShrink: 0 }} />

      <input
        ref={inputRef}
        id={size === "lg" ? "main-search" : undefined}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoFocus={autoFocus}
        aria-label="Search U.S. federal law"
        style={{
          flex: 1,
          background: "none",
          border: "none",
          outline: "none",
          color: "hsl(var(--text-primary))",
          fontSize: `${fontSize}px`,
          fontFamily: "var(--font-inter), system-ui, sans-serif",
          caretColor: "hsl(var(--accent))",
        }}
      />

      <button
        type="button"
        onClick={handleButtonClick}
        disabled={!showStop && !canSubmit}
        aria-label={showStop ? "Stop generating" : "Submit search"}
        title={showStop ? "Stop generating" : undefined}
        style={{
          flexShrink: 0,
          width: "40px",
          height: "40px",
          borderRadius: "50%",
          border: "none",
          background: showStop
            ? "hsl(var(--bg-surface))"
            : "hsl(var(--accent))",
          color: "white",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "background 0.15s ease, transform 0.1s ease",
          cursor: showStop || canSubmit ? "pointer" : "default",
        }}
        onMouseEnter={(e) => {
          if (showStop || canSubmit) e.currentTarget.style.transform = "scale(1.05)"
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = "scale(1)"
        }}
      >
        {showStop ? (
          // Filled stop square — same as Claude
          <Square size={14} fill="currentColor" strokeWidth={0} />
        ) : (
          <ArrowRight size={16} />
        )}
      </button>
    </div>
  )
}
