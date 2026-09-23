import React, { useEffect, useState } from 'react';
import { Button, Result, Spin, Tag } from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { useAppStore } from '@/stores/useAppStore';
import { applicationPath } from '@/lib/applicationCatalog';
import ApplicationIcon from '@/components/ApplicationIcon';
import type { AppItem } from '@/types';
import './AppDetailPage.css';

const AppDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { loadApp, categories } = useAppStore();

  const [app, setApp] = useState<AppItem | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) {
      setLoading(false);
      setApp(null);
      return;
    }
    setLoading(true);
    loadApp(id)
      .then(setApp)
      .finally(() => setLoading(false));
  }, [id, loadApp]);

  const categoryName = (slug: string) =>
    categories.find((c) => c.slug === slug)?.name ?? slug;

  if (loading) {
    return (
      <div className="app-detail-page">
        <div className="flex items-center justify-center py-20">
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (!app) {
    return (
      <div className="app-detail-page">
        <Result
          status="404"
          title="应用不存在"
          subTitle="该应用可能已下线或链接有误。"
          extra={
            <Button type="primary" onClick={() => navigate('/apps')}>
              返回应用中心
            </Button>
          }
        />
      </div>
    );
  }

  // Real screenshots if provided; otherwise fall back to 3 generated placeholders.
  const shots = app.screenshots && app.screenshots.length > 0 ? app.screenshots : ['', '', ''];

  const handleOpen = () => {
    window.open(applicationPath(app), '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="app-detail-page animate-fade-in">
      {/* Header */}
      <div className="app-detail-header">
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/apps')}
          className="app-detail-back"
        >
          返回
        </Button>

        <div className="app-detail-title-row">
          <div
            className="app-detail-icon"
            style={
              app.color
                ? { background: `linear-gradient(135deg, ${app.color}, color-mix(in srgb, ${app.color} 40%, #000))` }
                : undefined
            }
          >
            <span><ApplicationIcon app={app} /></span>
          </div>
          <div className="app-detail-meta">
            <h1 className="app-detail-name">{app.name}</h1>
            <div className="app-detail-sub">
              <Tag className="app-detail-cat">{categoryName(app.category)}</Tag>
              {app.developer && <span className="app-detail-dev">· {app.developer}</span>}
            </div>
            <div className="app-detail-tags">
              {app.tags.map((tag) => (
                <span key={tag} className="app-detail-tag">{tag}</span>
              ))}
            </div>
          </div>

          <div className="app-detail-actions">
            <Button type="primary" size="large" icon={<PlayCircleOutlined />} onClick={handleOpen}>
              打开应用
            </Button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="app-detail-section">
        <h2 className="app-detail-section-title">应用介绍</h2>
        <p className="app-detail-desc">{app.description}</p>
      </div>

      {/* Screenshots */}
      <div className="app-detail-section">
        <h2 className="app-detail-section-title">截图预览</h2>
        <div className="app-detail-shots">
          {shots.map((src, i) => (
            <div
              key={i}
              className="app-detail-shot"
              style={
                app.color
                  ? { background: `linear-gradient(135deg, ${app.color}, color-mix(in srgb, ${app.color} 40%, #000))` }
                  : undefined
              }
            >
              <div className="app-detail-shot-chrome">
                <span className="app-detail-shot-dot" />
                <span className="app-detail-shot-dot" />
                <span className="app-detail-shot-dot" />
              </div>
              {src ? (
                <img className="app-detail-shot-img" src={src} alt={`${app.name} 截图 ${i + 1}`} />
              ) : (
                <div className="app-detail-shot-placeholder">
                  <div className="app-detail-shot-emoji"><ApplicationIcon app={app} /></div>
                  <div className="app-detail-shot-name">{app.name}</div>
                  <div className="app-detail-shot-mock">
                    <span /><span /><span />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default AppDetailPage;
