import React, { useEffect, useRef, type CSSProperties } from 'react';
import { Empty, Spin, Input } from 'antd';
import { SearchOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '@/stores/useAppStore';
import { applicationPath } from '@/lib/applicationCatalog';
import './AppsPage.css';

const { Search } = Input;

const AppsPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    apps,
    isLoading,
    selectedCategory,
    searchQuery,
    loadApps,
    setSearchQuery,
    categories,
  } = useAppStore();

  const isFirstRun = useRef(true);

  useEffect(() => {
    // First load fires immediately; later category/search changes are debounced.
    // The isFirstRun guard avoids a second fetch on the initial mount.
    if (isFirstRun.current) {
      isFirstRun.current = false;
      loadApps(selectedCategory || undefined);
      return;
    }
    const timer = setTimeout(() => {
      loadApps(selectedCategory || undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [selectedCategory, searchQuery, loadApps]);

  const categoryName = (slug: string) =>
    categories.find((c) => c.slug === slug)?.name ?? slug;

  return (
    <div className="apps-page animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">应用中心</h1>
        <p className="page-subtitle">汇集不同业务场景的应用与 AI 工具，点开即可使用</p>
      </div>

      <div className="page-toolbar">
        <Search
          placeholder="搜索应用..."
          prefix={<SearchOutlined className="text-text-dim" />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
          className="max-w-xs"
        />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" />
        </div>
      ) : apps.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <Empty description={<span className="text-text-sec">暂无应用</span>} />
        </div>
      ) : (
        <div className="app-grid">
          {apps.map((app, index) => (
            <article
              key={app.id}
              className="app-card"
              style={{
                '--app-accent': app.color || 'var(--color-primary)',
                animationDelay: `${Math.min(index, 8) * 45}ms`,
              } as CSSProperties}
              onClick={() => navigate(applicationPath(app))}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  navigate(applicationPath(app));
                }
              }}
              role="link"
              tabIndex={0}
            >
              <div className="app-card-body">
                <div className="app-card-heading">
                  <span className="app-card-icon" aria-hidden="true">{app.icon}</span>
                  <span className="app-card-category">{categoryName(app.category)}</span>
                </div>
                <div className="app-card-content">
                  <h2 className="app-card-name">{app.name}</h2>
                  <p className="app-card-desc">{app.description}</p>
                  {app.tags.length > 0 && (
                    <div className="app-card-tags" aria-label="应用标签">
                      {app.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="app-card-tag">{tag}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="app-card-footer">
                  <span className="app-card-hint">立即体验</span>
                  <span className="app-card-open" aria-hidden="true">
                    <ArrowRightOutlined />
                  </span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

export default AppsPage;
