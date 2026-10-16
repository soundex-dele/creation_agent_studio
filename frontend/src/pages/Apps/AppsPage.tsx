import React, { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Button, Empty, Input, Select, Spin } from 'antd';
import {
  ArrowRightOutlined,
  MessageOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons';
import { useAppStore } from '@/stores/useAppStore';
import { useApplicationPreferences } from '@/hooks/useApplicationPreferences';
import { applicationPath } from '@/lib/applicationCatalog';
import { openApplicationWindow } from '@/lib/applicationPresentation';
import ApplicationIcon from '@/components/ApplicationIcon';
import type { AppItem } from '@/types';
import { CONVERSATION_APP, CONVERSATION_APP_ID, isCoworkApplication } from '@/lib/conversationApplication';
import './AppsPage.css';

type AppView = 'all' | 'favorites';
type AppSort = 'recommended' | 'recent' | 'popular' | 'name';

const CONVERSATION_ID = CONVERSATION_APP_ID;

const AppsPage: React.FC = () => {
  const { preferences, recordUsage, toggleFavorite } = useApplicationPreferences();
  const conversationPath = '/chat?entry=apps';
  const {
    apps,
    isLoading,
    error,
    selectedCategory,
    searchQuery,
    loadApps,
    loadCategories,
    setSearchQuery,
    selectCategory,
    categories,
  } = useAppStore();
  const [view, setView] = useState<AppView>('all');
  const [sort, setSort] = useState<AppSort>('recommended');

  const isFirstRun = useRef(true);

  useEffect(() => {
    void loadCategories();
  }, [loadCategories]);

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
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const showConversationCard = (!selectedCategory || selectedCategory === 'chat' || apps.some(isCoworkApplication))
    && (!normalizedQuery || [CONVERSATION_APP.name, CONVERSATION_APP.description, ...CONVERSATION_APP.tags, '沟通', '智能助手', 'chat', 'cowork']
      .some((value) => value.includes(normalizedQuery)));

  const openApplication = (id: string, path: string) => {
    recordUsage(id);
    openApplicationWindow(path);
  };

  const visibleApps = useMemo(() => {
    let result = apps.filter(app => !isCoworkApplication(app));
    if (view === 'favorites') {
      result = result.filter((app) => preferences.favorites.includes(app.id));
    }
    return [...result].sort((left, right) => {
      if (sort === 'recent') {
        return (preferences.recent[right.id] || 0) - (preferences.recent[left.id] || 0);
      }
      if (sort === 'popular') return (right.usage_count || 0) - (left.usage_count || 0);
      if (sort === 'name') return left.name.localeCompare(right.name, 'zh-CN');
      return 0;
    });
  }, [apps, preferences.favorites, preferences.recent, sort, view]);

  const conversationVisible = showConversationCard
    && (view === 'all' || preferences.favorites.includes(CONVERSATION_ID));
  const resultCount = visibleApps.length + (conversationVisible ? 1 : 0);
  const hasFilters = Boolean(selectedCategory || normalizedQuery || view === 'favorites');

  const resetFilters = () => {
    selectCategory(null);
    setSearchQuery('');
    setView('all');
  };

  const renderFavorite = (id: string, name: string) => {
    const favorite = preferences.favorites.includes(id);
    return <button
      type="button"
      className={`app-card-favorite ${favorite ? 'active' : ''}`}
      aria-label={favorite ? `取消收藏${name}` : `收藏${name}`}
      aria-pressed={favorite}
      onClick={(event) => {
        event.stopPropagation();
        toggleFavorite(id);
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {favorite ? <StarFilled aria-hidden="true" /> : <StarOutlined aria-hidden="true" />}
    </button>;
  };

  const renderApplicationCard = (app: AppItem, index: number) => (
    <article
      key={app.id}
      className="app-card"
      style={{
        '--app-accent': app.color || 'var(--color-primary)',
        animationDelay: `${Math.min(index, 8) * 45}ms`,
      } as CSSProperties}
      onClick={() => openApplication(app.id, applicationPath(app))}
      onKeyDown={(event) => {
        if (event.currentTarget === event.target && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          openApplication(app.id, applicationPath(app));
        }
      }}
      role="link"
      aria-label={`${app.name}（在新窗口中打开）`}
      tabIndex={0}
    >
      {renderFavorite(app.id, app.name)}
      <div className="app-card-body">
        <div className="app-card-heading">
          <span className="app-card-icon" aria-hidden="true"><ApplicationIcon app={app} /></span>
          <div className="app-card-identity">
            <h2 className="app-card-name">{app.name}</h2>
            <span className="app-card-category">{categoryName(app.category)}</span>
          </div>
        </div>
        <div className="app-card-content">
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
          <span className="app-card-open">
            打开应用 <ArrowRightOutlined aria-hidden="true" />
          </span>
          {app.usage_count ? <span className="app-card-usage">{app.usage_count.toLocaleString()} 次使用</span> : null}
        </div>
      </div>
    </article>
  );

  return (
    <div className="apps-page animate-fade-in">
      <div className="apps-heading">
        <div className="page-header">
          <h1 className="page-title">应用</h1>
          <p className="page-subtitle">发现并打开你的 AI 工作应用</p>
        </div>
        <div className="apps-search-field">
          <label htmlFor="apps-search">搜索应用</label>
          <Input
            id="apps-search"
            placeholder="搜索名称、描述或标签"
            prefix={<SearchOutlined aria-hidden="true" />}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            allowClear
            className="apps-search"
          />
        </div>
      </div>

      <div className="apps-category-strip" role="group" aria-label="应用分类">
        <button type="button" aria-pressed={!selectedCategory} className={!selectedCategory ? 'active' : ''} onClick={() => selectCategory(null)}>全部</button>
        <button type="button" aria-pressed={selectedCategory === 'chat'} className={selectedCategory === 'chat' ? 'active' : ''} onClick={() => selectCategory('chat')}>沟通协作</button>
        {categories.filter((category) => category.slug !== 'chat').map((category) => (
          <button
            type="button"
            key={category.slug}
            className={selectedCategory === category.slug ? 'active' : ''}
            aria-pressed={selectedCategory === category.slug}
            onClick={() => selectCategory(category.slug)}
          >
            {category.name}
          </button>
        ))}
      </div>

      <div className="page-toolbar apps-toolbar">
        <div className="apps-view-switch" role="group" aria-label="应用视图">
          <button type="button" aria-pressed={view === 'all'} className={view === 'all' ? 'active' : ''} onClick={() => setView('all')}>全部应用</button>
          <button type="button" aria-pressed={view === 'favorites'} className={view === 'favorites' ? 'active' : ''} onClick={() => setView('favorites')}>
            <StarOutlined aria-hidden="true" /> 常用应用
          </button>
        </div>
        <span className="apps-result-count" role="status">
          {isLoading ? '正在加载应用…' : error ? '加载失败' : `${resultCount} 个${hasFilters ? '匹配' : '可用'}应用`}
        </span>
        <div className="apps-toolbar-actions">
          <div className="apps-sort-field">
            <label htmlFor="apps-sort">排序</label>
            <Select<AppSort>
              id="apps-sort"
              value={sort}
              onChange={setSort}
              className="apps-sort"
              aria-label="应用排序"
              options={[
                { value: 'recommended', label: '推荐排序' },
                { value: 'recent', label: '最近使用' },
                { value: 'popular', label: '使用最多' },
                { value: 'name', label: '名称排序' },
              ]}
            />
          </div>
          <Button
            type="text"
            className="apps-refresh"
            icon={<ReloadOutlined aria-hidden="true" />}
            loading={isLoading}
            onClick={() => void Promise.all([loadApps(selectedCategory || undefined), loadCategories()])}
          >刷新</Button>
        </div>
      </div>

      {isLoading && apps.length === 0 ? (
        <div className="apps-state">
          <Spin size="large" />
        </div>
      ) : error ? (
        <div className="apps-state">
          <Empty description={<span className="text-text-sec">{error}</span>}>
            <Button type="primary" onClick={() => void loadApps(selectedCategory || undefined)}>重新加载</Button>
          </Empty>
        </div>
      ) : resultCount === 0 ? (
        <div className="apps-state">
          <Empty description={<span className="text-text-sec">{view === 'favorites' ? '还没有收藏常用应用' : '暂无匹配应用'}</span>}>
            {hasFilters && <Button onClick={resetFilters}>清除筛选</Button>}
          </Empty>
        </div>
      ) : (
        <div className="app-grid">
          {conversationVisible && (
            <article
              className="app-card app-card--conversation"
              style={{ '--app-accent': '#6d5dfc' } as CSSProperties}
              onClick={() => openApplication(CONVERSATION_ID, conversationPath)}
              onKeyDown={(event) => {
                if (event.currentTarget === event.target && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  openApplication(CONVERSATION_ID, conversationPath);
                }
              }}
              role="link"
              aria-label="对话（在新窗口中打开）"
              tabIndex={0}
            >
              {renderFavorite(CONVERSATION_ID, '对话')}
              <div className="app-card-body">
                <div className="app-card-heading">
                  <span className="app-card-icon" aria-hidden="true"><MessageOutlined /></span>
                  <div className="app-card-identity">
                    <h2 className="app-card-name">对话</h2>
                    <span className="app-card-category">沟通协作</span>
                  </div>
                </div>
                <div className="app-card-content">
                  <p className="app-card-desc">{CONVERSATION_APP.description}</p>
                  <div className="app-card-tags" aria-label="对话标签">
                    <span className="app-card-tag">AI 助手</span>
                    <span className="app-card-tag">多轮对话</span>
                    <span className="app-card-tag">任务协作</span>
                  </div>
                </div>
                <div className="app-card-footer">
                  <span className="app-card-open">打开对话 <ArrowRightOutlined aria-hidden="true" /></span>
                </div>
              </div>
            </article>
          )}
          {visibleApps.map(renderApplicationCard)}
        </div>
      )}
    </div>
  );
};

export default AppsPage;
