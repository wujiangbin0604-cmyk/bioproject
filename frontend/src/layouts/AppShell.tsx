import { useEffect, useState } from 'react';
import { Badge, Button, Drawer, Input, Menu, Modal, Tag, Tooltip } from '@arco-design/web-react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { Dataset, Model, Task } from '../api/platform';
import { names, terminal } from '../api/platform';
import type { HealthData, Envelope } from '../types/api';
import { useLiveResource } from '../hooks/useLiveResource';
import { usePreferences } from '../hooks/usePreferences';
import { Icon } from '../components/ui/Icon';
import type { IconName } from '../components/ui/Icon';
import { HeaderDNA, SidebarDNA } from '../components/visuals/AnimatedDNA';
import { PageTransition } from '../components/ui/PageTransition';
import { EmptyState } from '../components/ui/States';

const NAV: { path: string; label: string; icon: IconName }[] = [
  { path: '/', label: '研究总览', icon: 'home' }, { path: '/datasets', label: '数据集中心', icon: 'database' },
  { path: '/lab', label: '模型实验室', icon: 'flask' }, { path: '/monitor', label: '实时监控', icon: 'monitor' },
  { path: '/comparison', label: '模型对比', icon: 'compare' }, { path: '/features', label: '特征分析', icon: 'features' },
  { path: '/predict', label: '单样本预测', icon: 'target' }, { path: '/experiments', label: '实验历史', icon: 'history' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];
const RESEARCH = [{ path: '/research', label: '原研究总览' }, { path: '/dataset', label: 'RNA-Seq 数据探索' },
  { path: '/research/features', label: '原特征选择与稳定性' }, { path: '/models', label: 'M0–M5 回顾性评价' },
  { path: '/fusion', label: '特征融合与消融' }, { path: '/legacy/lab', label: '原冻结模型实验室' }, { path: '/about', label: '关于项目' }];

export function AppShell() {
  const { settings, update } = usePreferences();
  const location = useLocation(), navigate = useNavigate();
  const [drawer, setDrawer] = useState(false), [searchOpen, setSearchOpen] = useState(false), [query, setQuery] = useState('');
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const health = useLiveResource<Envelope<HealthData>>('/api/v1/health', { interval: 15000 });
  const tasks = useLiveResource<{ items: Task[] }>('/api/v1/experiments', { interval: settings.pollSeconds * 1000 });
  const datasets = useLiveResource<{ items: Dataset[] }>(searchOpen ? '/api/v1/datasets' : null);
  const models = useLiveResource<{ items: Model[] }>(searchOpen ? '/api/v1/models' : null);
  const running = tasks.data?.items.filter(t => !terminal(t.status)) ?? [];
  const active = location.pathname.startsWith('/monitor/') ? '/monitor' : [...NAV, ...RESEARCH].sort((a, b) => b.path.length - a.path.length).find(n => n.path === location.pathname)?.path ?? '/';
  const current = [...NAV, ...RESEARCH].find(n => n.path === active)?.label ?? '研究页面';
  useEffect(() => { if (RESEARCH.some(r => r.path === location.pathname)) setOpenKeys(['research']); }, [location.pathname]);
  useEffect(() => {
    const shortcuts = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearchOpen(v => !v); } };
    document.addEventListener('keydown', shortcuts); return () => document.removeEventListener('keydown', shortcuts);
  }, []);
  const links = [
    ...NAV.map(n => ({ title: n.label, detail: '平台功能', path: n.path })),
    ...(datasets.data?.items ?? []).map(d => ({ title: d.name, detail: `${d.platform} / ${d.task_definition}`, path: `/datasets?dataset=${d.dataset_id}` })),
    ...(tasks.data?.items ?? []).slice(0, 30).map(t => ({ title: `${t.dataset_id} / ${t.task_id.slice(0, 12)}`, detail: `${t.experiment_config.algorithms?.map(a => names[a]).join(' / ')} ${t.task_id}`, path: `/monitor/${t.task_id}` })),
    ...(models.data?.items ?? []).map(m => ({ title: `${names[m.algorithm]} / ${m.model_version}`, detail: m.dataset_id, path: `/predict?dataset=${m.dataset_id}&model=${m.model_id}` })),
  ].filter(item => `${item.title} ${item.detail}`.toLowerCase().includes(query.toLowerCase())).slice(0, 16);

  function navigation(mobile = false) {
    const compact = settings.collapsed && !mobile;
    return <Menu className="bio-navigation" selectedKeys={[active]} openKeys={compact ? [] : openKeys} onClickSubMenu={(_, keys) => setOpenKeys(keys)} onClickMenuItem={key => { navigate(key); setDrawer(false); }}>
      {NAV.map(item => <Menu.Item key={item.path}><Tooltip content={item.label} disabled={!compact} position="right"><span className="nav-item-content"><Icon name={item.icon} size={19} /><span className="nav-label">{item.label}</span>{item.path === '/monitor' && running.length > 0 && <span className="nav-task-count">{running.length}</span>}</span></Tooltip></Menu.Item>)}
      <Menu.SubMenu key="research" title={<span className="nav-item-content"><Icon name="dna" size={19} /><span className="nav-label">原研究档案</span></span>}>{RESEARCH.map(r => <Menu.Item key={r.path}>{r.label}</Menu.Item>)}</Menu.SubMenu>
    </Menu>;
  }

  return <div className={`app-shell bio-shell ${settings.theme === 'dark' ? 'theme-dark' : ''} ${settings.collapsed ? 'sidebar-collapsed' : ''}`}>
    <aside className="bio-sidebar"><Link to="/" className="bio-brand" aria-label="GeneScope首页"><span className="brand-dna"><Icon name="dna" size={32} /></span><span className="brand-text">GeneScope <b>2.0</b><small>生物信息学实验平台</small></span></Link>
      <div className="nav-section-label">科研工作台</div>{navigation()}<div className="sidebar-science"><SidebarDNA /><span>从表达数据，探索生物学洞察</span></div>
      <Button className="collapse-button" type="text" onClick={() => update({ collapsed: !settings.collapsed })} aria-label={settings.collapsed ? '展开侧边栏' : '收起侧边栏'} icon={<Icon name="collapse" size={18} />}><span className="nav-label">收起导航</span></Button>
    </aside>
    <div className="bio-main-frame"><header className="bio-topbar"><Button type="text" className="mobile-menu-button" aria-label="打开导航" onClick={() => setDrawer(true)} icon={<Icon name="menu" />} /><div className="topbar-context"><span>基因表达分析与模型实验</span><i /><strong>{current}</strong></div><HeaderDNA />
      <div className="topbar-right"><button type="button" className="global-search-trigger" onClick={() => setSearchOpen(true)} aria-label="全局搜索"><Icon name="search" size={16} /><span>搜索数据集、实验、模型...</span><kbd>Ctrl K</kbd></button>
        <Tag className="service-tag" color={health.data?.data.api === 'ok' ? 'green' : health.error ? 'red' : 'orange'}><span className="connection-dot" />{health.data?.data.api === 'ok' ? 'API 在线' : health.error ? '连接异常' : '连接中'}</Tag>
        <Tooltip content="实验任务"><Badge count={running.length} dot><Button type="text" shape="circle" aria-label="查看实验任务" icon={<Icon name="bell" size={20} />} onClick={() => navigate('/monitor')} /></Badge></Tooltip><Tooltip content="系统设置"><Button type="text" shape="circle" className="profile-button" aria-label="打开系统设置" icon={<Icon name="user" size={18} />} onClick={() => navigate('/settings')} /></Tooltip></div>
    </header><main className="bio-page-content"><PageTransition key={location.pathname}><Outlet /></PageTransition></main><footer className="bio-footer"><span><Icon name="dna" size={14} /> GeneScope 2.0 · 生物信息学交互式实验平台</span><span>真实数据 · 可复现实验 <i /> 科研与教学用途</span></footer></div>
    <Drawer title="GeneScope 2.0" visible={drawer} onCancel={() => setDrawer(false)} placement="left" width={270} footer={null} className="bio-nav-drawer">{navigation(true)}</Drawer>
    <Modal title={<span className="modal-title-icon"><Icon name="search" /> 全局搜索</span>} visible={searchOpen} footer={null} onCancel={() => setSearchOpen(false)} style={{ width: 'min(650px, 94vw)' }} autoFocus>
      <Input autoFocus placeholder="输入数据集、任务ID、模型或功能名称" aria-label="搜索平台内容" value={query} onChange={setQuery} allowClear />
      <div className="search-results">{links.length ? links.map(item => <button key={`${item.path}_${item.title}`} onClick={() => { navigate(item.path); setSearchOpen(false); setQuery(''); }}><span><strong>{item.title}</strong><small>{item.detail}</small></span><Icon name="arrow" size={16} /></button>) : <EmptyState title="没有匹配项" description="尝试数据集名称、完整任务ID或功能名称" />}</div>
    </Modal>
  </div>;
}
