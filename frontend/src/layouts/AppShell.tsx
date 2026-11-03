import { useEffect, useState } from 'react';
import { Button, Drawer, Menu, Switch, Tag } from '@arco-design/web-react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useApi } from '../hooks';
import type { HealthData } from '../types/api';

const NAV = [
  { path: '/', label: '研究总览', marker: '01' },
  { path: '/lab', label: '交互式模型实验室', marker: 'LAB' },
  { path: '/datasets', label: '数据集中心', marker: '▦' },
  { path: '/experiments', label: '实验历史', marker: '◷' },
  { path: '/comparison', label: '实验模型对比', marker: '▤' },
  { path: '/dataset', label: 'RNA-Seq 数据探索', marker: '02' },
  { path: '/features', label: '特征选择与稳定性', marker: '03' },
  { path: '/models', label: '模型性能对比', marker: '04' },
  { path: '/fusion', label: '特征融合与消融', marker: '05' },
  { path: '/predict', label: '单样本预测', marker: '06' },
  { path: '/about', label: '关于项目', marker: '07' },
];

const PAGE_NAMES = Object.fromEntries(NAV.map((item) => [item.path, item.label]));

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [dark, setDark] = useState(() => localStorage.getItem('genescope-theme') === 'dark');
  const [drawer, setDrawer] = useState(false);
  const health = useApi<HealthData>('/api/v1/health');
  const activePath = location.pathname.startsWith('/monitor/') ? '/lab' : NAV.find((item) => item.path !== '/' && location.pathname.startsWith(item.path))?.path ?? '/';
  const pageName = location.pathname.startsWith('/monitor/') ? '实时任务监控' : PAGE_NAMES[activePath] ?? '研究页面';

  useEffect(() => {
    document.documentElement.classList.toggle('arco-theme-dark', dark);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.body.setAttribute('arco-theme', dark ? 'dark' : 'light');
    localStorage.setItem('genescope-theme', dark ? 'dark' : 'light');
  }, [dark]);

  function navigation() {
    return <Menu selectedKeys={[activePath]} className="side-menu" onClickMenuItem={(key) => { navigate(key); setDrawer(false); }}>
      {NAV.map((item) => <Menu.Item key={item.path}>
        <span className="menu-marker">{item.marker}</span><span>{item.label}</span>
      </Menu.Item>)}
    </Menu>;
  }

  return <div className={`app-shell ${dark ? 'theme-dark' : ''}`}>
    <aside className="desktop-sidebar">
      <div className="brand-lockup"><div className="brand-glyph"><i /><i /><i /><i /></div><div><strong>GeneScope 2.0</strong><small>生物信息学实验平台</small></div></div>
      <div className="side-caption">研究导航</div>
      {navigation()}
      <div className="sidebar-footer"><span className="footer-pulse" /> <span>历史结果 · 现场实验</span></div>
    </aside>

    <div className="main-frame">
      <header className="topbar">
        <Button className="mobile-menu-button" type="text" aria-label="打开导航" onClick={() => setDrawer(true)}>☰</Button>
        <div className="breadcrumb"><span>GeneScope</span><b>/</b><strong>{pageName}</strong></div>
        <div className="topbar-actions">
          <a className="github-link" href="https://github.com/wujiangbin0604-cmyk/bioproject" target="_blank" rel="noreferrer">GitHub 仓库 ↗</a>
          <Tag color={health.envelope?.data.api === 'ok' ? 'green' : health.error ? 'red' : 'orange'} className="service-tag">
            <span className="status-dot" />{health.loading ? '服务检查中' : health.envelope?.data.api === 'ok' ? 'API 在线' : 'API 未连接'}
          </Tag>
          <div className="theme-control"><span>{dark ? '深色' : '浅色'}</span><Switch size="small" checked={dark} onChange={setDark} aria-label="切换深色主题" /></div>
        </div>
      </header>
      <main className="page-content"><Outlet /></main>
      <footer className="app-footer"><span>GeneScope · 生物信息学交互式机器学习实验平台</span><span>科研与课程演示用途</span></footer>
    </div>

    <Drawer className="nav-drawer" title="GeneScope 导航" visible={drawer} placement="left" onCancel={() => setDrawer(false)} footer={null} width={280}>
      {navigation()}
    </Drawer>
  </div>;
}
