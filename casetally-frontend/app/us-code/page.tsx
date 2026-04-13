"use client"

import React from "react"
import { GlassCard } from "@/components/glass/glass-card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { BookOpen, ChevronRight, FileText, Filter, Search, SlidersHorizontal } from "lucide-react"

const sections = [
  {
    citation: "1 U.S.C. § 1",
    title: "Words denoting number, gender, and so forth",
    snippet:
      "In determining the meaning of any Act of Congress, unless the context indicates otherwise...",
    updatedAt: "2025-01-06",
    tags: ["definitions", "construction"],
  },
  {
    citation: "1 U.S.C. § 2",
    title: '"County" as including "parish", and so forth',
    snippet:
      'The word "county" includes a parish, or any other equivalent subdivision of a State...',
    updatedAt: "2025-01-06",
    tags: ["definitions"],
  },
  {
    citation: "1 U.S.C. § 8",
    title: "Effect of repeals on existing liabilities",
    snippet:
      "The repeal of any statute shall not have the effect to release or extinguish any penalty...",
    updatedAt: "2025-01-06",
    tags: ["repeals", "liability"],
  },
]

export default function UscodePage() {
  const [activeCitation, setActiveCitation] = React.useState(sections[0].citation)
  const activeSection = sections.find((item) => item.citation === activeCitation) ?? sections[0]

  return (
    <div className="min-h-screen w-full bg-background">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-accent/15 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-80 w-80 rounded-full bg-sky-400/10 blur-3xl" />
      </div>

      <main className="mx-auto w-full max-w-7xl px-4 pb-8 pt-6 sm:px-6 lg:px-8">
        <GlassCard className="mb-4 flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">United States Code</h1>
            <p className="text-sm text-muted-foreground">
              Federal statutes with citation-first navigation and legal context.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">Federal</Badge>
            <Badge variant="secondary">Current</Badge>
            <Badge variant="outline">Updated 2025-01-06</Badge>
          </div>
        </GlassCard>

        <div className="mb-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <label htmlFor="uscode-search" className="sr-only">
            Search U.S. Code
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="uscode-search"
              placeholder="Search by keyword, citation, or phrase"
              className="h-10 rounded-xl border-glass-border bg-glass/70 pl-9 backdrop-blur-md"
            />
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" className="rounded-xl">
              <Filter className="mr-2 h-4 w-4" />
              Filters
            </Button>
            <Button variant="outline" className="rounded-xl">
              <SlidersHorizontal className="mr-2 h-4 w-4" />
              Layout
            </Button>
          </div>
        </div>

        <section className="grid gap-4 lg:grid-cols-[300px_1fr_280px]">
          <GlassCard className="p-0">
            <header className="border-b border-glass-border p-4">
              <div className="flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-accent" />
                <h2 className="text-sm font-semibold">Browse Sections</h2>
              </div>
            </header>
            <ul className="max-h-[65vh] space-y-1 overflow-auto p-2">
              {sections.map((item) => (
                <li key={item.citation}>
                  <button
                    type="button"
                    onClick={() => setActiveCitation(item.citation)}
                    className={`w-full rounded-xl px-3 py-2 text-left transition-colors ${
                      activeCitation === item.citation
                        ? "bg-accent/15 text-foreground"
                        : "hover:bg-secondary/60"
                    }`}
                    aria-current={activeCitation === item.citation ? "true" : undefined}
                  >
                    <p className="text-xs font-medium text-muted-foreground">{item.citation}</p>
                    <p className="line-clamp-2 text-sm">{item.title}</p>
                  </button>
                </li>
              ))}
            </ul>
          </GlassCard>

          <GlassCard className="min-h-[65vh] p-0">
            <header className="border-b border-glass-border p-5">
              <p className="text-xs font-medium text-muted-foreground">{activeSection.citation}</p>
              <h2 className="mt-1 text-xl font-semibold">{activeSection.title}</h2>
            </header>
            <article className="space-y-5 p-5 text-sm leading-7 text-foreground/90">
              <p>{activeSection.snippet}</p>
              <p>
                The words importing the singular include and apply to several persons, parties, or
                things. Words importing the plural include the singular. Words importing the
                masculine gender include the feminine as well.
              </p>
              <p>
                This reading pane is designed for statute-first review, with context and metadata in
                adjacent glass panels.
              </p>
            </article>
          </GlassCard>

          <GlassCard className="p-0">
            <header className="border-b border-glass-border p-4">
              <h2 className="text-sm font-semibold">Context</h2>
            </header>
            <div className="space-y-4 p-4">
              <div className="rounded-xl border border-glass-border bg-glass/60 p-3">
                <p className="text-xs text-muted-foreground">Document Type</p>
                <p className="text-sm font-medium">United States Code</p>
              </div>
              <div className="rounded-xl border border-glass-border bg-glass/60 p-3">
                <p className="text-xs text-muted-foreground">Last Updated</p>
                <p className="text-sm font-medium">{activeSection.updatedAt}</p>
              </div>
              <div className="rounded-xl border border-glass-border bg-glass/60 p-3">
                <p className="mb-2 text-xs text-muted-foreground">Tags</p>
                <div className="flex flex-wrap gap-2">
                  {activeSection.tags.map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
              <Button className="w-full rounded-xl">
                <FileText className="mr-2 h-4 w-4" />
                Open PDF Artifact
              </Button>
            </div>
          </GlassCard>
        </section>

        <section className="mt-4 grid gap-3 sm:grid-cols-2 lg:hidden">
          <GlassCard className="p-4">
            <h3 className="mb-2 text-sm font-semibold">Quick Jump</h3>
            <Button variant="outline" className="w-full justify-between rounded-xl">
              Jump to citation
              <ChevronRight className="h-4 w-4" />
            </Button>
          </GlassCard>
          <GlassCard className="p-4">
            <h3 className="mb-2 text-sm font-semibold">Result Mode</h3>
            <p className="text-sm text-muted-foreground">
              Reading Pane mode optimized for iOS glass style.
            </p>
          </GlassCard>
        </section>
      </main>
    </div>
  )
}
