import { Button, Card } from 'antd';
import { FolderOutlined, PartitionOutlined, RightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { workflowPresets } from './presets';

export default function WorkflowPresetsFolder() {
  const navigate = useNavigate();
  return (
    <details className="workflow-preset-folder">
      <summary>
        <span className="workflow-card-icon" aria-hidden="true"><FolderOutlined /></span>
        <span className="workflow-preset-folder-copy">
          <strong>预设</strong>
          <small>{workflowPresets.length} 个预设 · 选择预设，创建自己的工作流</small>
        </span>
        <RightOutlined className="workflow-preset-folder-chevron" aria-hidden="true" />
      </summary>
      <div className="workflow-grid workflow-preset-folder-content">
        {workflowPresets.map((preset) => (
          <Card key={preset.id} className="workflow-card">
            <div className="workflow-card-heading">
              <span className="workflow-card-icon" aria-hidden="true"><PartitionOutlined /></span>
              <h3>{preset.name}</h3>
            </div>
            <p className="workflow-card-description">{preset.description}</p>
            <Button onClick={() => navigate(`/workflows/new?preset=${encodeURIComponent(preset.id)}`)}>
              使用预设
            </Button>
          </Card>
        ))}
      </div>
    </details>
  );
}
