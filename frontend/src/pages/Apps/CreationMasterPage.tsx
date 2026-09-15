import { Alert, Button, Result, Spin } from 'antd';
import { ExportOutlined, ReloadOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import {
  getCreationMasterWebRuntime,
  type CreationMasterWebRuntime,
} from '@/services/creationMaster';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import './CreationMasterPage.css';


export default function CreationMasterPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [runtime, setRuntime] = useState<CreationMasterWebRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    if (!organizationId || !applicationId) return;
    setLoading(true);
    setFailed(false);
    try {
      setRuntime(await getCreationMasterWebRuntime(organizationId, applicationId));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [applicationId, organizationId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="creation-master-loading"><Spin size="large" /></div>;
  if (failed) {
    return <Result status="error" title="无法加载创作大师" extra={<Button onClick={load}>重试</Button>} />;
  }
  if (!runtime?.enabled || !runtime.url) {
    return (
      <Result
        status="info"
        title="React 版本尚未配置"
        subTitle="请在后端设置 CREATION_MASTER_REACT_URL。Qt 版本保持独立，可从子仓库直接启动。"
      />
    );
  }

  return (
    <div className="creation-master-page">
      <div className="creation-master-toolbar">
        <Alert
          type="info"
          showIcon
          message="当前为独立部署的 React 版本；Qt 客户端与 Django/Web 运行时互不依赖。"
        />
        <div className="creation-master-actions">
          <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>刷新</Button>
          <Button
            type="primary"
            icon={<ExportOutlined />}
            onClick={() => window.open(runtime.url, '_blank', 'noopener,noreferrer')}
          >
            新窗口打开
          </Button>
        </div>
      </div>
      <iframe
        className="creation-master-frame"
        title="创作大师 React"
        src={runtime.url}
        sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
      />
    </div>
  );
}
