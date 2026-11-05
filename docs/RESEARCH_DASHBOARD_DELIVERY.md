# GeneScope 2.0 医疗科研仪表盘升级

## 首页与布局

- 全宽白色顶部导航：平台标识、平台名称与副标题、实际 API 健康状态、共享数据集选择、动效开关、搜索、实验任务、研究员菜单。
- 固定左侧导航按分析工作台、科研与教学、系统分组；支持展开、收起、选中高亮、图标提示、移动抽屉。保留单样本预测、实验历史及原研究档案。
- 页面采用浅灰蓝底、实色白卡、14px 圆角、细边框及轻阴影；蓝、青、紫为主色。取消漂浮背景，大幅弱化 DNA 装饰。
- 首页顺序为标题与创建实验 → 基因猎手挑战卡 → 四项统计 → 左侧宽幅性能表 / 右侧类别与划分 → 数据特征探索 / 最近实验 → 六步研究流程。
- 新增 `/gallery` 科研可视化图库与 `/presentation` 课程答辩演示。已有学习引导与欢迎说明在演示页保留。

## 数据与交互

- 统计、类别、热图、任务、模型及模型指标均读取现有 API，不生成随机科研数据。
- 顶部数据集选择联动首页类别、样本/特征数、实验性能、划分、热图与最近记录，并保存到浏览器；图库复用该选择。
- 共享数据集、任务和模型列表，避免顶部与首页重复轮询。沿用按请求键隔离结果的 Hook，切换时不将旧数据贴上新数据集标签。
- 模型表提供 LinearSVC、Logistic Regression、Random Forest、RBF SVM 的最近已完成记录；未完成算法保留空值。支持指标表 / Macro-F1 图切换及查看来源实验。
- Accuracy 与 Macro-F1 为保存的 CV 折均值；Precision / Recall 为已有 OOF 逐类报告的宏平均，不混称为折均值。表内注明口径，悬停实验可查看配置。
- PANCAN 划分图显示原研究全队列 640 / 161 固定开发/保留划分，并与当前 640 例开发数据统计区分。其他数据集读取实际实验折的 Train / Validation 样本数，没有记录时显示空态，没有独立 Test 时明确说明。
- 环图有悬停提示，点击类别名称切换图例；划分图支持原生图例切换。相同类别在各图中使用相同颜色。
- 下方探索区支持实际类别样本数、Top-K 实验性能、真实表达热图。表格窄屏可在卡片内部横向滚动。
- 科研热图使用已有真实表达摘要；挑战入口的小热图仅为装饰。基因猎手继续使用明确标注的合成教学数据。

## 修改文件清单

### 布局、入口与状态

| 文件 | 变更 |
| --- | --- |
| `frontend/index.html` | 平台标题、描述、主题色与 DNA favicon |
| `frontend/src/main.tsx` | 引入科研仪表盘样式 |
| `frontend/src/App.tsx` | 共享工作台 Provider 与图库、演示路由 |
| `frontend/src/layouts/AppShell.tsx` | 顶栏、侧栏、抽屉、用户菜单与可访问图标导航 |
| `frontend/src/hooks/useWorkspace.tsx` | 共享列表资源与当前数据集选择 |
| `frontend/src/api/platform.ts` | 为已有折记录补充可选训练/验证样本类型 |
| `frontend/src/styles/research-dashboard.less` | 全站浅色科研视觉、首页布局与响应式 |

### 首页与图表

| 文件 | 变更 |
| --- | --- |
| `frontend/src/pages/workspace/OverviewPage.tsx` | API 驱动的首页信息组织 |
| `frontend/src/components/dashboard/DashboardCards.tsx` | 挑战入口、统计卡、六步流程 |
| `frontend/src/components/dashboard/DistributionCards.tsx` | 环图、类别表与真实划分 |
| `frontend/src/components/dashboard/PerformanceTable.tsx` | 性能表、进度条、Macro-F1 图 |
| `frontend/src/components/dashboard/ExplorationCard.tsx` | 类别 / Top-K / 热图切换 |
| `frontend/src/components/dashboard/RecentExperimentsTable.tsx` | 当前数据集最近实验表 |
| `frontend/src/utils/dashboard.ts` | 指标格式、宏平均与类别配色 |

### 教学、图库与小修复

| 文件 | 变更 |
| --- | --- |
| `frontend/src/pages/workspace/ResearchResourcesPage.tsx` | 图库与课程演示页面 |
| `frontend/src/components/onboarding/WelcomeGuideModal.tsx` | 更新学习引导入口说明 |
| `frontend/src/pages/workspace/FeaturesPage.tsx` | 修正 Tag 所在段落的无效 DOM 嵌套 |
| `frontend/src/pages/workspace/SettingsPage.tsx` | 修正 Tag 所在段落的无效 DOM 嵌套 |

### 验证

| 文件 | 用途 |
| --- | --- |
| `frontend/tests/dashboard.test.mjs` | 实际指标宏平均、缺失值与零值、配色一致性 |
| `frontend/tests/dashboard_browser.py` | 真实本机 API、路由、响应式、切换、空态与错误态验收 |
| `docs/RESEARCH_DASHBOARD_DELIVERY.md` | 本交付说明 |

## 构建与测试结果

- `npm run build`：TypeScript 与 Vite 生产构建通过，生成 `frontend/dist`。
- `npm test`：26 / 26 通过，包含既有基因猎手、CSV、实验配置与任务阶段测试。
- `python frontend/tests/dashboard_browser.py --url http://127.0.0.1:5176`：通过。真实环境包含 4 个就绪数据集；验证 1920、1440、1024、390px 布局无整页或顶栏横向溢出、数据集切换与保存、图表 Tab、类别图例、动效开关、折叠导航、移动抽屉、挑战路由、10 个功能路由、断网空态与系统减少动态效果；页面错误 0、控制台错误 0。
- `python frontend/tests/gene_hunter_browser.py --url http://127.0.0.1:5176`：既有完整回归通过，覆盖五关、计分、连击、计时、重复点击、结算、历史保存、键盘、帮助、搜索、导航、手机热图滚动。
- `git diff --check`：通过。仓库另有 Windows 换行提示，不影响构建。
- 本次未重新训练模型或改写后台计算流程，业务页验证为路由与页面渲染回归。

验收文件：

- `reports/research-dashboard/browser-acceptance.json`
- `reports/research-dashboard/desktop-wide.png`
- `reports/research-dashboard/desktop.png`
- `reports/research-dashboard/tablet.png`
- `reports/research-dashboard/mobile.png`
- `reports/research-dashboard/offline-mobile.png`
- `reports/gene-hunter/browser-acceptance.json`

## 仍待完善项与边界

- Vite 仍提示主应用与 ECharts 分包超过 500 kB，可在后续专项优化依赖拆包；不影响本次构建或功能。
- 没有完成的实验、实际折计数或独立 Test 数据时，相关区域按真实可用性显示空态或明确说明。现有 API 没有暴露每个 CV 折的逐类 Train / Validation 计数，因此这部分仅展示真实总数，不估算类别比例。
- 顶栏用户菜单沿用本机单用户研究员工作台定位；未添加多用户账号后台。
- 原项目的深色偏好入口保留，默认与本次验收使用浅色科研风格。

本机预览前端：`http://127.0.0.1:5176`；后端：`http://127.0.0.1:8001`。生产部署需使用本次生成的前端成品，本次未发布到远程服务器。
