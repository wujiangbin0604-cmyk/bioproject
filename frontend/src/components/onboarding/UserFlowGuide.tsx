import { useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { readStored, usePreferences, writeStored } from '../../hooks/usePreferences';
import { Icon } from '../ui/Icon';
import { FlowStep } from './FlowStep';
import { FlowHighlightCard } from './FlowHighlightCard';
import { FlowArrow } from './FlowArrow';
import { WelcomeGuideModal } from './WelcomeGuideModal';
import './user-flow-guide.less';

const WELCOME_SEEN_KEY = 'genescope-welcome-guide-v1';
const FEATURE_TAGS = ['多数据集', '模型实验', '特征分析'];
const revealStyle = (step: number): CSSProperties => ({ '--ufg-delay': `${step * 70}ms` } as CSSProperties);

export interface UserFlowGuideProps {
  title?: string;
  autoOpenOnFirstVisit?: boolean;
  className?: string;
}

export function UserFlowGuide({ title = '一、推荐的用户进入流程', autoOpenOnFirstVisit = true, className = '' }: UserFlowGuideProps) {
  const headingId = useId(), rootRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const { reduced } = usePreferences();
  const canObserve = typeof IntersectionObserver !== 'undefined';
  const [welcomeOpen, setWelcomeOpen] = useState(() => autoOpenOnFirstVisit && readStored<unknown>(WELCOME_SEEN_KEY, false) !== true);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || reduced || !canObserve) return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.setAttribute('data-revealed', 'true');
        observer.unobserve(entry.target);
      }
    }, { threshold: .12 });
    root.querySelectorAll('[data-flow-reveal]').forEach(step => observer.observe(step));
    return () => observer.disconnect();
  }, [reduced, canObserve]);

  function closeWelcome() {
    writeStored(WELCOME_SEEN_KEY, true);
    setWelcomeOpen(false);
  }

  return <section ref={rootRef} className={`user-flow-guide ${className}`} aria-labelledby={headingId} data-reveal={canObserve && !reduced ? 'enabled' : 'disabled'}>
    <header className="ufg-heading"><div><h2 id={headingId}><Icon name="target" size={24} />{title}</h2><p>第一次来到这里？从欢迎引导开始，循序体验平台。</p></div><span className="ufg-newcomer-label">新手推荐</span></header>
    <ol className="ufg-timeline" aria-label="推荐的平台使用步骤">
      <li data-flow-reveal style={revealStyle(0)}><FlowStep number={1} icon="home" title="进入 GeneScope 2.0 平台" description="首次访问时显示欢迎引导" /><FlowArrow /></li>
      <li data-flow-reveal style={revealStyle(1)}><FlowHighlightCard title="欢迎来到 GeneScope 2.0！" description="从基因表达分析开始，体验生物信息学如何帮助发现关键特征。" tags={FEATURE_TAGS} onLearn={trigger => { returnFocusRef.current = trigger; setWelcomeOpen(true); }} /><FlowArrow /></li>
      <li data-flow-reveal style={revealStyle(2)}><FlowStep number={3} icon="game" tone="mint" title="进入基因猎手小游戏" description="新手教学 → 热图观察 → 点击关键基因 → 结算与排名" to="/games/gene-hunter" /><FlowArrow /></li>
      <li data-flow-reveal style={revealStyle(3)}><FlowStep number={4} icon="flask" tone="purple" title="探索 GeneScope 其他科研功能" description="数据集管理、模型实验、实时监控、结果对比、特征分析" to="/datasets" /></li>
    </ol>
    <WelcomeGuideModal visible={welcomeOpen} onClose={closeWelcome} afterClose={() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus({ preventScroll: true });
    }} />
  </section>;
}
