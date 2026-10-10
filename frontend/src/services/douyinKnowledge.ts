export interface KnowledgeEvidence {
  ref: string; task_id: string; work_id: string; account_id: string; account_name: string;
  title: string; url: string; kind: 'segment' | 'text' | 'frame'; text: string; start?: number | null; end?: number | null;
}
export interface KnowledgeContent {
  title: string; text: string; application_notes: string; tags: string[];
  category: 'content' | 'method'; basis: 'author_view' | 'observation' | 'inference'; evidence: KnowledgeEvidence[];
}
export interface KnowledgeCandidate extends KnowledgeContent { candidate_id: string }
export interface KnowledgeSnapshot extends KnowledgeContent { id: string; revision: number }
export interface KnowledgeCard extends KnowledgeSnapshot {
  source_missing: boolean; index_status: string; index_error: string; created_at: string; updated_at: string;
}
export const knowledgeFields = (card: KnowledgeContent) => ({ title: card.title, text: card.text, application_notes: card.application_notes, tags: card.tags });
export const knowledgeSelection = (cards: KnowledgeSnapshot[]) => cards.map(({ id, revision }) => ({ id, revision }));
