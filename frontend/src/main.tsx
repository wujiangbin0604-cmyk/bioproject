import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider } from '@arco-design/web-react';
import zhCN from '@arco-design/web-react/es/locale/zh-CN';
import App from './App';
import '@arco-design/web-react/dist/css/arco.css';
import './styles/global.less';
import './styles/bio-theme.less';
import './styles/visual-refinement.less';
import './styles/research-dashboard.less';
import { PreferencesProvider } from './hooks/usePreferences';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ConfigProvider locale={zhCN}><PreferencesProvider><BrowserRouter><App /></BrowserRouter></PreferencesProvider></ConfigProvider></React.StrictMode>,
);
