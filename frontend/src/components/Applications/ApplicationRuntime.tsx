import { Empty } from 'antd';
import type { AppItem, ApplicationRuntime as ApplicationRuntimeData } from '@/types';
import ImageGenieRunner from '@/pages/Apps/ImageGenieRunner';
import BatchTranscribeRunner from '@/pages/Apps/BatchTranscribeRunner';
import ChatApplicationView from './ChatApplicationView';
import { ApplicationRuntimeProvider } from './ApplicationRuntimeContext';

interface Props {
  application: ApplicationRuntimeData;
  projectId?: number;
  workflowStepRunId?: string;
}

const toAppItem = (application: ApplicationRuntimeData): AppItem => ({
  id: application.application_slug,
  applicationId: application.id,
  name: application.application_name,
  description: application.application_description,
  category: '',
  icon: application.application_icon,
  color: application.application_color,
  tags: [],
  kind: application.kind,
  rendererKey: application.renderer_key,
  runtime: application,
});

const ApplicationRuntime: React.FC<Props> = ({ application: runtime, projectId, workflowStepRunId }) => {
  const application = toAppItem(runtime);
  let content: React.ReactNode;
  switch (runtime.renderer_key) {
    case 'chat':
      content = <ChatApplicationView application={runtime} projectId={projectId}
        workflowStepRunId={workflowStepRunId} />;
      break;
    case 'image-genie':
      content = <ImageGenieRunner application={application} embedded projectId={projectId} />;
      break;
    case 'batch-transcribe':
      content = <BatchTranscribeRunner application={application} embedded />;
      break;
    default:
      content = (
        <div style={{ display: 'grid', height: '100%', placeItems: 'center' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={`${runtime.application_name} 尚未注册界面：${runtime.renderer_key}`} />
        </div>
      );
  }
  if (runtime.organization_id && runtime.v2_application_id) {
    return (
      <ApplicationRuntimeProvider
        organizationId={runtime.organization_id}
        applicationId={runtime.v2_application_id}
        environment={runtime.environment}
      >
        {content}
      </ApplicationRuntimeProvider>
    );
  }
  return content;
};

export default ApplicationRuntime;
