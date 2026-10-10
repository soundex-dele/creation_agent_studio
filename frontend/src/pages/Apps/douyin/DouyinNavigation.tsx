import { Link } from 'react-router-dom';
import { ArrowLeft, Bell, Clapperboard, FolderOpen, History, Lightbulb, ScanSearch, Settings2, UserRound } from 'lucide-react';
import { douyinLocation, primarySection } from './navigation';

export const douyinSections = [
  { key: 'owned', label: '我的账号', icon: UserRound, description: '管理自己的定位与文风，回看已发布作品。' },
  { key: 'accounts', label: '发现与研究', icon: ScanSearch, description: '研究对标作品，发现热点与真实需求。' },
  { key: 'ideas', label: '选题库', icon: Lightbulb, description: '确定下一条写什么，把已选主题推进到创作。' },
  { key: 'create', label: '创作中心', icon: Clapperboard, description: '围绕自己的账号，完成文章、口播文案或拍摄脚本。' },
  { key: 'materials', label: '素材库', icon: FolderOpen, description: '收藏灵感，沉淀有出处、可复用的知识。' },
];
export const douyinUtilities = [
  { key: 'subscriptions', label: '通知与订阅', icon: Bell, description: '管理账号订阅，查看更新通知与日报。' },
  { key: 'tasks', label: '任务记录', icon: History, description: '查找全部历史任务，返回对应页面继续。' },
];
export function DouyinNavigation({ params, onNavigate, onSettings, showBack }: {
  params: URLSearchParams; onNavigate: () => void; onSettings: () => void; showBack: boolean;
}) {
  const active = primarySection(params.get('view') || (params.has('account') ? 'accounts' : 'owned'));
  const links = (items: typeof douyinSections) => items.map(({ key, label, icon: Icon }) =>
    <Link key={key} className="douyin-nav-link" to={{ search: `?${douyinLocation(params, key)}` }} aria-current={active === key ? 'page' : undefined} onClick={onNavigate}>
      <Icon size={18} aria-hidden="true" /><span>{label}</span>
    </Link>);
  return <div className="douyin-navigation">
    <div className="douyin-sidebar-brand"><span className="douyin-app-mark"><ScanSearch size={22} aria-hidden="true" /></span><div><strong>抖音对标助手</strong><small>围绕账号，持续创作</small></div></div>
    <nav className="douyin-nav" aria-label="抖音对标助手导航"><span className="douyin-nav-heading">创作工作台</span>{links(douyinSections)}</nav>
    <div className="douyin-sidebar-footer">{links(douyinUtilities)}
      <button type="button" className="douyin-nav-link" onClick={onSettings}><Settings2 size={18} aria-hidden="true" /><span>采集设置</span></button>
      {showBack && <Link className="douyin-nav-link" to="/apps"><ArrowLeft size={18} aria-hidden="true" /><span>返回应用</span></Link>}
    </div>
  </div>;
}
