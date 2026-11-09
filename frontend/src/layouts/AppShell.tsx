import { useEffect, useState } from 'react';
import { Badge, Button, Drawer, Dropdown, Input, Menu, Modal, Select, Tag, Tooltip } from '@arco-design/web-react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { names, terminal } from '../api/platform';
import type { HealthData, Envelope } from '../types/api';
import { useLiveResource } from '../hooks/useLiveResource';
import { usePreferences } from '../hooks/usePreferences';
import { useWorkspace } from '../hooks/useWorkspace';
import { Icon } from '../components/ui/Icon';
import type { IconName } from '../components/ui/Icon';
import { SidebarDNA } from '../components/visuals/AnimatedDNA';
import { PageTransition } from '../components/ui/PageTransition';
import { EmptyState } from '../components/ui/States';

const NAV: { path: string; label: string; icon: IconName }[] = [
  { path: '/', label: '项目总览', icon: 'grid' }, { path: '/datasets', label: '数据集中心', icon: 'database' },
  { path: '/lab', label: '模型实验室', icon: 'flask' }, { path: '/monitor', label: '实时监控', icon: 'monitor' },
  { path: '/comparison', label: '模型对比', icon: 'compare' }, { path: '/features', label: '特征分析', icon: 'features' },
  { path: '/predict', label: '单样本预测', icon: 'target' }, { path: '/experiments', label: '实验历史', icon: 'history' },
  { path: '/gallery', label: '科研可视化图库', icon: 'grid' }, { path: '/presentation', label: '课程答辩演示', icon: 'play' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];
const RESEARCH = [{ path: '/research', label: '原研究总览' }, { path: '/dataset', label: 'RNA-Seq 数据探索' },
  { path: '/research/features', label: '原特征选择与稳定性' }, { path: '/models', label: 'M0–M5 回顾性评价' },
  { path: '/fusion', label: '特征融合与消融' }, { path: '/legacy/lab', label: '原冻结模型实验室' }, { path: '/about', label: '关于项目' }];
const GAMES = [{ path: '/games/gene-hunter', label: '基因猎手：寻找关键特征' }];

export function AppShell() {
  const { settings, update } = usePreferences();
  const { tasks, datasets, models, datasetId, selectDataset } = useWorkspace();
  const location = useLocation(), navigate = useNavigate();
  const [drawer, setDrawer] = useState(false), [searchOpen, setSearchOpen] = useState(false), [query, setQuery] = useState('');
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const health = useLiveResource<Envelope<HealthData>>('/api/v1/health', { interval: 15000 });
  const running = tasks.data?.items.filter(t => !terminal(t.status)) ?? [];
  const active = location.pathname.startsWith('/monitor/') ? '/monitor' : [...NAV, ...RESEARCH, ...GAMES].find(n => n.path === location.pathname)?.path ?? '/';
  useEffect(() => {
    if (RESEARCH.some(r => r.path === location.pathname)) setOpenKeys(['research']);
    if (GAMES.some(r => r.path === location.pathname)) setOpenKeys(['games']);
  }, [location.pathname]);
  useEffect(() => {
    const shortcuts = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearchOpen(v => !v); } };
    document.addEventListener('keydown', shortcuts); return () => document.removeEventListener('keydown', shortcuts);
  }, []);
  const links = [
    ...NAV.map(n => ({ title: n.label, detail: '平台功能', path: n.path })),
    ...GAMES.map(n => ({ title: n.label, detail: '学习与游戏', path: n.path })),
    ...(datasets.data?.items ?? []).map(d => ({ title: d.name, detail: `${d.platform} / ${d.task_definition}`, path: `/datasets?dataset=${d.dataset_id}` })),
    ...(tasks.data?.items ?? []).slice(0, 30).map(t => ({ title: `${t.dataset_id} / ${t.task_id.slice(0, 12)}`, detail: `${t.experiment_config.algorithms?.map(a => names[a]).join(' / ')} ${t.task_id}`, path: `/monitor/${t.task_id}` })),
    ...(models.data?.items ?? []).map(m => ({ title: `${names[m.algorithm]} / ${m.model_version}`, detail: m.dataset_id, path: `/predict?dataset=${m.dataset_id}&model=${m.model_id}` })),
  ].filter(item => `${item.title} ${item.detail}`.toLowerCase().includes(query.toLowerCase())).slice(0, 16);

  function navigation(mobile = false) {
    const compact = settings.collapsed && !mobile;
    const item = (entry: typeof NAV[number]) => <Menu.Item key={entry.path} aria-label={entry.label}><Tooltip content={entry.label} disabled={!compact} position="right"><span className="nav-item-content"><Icon name={entry.icon} size={19} /><span className="nav-label">{entry.label}</span>{entry.path === '/monitor' && running.length > 0 && <span className="nav-task-count">{running.length}</span>}</span></Tooltip></Menu.Item>;
    return <Menu className="bio-navigation" selectedKeys={[active]} openKeys={compact ? [] : openKeys} onClickSubMenu={(_, keys) => setOpenKeys(keys)} onClickMenuItem={key => { navigate(key); setDrawer(false); }}>
      <Menu.ItemGroup title="分析工作台">{NAV.slice(0, 8).map(item)}</Menu.ItemGroup>
      <Menu.ItemGroup title="科研与教学">{NAV.slice(8, 10).map(item)}
        {compact ? item({ path: GAMES[0].path, label: GAMES[0].label, icon: 'game' }) : <Menu.SubMenu key="games" title={<span className="nav-item-content"><Icon name="game" size={19} /><span className="nav-label">学习与游戏</span></span>}>{GAMES.map(g => <Menu.Item key={g.path}><span className="game-nav-label">基因猎手：寻找关键特征</span></Menu.Item>)}</Menu.SubMenu>}
        {compact ? item({ path: '/research', label: '原研究档案', icon: 'dna' }) : <Menu.SubMenu key="research" title={<span className="nav-item-content"><Icon name="dna" size={19} /><span className="nav-label">原研究档案</span></span>}>{RESEARCH.map(r => <Menu.Item key={r.path}>{r.label}</Menu.Item>)}</Menu.SubMenu>}
      </Menu.ItemGroup>
      <Menu.ItemGroup title="系统">{item(NAV[NAV.length - 1])}</Menu.ItemGroup>
    </Menu>;
  }

  return <div className={`app-shell bio-shell research-shell ${settings.theme === 'dark' ? 'theme-dark' : ''} ${settings.collapsed ? 'sidebar-collapsed' : ''}`}>
    <header className="bio-topbar">
      <Button type="text" className="mobile-menu-button" aria-label="打开导航" onClick={() => setDrawer(true)} icon={<Icon name="menu" />} />
      <Link to="/" className="platform-brand" aria-label="GeneScope首页"><span className="brand-dna"><Icon name="dna" size={30} /></span><strong>GeneScope <b>2.0</b></strong></Link>
      <div className="platform-heading"><strong>GeneScope 生物信息学智能分析平台</strong><span>基于机器学习的多数据集分析与特征探索</span></div>
      <div className="topbar-right">
        <Tag className="service-tag" color={health.data?.data.api === 'ok' && !health.error ? 'green' : health.error ? 'red' : 'orange'}><span className="connection-dot" />{health.error ? '连接异常' : health.data?.data.api === 'ok' ? '系统运行正常' : '正在连接'}</Tag>
        <div className="header-dataset"><Icon name="database" size={15} /><Select aria-label="当前数据集" value={datasetId} loading={datasets.loading} onChange={selectDataset} placeholder="选择数据集" options={(datasets.data?.items ?? []).map(d => ({ value: d.dataset_id, label: `${d.dataset_id.toUpperCase()}${d.status === 'ready' ? '' : ' · 待导入'}` }))} /></div>
        <Tooltip content="切换页面与图表动效；同时遵循系统偏好"><button type="button" role="switch" aria-checked={settings.motion} aria-label="页面动效" className="motion-toggle" onClick={() => update({ motion: !settings.motion })}><span className="motion-switch"><i /></span><span>动效{settings.motion ? '开' : '关'}</span></button></Tooltip>
        <Tooltip content="全局搜索 · Ctrl K"><Button type="text" shape="circle" aria-label="全局搜索" onClick={() => setSearchOpen(true)} icon={<Icon name="search" size={19} />} /></Tooltip>
        <Tooltip content="实验任务"><Badge count={running.length} dot><Button type="text" shape="circle" aria-label="查看实验任务" icon={<Icon name="bell" size={19} />} onClick={() => navigate('/monitor')} /></Badge></Tooltip>
        <Dropdown trigger="click" droplist={<Menu onClickMenuItem={key => navigate(key)}><Menu.Item key="/settings">工作台偏好</Menu.Item><Menu.Item key="/experiments">我的实验</Menu.Item><Menu.Item key="/about">关于 GeneScope</Menu.Item></Menu>}><button className="user-menu-trigger" aria-label="用户菜单"><span className="profile-avatar"><Icon name="user" size={19} /></span><span>研究员</span><Icon name="chevron" size={12} /></button></Dropdown>
      </div>
    </header>
    <aside className="bio-sidebar"><nav aria-label="平台导航">{navigation()}</nav><div className="sidebar-science"><SidebarDNA /><span><Icon name="check" size={13} /> 可复现 · 可追溯 · 可探索</span></div>
      <Button className="collapse-button" type="text" onClick={() => update({ collapsed: !settings.collapsed })} aria-label={settings.collapsed ? '展开侧边栏' : '收起侧边栏'} icon={<Icon name="collapse" size={18} />}><span className="nav-label">收起导航</span></Button>
    </aside>
    <div className="bio-main-frame"><main className="bio-page-content"><PageTransition key={location.pathname}><Outlet /></PageTransition></main><footer className="bio-footer"><span><Icon name="dna" size={14} /> GeneScope 2.0 · 生物信息学智能分析平台</span><span>真实数据 · 可复现实验</span></footer></div>
    <Drawer title="GeneScope 2.0" visible={drawer} onCancel={() => setDrawer(false)} placement="left" width={270} footer={null} className="bio-nav-drawer">{navigation(true)}</Drawer>
    <Modal title={<span className="modal-title-icon"><Icon name="search" /> 全局搜索</span>} visible={searchOpen} footer={null} onCancel={() => setSearchOpen(false)} style={{ width: 'min(650px, 94vw)' }} autoFocus>
      <Input autoFocus placeholder="输入数据集、任务ID、模型或功能名称" aria-label="搜索平台内容" value={query} onChange={setQuery} allowClear />
      <div className="search-results">{links.length ? links.map(item => <button key={`${item.path}_${item.title}`} onClick={() => { navigate(item.path); setSearchOpen(false); setQuery(''); }}><span><strong>{item.title}</strong><small>{item.detail}</small></span><Icon name="arrow" size={16} /></button>) : <EmptyState title="没有匹配项" description="尝试数据集名称、完整任务ID或功能名称" />}</div>
    </Modal>
  </div>;
}
