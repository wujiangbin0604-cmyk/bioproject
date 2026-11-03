# GeneScope 2.0 开发与启动

在原 React / TypeScript / Vite / Arco 工作台、FastAPI 和受监督实验进程上增量开发。未另建网站、未推送远程。保留前端兼容依赖和Arco MIT声明。旧版说明已存于 [WEB_DEVELOPMENT_V1.md](WEB_DEVELOPMENT_V1.md)，原实验室说明见 [LAB_GUIDE.md](LAB_GUIDE.md)。

## 已验证的本机启动方式

仓库目录：`D:\生物信息学\癌症基因表达机器学习实验`。本机默认python为3.12.10；冻结M1要求3.14.0。脚本会选择已有Python3.14及backend/.vendor314。8000端口有其他服务，本次验收使用8001/5174。

在仓库根目录打开两个PowerShell窗口：

```powershell
# 窗口1
.\start_genescope2_backend.ps1 -Port 8001 -FrontendPort 5174
# 窗口2
.\start_genescope2_frontend.ps1 -Port 5174 -ApiPort 8001
```

前端：http://127.0.0.1:5174；API文档：http://127.0.0.1:8001/docs。
脚本退出时恢复原环境变量。任务进程由API自动启动，不需Redis或额外worker命令。单API worker运行，关闭API会终止未完成计算并保留结果。

新环境安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
# 另一个PowerShell窗口
cd frontend
npm install
npm run dev
```

默认前端5173代理到后端8000。GENESCOPE_API_URL设置Vite代理，GENESCOPE_ALLOWED_ORIGINS设置明确浏览器来源，VITE_API_BASE_URL用于独立API部署。冻结M1仍执行deployment/requirements.txt的精确运行库和SHA校验，环境不符会禁用M1预测，不绕过检查。

`python -m uvicorn backend.app.main:app --reload --port 8000`可用于开发；热重载会中断训练，执行实验请使用单worker无reload模式。

## 已实现页面

| 路由 | 行为 |
|---|---|
| / | API驱动的数据集/模型/实验数、运行状态和最近实验 |
| /datasets | 官方来源、实际统计、质量、类别分布、热图、下载/上传/本地导入 |
| /lab | 四模型多选、四种选择方法、K、折数、种子、重复轮次、高级参数 |
| /monitor/:taskId | SSE实际进度、逐折三指标、耗时、配置、日志、取消、最终汇总 |
| /comparison | 历史实验指标、时间、特征数、混淆矩阵、逐类F1、Jaccard |
| /features | 排名、CV频率/Jaccard、不同K、方法重合、表达热图 |
| /predict | 数据集绑定注册模型、特征清单下载、单样本CSV预测、原冻结M1 |
| /experiments | 搜索、数据集/状态筛选、时间/耗时排序、详情、对比、CSV/JSON导出 |
| /research、/dataset、/research/features、/models、/fusion | 原正式研究展示 |
| /legacy/lab、/legacy/predict | 原冻结模型实验室和旧预测界面 |

浅色默认、持久化深色主题、桌面侧栏、移动抽屉。Arco声明位于frontend/ARCO_PRO_NOTICE.md和frontend/ARCO_PRO_LICENSE。

## 实验与持久化

结构化数据集定义：datasets/registry.json；统一对象提供X、y、sample_ids、feature_names、groups、metadata、split_protocol。具体标签与表达处理见 [DATASET_GUIDE.md](DATASET_GUIDE.md)。

PANCAN新实验只使用原固定640例开发行，核对原split摘要与开发数据指纹；161例保留表达及标签不解析。所有新结果写入experiment_runs，不重算正式结果或覆盖冻结模型。

选择器→StandardScaler（适用时）→分类器组成完整Pipeline，各折重新拟合。RF省略标准化。ANOVA、方差和系数选择均只排名当前训练折有效特征；K不足则失败，绝不补齐或全数据预筛。多模型共用split_indices.json，GSE44076采用患者分组CV。

CV保存逐折Accuracy、Balanced Accuracy、Macro-F1、实际K、样本数和标准化拟合审计。重复CV的均值与样本标准差仅为描述统计，不作独立显著性检验。最终注册模型在CV后另行拟合全部允许开发样本，其最终训练不用于已报告CV评分。

特征频率和Jaccard来自CV训练折选择集合，不等同于原研究30次子采样指标。最终拟合排名仅供探索；GSE45827源归一化、批次校正和表达过滤已使用整队列，内部CV明确为探索性，不宣称外部验证或原始CEL端到端无泄漏。

任务状态为queued、preparing、running、completed、failed、cancel_requested、cancelled。导入同样运行于独立受监督子进程。新旧实验室共用操作系统文件锁，单任务并发，忙时返回409，不建立无限等待队列。CPU数值线程及RF n_jobs均为1。

复用原资源监督器：默认900秒、2048MiB采样RSS限制、至少1024MiB可用内存、1GiB可用磁盘、100条任务上限。GENESCOPE_LAB_TIMEOUT、GENESCOPE_LAB_MEMORY_MB、GENESCOPE_LAB_MIN_AVAILABLE_MB可在有界范围调整。内存限制是每0.5秒采样后终止进程树，不是OS硬配额。Windows原子状态文件替换增加有界共享占用重试。

取消真实终止并等待进程树；API关闭/死亡也停止计算。重启保留完整结果，未完成任务标记失败，不自动续接未完成fit。SSE重连与页面刷新读取完整持久化快照。未完成实验创建的模型不会进入可用清单。

```text
datasets/<id>/raw/             官方原文件、下载时间和摘要
datasets/<id>/<version>/       matrix.npy、samples.json、metadata.json
experiment_runs/<task_id>/     状态、逐折结果、索引、日志、汇总、资源记录
model_registry/<model_id>/     pipeline.joblib、完整元数据
reports/genescope2_*           本轮验收记录
```

矩阵、下载、模型和运行目录已加入.gitignore。API不接受任意服务器路径、代码、joblib/pickle上传。模型加载校验完成来源、ID、SHA-256和精确版本。CSV预测在内存中处理：≤5MiB、一行、完整特征清单，不保存上传样本，不跨数据集推理，不伪造概率。

## 测试与构建

```powershell
$py="$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$env:PYTHONPATH=(Resolve-Path backend/.vendor314).Path
$env:PYTHONUTF8='1'
& $py -m pytest backend/tests deployment/tests -q --basetemp backend/.pytest-tmp-v2-final
# 以下需先启动8001后端、5174前端，会创建真实实验
& $py -m backend.tests.platform2_live_smoke
& $py -m backend.tests.platform2_browser
python backend/audit_protected.py --verify
cd frontend
npm run typecheck
npm run build
```

新环境安装backend/requirements-test.txt后可执行python -m pytest。真实验收脚本不包含在日常pytest中。模型单元测试使用明确标注的实测iris夹具，不进入生物信息学目录或页面成绩。实际结果及限制见 [GENESCOPE2_DELIVERY.md](GENESCOPE2_DELIVERY.md)。API请求示例见 [API_GUIDE.md](API_GUIDE.md)。

本版为本机单用户科研工作台；未实现公网多用户鉴权、分布式队列、中断fit恢复、批量参数网格、配置模板、PDF报告、自动基因映射、独立原始CEL重处理或临床能力。
