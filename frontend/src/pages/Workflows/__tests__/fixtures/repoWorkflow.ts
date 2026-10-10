import type { RepoDetail, RepoReport } from '@/services/repoExplainer';
import type { RepoWorkflowSource } from '../../repoWorkflowSource';

export const repoSource: RepoWorkflowSource = {
  organizationId: '11111111-1111-4111-8111-111111111111', applicationId: '7',
  projectId: '22222222-2222-4222-8222-222222222222',
  analysisId: '33333333-3333-4333-8333-333333333333', featureIds: ['f1', 'f2', 'f3'],
};

export function repoProjectFixture(): RepoDetail {
  const report: RepoReport = {
    summary: '源码工具简介', audience: '工具使用者', workflow: ['先导入再查询'],
    deployment: ['需要数据库'], limitations: ['仅静态分析'],
    coverage: { files_read: 2, files_total: 5, chunks_read: 3, chunks_total: 8, incomplete: true, note: '尚有文件未读取' },
    features: ['documented', 'implemented', 'unconfirmed', 'implemented'].map((status, index) => ({
      id: `f${index + 1}`, title: `功能${index + 1}`, status: status as RepoReport['features'][number]['status'],
      description: `功能说明${index + 1}`, scenario: '查询资料', entry: '工具首页',
      requirements: '需要登录', limitations: '需要联网', discrepancies: '缺少运行验证',
      evidence_ids: [index < 3 ? 'e1' : 'e2'],
    })),
    evidence: {
      e1: { id: 'e1', path: 'src/tool.ts', start: 2, end: 3, quote: 'selectedEvidence();\nreturn true;' },
      e2: { id: 'e2', path: 'src/other.ts', start: 1, end: 1, quote: 'unselectedEvidence();' },
    },
  };
  const snapshot = { id: '44444444-4444-4444-8444-444444444444',
    origin: { kind: 'local', path: '/repo/source', commit: 'analyzed-commit', working_tree: true },
    digest: 'analyzed-digest', status: 'ready', error: '', created_at: '2026-10-10T00:00:00Z', coverage: {} };
  return {
    id: repoSource.projectId, title: '示例仓库', archived: false, updated_at: '',
    snapshots: [{ ...snapshot, id: '55555555-5555-4555-8555-555555555555',
      digest: 'newest-digest', origin: { ...snapshot.origin, commit: 'newest-commit' } }, snapshot],
    tasks: [{ id: repoSource.analysisId, snapshot_id: snapshot.id, kind: 'analyze', status: 'succeeded',
      error: '', progress: {}, options: {}, output: report }], contents: [], handoffs: [], limits: {},
  };
}
