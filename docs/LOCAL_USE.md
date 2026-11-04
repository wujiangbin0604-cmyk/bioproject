# 在本机使用GeneScope

本地运行不依赖香港服务器，也不要求线上网站可访问。浏览器只是本机界面，地址为`127.0.0.1`；数据、任务和模型保存在解压目录。

## 下载和第一次启动

推荐下载GitHub [Releases](https://github.com/wujiangbin0604-cmyk/bioproject/releases/latest) 中的本地ZIP及同名`.sha256`。完整解压，不要在ZIP内部双击运行。

- Python：推荐**3.14.0**。原M1验证Python、numpy、scikit-learn和joblib精确版本；Python3.12+可运行工作台，但版本不符时M1会明确不可用。
- 成品包：已有`frontend/dist`，运行不需要Node/npm。
- GitHub源码ZIP或`git clone`：第一次需要Node/npm构建；本项目验收使用Node24。
- 安装目录需可写、至少预留数GiB；实际训练资源限制仍由原任务监督器执行。

Windows双击`start_local.cmd`，会优先使用本项目虚拟环境或常见位置的Python3.14，也支持`py -3.14`。首次自动执行安装，再打开本机浏览器。

Windows也可明确指定Python版本：

```powershell
py -3.14 genescope.py setup
py -3.14 genescope.py
```

macOS/Linux：

```bash
python3.14 genescope.py setup
python3.14 genescope.py
# 或 sh start_local.sh
```

第一次安装运行依赖需要网络。之后启动只读取本机环境与前端成品。

## 原有环境与环境诊断

```bash
python genescope.py doctor
python genescope.py verify
```

`doctor`报告实际解释器、依赖、前端成品及M1是否可用，不伪造模型状态。`verify`逐文件检查Release清单；源码目录没有发布清单时会明确说明。

已有完整兼容环境的开发者可以显式复用：

```bash
python genescope.py doctor --current-env
python genescope.py --current-env
```

默认不会把依赖安装到系统Python，而是使用项目内`.venv-local`。需要补全依赖时重新执行`setup`。

## 不访问任何线上GeneScope页面的使用流程

1. 启动后访问`http://127.0.0.1:8787`。
2. 数据集中心选择GSE45827，从官方源下载，或上传事先下载的`GSE45827_series_matrix.txt.gz`。
3. 等导入任务完成后创建实验，选择LinearSVC、ANOVA、K20、3折CV。
4. 实时监控读取真实进程事件。完成后查看结果、特征和模型比较。
5. 预测页选择刚注册的同数据集模型，下载完整特征清单，再上传一行真实表达数据。

没有缓存时显示“待导入”，没有实验时显示空状态，这是新安装的正常状态。截图和原服务器中的数据/20余个注册模型不会自动复制到新电脑。

## 命令行数据与预测

官方源下载并导入：

```bash
python genescope.py data gse45827 --download
```

已在其他电脑下载好官方文件时，导入本地路径：

```bash
python genescope.py data gse45827 --file /path/to/GSE45827_series_matrix.txt.gz
```

Windows路径有空格时使用引号。支持gse4290、gse44076、gse45827，标签规则及分组保持原适配器要求。

PANCAN不下载或猜测替代矩阵。准备原始`data/data.csv`和`data/labels.csv`（或原合法研究数据位置）后执行：

```bash
python genescope.py data pancan
```

仅原固定640例开发行进入训练，原161例保留区仍隔离。详细来源见[数据集指南](../DATASET_GUIDE.md)。

不打开网页，使用原冻结M1预测：

```bash
python genescope.py predict --input deployment/examples/sample_input.csv --output prediction.json
```

该自带CSV为合成格式示例。真实样本需要完整20,531个`gene_*`输入列及匹配的表达尺度。此命令直接调用既有`deployment/predict.py`，模型摘要、结构和运行版本检查仍执行。

## 完全离线安装

在可联网、**相同操作系统/CPU架构/Python版本**的电脑下载依赖轮子：

```bash
python -m pip download --only-binary=:all: -r requirements-local.lock.txt -d wheelhouse
```

把Release完整解压目录和`wheelhouse`一起复制到离线电脑，然后：

```bash
python genescope.py setup --wheelhouse wheelhouse
python genescope.py
```

离线安装不会访问PyPI，成品前端也不需要Node。需要训练时，还须事先携带官方Series Matrix文件并用`--file`导入。训练数据、模型和依赖未准备好时，安装界面不会把它们标成可用。

## 端口、停止与持久化

```bash
python genescope.py --port 8788
python genescope.py --no-browser
```

只监听`127.0.0.1`；端口被其他应用占用时会停止并提示换端口，不关闭其他应用。当前终端按`Ctrl+C`退出，既有进程监督器负责停止未完成计算。

| 本机目录 | 内容 |
|---|---|
| `.venv-local/` | 本项目Python环境 |
| `datasets/<id>/` | 官方原文件与带摘要的版本缓存 |
| `experiment_runs/` | 本机真实实验状态、折结果、日志 |
| `model_registry/` | 已完成实验生成的模型与元数据 |
| `results/lab_experiments/` | 旧实验室现场任务 |

备份时停止运行，完整复制项目目录与上述本地数据；不要覆盖原冻结工件。更换版本前保留旧目录，随后按需迁移自己的数据目录。

## 常见情况

| 情况 | 处理 |
|---|---|
| 提示找不到Python | 安装Python，Windows可用`py -3.14`；或用解释器绝对路径执行 |
| 安装依赖失败 | 检查网络/代理，重跑setup；离线使用匹配的wheelhouse |
| 源码版提示npm不存在 | 安装Node/npm，或下载带成品前端的Release ZIP |
| M1显示环境版本不匹配 | 使用精确Python3.14.0，运行doctor核对；不修改可信摘要绕过 |
| 数据集显示待导入 | 下载/上传官方矩阵；源码包不附带原始数据 |
| 原研究历史卡片不可用 | 未附带完整results；按科研指南复现或使用自己的已保存合规结果 |
| 浏览器未自动弹出 | 手动打开终端打印的127.0.0.1地址 |

开发模式的双终端启动及测试见[WEB_DEVELOPMENT](../WEB_DEVELOPMENT.md)。原始研究说明见[RESEARCH_REFERENCE](RESEARCH_REFERENCE.md)。
