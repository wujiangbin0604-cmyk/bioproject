# GeneScope Web 平台

GeneScope 为现有 RNA-Seq 五癌种机器学习项目提供 React 研究结果浏览界面与 FastAPI 接口。历史页面读取已保存汇总；新增 `/lab` 支持冻结模型现场推理及独立后台进程中的开发集探索性CV，不重新评价保留集。实验室的精确环境、注册和启动说明见 [LAB_GUIDE.md](LAB_GUIDE.md)。

## 环境要求

- Windows 10/11、Git 工作区可读写。
- Node.js 20.19+ 或 22.12+；本项目在 Node 24 上开发。
- Python 3.12+ 可运行浏览与结果API。M1冻结模型还要求 `deployment/requirements.txt` 中锁定的 Python 3.14.0、NumPy、scikit-learn、joblib 版本完全一致；版本不符时浏览功能照常运行，预测接口会明确返回环境不匹配。
- 前端采用官方 Arco Design Pro React Vite 模板的布局/设计体系与组件库，使用现代 React/Vite 工程重建。上游模板的旧版 React 17、Vite 2 依赖与当前 Node 环境不兼容，因此没有沿用旧依赖锁。版权与 MIT 文本见 `frontend/ARCO_PRO_NOTICE.md` 和 `frontend/ARCO_PRO_LICENSE`。

## 安装与启动

在仓库根目录打开 PowerShell：

```powershell
# 后端依赖（可先激活你自己的 Python 虚拟环境）
python -m pip install -r backend/requirements.txt

# 启动 FastAPI；Swagger 文档地址为 http://127.0.0.1:8000/docs
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

另开一个 PowerShell：

```powershell
Set-Location frontend
npm install
npm run dev
```

打开 Vite 输出的本地地址（默认 `http://127.0.0.1:5173`）。开发服务器将 `/api` 代理到 `http://127.0.0.1:8000`。若后端使用其他地址，可设置 `GENESCOPE_API_URL`；若前端使用非默认地址，设置 `GENESCOPE_ALLOWED_ORIGINS` 为逗号分隔的明确来源，例如 `http://localhost:5173,http://127.0.0.1:5173`。API 不接受通配符 CORS 来源。

生产前端构建：

```powershell
Set-Location frontend
npm run typecheck
npm run build
npm run preview
```

## 项目目录

```text
backend/app/              FastAPI路由、Pydantic响应及数据适配服务
backend/tests/            API契约测试（使用临时隔离夹具）
frontend/src/api/         Axios API客户端与上传接口
frontend/src/layouts/     Arco风格侧栏、顶栏、主题及响应式布局
frontend/src/pages/       总览、数据、特征、模型、融合、预测、项目说明
results/latest_*.json     已完成实验运行指针（本机结果目录可能被Git忽略）
deployment/               原有冻结M1模型、输入校验器和预测接口
```

## 页面与接口

侧栏新增核心入口 `/lab`（交互式模型实验室），并保留研究总览、RNA-Seq数据探索、特征选择与稳定性、模型性能对比、特征融合与消融、单样本预测和关于项目。浅色为默认主题，右上角可切换深色主题；移动屏幕使用抽屉导航。

API 前缀为 `/api/v1`：

| 路由 | 内容 |
|---|---|
| `GET /health` | API、结果读取、M1环境状态 |
| `GET /project/meta` | 项目与类别元数据 |
| `GET /experiments/status` | 真实汇总文件存在性及格式检查 |
| `GET /dataset/summary` | 数据质量、类别计数、划分摘要 |
| `GET /dataset/heatmaps` | 已保存的开发集真实热图索引 |
| `GET /features/performance` | K值分类性能 |
| `GET /features/stability` | 子采样稳定性统计 |
| `GET /features/genes` | 基因入选频率搜索、排序、分页 |
| `GET /models/comparison` | M0–M5回顾性评价汇总 |
| `GET /models/per-class`、`/models/confusion-matrix`、`/models/errors` | 逐类结果、混淆矩阵及聚合错误分析 |
| `GET /fusion/summary` | 融合、硬投票、动态仲裁汇总 |
| `GET /predict/example` | 合成的零值格式示例，带有非生物学含义标记 |
| `POST /predict` | 上传一个CSV样本并调用现有M1推理 |

API 只从 `backend/app/services/results.py` 登记的文件白名单中读取汇总。它拒绝结果目录指针的路径穿越，并且不返回全量表达矩阵、样本级预测表或保留样本ID。结果缺失或格式无效时分别返回 unavailable 或明确的 HTTP 错误。

## 结果文件接入

结果目录应位于仓库 `results/` 下，并使用项目已有的 `latest_*.json` 指针，内容至少包含 `{"status":"complete","run_directory":"相对运行目录"}`。读取服务对实验类型和相对文件名使用固定映射，不支持浏览器传入任意路径。添加新实验时，应先核对真实文件的列名与统计层级，再在适配层声明其结构；没有结果时页面显示空状态，不以占位数据代替。

特征热图从 `latest_development_heatmaps.json` 指向的运行目录读取 `生成图片/` 中的 PNG。热图标注为开发集探索性分析、预设癌种排序及基因行方向Z-score。保留集指标是同源数据回顾性结果；该数据曾参与早期全样本探索，不称作跨机构外部验证。

## 预测约束

上传端点将请求限制在 5 MiB，CSV 只在内存中解析，并调用 `deployment.input_validator.validate_single_sample()` 与 `deployment.predict.predict_single_sample()`。所有基因列名必须与冻结 Pipeline 的原始列名严格匹配，顺序可不同并按名称恢复；`sample_id` 可选且不进入模型。API 不输出概率、置信度或风险评分，不持久化上传记录。

M1 加载仍受既有模型和元数据 SHA-256、版本和 Pipeline 结构检查保护。不得为启动 Web 服务而修改摘要或绕过版本验证。可浏览的 API 运行环境与冻结推理环境是两项条件：当前 Python 版本不匹配时，预测端点返回 `503 model_unavailable`，而其他研究结果页面继续工作。

## 测试

从仓库根目录执行：

```powershell
python -m pip install -r backend/requirements-test.txt
python -m pytest backend/tests -q
Set-Location frontend
npm run typecheck
npm run build
```

后端测试使用临时结果目录或注入的测试预测器，仅验证 API 输入输出契约，不将夹具作为科研成绩展示。开发联调时还可检查 `/docs`、`/api/v1/health` 和各页面的空数据、错误及正常数据显示。

## 常见问题

- **页面显示 API 未连接：** 确认后端已在 8000 端口启动；前端代理默认只使用本机回环地址。
- **实验结果显示未导入：** 检查 `results/latest_*.json` 的 `status`、相对运行目录及适配层登记的汇总文件是否存在。`results/` 在该仓库中可被 `.gitignore` 忽略，克隆项目时需要本地已有结果。
- **实验状态为格式异常：** 查看API响应的字段诊断；适配层不会猜测或改名缺失字段。
- **预测返回环境不匹配：** 使用部署说明要求的 Python 3.14.0 与锁定依赖。不要重存、重训或修改可信模型摘要来规避此检查。
- **CORS拒绝浏览器请求：** 将正在使用的确切前端 origin 添加到 `GENESCOPE_ALLOWED_ORIGINS`，不要配置 `*`。
- **`npm install` 无法联网：** 确认网络或使用受信任的包镜像，然后再次运行；请保留提交的 `package-lock.json` 以保证版本复现。

## 已完成与限制

已实现历史研究页面与交互式模型实验室、结果白名单读取、真实结果适配、热图与交互图表、冻结模型推理、响应式布局及主题切换。历史研究脚本和最终保留集评价不会由Web接口调用；现场开发集CV在独立受控进程执行。预测只有在精确冻结环境及完整工件验证通过后可用。跨院/跨平台验证、健康对照、随访及临床部署均不属于本平台能力。
