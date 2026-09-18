import {
  BookOutlined, RobotOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import CapabilityHubPage from './CapabilityHubPage';

export default function ResourceLibraryPage() {
  return <CapabilityHubPage
    eyebrow="RESOURCES"
    title="资源库"
    description="管理构建过程中可被反复引用的智能、方法与知识资源。"
    items={[
      {
        path: '/agents', title: '智能体', eyebrow: '执行能力',
        description: '创建和管理处理专项任务的 AI 智能体。', icon: <RobotOutlined />,
      },
      {
        path: '/skills', title: '技能', eyebrow: '专业方法',
        description: '查看当前运行环境可供智能体调用的技能。', icon: <ThunderboltOutlined />,
      },
      {
        path: '/knowledge', title: '知识库', eyebrow: '业务知识',
        description: '沉淀业务文档、检索内容并为应用提供可追溯的上下文。', icon: <BookOutlined />,
      },
    ]}
  />;
}
