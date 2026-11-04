# GeneScope 2.0 高保真视觉修复 · 2026-11-04

本轮在已有工作台上进行两轮视觉精修。首页原有十个区域、API、实验参数及任务流程均继续使用；主要修改全局样式、DNA、指标卡片、首页图表和面板过渡。

## 参考与实际截图

`design-reference/target.png`、`current.png`不存在。按请求检查后，目标首页采用`design-reference/genescope-ui.png`左上角区域，流程组件参考`genescope-workflow.png`；当前页面在实际浏览器1440×900视口重新截图作为修复前基线。

- [修复前实际首页](../docs/screenshots/genescope2-before-polish.png)
- [第一轮实际首页](../docs/screenshots/genescope2-polish-round1.png)
- [第二轮修复后首页](../docs/screenshots/genescope2-overview.png)
- [修复后手机首页](../docs/screenshots/genescope2-mobile.png)
- [真实图表Tooltip](../docs/screenshots/genescope2-chart-tooltip.png)

以上运行截图不使用目标展板替代。

## 视觉差距审查与修复

| 范围 | 原页面差距 | 本轮实现 |
|---|---|---|
| 布局结构 | Hero及任务区偏高，分析区位于较低位置 | 保留区块顺序，缩小冗余间距，任务行两层信息对齐 |
| 页面配色 | 灰白层次接近、蓝青紫色彩存在但偏淡 | 顶部浅蓝、右上紫色、左下薄荷绿光晕，主色保持蓝青紫 |
| DNA视觉 | 近似平面线条、裁切、鼠标事件被透明文字容器遮挡 | 投影双链、斜向配对横杆、前后分层、高光、阴影、流动亮纹和真实鼠标视差 |
| 卡片样式 | 所有卡片视觉权重接近 | 指标卡轻量色调、图标光圈、玻璃边缘、渐变微光与分区层次 |
| 字体与留白 | 辅助文字9–11px，卡片内部空白多 | 标题28px、卡片16px、正文13px、主要辅助12px、图表11–12px |
| 图标设计 | 尺寸偏小、反馈不足 | 统一线性图标；快速入口34px；Hover缩放1.05 |
| 图表美观 | 标签过小、实色柱、缺少导出入口 | 保留实际柱状数据，渐变柱、浅虚线网格、白色Tooltip、统一图例及PNG导出 |
| 背景层次 | 主体背景平淡 | CSS径向/线性渐变与伪元素流线，装饰位于文字下层 |
| 阴影与边框 | 卡片分离感弱 | 白色内高光、极浅蓝边框、柔和多层阴影和Hover边缘高亮 |
| 实际交互动效 | 已有CSS声明但存在触发冲突 | 修复入场动画冻结transform的问题；连续帧验证上浮、流光、视差和Tab过渡 |

## 两轮浏览器复查

1440×900视口，同一业务布局的实际测量，单位px：

| 项目 | 修复前 | 第一轮 | 第二轮 |
|---|---:|---:|---:|
| Hero高度 | 177.8 | 166.4 | 140.0 |
| 指标区高度 | 126.5 | 120.0 | 120.0 |
| 快速启动/任务行高度 | 231 | 225 | 194 |
| 分析区顶部位置 | 696.3 | 651.4 | 594.0 |

第一轮处理字号、对比度、玻璃卡片和背景。复查发现Hero仍高、DNA偏平、任务区留白多、图表标签小、Tab只有进入动画；第二轮逐项修复。手机长模型名称按完整单词换行，避免标签重叠。

## 修改的组件与文件

- `src/styles/visual-refinement.less`：排版Token、层次、密度、响应式、Hover与过渡规则。
- `src/components/visuals/AnimatedDNA.tsx`：投影几何、前后双链、管线高光、粒子及流光；支持页面/视口可见性和减少动态效果。
- `src/components/ui/AnimatedStat.tsx`：保留真实数值动画，增加可访问的真实导航；没有导航用途的统计不添加可点击样式。
- `src/components/ui/Crossfade.tsx`：旧内容淡出130ms后更新，新内容淡入220ms；支持快速反向切换和定时器清理。
- `src/components/charts/OverviewAnalysisChart.tsx`：真实柱状/分布数据的统一主题、图例、Tooltip、缩放与图像导出。
- `src/components/EChart.tsx`及三类共享图表：统一字号、Tooltip、配色，保留ResizeObserver与实例生命周期。
- `src/pages/workspace/OverviewPage.tsx`：Hero层级、可导航指标、紧凑入口、实际任务进度及分析面板组合；数据接口继续使用原请求。
- `src/components/prediction/FileUploadArea.tsx`：增加真正的DragEnter，修复子元素切换时的DragLeave闪烁。
- 模型对比、特征、原模型与融合页面：仅提高显式图表标签字号。
- `backend/tests/frontend_visual_repair.py`：从浏览器触发实际控件，记录连续帧、原始图表导出及真实任务状态。

## 动效与交互验收证据

`reports/visual-repair/interaction-acceptance.json`记录实际浏览器结果：

- 指标卡上浮4px，图标缩放1.05；指标导航与快速入口可点击。
- DNA连续两帧流光偏移变化：约`-34.97px → -46.55px`；鼠标移动真实修改视差偏移。
- Tab淡出、数据更新、淡入通过；快速反向切换后面板不会保持透明。
- 实际ECharts Tooltip、图例点击和PNG导出通过。
- 子菜单展开/收起、侧栏收缩和图表Resize通过。
- 上传DragEnter高亮、DragLeave恢复、真实Drop后的重复列错误通过。
- 系统减少动态效果后DNA亮纹停止，CSS微交互停用。
- 启动真实本地任务`e053ad17ced045d49942d616b5ff194d`，记录运行节点与进度连续帧，再通过真实取消接口结束。
- 1440×900、1920×1080、1280×800、390×844均无页面横向溢出。
- 浏览器`pageerror=[]`。

连续帧原图位于本地`reports/visual-repair`：`stat-hover-before/mid/after`、`dna-frame-1/2`、`tab-before/exit/after`、`monitor-live-1/2`等。动画判断使用计算样式、位置测量与连续截图；未以单张静态图作为动效证据。

## 构建与业务保护

`npm test`的10项测试通过，TypeScript与生产构建通过。项目未配置ESLint。所有引用共享组件的新旧路由继续执行浏览器检查；完整业务/部署回归在本次升级中为105通过、1项本机Docker检查跳过。

统计与图表保留真实API结果，任务进度来自后端事件。原始实验、矩阵、模型权重、冻结参数与FastAPI协议未修改。完整功能清单见[此前升级交付说明](FRONTEND_REFRESH.md)。

## 仍存在的视觉差距与验证范围

DNA采用浏览器SVG投影和高光，材质细节与展板中的插画渲染仍有差异。长基因/探针ID在窄屏依赖Tooltip查看完整信息。表格保留真实科研字段，因此部分窄屏需要表格内部横滚。

动效已通过实际触发与连续帧验收；没有对所有设备做60FPS或长时间压力测量。ECharts共享模块仍有构建体积提示，页面继续按路由懒加载。

## 交付与启动

更新包为`cloud_deployment/dist/GeneScope2_UI_20261104_v2.zip`及同名`.sha256`，使用[Workbench更新命令](../cloud_deployment/FRONTEND_UPDATE.md)。线上部署仍待用户通过Workbench执行，新包支持原文件校验、备份与回滚。

本地两个PowerShell终端分别运行：

```powershell
.\start_genescope2_backend.ps1 -Port 8001 -FrontendPort 5174
.\start_genescope2_frontend.ps1 -Port 5174 -ApiPort 8001
```

访问`http://127.0.0.1:5174`。
