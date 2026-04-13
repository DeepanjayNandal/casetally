export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  artifact?: Artifact
}

export interface Artifact {
  id: string
  type: "pdf" | "code" | "document" | "table"
  title: string
  content: string
  highlights?: TextHighlight[]
}

export interface TextHighlight {
  id: string
  text: string
  startIndex: number
  endIndex: number
  color: "yellow" | "blue" | "green" | "pink"
  note?: string
}

export interface ChatSession {
  id: string
  title: string
  messages: Message[]
  createdAt: Date
  updatedAt: Date
}

export interface LegalDocument {
  id: string
  title: string
  code: string
  section: string
  content: string
  jurisdiction: "federal" | "state"
  state?: string
  lastUpdated: Date
}

export interface Politician {
  id: string
  name: string
  title: string
  party: "Democrat" | "Republican" | "Independent"
  state: string
  chamber: "Senate" | "House"
  imageUrl?: string
  website?: string
  phone?: string
  email?: string
}
