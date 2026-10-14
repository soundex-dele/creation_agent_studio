import type { SourceSnapshot } from '@/services/projectPromotion';

export default function SourceEvidence({ source }: { source?: SourceSnapshot }) {
  if (!source?.evidence || !Object.keys(source.evidence).length) return null;
  return <details className="promotion-source"><summary>源码依据与探索范围</summary>
    <p className="promotion-muted">本次只读快照，未运行项目。请结合实际演示核实能力后确认案例。</p>
    {source.origin?.path && <p>项目：{source.origin.path}</p>}
    {source.coverage && <p>{source.coverage.files_cited !== undefined ? `引用 ${source.coverage.files_cited} 个文件，项目快照共 ${source.coverage.files_total} 个文本文件。` : `读取 ${source.coverage.files_read} / ${source.coverage.files_total} 个文本文件。`}{source.coverage.note}</p>}
    {source.origin?.commit && <p>基准提交：{source.origin.commit}（包含当时工作区修改）</p>}
    {Object.entries(source.evidence).map(([id, row]) => <details key={id}><summary>{row.path}:{row.start}-{row.end}</summary>
      <pre className="promotion-prose">{row.quote}</pre><p className="promotion-muted">文件 SHA256：{row.sha256}</p>
    </details>)}
  </details>;
}
