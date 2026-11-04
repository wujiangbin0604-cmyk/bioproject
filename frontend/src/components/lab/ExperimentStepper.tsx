import { Steps } from '@arco-design/web-react';
export function ExperimentStepper({ step, onChange }: { step: number; onChange?: (step: number) => void }) {
  return <div className="experiment-stepper"><Steps current={step + 1} size="small" onChange={onChange ? current => { if (current - 1 < step) onChange(current - 1); } : undefined}>{['选择数据集', '算法与特征', '参数与协议', '确认并启动'].map(title => <Steps.Step key={title} title={title} />)}</Steps></div>;
}
