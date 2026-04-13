const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api"

interface ApiResponse<T> {
  data: T
  success: boolean
  error?: string
}

interface RequestConfig extends RequestInit {
  params?: Record<string, string>
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async request<T>(
    endpoint: string,
    config: RequestConfig = {}
  ): Promise<ApiResponse<T>> {
    const { params, ...fetchConfig } = config

    let url = `${this.baseUrl}${endpoint}`
    if (params) {
      const searchParams = new URLSearchParams(params)
      url += `?${searchParams.toString()}`
    }

    try {
      const response = await fetch(url, {
        ...fetchConfig,
        headers: {
          "Content-Type": "application/json",
          ...fetchConfig.headers,
        },
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      return { data, success: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error"
      return { data: null as T, success: false, error: message }
    }
  }

  async get<T>(endpoint: string, params?: Record<string, string>) {
    return this.request<T>(endpoint, { method: "GET", params })
  }

  async post<T>(endpoint: string, body?: unknown) {
    return this.request<T>(endpoint, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  async put<T>(endpoint: string, body?: unknown) {
    return this.request<T>(endpoint, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  async delete<T>(endpoint: string) {
    return this.request<T>(endpoint, { method: "DELETE" })
  }
}

export const apiClient = new ApiClient(API_BASE_URL)

// API endpoints
export const api = {
  // US Code
  usCode: {
    list: (params?: Record<string, string>) => apiClient.get("/us-code", params),
    get: (id: string) => apiClient.get(`/us-code/${id}`),
    search: (query: string) => apiClient.get("/us-code/search", { q: query }),
  },

  // State Codes
  stateCodes: {
    list: (state?: string) => apiClient.get("/state-codes", state ? { state } : undefined),
    get: (id: string) => apiClient.get(`/state-codes/${id}`),
    states: () => apiClient.get("/state-codes/states"),
  },

  // Federal Regulations
  federal: {
    list: (params?: Record<string, string>) => apiClient.get("/federal", params),
    get: (id: string) => apiClient.get(`/federal/${id}`),
    agencies: () => apiClient.get("/federal/agencies"),
  },

  // Politicians
  politicians: {
    list: (params?: Record<string, string>) => apiClient.get("/politicians", params),
    get: (id: string) => apiClient.get(`/politicians/${id}`),
    senators: () => apiClient.get("/politicians/senators"),
    representatives: () => apiClient.get("/politicians/representatives"),
  },

  // Chat
  chat: {
    send: (message: string, sessionId?: string) =>
      apiClient.post("/chat", { message, sessionId }),
    history: (sessionId: string) => apiClient.get(`/chat/${sessionId}`),
  },
}
