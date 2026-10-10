import { Link } from 'react-router-dom';
import { BookOpen } from 'lucide-react';
import { ArrowLeft, Bell, ChartNoAxesCombined, Clapperboard, Lightbulb, Radar, ScanSearch, Settings2, UserRound, UsersRound } from 'lucide-react';

export const douyinSections = [
  { key: '', label: '对标账号', icon: UsersRound, description: '管理值得学习的账号，积累真实作品样本。' },
  { key: 'owned', label: '我的账号', icon: UserRound, description: '分析自己的定位与文风，让每个账号保持独立表达。' },
  { key: 'research', label: '对标研究', icon: ScanSearch, description: '跨账号研究作品，发现值得继续探索的选题。' },
  { key: 'radar', label: '选题雷达', icon: Radar, description: '从抖音热榜与关键词搜索发现选题，保留真实来源。' },
  { key: 'ideas', label: '选题库', icon: Lightbulb, description: '整理研究中发现的灵感，推进下一条内容。' },
  { key: 'knowledge', label: '创作知识库', icon: BookOpen, description: '从作品中沉淀有出处的知识，供下次创作选择使用。' },
  { key: 'create', label: '创作中心', icon: Clapperboard, description: '结合自身定位，把灵感写成可拍摄的脚本。' },
  { key: 'review', label: '作品复盘', icon: ChartNoAxesCombined, description: '回看自己的作品表现，积累创作经验。' },
  { key: 'subscriptions', label: '订阅通知', icon: Bell, description: '管理关注的更新，查看采集与研究通知。' },
  { key: 'profiles', label: '个人创作档案', icon: UserRound, description: '记录你的内容定位、目标观众与拍摄条件。' },
];

export function DouyinNavigation({ params, onNavigate, onSettings, showBack }: {
  params: URLSearchParams;
  onNavigate: () => void;
  onSettings: () => void;
  showBack: boolean;
}) {
  const active = params.get('view') || '';
  return <div className="douyin-navigation">
    <div className="douyin-sidebar-brand"><span className="douyin-app-mark"><ScanSearch size={22} aria-hidden="true" /></span><div><strong>抖音对标助手</strong><small>内容研究 · 创作工作台</small></div></div>
    <nav className="douyin-nav" aria-label="抖音对标助手导航">
      <span className="douyin-nav-heading">研究与创作</span>
      {douyinSections.map(({ key, label, icon: Icon }) => {
        const next = new URLSearchParams(params);
        next.delete('account');
        if (key !== active && (key === 'radar' || active === 'radar')) next.delete('task');
        if (key) next.set('view', key); else next.delete('view');
        return <Link key={key} className={`douyin-nav-link${key === 'review' ? ' douyin-nav-link--separated' : ''}`} to={{ search: next.toString() ? `?${next}` : '' }} aria-current={active === key ? 'page' : undefined} onClick={onNavigate}>
          <Icon size={18} aria-hidden="true" /><span>{label}</span>
        </Link>;
      })}
    </nav>
    <div className="douyin-sidebar-footer">
      <button type="button" className="douyin-nav-link" onClick={onSettings}><Settings2 size={18} aria-hidden="true" /><span>采集设置</span></button>
      {showBack && <Link className="douyin-nav-link" to="/apps"><ArrowLeft size={18} aria-hidden="true" /><span>返回应用</span></Link>}
    </div>
  </div>;
}
