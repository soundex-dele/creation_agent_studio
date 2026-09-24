import React, { useEffect } from 'react';
import { Button, Result, Spin, Tag } from 'antd';
import {
  ArrowLeftOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  ExportOutlined,
  FileTextOutlined,
  LinkOutlined,
  UserOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { useParams, useSearchParams } from 'react-router-dom';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';
import { useTemplateStore } from '@/stores/useTemplateStore';
import './TemplateDetailPage.css';

const formatDate = (date?: string | null) =>
  date ? new Date(`${date}T00:00:00`).toLocaleDateString('zh-CN') : '未注明';

const TemplateDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useApplicationNavigate();
  const [searchParams] = useSearchParams();
  const libraryPath = `/apps/case-library?entry=${searchParams.get('entry') === 'home' ? 'home' : 'apps'}`;
  const { currentTemplate, isLoadingTemplate, loadTemplate, clearCurrentTemplate } =
    useTemplateStore();
  const templateId = id ? Number(id) : Number.NaN;

  useEffect(() => {
    if (!Number.isNaN(templateId)) loadTemplate(templateId).catch(() => undefined);
    return () => clearCurrentTemplate();
  }, [templateId, loadTemplate, clearCurrentTemplate]);

  if (isLoadingTemplate) {
    return <div className="template-detail-state"><Spin size="large" /></div>;
  }

  if (!currentTemplate) {
    return (
      <div className="template-detail-page">
        <Result
          status="404"
          title="案例不存在"
          subTitle="该案例可能尚未发布、已归档或链接有误。"
          extra={<Button type="primary" onClick={() => navigate(libraryPath)}>返回案例库</Button>}
        />
      </div>
    );
  }

  const sourceBody = currentTemplate.source_content || currentTemplate.source_excerpt;

  return (
    <div className="template-detail-page animate-fade-in">
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(libraryPath)}
        className="template-detail-back"
      >
        返回案例库
      </Button>

      <header className="template-detail-header">
        <div className="template-detail-eyebrow">
          {currentTemplate.source_platform || currentTemplate.category?.name || '案例'}
          <span>·</span>
          {currentTemplate.content_type_display}
        </div>
        <h1 className="template-detail-title">{currentTemplate.title}</h1>
        <p className="template-detail-summary">{currentTemplate.summary}</p>
        <div className="template-detail-tags">
          {(currentTemplate.tags || []).map((tag) => (
            <Tag key={tag} className="template-detail-tag">{tag}</Tag>
          ))}
        </div>
      </header>

      <div className="template-detail-layout">
        <main className="template-detail-main">
          {currentTemplate.recommended_reason && (
            <section className="template-detail-reason">
              <div className="template-detail-kicker">为什么值得看</div>
              <p>{currentTemplate.recommended_reason}</p>
            </section>
          )}

          <section className="template-detail-section">
            <div className="template-detail-section-head">
              <div>
                <div className="template-detail-kicker">SOURCE</div>
                <h2>原文</h2>
              </div>
              {currentTemplate.source_url && (
                <a
                  className="template-source-link"
                  href={currentTemplate.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  打开原文 <ExportOutlined />
                </a>
              )}
            </div>
            {currentTemplate.source_title && currentTemplate.source_title !== currentTemplate.title && (
              <h3 className="template-source-title">{currentTemplate.source_title}</h3>
            )}
            <div className="template-source-note">
              {currentTemplate.copyright_mode_display} · 内容以原始来源为准
            </div>
            {sourceBody ? (
              <div className="template-prose"><ReactMarkdown>{sourceBody}</ReactMarkdown></div>
            ) : (
              <div className="template-source-empty">
                当前案例仅保存来源信息，请通过原文链接阅读完整内容。
              </div>
            )}
          </section>

          <section className="template-detail-section">
            <div className="template-detail-section-head">
              <div>
                <div className="template-detail-kicker">ANALYSIS</div>
                <h2>内容拆解</h2>
              </div>
              <span className="template-section-count">
                {currentTemplate.analysis_sections.length} 项
              </span>
            </div>
            {currentTemplate.analysis_sections.length > 0 ? (
              <div className="template-analysis-list">
                {currentTemplate.analysis_sections.map((section, index) => (
                  <article key={section.id} className="template-analysis-item">
                    <div className="template-analysis-index">{String(index + 1).padStart(2, '0')}</div>
                    <div className="template-analysis-content">
                      <div className="template-analysis-type">{section.section_type_display}</div>
                      <h3>{section.title}</h3>
                      <div className="template-prose compact">
                        <ReactMarkdown>{section.content}</ReactMarkdown>
                      </div>
                      {section.evidence_quote && (
                        <blockquote>“{section.evidence_quote}”</blockquote>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="template-source-empty">该案例暂未完成拆解。</div>
            )}
          </section>

          {currentTemplate.reusable_patterns.length > 0 && (
            <section className="template-detail-section">
              <div className="template-detail-kicker">PATTERNS</div>
              <h2>可复用规律</h2>
              <ol className="template-pattern-list">
                {currentTemplate.reusable_patterns.map((pattern, index) => (
                  <li key={`${index}-${pattern}`}>
                    <span>{index + 1}</span>
                    <p>{pattern}</p>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </main>

        <aside className="template-detail-aside">
          <div className="template-case-info">
            <h2>案例信息</h2>
            <dl>
              <div><dt><FileTextOutlined /> 内容类型</dt><dd>{currentTemplate.content_type_display}</dd></div>
              <div><dt><LinkOutlined /> 来源平台</dt><dd>{currentTemplate.source_platform || '未注明'}</dd></div>
              <div><dt><UserOutlined /> 作者</dt><dd>{currentTemplate.source_author || '未注明'}</dd></div>
              <div><dt><CalendarOutlined /> 发布时间</dt><dd>{formatDate(currentTemplate.source_published_at)}</dd></div>
              <div><dt><ClockCircleOutlined /> 篇幅</dt><dd>
                {currentTemplate.word_count ? `${currentTemplate.word_count.toLocaleString()} 字` : '未统计'}
                {currentTemplate.reading_time_minutes ? ` · ${currentTemplate.reading_time_minutes} 分钟` : ''}
              </dd></div>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
};

export default TemplateDetailPage;
