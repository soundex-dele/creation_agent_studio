import { useMemo, useState } from 'react';
import { Button, Empty, message } from 'antd';
import { ApartmentOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  type Node, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
import type { WorkflowStep } from '@/types';
import WorkflowGraphEdge, { type WorkflowEdge } from './WorkflowGraphEdge';
import {
  layoutWorkflowGraph, updateWorkflowDependencies, workflowGraphError, workflowNodePosition,
  type WorkflowNodePosition,
} from '@/lib/workflowGraph';
import '@xyflow/react/dist/style.css';
import './WorkflowGraphEditor.css';

type ApplicationNode = Node<{
  name: string; applicationName: string; description: string; index: number; dependencies: number; onConfigure: () => void;
}>;

function WorkflowNode({ data, selected }: NodeProps<ApplicationNode>) {
  return (
    <div className={`workflow-graph-node${selected ? ' is-selected' : ''}`}>
      <Handle type="target" position={Position.Left} aria-label="输入连接点" />
      <div className="workflow-graph-node-heading">
        <span>{data.index + 1}</span>
        <strong title={data.name}>{data.name}</strong>
      </div>
      <p className="workflow-graph-node-application" title={data.description || data.applicationName}>
        <span>使用应用</span>
        <strong>{data.applicationName}</strong>
      </p>
      <div className="workflow-graph-node-footer">
        <small>{data.dependencies ? `${data.dependencies} 个前置节点` : '无前置依赖'}</small>
        <button className="nodrag nopan" type="button" aria-haspopup="dialog" onClick={(event) => {
          event.stopPropagation();
          data.onConfigure();
        }}>
          配置节点
        </button>
      </div>
      <Handle type="source" position={Position.Right} aria-label="输出连接点" />
    </div>
  );
}

const nodeTypes = { application: WorkflowNode };
const edgeTypes = { workflow: WorkflowGraphEdge };

interface Props {
  steps: WorkflowStep[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onConfigure: (key: string) => void;
  onDependenciesChange: (key: string, dependencies: string[]) => void;
  onPositionsChange: (positions: Record<string, WorkflowNodePosition>) => void;
  onAdd: () => void;
}

export default function WorkflowGraphEditor({
  steps, selectedKey, onSelect, onConfigure, onDependenciesChange, onPositionsChange, onAdd,
}: Props) {
  const [instance, setInstance] = useState<ReactFlowInstance<ApplicationNode, WorkflowEdge> | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [measurements, setMeasurements] = useState<Record<string, { width: number; height: number }>>({});
  const positions = useMemo(() => layoutWorkflowGraph(steps), [steps]);
  const nodes: ApplicationNode[] = steps.map((step, index) => ({
    id: step.key,
    type: 'application',
    position: workflowNodePosition(step) || positions[step.key],
    measured: measurements[step.key],
    selected: step.key === selectedKey,
    ariaLabel: `节点 ${index + 1}：${step.name || step.application.application_name}，使用应用：${step.application.application_name}`,
    data: {
      name: step.name || step.application.application_name,
      applicationName: step.application.application_name,
      description: step.application.application_description || '',
      index, dependencies: (step.depends_on || []).length,
      onConfigure: () => { setSelectedEdge(null); onConfigure(step.key); },
    },
  }));
  const bounds = nodes.map((node) => ({
    ...node.position, width: node.measured?.width ?? 236, height: node.measured?.height ?? 124,
  }));
  const edges: WorkflowEdge[] = steps.flatMap((step) => (step.depends_on || []).map((source) => ({
    id: `${source}->${step.key}`, source, target: step.key,
    type: 'workflow',
    data: { bounds, description: `${steps.find((item) => item.key === source)?.name || source} → ${step.name || step.key}` },
    selected: selectedEdge === `${source}->${step.key}`,
    markerEnd: { type: MarkerType.ArrowClosed },
    ariaLabel: `${steps.find((item) => item.key === source)?.name || source} 到 ${step.name || step.key}`,
  })));
  const activeEdge = edges.find((edge) => edge.id === selectedEdge);

  return (
    <section className="workflow-graph" aria-label="工作流图编辑器">
      <div className="workflow-graph-toolbar">
        <span>{steps.length} 个节点 · {edges.length} 条连线</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={onAdd}>添加应用</Button>
        <Button icon={<ApartmentOutlined />} disabled={!steps.length} onClick={() => {
          onPositionsChange(layoutWorkflowGraph(steps));
          setTimeout(() => void instance?.fitView({ padding: 0.2 }), 0);
        }}>自动布局</Button>
        <Button danger icon={<DeleteOutlined />} disabled={!activeEdge} onClick={() => {
          if (!activeEdge) return;
          const target = steps.find((step) => step.key === activeEdge.target);
          if (target) onDependenciesChange(target.key,
            target.depends_on.filter((key) => key !== activeEdge.source));
          setSelectedEdge(null);
        }}>删除连线</Button>
      </div>
      <p className="workflow-graph-help">
        拖动节点调整位置，连接右侧圆点到另一节点左侧圆点。也可点击两个连接点，或在节点配置中选择前置依赖。
        删除依赖会清除引用该依赖的输入映射与条件。
      </p>
      <p className="workflow-graph-help" aria-live="polite">
        {activeEdge ? `当前连线：${activeEdge.data?.description}` : '连线从右侧输出到左侧输入，点击连线可查看起点和终点。'}
      </p>
      <div className="workflow-graph-canvas">
        {!steps.length ? (
          <Empty description="添加应用，开始编排工作流">
            <Button type="primary" onClick={onAdd}>添加应用</Button>
          </Empty>
        ) : (
          <ReactFlow<ApplicationNode, WorkflowEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onInit={setInstance}
            onNodesChange={(changes) => {
              const nextPositions: Record<string, WorkflowNodePosition> = {};
              const nextMeasurements: typeof measurements = {};
              changes.forEach((change) => {
                if (change.type === 'position' && change.position) nextPositions[change.id] = change.position;
                if (change.type === 'select' && change.selected) onSelect(change.id);
                if (change.type === 'dimensions' && change.dimensions) {
                  nextMeasurements[change.id] = change.dimensions;
                }
              });
              // Controlled nodes must retain measured sizes to keep handles and edges initialized.
              if (Object.keys(nextMeasurements).length) {
                setMeasurements((current) => ({ ...current, ...nextMeasurements }));
              }
              if (Object.keys(nextPositions).length) {
                // Freeze fallback positions on first drag so list edits do not move other nodes.
                onPositionsChange({ ...Object.fromEntries(nodes.map((node) => [node.id, node.position])), ...nextPositions });
              }
            }}
            onEdgesChange={(changes) => changes.forEach((change) => {
              if (change.type === 'select') {
                setSelectedEdge((current) => change.selected ? change.id : current === change.id ? null : current);
              }
            })}
            onNodeClick={(_, node) => { onSelect(node.id); setSelectedEdge(null); }}
            onEdgeClick={(_, edge) => setSelectedEdge(edge.id)}
            onPaneClick={() => setSelectedEdge(null)}
            onConnect={({ source, target }) => {
              const step = steps.find((item) => item.key === target);
              if (!step || step.depends_on.includes(source)) return;
              const dependencies = [...step.depends_on, source];
              const error = workflowGraphError(updateWorkflowDependencies(steps, target, dependencies));
              if (error) { message.warning(error); return; }
              onDependenciesChange(target, dependencies);
            }}
            deleteKeyCode={null}
            edgesReconnectable={false}
            minZoom={0.2}
            maxZoom={1.5}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            ariaLabelConfig={{
              'node.a11yDescription.default': '按回车或空格选择节点，使用方向键移动节点。',
              'node.a11yDescription.ariaLiveMessage': ({ x, y }) => `节点已移动到 ${x}，${y}`,
              'edge.a11yDescription.default': '按回车或空格选择连线，然后使用删除连线按钮删除。',
              'controls.ariaLabel': '画布缩放控制',
              'controls.zoomIn.ariaLabel': '放大画布',
              'controls.zoomOut.ariaLabel': '缩小画布',
              'controls.fitView.ariaLabel': '适应画布',
            }}
          >
            <Background gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        )}
      </div>
    </section>
  );
}
