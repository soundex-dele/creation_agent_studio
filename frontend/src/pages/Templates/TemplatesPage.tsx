import React, { useEffect, useRef } from 'react';
import { Empty, Input, Spin } from 'antd';
import {
  ArrowRightOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { useTemplateStore } from '@/stores/useTemplateStore';
import './TemplatesPage.css';

const { Search } = Input;

const TYPE_ICONS: Record<string, string> = {
  article: '✍️',
  social_post: '📱',
  video_script: '🎬',
  brand_story: '🏷️',
  podcast: '🎙️',
  product_analysis: '🔍',
  other: '📄',
};

const formatSource = (platform?: string, author?: string) =>
  [platform, author].filter(Boolean).join(' · ') || '来源待补充';

const TemplatesPage: React.FC = () => {
  const navigate = useApplicationNavigate();
  const [searchParams] = useSearchParams();
  const { entry, showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const {
    templates,
    isLoading,
    selectedCategory,
    searchQuery,
    loadTemplates,
    setSearchQuery,
  } = useTemplateStore();
  const isFirstRun = useRef(true);

  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false;
      loadTemplates(selectedCategory || undefined);
      return;
    }
    const timer = window.setTimeout(
      () => loadTemplates(selectedCategory || undefined),
      300,
    );
    return () => window.clearTimeout(timer);
  }, [selectedCategory, searchQuery, loadTemplates]);

  return (
    <div className="templates-page animate-fade-in">
      {showApplicationHeader && <div className="page-header case-library-header">
        <div>
          <h1 className="page-title">案例库</h1>
          <p className="page-subtitle">阅读真实案例，理解内容结构、表达方法与可复用规律</p>
        </div>
        <div className="case-library-count">{templates.length} 个案例</div>
      </div>}

      <div className="page-toolbar case-library-toolbar">
        <Search
          placeholder="搜索标题、作者、平台或方法..."
          prefix={<SearchOutlined className="text-text-dim" />}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          allowClear
          className="case-library-search"
        />
      </div>

      {isLoading ? (
        <div className="case-library-state"><Spin size="large" /></div>
      ) : templates.length === 0 ? (
        <div className="case-library-state">
          <Empty description={<span className="text-text-sec">暂无匹配案例</span>} />
        </div>
      ) : (
        <div className="template-grid">
          {templates.map((template, index) => (
            <article
              key={template.id}
              className="template-card"
              style={{ animationDelay: `${index * 50}ms` }}
              onClick={() => navigate(`/apps/case-library/${template.id}?entry=${entry}`)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  navigate(`/apps/case-library/${template.id}?entry=${entry}`);
                }
              }}
              role="link"
              tabIndex={0}
            >
              <div className="template-thumb">
                {template.thumbnail ? (
                  <img src={template.thumbnail} alt="" className="template-thumb-img" />
                ) : (
                  <span className="template-thumb-emoji" aria-hidden="true">
                    {TYPE_ICONS[template.content_type] || TYPE_ICONS.other}
                  </span>
                )}
                <span className="template-type-label">{template.content_type_display}</span>
                {template.is_featured && <span className="template-featured">精选</span>}
              </div>

              <div className="template-body">
                <div className="template-source">
                  {formatSource(template.source_platform, template.source_author)}
                </div>
                <h2 className="template-name">{template.title}</h2>
                <p className="template-desc">{template.summary || template.recommended_reason}</p>
                <div className="template-tags">
                  {(template.tags || []).slice(0, 3).map((tag) => (
                    <span key={tag} className="template-tag">{tag}</span>
                  ))}
                </div>
                <div className="template-footer">
                  <span><FileTextOutlined /> {template.analysis_count} 项拆解</span>
                  {template.reading_time_minutes > 0 && (
                    <span><ClockCircleOutlined /> {template.reading_time_minutes} 分钟</span>
                  )}
                </div>
              </div>
              <div className="template-card-cta">
                查看案例与拆解 <ArrowRightOutlined />
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

export default TemplatesPage;
