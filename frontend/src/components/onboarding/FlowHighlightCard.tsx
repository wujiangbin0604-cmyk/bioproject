import { Tag } from '@arco-design/web-react';
import { GradientButton } from '../ui/GradientButton';
import { Icon } from '../ui/Icon';

export interface FlowHighlightCardProps {
  title: string;
  description: string;
  tags: readonly string[];
  onLearn: (trigger: HTMLButtonElement) => void;
}

export function FlowHighlightCard({ title, description, tags, onLearn }: FlowHighlightCardProps) {
  return <article className="ufg-highlight">
    <div className="ufg-highlight-decoration" aria-hidden="true"><Icon name="dna" size={100} /></div>
    <div className="ufg-welcome-mark"><Icon name="dna" size={31} /><span className="ufg-step-number" aria-label="第 2 步">2</span></div>
    <h3>{title}</h3>
    <p>{description}</p>
    <div className="ufg-tags" aria-label="平台功能">{tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</div>
    <GradientButton className="ufg-learn-button" size="large" onClick={event => {
      if (event.currentTarget instanceof HTMLButtonElement) onLearn(event.currentTarget);
    }}>了解欢迎引导设计<Icon name="arrow" size={17} /></GradientButton>
  </article>;
}
