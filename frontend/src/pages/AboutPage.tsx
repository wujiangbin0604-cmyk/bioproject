import { Alert, Card, Grid, Table, Tag } from '@arco-design/web-react';
import { PageHeading } from '../components/PageHeading';

const apiRows = [
  { path: 'GET /api/v1/health', purpose: '服务与冻结模型环境状态' },
  { path: 'GET /api/v1/project/meta', purpose: '项目、数据集與类别元数据' },
  { path: 'GET /api/v1/experiments/status', purpose: '已保存结果存在性及完整性摘要' },
  { path: 'GET /api/v1/dataset/summary', purpose: '数据质量、类别计数及划分摘要' },
  { path: 'GET /api/v1/features/*', purpose: '特征性能、稳定性和入选频率' },
  { path: 'GET /api/v1/models/*', purpose: '模型指标、逐类别表现、混淆矩阵和聚合错误' },
  { path: 'GET /api/v1/fusion/summary', purpose: '特征融合、投票与动态仲裁汇总' },
  { path: 'POST /api/v1/predict', purpose: '原有冻结M1 Pipeline单样本推理' },
];

export function AboutPage() {
  return <div className="page-stack">
    <PageHeading eyebrow="ABOUT GENESCOPE" title="关于项目" description="GeneScope 将既有生物信息学实验结果与冻结推理入口整理为一个可复现、只读的研究展示平台。" />
    <div className="about-hero"><div className="eyebrow">PROJECT SCOPE</div><h2>从高维表达矩阵到可审阅的实验结果</h2><p>平台只适配项目已经保存的汇总结果，不在页面请求中训练模型、重新选择特征或重算保留集分数。单样本推理通过原项目deployment接口执行。</p><div className="about-tags"><Tag color="arcoblue">UCI Dataset 401</Tag><Tag color="green">sklearn Pipeline</Tag><Tag color="purple">FastAPI + React</Tag></div></div>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title="研究范围与限制"><div className="prose-list">
        <p>样本是五类已患癌肿瘤组织，用于表达类别分类；不含健康对照，不能评价是否患癌。</p>
        <p>没有纵向随访或治疗数据，不能评价疾病进展、复发、治疗反应或临床监测。</p>
        <p>161例保留集来自同一数据源，不等于跨医院、跨平台外部验证。早期探索曾使用全体样本做描述性可视化，因此该保留集应按回顾性评价解释。</p>
        <p>基因名为 gene_0 等匿名列标识，不能据此宣称发现致癌基因或临床标志物。</p>
      </div></Card></Grid.Col>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title="结果接入与数据边界"><div className="prose-list">
        <p>API根据 <code>results/latest_*.json</code> 中已完成的运行指针读取白名单内的CSV/JSON汇总。</p>
        <p>适配层拒绝路径穿越，默认不读取完整表达矩阵，不返回患者级预测表或测试样本ID。</p>
        <p>每个页面展示结果来源、数据范围和相关性说明；结果缺失时返回 unavailable 并呈现空状态。</p>
        <p>预测CSV仅在内存中解析；环境版本、模型摘要或Pipeline结构不符合冻结契约时，预测接口明确返回不可用。</p>
      </div></Card></Grid.Col>
    </Grid.Row>
    <Card className="panel-card" bordered={false} title="API 路由">
      <Table rowKey="path" columns={[{ title: '路由', dataIndex: 'path', render: (value: string) => <code>{value}</code> }, { title: '用途', dataIndex: 'purpose' }]} data={apiRows} pagination={false} />
    </Card>
    <Alert type="info" title="再现性与数据泄漏" content="正式CV中的方差筛选、ANOVA和标准化均在训练折内部拟合。全开发集的探索性热图/筛选名单不作为后续CV固定特征集。重复交叉验证折之间存在相关性，不按独立实验进行常规显著性推断。" />
    <div className="license-note">前端使用 Arco Design Pro React Vite 模板的设计与工程参考，并保留其 MIT 许可证声明；项目原有许可状态不由本平台更改。</div>
  </div>;
}
