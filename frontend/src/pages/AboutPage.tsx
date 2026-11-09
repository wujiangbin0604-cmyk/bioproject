import { Card, Grid, Table, Tag } from '@arco-design/web-react';
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
    <PageHeading eyebrow="ABOUT GENESCOPE" title="关于项目" description="GeneScope 将生物信息学实验结果与模型推理入口整理为一个可复现的研究分析平台。" />
    <div className="about-hero"><div className="eyebrow">PROJECT SCOPE</div><h2>从高维表达矩阵到可审阅的实验结果</h2><p>平台汇集数据探索、特征选择、模型实验与结果分析，单样本推理通过项目 deployment 接口执行。</p><div className="about-tags"><Tag color="arcoblue">UCI Dataset 401</Tag><Tag color="green">sklearn Pipeline</Tag><Tag color="purple">FastAPI + React</Tag></div></div>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title="研究数据"><div className="prose-list">
        <p>样本覆盖五类肿瘤组织的基因表达类别。</p>
        <p>数据来自 UCI Dataset 401。</p>
        <p>数据按固定方案划分为开发集与161例保留集。</p>
        <p>基因使用 gene_0 等原始匿名列标识。</p>
      </div></Card></Grid.Col>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title="结果与数据接入"><div className="prose-list">
        <p>API根据 <code>results/latest_*.json</code> 中的运行指针读取CSV/JSON汇总。</p>
        <p>分析页面展示分类指标、特征排名、热图与混淆矩阵。</p>
        <p>实验记录包含数据集版本、模型配置和结果来源。</p>
        <p>单样本预测支持CSV输入，按列名匹配模型特征。</p>
      </div></Card></Grid.Col>
    </Grid.Row>
    <Card className="panel-card" bordered={false} title="API 路由">
      <Table rowKey="path" columns={[{ title: '路由', dataIndex: 'path', render: (value: string) => <code>{value}</code> }, { title: '用途', dataIndex: 'purpose' }]} data={apiRows} pagination={false} />
    </Card>
    <div className="license-note">前端使用 Arco Design Pro React Vite 模板的设计与工程参考，并保留其 MIT 许可证声明。</div>
  </div>;
}
