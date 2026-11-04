import { Icon } from '../ui/Icon';
import { names } from '../../api/platform';
const descriptions: Record<string, string> = { linear_svc: '线性决策边界，适合高维表达特征', logistic_regression: '线性分类对照，使用正则化控制复杂度', random_forest: '多棵决策树集成，捕捉非线性关系', rbf_svm: 'RBF 核映射，学习非线性分类边界' };
export function ModelSelectionCard({ algorithm, selected, onSelect }: { algorithm: string; selected: boolean; onSelect: () => void }) {
  return <button type="button" className={`model-selection-card ${selected ? 'is-selected' : ''}`} onClick={onSelect} aria-pressed={selected} aria-label={`选择模型 ${names[algorithm]}`}><span className="model-card-symbol"><Icon name={algorithm === 'random_forest' ? 'features' : algorithm === 'rbf_svm' ? 'target' : 'flask'} size={28} /></span><strong>{names[algorithm]}</strong><small>{descriptions[algorithm]}</small><span className="model-card-check">{selected && <Icon name="check" size={12} />}</span><span className="model-card-params">{algorithm === 'random_forest' ? '参数：树数量 / 最大深度' : algorithm === 'rbf_svm' ? '参数：C / gamma' : '参数：C'}</span></button>;
}
