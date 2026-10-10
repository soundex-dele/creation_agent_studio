export type TemplateContentType =
  | 'article'
  | 'social_post'
  | 'video_script'
  | 'brand_story'
  | 'podcast'
  | 'product_analysis'
  | 'other';

export type TemplateCopyrightMode = 'link_only' | 'excerpt' | 'authorized' | 'owned' | 'reference';
export type TemplateStatus = 'draft' | 'review' | 'published' | 'archived';

export interface TemplateCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  order: number;
  template_count: number;
}

export interface TemplateSummary {
  status?: TemplateStatus;
  source_kind?: string;
  id: number;
  title: string;
  summary: string;
  thumbnail?: string;
  tags: string[];
  category_name: string;
  content_type: TemplateContentType;
  content_type_display: string;
  source_author?: string;
  source_platform?: string;
  source_published_at?: string | null;
  recommended_reason?: string;
  word_count: number;
  reading_time_minutes: number;
  analysis_count: number;
  is_featured: boolean;
  view_count: number;
  created_by_username?: string;
  created_at: string;
  updated_at: string;
}

export interface TemplateAnalysisSection {
  id: number;
  section_type: string;
  section_type_display: string;
  title: string;
  content: string;
  evidence_quote?: string;
  order: number;
}

export interface TemplateDetail extends Omit<TemplateSummary, 'category_name' | 'analysis_count'> {
  source_navigation?: { available: boolean; application_id?: number; account_id?: string; task_id?: string | null } | null;
  category: TemplateCategory | null;
  source_title?: string;
  source_url?: string;
  source_excerpt?: string;
  source_content?: string;
  reusable_patterns: string[];
  copyright_mode: TemplateCopyrightMode;
  copyright_mode_display: string;
  source_snapshot_at?: string | null;
  analysis_sections: TemplateAnalysisSection[];
  status: TemplateStatus;
}
