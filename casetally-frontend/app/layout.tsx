// Global stylesheet. Loaded for its side effect, so it has no named binding
// and linters may report it as unused — removing it strips every style in the
// app, since all components resolve colours and fonts through the CSS custom
// properties this file defines.
import './globals.css'

import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Newsreader, Inter } from 'next/font/google'
import { KeyboardShortcuts } from '@/components/keyboard-shortcuts'

const newsreader = Newsreader({
  subsets: ['latin'],
  variable: '--font-newsreader',
  weight: ['400', '500', '600'],
  style: ['normal', 'italic'],
  display: 'swap',
})

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  weight: ['400', '500', '600'],
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'CaseTally — AI Legal Research',
  description: 'Search the entire U.S. Code using natural language. Get grounded, cited answers with exact statute citations.',
  keywords: ['legal research', 'US Code', 'federal law', 'AI', 'citations'],
  icons: {
    icon: '/favicon.svg',
  },
}

export default function RootLayout({
  children,
}: {
  children: ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${newsreader.variable} ${inter.variable}`}>
        <a href="#main-content" className="skip-link">Skip to content</a>
        <KeyboardShortcuts />
        {children}
      </body>
    </html>
  )
}
