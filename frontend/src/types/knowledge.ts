export type KnowledgeDocumentStatus = 'pending' | 'indexing' | 'ready' | 'failed';

export interface KnowledgeBaseSummary {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseDetail extends KnowledgeBaseSummary {
  embedding_provider: string;
  embedding_model: string;
  answer_provider: string;
  answer_model: string;
  chunk_size: number;
  chunk_overlap: number;
}

export interface KnowledgeDocument {
  id: number;
  knowledge_base_id: number;
  title: string;
  source_type: 'text' | 'upload';
  original_filename: string;
  mime_type: string;
  byte_size: number;
  checksum: string;
  status: KnowledgeDocumentStatus;
  active_revision: number;
  indexing_run_id: string | null;
  metadata: Record<string, unknown>;
  error_code: string;
  error: string;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSearchResult {
  chunk_id: number;
  document_id: number;
  knowledge_base_id: number;
  knowledge_base_name: string;
  title: string;
  snippet: string;
  score: number;
  page_number: number | null;
  section_path: string[];
  citation: string;
}

export interface KnowledgeSearchResponse {
  query: string;
  retrieval_mode: 'hybrid' | 'vector' | 'lexical';
  results: KnowledgeSearchResult[];
}

export interface KnowledgeCitation extends KnowledgeSearchResult {
  label: string;
}

export interface KnowledgeAnswerOutput {
  result: string;
  answer: string;
  citations: KnowledgeCitation[];
  retrieval_mode: 'hybrid' | 'vector' | 'lexical';
  model: string;
  usage: Record<string, unknown>;
}
