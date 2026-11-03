# GeneScope 2.0 实际交付报告

验收日期：2026-11-03（Asia/Shanghai）。在现有工作区增量开发，未自动推送GitHub。

## 项目现状与保护

开发前已检查README、config.py、data_loader.py、baseline.py、feature_selection.py、variance_topk.py、cross_validation.py、full_feature_ablation.py、ablation_stability.py、final_holdout.py、deployment/predict.py、model_loader.py、requirements.txt及现有前后端、数据和results。已有React18/Vite/Arco/Axios/ECharts、FastAPI、冻结模型桥接及实验子进程；继续复用这些实现。

初始分支main且工作区已有未提交修改和大量未跟踪前后端/部署文件；保留这些内容，使用本报告记录改动，不替用户提交或改写Git历史。Git所有权检查使用仅当前命令的safe.directory选项，未修改全局Git设置。

保护性SHA-256复核覆盖16,906个文件：原根目录研究Python源码、deployment原入口、冻结模型工件/元数据/特征清单、固定split和历史正式results。复核结果changed=[]。原640/161分区未改变，M1未训练、覆盖或修改，161保留集未重新评价。正式研究结果与新增experiment_runs完全分离。

原M1工件SHA-256仍为323c5e9c28faf5426467e17c5429e593235a4c811519e9e1efe04c4910aef7d4，元数据仍为d52a3514848864a910bc2d8369b45292c2cb2cca2f515183112bc60c62ccc31b。真实开发样本sample_391通过原predict_single_sample和新Web入口均输出BRCA；原摘要、版本及Pipeline校验未绕过。

## 创建和修改

新增源码：

- backend/app/platform2/：__init__.py、data.py（数据集统一对象/导入/校验）、engine.py（有界配置/四模型/Pipeline/CV）、jobs.py（复用原任务监督器与并发锁）、worker.py（独立进程）、models.py（可信注册/预测）、routes.py（v2 API及Pydantic响应）。
- backend/download_geo.py、backend/import_datasets.py、backend/audit_protected.py。
- backend/tests/test_platform2.py、platform2_live_smoke.py、platform2_browser.py、platform2_final_check.py。
- frontend/src/api/platform.ts、frontend/src/pages/PlatformPages.tsx。
- datasets/registry.json。
- start_genescope2_backend.ps1、start_genescope2_frontend.ps1。
- DATASET_GUIDE.md、API_GUIDE.md、本报告、WEB_DEVELOPMENT_V1.md旧文档备份。

修改已有文件：backend/app/main.py、backend/app/lab_config.py、frontend/src/App.tsx、frontend/src/layouts/AppShell.tsx、frontend/src/styles/global.less、.gitignore、README.md、WEB_DEVELOPMENT.md。原研究源码与deployment冻结入口未改。

运行生成数据位于datasets/<id>，新模型位于model_registry，任务位于experiment_runs；全部忽略Git。验收记录位于reports/genescope2_live_acceptance.json、genescope2_browser_acceptance.json、genescope2_final_check.json、genescope2_protected_verification.json及浏览器截图。

## 实际导入

| 数据集 | 纳入样本 | 特征 | 类别/分组 |
|---|---:|---:|---|
| PANCAN | 640 | 20,531 | 5类，仅原固定开发集 |
| GSE4290 | 176 | 54,613 | 4类，排除4例官方诊断为空 |
| GSE44076 | 246 | 49,386 | 3类，148供者；98对组织+50健康供者 |
| GSE45827 | 130 | 29,873 | 4亚型，排除11正常组织和14细胞系 |

四套均成功，没有待导入的数据集。GEO来源均为NCBI官方Series Matrix，真实原文件下载时间/摘要与样本标签字段已保存。GSE4290处理为log2(1+源MAS5强度)，另外两GEO保留官方已处理尺度；不是RNA-Seq计数。不自动把探针解释为基因符号。标签、排除规则、分组、源预处理限制详见DATASET_GUIDE.md。

另实际验证了错误矩阵导入失败、现有ready版本保留，随后通过multipart上传官方矩阵恢复成功。最终上传导入任务：6b34f05b9f8b413c953fa881b66b2b14。

## 页面和接口

完成/、/datasets、/lab、/monitor/:taskId、/comparison、/features、/predict、/experiments八个核心页面。保留原研究页面和/legacy/lab、/legacy/predict。具备实际配置、训练、SSE图表、查询、热图、特征频率/稳定性、混淆矩阵、逐类F1、预测和CSV/JSON导出；不以占位成绩代替训练。

请求的health、datasets、import、summary、algorithms、features/methods、experiments CRUD查询/取消/结果/SSE、models、predict、comparison、features/analysis均已接入，另提供任务日志与导出。详细契约和示例见API_GUIDE.md，Swagger由实际应用生成。

四分类器：LinearSVC、Logistic Regression、Random Forest、RBF SVM。选择方法：全特征、ANOVA、Variance Top-K、线性模型系数。支持K20/50/100/300/500/1000、CV2–10折、种子、1–5轮重复、C/gamma/RF树数和深度；有界配置拒绝非法字段、超资源组合和训练折有效K不足。

## 真实训练验收

四数据集均实际运行ANOVA50、共享3折、随机种子42的四模型任务（RF30树）。另对GSE45827实际运行Variance20、Coefficient20、全特征各3折。该显式验收共7个完成任务、57次折拟合。浏览器另启动GSE45827 Variance20/LinearSVC 3折，合计8个完成任务、60次真实折拟合及20个独立注册模型。不是科研最优参数搜索或正式论文结果。

| 数据集 | LinearSVC | Logistic Regression | Random Forest | RBF SVM |
|---|---:|---:|---:|---:|
| PANCAN开发集 | 1.0000 | 0.9974 | 0.9937 | 0.9974 |
| GSE4290 | 0.5955 | 0.5675 | 0.6056 | 0.5769 |
| GSE44076 | 0.9453 | 0.9258 | 0.8658 | 0.8894 |
| GSE45827 | 0.9416 | 0.9525 | 0.9450 | 0.9671 |

表为上述真实3折Macro-F1均值；完整标准差、Accuracy、Balanced Accuracy、逐类F1、混淆矩阵、特征和划分摘要在验收JSON/各任务results.json。不同数据集不具备同一评价难度，不据此宣称某算法普遍更优。PANCAN得分仅为新增开发集探索CV，绝非161保留集重新评价。

四主任务分别为8de1431e0789408b886d090ed33d89b8、fe174ad0668e43a8b169ef0ce956f93b、e41b085ddffb4309abf387c03d32450e、d53bf89afd744cebb38bf556ef8286cf；收到16/14/13/7条真实SSE快照，包含运行状态与逐折计数。数据/训练较快时一次快照可含多折，未编造逐epoch损失。

取消任务e020896b9a6248bebdbf4bf50e11ebbe实际停止RF工作进程；单元测试亦断言process.poll()不为空。错误导入任务d65951092781423898a939b67182194a真实失败、错误可查询、旧数据版本仍可用。重启到脚本启动的另一API实例后，8个完成任务和20模型均可读取。

每数据集的已注册模型均用真实同数据集单样本CSV完成推理；反向跨数据集请求返回422。预测为已知样本的接口行为测试，不作为独立泛化证据，也不生成概率。

## 已执行的检查

- 后端既有与新增API/任务/部署测试：**109 passed**，用时49.20秒；包含四模型×四方法、有效K、分组/重复索引、非法配置、真实进程训练/取消、并发锁、失败恢复、摘要拒绝、SSE、导出、缓存、重启持久化和原冻结部署行为。
- 前端npm run typecheck及npm run build通过。Vite构建有ECharts分块大于500kB提示，不影响启动；未把此提示写成失败或隐藏。
- Playwright/无界面Edge实际浏览12个新旧路由，检查数据详情和真实热图，使用页面表单启动真实训练并等待完成，检查图表/刷新恢复/模型对比/特征结果/CSV上传预测/主题持久化/移动导航。page_errors=[]。
- 使用交付PowerShell脚本实际启动8002后端和5175前端，并确认代理返回200、历史结果和模型可恢复、官方矩阵上传导入成功、最终页面运行错误为空。
- 16,906个保护文件摘要未改变。

测试环境：Windows、Python3.14.0、NumPy2.4.2、pandas3.0.0、scikit-learn1.8.0、joblib1.5.3；Node24.14.0、npm11.9.0。pytest输出包含Starlette对httpx TestClient的弃用提示；测试仍通过，后续升级需协同锁定依赖。

## 限制与后续

本次完成P0和上述P1功能，保留清晰边界：单机单用户、单并发、无公网鉴权或分布式队列，服务中断不能恢复到fit内部。内存为采样监督后终止，不是硬OS配额。没有实现配置模板、批量参数网格、PDF报告、自动基因映射、CEL重处理或临床诊断。GSE45827源整队列预处理限制已在数据协议注明。

启动、API、数据处理分别见WEB_DEVELOPMENT.md、API_GUIDE.md、DATASET_GUIDE.md。默认8000已被本机其他服务占用，本次未关闭该服务，使用独立端口验收。
