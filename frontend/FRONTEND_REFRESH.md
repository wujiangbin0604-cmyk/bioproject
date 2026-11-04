# GeneScope 2.0 前端升级交付

默认浅色工作台，采用蓝、青、薄荷绿、淡紫配色。玻璃卡片、圆角、轻阴影和DNA装饰统一各页面。保留后端API、真实任务引擎、原研究路由、冻结模型及独立数据协议。

## 修改范围

| 文件或目录 | 实现内容 |
|---|---|
| `src/layouts/AppShell.tsx` | 浅色侧栏、可折叠导航、研究子菜单、手机Drawer、Ctrl+K真实内容搜索、API与任务状态 |
| `src/styles/bio-theme.less` | 颜色、间距、圆角、阴影、响应式与动效Token；兼容旧研究页面 |
| `src/animations` | 微交互180ms、页面280ms、卡片340ms、图表550ms、数值420ms |
| `src/pages/workspace` | 独立的总览、数据集、模型实验室、监控、对比、特征、预测、历史、设置页面 |
| `src/pages/PlatformPages.tsx` | 改为兼容导出，移除原单文件页面实现 |
| `src/components/ui` | GlassCard、AnimatedStat、GradientButton、ExperimentStatus、PageTransition、LoadingSkeleton、EmptyState、ErrorState、DatasetPicker、PageTitle、SVG图标 |
| `src/components/visuals` | AnimatedDNA、FloatingParticles、HeaderDNA、SidebarDNA、HeroDNA |
| `src/components/datasets` | InteractiveDatasetCard、真实计数、收藏及详情入口 |
| `src/components/lab` | ModelSelectionCard、ExperimentStepper、多模型配置 |
| `src/components/monitor` | TrainingProgress五阶段时间线、最近200条日志、过滤/复制/自动滚动 |
| `src/components/charts` | RealTimeChart、HeatmapExplorer、ConfusionMatrix、缩放与图像导出 |
| `src/components/experiments` | TaskTable、ResultSummary、排序/选择/导出与CV来源说明 |
| `src/components/prediction` | FileUploadArea、PredictionResultCard、真实上传进度 |
| `src/hooks` | 资源请求取消、数据归属、SSE节流/重连/轮询回退/清理、偏好及页面可见性 |
| `src/utils` | 实验配置校验、RFC4180单样本CSV校验、真实任务阶段推导、下载/复制 |
| `src/components/EChart.tsx` | 按需模块、稳定系列更新、ResizeObserver和减少动态效果 |
| `src/App.tsx`、`src/main.tsx` | 独立页面懒加载、偏好Provider、新主题及新增路由 |
| `tests/platform-utils.test.mjs` | 10项CSV、参数范围和科学状态边界测试 |
| `../backend/tests/frontend_refresh_*.py` | 真实浏览器路由、实验、预测、取消、断网及清理验收 |
| `../cloud_deployment/*frontend*.py` | 仅静态前端更新打包、逐文件校验、备份与回滚 |

## 已完成的交互和动效

- DNA使用SVG双链和5个CSS粒子，轻浮动、透明度变化和鼠标视差；进入视口才播放，页面隐藏或减少动态效果时暂停。
- 数值由真实API目标值驱动；卡片上浮、按钮按压、选择状态、Tabs和路由过渡均通过React/CSS实现。
- 总览展示实际数据集、实验和注册模型计数，切换真实CV表现、特征稳定性与类别分布。
- 数据集支持搜索、状态筛选、收藏持久化、卡片/表格、Drawer质量报告及热图；导入仍提交真实后台任务。
- 实验室使用四步配置，支持四个现有分类器、四类特征方法、离散K滑块/输入同步、高级参数及本地草稿。仅确认启动才提交真实任务。
- 监控读取真实折级事件，展示真实折指标、耗时、日志和取消状态；支持刷新恢复与导出。
- 对比页展示CV指标、特征数量、耗时、混淆矩阵、各类别F1及数据版本/共享划分来源。
- 特征页保留原始探针/基因ID，展示真实排名、频率、Jaccard、方法/K结果与表达热图；支持Top10/20、转置、缩放、全屏与图像导出。
- 预测以三步流程完成格式校验、同数据集模型特征核验、上传和真实推理；上传进度来自Axios传输事件。
- 设置可保存主题、动效、布局密度、侧栏及列表刷新周期。深色为可选，默认浅色。

## 实际验收

| 检查 | 结果 |
|---|---|
| TypeScript | `npm run typecheck`通过；生产构建再次执行`tsc -b`通过 |
| 生产构建 | `npm run build`通过；独立页面懒加载 |
| 前端纯函数测试 | `npm test`：10通过 |
| 后端及部署回归 | `pytest backend/tests`：105通过、1跳过；跳过项需本机Docker引擎 |
| 路由 | 18个新旧路由通过，浏览器`pageerror=[]` |
| 响应式 | 1440、1920、1024、390px检查，无页面水平溢出；表格在自身容器横滚 |
| 数据/导航 | 搜索、收藏持久化、详情热图、表格切换、Ctrl+K、侧栏折叠/恢复与图表重排通过 |
| 实际训练 | 浏览器创建GSE45827、ANOVA K20、LinearSVC、3折CV；任务`b70a58305ec54a2abee3df43952612ba`完成；刷新恢复通过 |
| 实际推理 | GEO测量样本GSM1116084，29,873输入特征，返回Basal/TN；重复列CSV被阻止 |
| 真实取消 | 任务`d6a007f5f0e04772bd437d2b571b3976`取消并保留已完成折 |
| 网络恢复 | 两次SSE传输失败后GET回退和自动重连通过；切页后EventSource关闭且不再轮询 |
| 数据切换/失败 | 切换数据集清除旧排名，API断连显示明确错误 |
| 减少动态效果 | 本地偏好和系统`prefers-reduced-motion`均通过 |
| 科研保护 | 16,906个受保护文件，`changed=[]` |
| 更新包 | 原259文件v3发布副本更新后285文件完整性检查通过；非前端摘要未改变；回滚恢复原清单 |

详细JSON证据在本地`reports/frontend-refresh`：`routes-acceptance.json`、`flows-acceptance.json`、`resilience-acceptance.json`、`release-update-acceptance.json`。

代码未配置ESLint，未添加仅用于关闭告警的配置。构建仍提示共享ECharts模块约665KB（gzip约222KB）和主模块约508KB（gzip约156KB），路由已按需加载；未对所有设备作帧率或长时间压力测试。后端事件只提供折级阶段，界面不虚构Pipeline内部子步骤耗时、Loss、GPU利用率或预测置信度。

## 实际运行截图

这些是浏览器运行结果，用户参考图另存于`design-reference`。

- [桌面研究总览](../docs/screenshots/genescope2-overview.png)
- [四步实验配置](../docs/screenshots/genescope2-lab.png)
- [真实完成实验](../docs/screenshots/genescope2-monitor.png)
- [真实样本预测](../docs/screenshots/genescope2-prediction.png)
- [手机总览](../docs/screenshots/genescope2-mobile.png)

完整逐页截图（桌面/平板/手机）位于本地`reports/frontend-refresh`。

## 本地启动

在项目根目录的两个PowerShell终端分别执行：

```powershell
.\start_genescope2_backend.ps1 -Port 8001 -FrontendPort 5174
.\start_genescope2_frontend.ps1 -Port 5174 -ApiPort 8001
```

访问`http://127.0.0.1:5174`。脚本优先使用本机Python3.14和既有vendor依赖，API与冻结模型继续执行原运行环境校验。

## 服务器更新

交付包：`cloud_deployment/dist/GeneScope2_UI_20261104_v2.zip`及同名`.sha256`。只包含静态前端和校验/更新工具，无需重新上传矩阵或模型。

按照[Workbench更新和回滚命令](../cloud_deployment/FRONTEND_UPDATE.md)执行。服务器仍需用户在Workbench上传并运行，当前未自动改动线上版本。服务器镜像构建与公网最终验收尚待服务器执行结果；本地未提供Docker引擎，未声称完成Linux镜像实测。
