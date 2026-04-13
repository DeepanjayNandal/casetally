"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export function useKeyboardShortcuts() {
  const router = useRouter()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement).isContentEditable

      if (e.key === "/" && !isInput) {
        e.preventDefault()
        const el = document.getElementById("main-search")
        if (el) {
          el.focus()
        } else {
          // Not on homepage — navigate then focus
          router.push("/")
          // Focus after navigation settles
          setTimeout(() => document.getElementById("main-search")?.focus(), 300)
        }
      }
    }

    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [router])
}
