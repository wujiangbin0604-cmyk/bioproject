import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spin } from '@arco-design/web-react';
import { AppShell } from './layouts/AppShell';

const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })));
const DatasetPage = lazy(() => import('./pages/DatasetPage').then((module) => ({ default: module.DatasetPage })));
const FeaturesPage = lazy(() => import('./pages/FeaturesPage').then((module) => ({ default: module.FeaturesPage })));
const ModelsPage = lazy(() => import('./pages/ModelsPage').then((module) => ({ default: module.ModelsPage })));
const FusionPage = lazy(() => import('./pages/FusionPage').then((module) => ({ default: module.FusionPage })));
const PredictionPage = lazy(() => import('./pages/PredictionPage').then((module) => ({ default: module.PredictionPage })));
const AboutPage = lazy(() => import('./pages/AboutPage').then((module) => ({ default: module.AboutPage })));
const LabPage = lazy(() => import('./pages/LabPage').then((module) => ({ default: module.LabPage })));
const Overview = lazy(() => import('./pages/workspace/OverviewPage'));
const Datasets = lazy(() => import('./pages/workspace/DatasetsPage'));
const ModelLab = lazy(() => import('./pages/workspace/ModelLabPage'));
const Monitor = lazy(() => import('./pages/workspace/MonitoringPage'));
const MonitorCenter = lazy(() => import('./pages/workspace/MonitoringPage').then(m => ({ default: m.MonitoringCenterPage })));
const Comparison = lazy(() => import('./pages/workspace/ComparisonPage'));
const Experiments = lazy(() => import('./pages/workspace/ExperimentsPage'));
const FeatureAnalysis = lazy(() => import('./pages/workspace/FeaturesPage'));
const RegisteredPrediction = lazy(() => import('./pages/workspace/PredictionPage'));
const Settings = lazy(() => import('./pages/workspace/SettingsPage'));

function PageLoader() {
  return <div className="remote-state"><Spin tip="正在载入研究页面…" /></div>;
}

export default function App() {
  return <Routes><Route element={<AppShell />}>
    <Route path="/" element={<Suspense fallback={<PageLoader />}><Overview /></Suspense>} />
    <Route path="/research" element={<Suspense fallback={<PageLoader />}><DashboardPage /></Suspense>} />
    <Route path="/datasets" element={<Suspense fallback={<PageLoader />}><Datasets /></Suspense>} />
    <Route path="/monitor/:taskId" element={<Suspense fallback={<PageLoader />}><Monitor /></Suspense>} />
    <Route path="/monitor" element={<Suspense fallback={<PageLoader />}><MonitorCenter /></Suspense>} />
    <Route path="/settings" element={<Suspense fallback={<PageLoader />}><Settings /></Suspense>} />
    <Route path="/comparison" element={<Suspense fallback={<PageLoader />}><Comparison /></Suspense>} />
    <Route path="/experiments" element={<Suspense fallback={<PageLoader />}><Experiments /></Suspense>} />
    <Route path="/dataset" element={<Suspense fallback={<PageLoader />}><DatasetPage /></Suspense>} />
    <Route path="/features" element={<Suspense fallback={<PageLoader />}><FeatureAnalysis /></Suspense>} />
    <Route path="/research/features" element={<Suspense fallback={<PageLoader />}><FeaturesPage /></Suspense>} />
    <Route path="/models" element={<Suspense fallback={<PageLoader />}><ModelsPage /></Suspense>} />
    <Route path="/fusion" element={<Suspense fallback={<PageLoader />}><FusionPage /></Suspense>} />
    <Route path="/predict" element={<Suspense fallback={<PageLoader />}><RegisteredPrediction /></Suspense>} />
    <Route path="/legacy/predict" element={<Suspense fallback={<PageLoader />}><PredictionPage /></Suspense>} />
    <Route path="/about" element={<Suspense fallback={<PageLoader />}><AboutPage /></Suspense>} />
    <Route path="/lab" element={<Suspense fallback={<PageLoader />}><ModelLab /></Suspense>} />
    <Route path="/legacy/lab" element={<Suspense fallback={<PageLoader />}><LabPage /></Suspense>} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes>;
}
