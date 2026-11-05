import { Link } from 'react-router-dom';
import { Icon } from '../ui/Icon';
import type { IconName } from '../ui/Icon';

export interface FlowStepProps {
  number: number;
  title: string;
  description: string;
  icon: IconName;
  to?: string;
  tone?: 'blue' | 'mint' | 'purple';
}

export function FlowStep({ number, title, description, icon, to, tone = 'blue' }: FlowStepProps) {
  return <div className={`ufg-step ufg-tone-${tone}`}>
    <span className="ufg-step-icon"><Icon name={icon} size={23} /><span className="ufg-step-number" aria-label={`第 ${number} 步`}>{number}</span></span>
    <h3>{to ? <Link to={to}>{title}<Icon name="chevron" size={15} /></Link> : title}</h3>
    <p>{description}</p>
  </div>;
}
