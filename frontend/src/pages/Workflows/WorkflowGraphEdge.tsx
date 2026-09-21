import { BaseEdge, getSmoothStepPath, type Edge, type EdgeProps } from '@xyflow/react';
import { routeWorkflowEdge, type WorkflowNodeBounds } from '@/lib/workflowEdgeRouting';

export type WorkflowEdge = Edge<{ bounds: WorkflowNodeBounds[]; description: string }>;

export default function WorkflowGraphEdge(props: EdgeProps<WorkflowEdge>) {
  const { id, sourceX, sourceY, targetX, targetY, data, markerEnd, style, interactionWidth } = props;
  const points = routeWorkflowEdge(
    { x: sourceX, y: sourceY }, { x: targetX, y: targetY }, data?.bounds || [],
  );
  const path = points
    ? points.map((point, index) => `${index ? 'L' : 'M'} ${point.x},${point.y}`).join(' ')
    : getSmoothStepPath(props)[0];
  return (
    <g>
      <title>{data?.description}</title>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={interactionWidth} />
    </g>
  );
}
