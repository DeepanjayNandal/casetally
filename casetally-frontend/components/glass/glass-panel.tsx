"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

interface GlassPanelProps extends React.HTMLAttributes<HTMLDivElement> {
  blur?: "sm" | "md" | "lg" | "xl"
}

const blurClasses = {
  sm: "backdrop-blur-sm",
  md: "backdrop-blur-md",
  lg: "backdrop-blur-lg",
  xl: "backdrop-blur-xl",
}

export function GlassPanel({
  className,
  blur = "xl",
  children,
  ...props
}: GlassPanelProps) {
  return (
    <div
      className={cn(
        "bg-glass/80 border-glass-border/50 border",
        blurClasses[blur],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
