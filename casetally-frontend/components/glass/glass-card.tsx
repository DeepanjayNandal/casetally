"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  blur?: "sm" | "md" | "lg" | "xl"
  variant?: "default" | "subtle" | "prominent"
}

const blurClasses = {
  sm: "backdrop-blur-sm",
  md: "backdrop-blur-md",
  lg: "backdrop-blur-lg",
  xl: "backdrop-blur-xl",
}

const variantClasses = {
  default: "bg-glass border-glass-border shadow-glass-shadow",
  subtle: "bg-glass/50 border-glass-border/50",
  prominent: "bg-glass border-glass-border shadow-lg shadow-glass-shadow",
}

export function GlassCard({
  className,
  blur = "lg",
  variant = "default",
  children,
  ...props
}: GlassCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border p-6",
        blurClasses[blur],
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
