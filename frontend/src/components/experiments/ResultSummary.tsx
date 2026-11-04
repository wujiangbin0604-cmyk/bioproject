import { Table, Tag } from '@arco-design/web-react';
import type { Result, Results } from '../../api/platform';
import { names, number } from '../../api/platform';
import { datasetNames } from '../../utils/platform';
export function ResultSummary({ output }: { output: Results }) {
  return <div className="result-summary"><div className="result-source"><Tag color="arcoblue">{datasetNames[output.dataset_id]}</Tag><span>{output.task_definition}</span><small>版本 {output.dataset_version}</small></div><Table<Result> rowKey="algorithm" pagination={false} scroll={{ x: 760 }} data={output.results} columns={[{ title: '模型', dataIndex: 'algorithm', render: a => names[a] }, ...['macro_f1', 'balanced_accuracy', 'accuracy'].map(key => ({ title: key === 'macro_f1' ? 'Macro-F1' : key === 'accuracy' ? 'Accuracy' : 'Balanced Accuracy', render: (_: unknown, r: Result) => `${number(r.metrics[key].mean)} ± ${number(r.metrics[key].std)}` })), { title: '特征数', dataIndex: 'n_features' }, { title: 'CV耗时(s)', render: (_, r) => number(r.fit_seconds, 2) }]} /><p className="small-note">{output.split_protocol}。均值 ± 折间样本标准差；重复CV仅作描述性统计。</p></div>;
}
