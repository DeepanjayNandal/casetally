import { Nav } from "@/components/nav"
import { Footer } from "@/components/footer"

export default function PoliticalPage() {
  return (
    <div style={{ minHeight: "100vh", backgroundColor: "hsl(var(--bg-primary))", display: "flex", flexDirection: "column" }}>
      <Nav />
      <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", paddingTop: "64px" }}>
        <p style={{ fontSize: "15px", color: "hsl(var(--text-muted))", fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
          Coming soon
        </p>
      </main>
      <Footer />
    </div>
  )
}
