import {
  ApartmentOutlined, ClockCircleOutlined, CompassOutlined,
} from '@ant-design/icons';
import CapabilityHubPage from './CapabilityHubPage';

export default function BuildPage() {
  return <CapabilityHubPage
    eyebrow="BUILD"
    title="构建"
    description="将已有应用和可复用资源组合为可持续执行的业务能力。"
    items={[
      {
        path: '/delegates', title: 'AI 分身', eyebrow: '智能协作',
        description: '创建可以规划、分派并跟进复杂任务的总指挥。', icon: <CompassOutlined />,
      },
      {
        path: '/workflows', title: '工作流', eyebrow: '流程编排',
        description: '将多个应用按依赖和条件组合成完整业务流程。', icon: <ApartmentOutlined />,
      },
      {
        path: '/automations', title: '自动化', eyebrow: '触发与调度',
        description: '通过定时、Webhook 或事件自动启动应用和工作流。', icon: <ClockCircleOutlined />,
      },
    ]}
  />;
}
