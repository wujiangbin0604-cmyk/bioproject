# GeneScope 交互式模型实验室

入口 `/lab`，侧栏及首页按钮均可进入。A模式输出**现场冻结模型推理**；B模式输出**现场新开发集CV**；`/models` 等原页面保留**历史研究成绩**。三类结果不混写。

## 启动

所有命令从项目根目录执行。完整推理需要 Python **3.14.0**、NumPy **2.4.2**、scikit-learn **1.8.0**、joblib **1.5.3**，遵守原部署校验。推荐激活匹配环境后：

```powershell
python -m pip install -r deployment/requirements.txt
python -m pip install -r backend/requirements-web-runtime.txt

# 一次离线导出，不训练、不调用保留集；已有相同工件可安全重复验证。
python -m deployment.lab_registry

# API用一个worker；不要在有任务运行时开启热重载。
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

也可使用 `./start_genescope_backend.ps1`：优先使用 `GENESCOPE_PYTHON` 指定解释器，其次检测 Windows 用户目录常见的 Python314 安装；可用 `-PythonExe <解释器路径>` 明确指定。脚本先核对精确冻结环境，不自动安装或降低校验要求。本机验证用的隔离Web依赖位于被Git忽略的 `backend/.vendor314/`；其他机器按上方命令安装到自己的环境。

`backend/requirements-web-runtime.lock.txt` 记录此次验收实际安装的Web依赖版本，精确复现可用它替换宽范围的Web依赖文件。科学计算环境仍以原部署锁定要求为准。

另开终端：

```powershell
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173/lab`。原8000服务若仍在运行，先在其终端停止后再用新环境启动。使用备用端口时，前端启动前设置 `GENESCOPE_API_URL`，后端设置明确的 `GENESCOPE_ALLOWED_ORIGINS`。

## A：多模型真实推理

| ID | 固定方案 | 特征数量口径 |
|---|---|---|
| M0 | 全特征 + StandardScaler + LinearSVC | 20,531 |
| M1 | ANOVA50 + StandardScaler + LinearSVC | 50 |
| M2 | 高方差20 + StandardScaler + LinearSVC | 20 |
| M3 | ANOVA300 + StandardScaler + LinearSVC | 300 |
| M4 | ANOVA50 + 方差排名未入选30 + SVM | 80个不重复基因 |
| M5 | ANOVA50 SVM、高方差50 SVM、ANOVA50 LR硬投票 | 三个实际支持集的并集；不是50或150的假定值 |

从可用模型中多选，上传恰好一行的UTF-8 CSV。列必须是完整且唯一的 `gene_0..gene_20530`，可选 `sample_id`，最多5 MiB。复用原 `validate_single_sample`；顺序可调整，按基因名恢复。不持久化上传文件，框架的临时上传在请求结束时关闭清理。

一次提交依次调用所选已拟合模型，逐模型展示实际类别、墙钟推理耗时、独立基因数、状态和部署版本。计时从单模型注册缓存读取/首次加载开始，包含 `predict`，不包含公共CSV解析；这不是并行硬件效率基准。推理失败不会填入类别。M5仍调用原硬投票类，三者全不同时用A，不解释投票比例为概率。

### 安全导出与注册

`deployment/lab_registry.py` 中的模型摘要来自原最终评价审计，固定在代码中。离线命令依次核对原配置、审计、划分和自定义类型源码摘要；仅在精确环境通过后反序列化。核对全部成员的选择规则、拟合维度、640样本标准化器、类别顺序、有限参数和实际基因支持集。

原M1仍调用原 `load_deployment_model`，原工件与元数据双摘要机制不变。额外工件复制至 `deployment/lab_models/`，保留原二进制字节，不重新序列化或训练。确定性元数据由可信工件重构；加载时逐字段严格比较，用户提供的摘要不作为信任根。Web不提供上传模型、导出注册或修改可信摘要的接口。

当前 `variance_topk.py` 与历史快照仅多一行稳定排序说明注释，逻辑相同；已审阅的当前源码摘要单独固定并写入元数据。模型或自定义源码变更需要重新审查，不能在网页中“确认信任”后直接使用。

若克隆项目只有公开M1包，其他模型会禁用并注明缺失原因。复制原始 `results` 文件并不自动启用额外模型，必须通过离线导出。版本不符时全部受影响模型禁用；可继续浏览历史页面及在当前合法环境运行探索CV。

## B：实时训练与交叉验证

允许的预设：LinearSVC或Logistic Regression；全部基因、ANOVA或高方差；K为20/50/100/300/500/1000；C为0.1/1/10。StandardScaler在筛选之后。其余参数复用已有研究工厂：seed42、max_iter50000、tol1e-4，SVM dual=auto，LR lbfgs、class_weight=None。没有自动搜索。

默认分层5折；可明确选择5折×20轮重复CV，共100个验证折。固定640例开发ID及其顺序来自原清单；不重新划分640/161。复用 `load_existing_development_data(strict_rows_only=True)`，TAR/CSV顺序读取仍经过原文件字节，但保留行只解析首列ID，不把其表达值/标签交给pandas，不拟合、预测或评分保留集。核对原划分和开发数据指纹。

每折克隆完整Pipeline，512例训练、128例验证；保存训练/验证Macro-F1、Balanced Accuracy、Accuracy、差距、耗时、OOF、选择基因、折索引及标准化器均值/方差/样本计数审计。ANOVA常数列NaN保留诊断；选中特征非有限、未收敛或隔离审计失败会使任务明确失败，不静默改数据。

后台任务采用独立Python进程，Web请求不执行fit。SSE每次完成真实折时发送快照，等待期间按真实时钟刷新耗时；进度指**交叉验证折**，没有epoch或虚构Loss。浏览器断线自动重连，刷新后按任务ID读取持久化快照，不重新训练。

资源策略：单任务并发（Windows/POSIX文件锁，跨API实例互斥）、数值线程1、默认900秒/2048 MiB、最多100条运行记录、启动时检查至少1 GiB可用内存/磁盘。内存以进程树RSS每0.5秒采样，超过上限即终止进程树；属于采样终止策略，不声称操作系统级硬内存配额。可在启动前用 `GENESCOPE_LAB_TIMEOUT`（60–1800）和 `GENESCOPE_LAB_MEMORY_MB`（512–4096）调整有界配额。Windows进程使用较低优先级。

取消会终止正在拟合的进程，保留已完成折。API关闭时停止所拥有的工作进程；工作进程也监测API所有者退出。重启后未完成记录标记中断，不自动重训或冒充完成。跨API实例的写入并发受文件锁限制，部署使用单worker。写接口限定本机客户端和明确的Origin，当前实现定位为本地研究工作台。

## 运行产物及接口

新结果只写入 `results/lab_experiments/<随机任务ID>/`，不更新任何 `latest_*.json` 正式研究指针。包含 `state.json`、配置、运行环境、逐折/逐轮CSV、640例OOF、逐类指标、基因名单、CV索引、fit审计、资源采样记录、日志和汇总。导出的ZIP使用文件白名单，不包含原始矩阵或含保留ID的划分清单。取消、失败的任务可以导出部分记录，明确保留其状态。

| 接口（前缀 `/api/v1/lab`） | 用途 |
|---|---|
| GET `/models` | 冻结模型可用性、版本及实际独立基因数 |
| POST `/predict` | multipart：file与JSON数组model_ids |
| GET `/capabilities` | 合法预设、开发数据可用性、资源上限 |
| GET/POST `/tasks` | 记录列表 / 创建受控任务 |
| GET `/tasks/{id}` | 完整状态快照 |
| GET `/tasks/{id}/events` | SSE，snapshot事件；完整快照支持重连 |
| POST `/tasks/{id}/cancel` | 取消当前API创建的任务 |
| GET `/tasks/{id}/export` | 当前运行结果ZIP（包括部分完成状态） |

100个验证折、20轮OOF及同一患者的重复预测均相关，只作描述。现场可反复选择配置，因此不能将事后最好分数称为无偏新验证；不据此修改冻结主要模型或正式研究成绩。数据仅包含五类已患癌肿瘤，不能评价患癌风险、早筛或临床监测。

## 验收

常规测试不训练模型：`python -m pytest backend/tests/test_api.py backend/tests/test_lab.py -q`。前端：`npm run build`。

`backend/tests/lab_smoke.py` 是显式本机端到端验收：要求六个真实模型和本机已有开发样本，确认其ID属于原640开发集后执行六模型推理；页面提交一个ANOVA50+SVM五折任务，检查SSE、导出并独立复算分数；再启动一个重复CV任务验证并发拒绝和取消。只生成现场实验结果，不重新最终评价。设置 `GENESCOPE_SMOKE_BASE` 可使用备用验证端口；真实验收报告位于 `reports/lab_validation.json`。
