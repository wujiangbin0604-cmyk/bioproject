import { Icon } from '../../components/ui/Icon';
import { comboMultiplier } from './gameEngine';

export function ComboBadge({ combo }: { combo: number }) {
  return <div className={`gh-combo ${combo >= 2 ? 'gh-combo-active' : ''}`} key={combo}>
    <span className="gh-stat-icon"><Icon name="flame" size={26} /></span>
    <div><span>Combo 连击</span><strong data-testid="combo">{combo}<small>连击</small></strong></div>
    <b className="gh-multiplier">×{comboMultiplier(combo).toFixed(1)}</b>
  </div>;
}
