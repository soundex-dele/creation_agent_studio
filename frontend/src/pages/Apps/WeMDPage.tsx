import { useState } from 'react';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Button, Spin } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { resolveApplicationPresentation } from '@/lib/applicationPresentation';

import './WeMDPage.css';

export default function WeMDPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);

  return (
    <section className="wemd-runtime" aria-label="WeMD 编辑器">
      {showApplicationHeader && (
        <header className="wemd-runtime__bar">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/apps')}
          >
            返回应用中心
          </Button>
          <div className="wemd-runtime__identity">
            <span className="wemd-runtime__mark" aria-hidden="true">W</span>
            <span>WeMD</span>
            <small>公众号 Markdown 排版编辑器</small>
          </div>
        </header>
      )}

      <div className="wemd-runtime__frame-wrap">
        {loading && (
          <div className="wemd-runtime__loading" role="status" aria-live="polite">
            <Spin size="large" />
            <span>正在启动 WeMD…</span>
          </div>
        )}
        <iframe
          className="wemd-runtime__frame"
          src="/wemd.html"
          title="WeMD Markdown 编辑器"
          allow="clipboard-read; clipboard-write"
          onLoad={() => setLoading(false)}
        />
      </div>
    </section>
  );
}
