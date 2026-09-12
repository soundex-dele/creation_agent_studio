// User Types
export interface User {
  id: string
  email: string
  name: string
  createdAt: string
  updatedAt: string
}

// Agent Types
export interface Agent {
  id: string
  name: string
  description: string
  type: 'text' | 'image' | 'video' | 'composite'
  capabilities: string[]
  config: Record<string, unknown>
}

export * from './template'
export * from './workflow'
export * from './workspaceFiles'
export * from './contact'

// App Types
export interface AppItem {
  id: string
  name: string
  description: string
  category: string          // category slug, e.g. 'video'
  icon: string              // emoji or icon glyph, e.g. '🎬'
  color?: string            // accent color for the thumbnail gradient
  tags: string[]
  developer?: string
  screenshots?: string[]   // optional app screenshots; falls back to generated placeholders
  usage_count?: number
  kind?: import('./application').ApplicationKind
  rendererKey?: string
  applicationId?: number
  runtime?: import('./application').ApplicationRuntime
  canEdit?: boolean
}

export * from './application'

export interface AppCategory {
  slug: string
  name: string
  icon?: string
  description?: string
  app_count?: number
}

// Project Types
export interface Project {
  id: string
  name: string
  status: 'draft' | 'active' | 'completed' | 'archived'
  templateId?: string
  createdAt: string
  updatedAt: string
  config: Record<string, unknown>
}

// Message Types
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
}

// API Response Types
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}
