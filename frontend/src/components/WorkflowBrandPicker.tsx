import { Collapse, Select, Space, Typography } from 'antd';
import BrandReferencePicker from './BrandReferencePicker';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { BrandConfig, BrandSelection } from '@/services/brandLibrary';
import type { Workflow } from '@/types';

export interface WorkflowBrandSelection {
  selection: BrandSelection | null;
  nodes: Record<string, { mode: 'inherit' | 'disabled' | 'override'; selection?: BrandSelection | null }>;
}
export const emptyWorkflowBrand = (): WorkflowBrandSelection => ({ selection: null, nodes: {} });
export function workflowBrandRequest(value: WorkflowBrandSelection) {
  return { reference: value.selection?.reference || null,
    nodes: Object.fromEntries(Object.entries(value.nodes).map(([key, node]) => [key, {
      mode: node.mode, ...(node.mode === 'override' && node.selection ? { reference: node.selection.reference } : {}),
    }])) };
}
export function workflowNodeBrand(value: WorkflowBrandSelection, key: string) {
  const node = value.nodes[key];
  return node?.mode === 'disabled' ? null : node?.mode === 'override' ? node.selection || null : value.selection;
}

export default function WorkflowBrandPicker({ workflow, value, onChange }: {
  workflow: Workflow; value: WorkflowBrandSelection; onChange: (value: WorkflowBrandSelection) => void;
}) {
  const organizationId = useOrganizationStore((s) => s.currentOrganizationId);
  const steps = (workflow.steps || []).filter((s) => (s.application.default_config.brand_reference as BrandConfig | undefined)?.enabled);
  if (!organizationId || !steps.length) return null;
  const root = tenantApiRoot(organizationId);
  const config: BrandConfig = { enabled: true, default_modules: ['positioning', 'voice', 'visual'], fields: {} };
  return <section aria-label="工作流品牌资料">
    <Typography.Paragraph type="secondary">本次品牌资料会供支持引用的节点使用，优先于模板；不会保存到共享工作流。</Typography.Paragraph>
    <BrandReferencePicker root={root} config={config} value={value.selection} onChange={(selection) => onChange({ ...value, selection })} />
    <Collapse items={[{ key: 'nodes', label: '逐节点调整品牌资料', children: <Space direction="vertical" style={{ width: '100%' }}>
      {steps.map((step) => {
        const node = value.nodes[step.key] || { mode: 'inherit' as const };
        return <div key={step.key} style={{ width: '100%' }}><label>{step.name || step.application.application_name}</label>
          <Select aria-label={`${step.name || step.application.application_name}的品牌来源`} style={{ width: '100%' }} value={node.mode}
            options={[{ value: 'inherit', label: '继承本次品牌' }, { value: 'override', label: '指定其他品牌资料' }, { value: 'disabled', label: '不使用品牌资料' }]}
            onChange={(mode) => onChange({ ...value, nodes: { ...value.nodes, [step.key]: { ...node, mode } } })} />
          {node.mode === 'override' && <BrandReferencePicker root={root} config={step.application.default_config.brand_reference as BrandConfig}
            value={node.selection || null} onChange={(selection) => onChange({ ...value, nodes: { ...value.nodes, [step.key]: { mode: 'override', selection } } })} />}
        </div>;
      })}
    </Space> }]} />
  </section>;
}
