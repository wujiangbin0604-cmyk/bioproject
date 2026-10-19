# 五癌种 RNA-Seq 单样本分类器

这是一个可独立运行的研究演示包，用冻结的 **M1：ANOVA Top50 + StandardScaler + LinearSVC** 将一条 RNA-Seq 表达记录分类为 BRCA、COAD、KIRC、LUAD 或 PRAD。包内已经包含拟合好的完整 scikit-learn Pipeline、原始基因名清单、模型元数据、输入校验器和命令行程序；运行预测不需要原始研究项目、训练数据或 `results/`。

## 研究用途和限制

训练来源是 UCI Machine Learning Repository 的 Gene Expression Cancer RNA-Seq Dataset 401。原始特征共 20,531 个，Pipeline 内的 ANOVA 选择器保留 50 个。模型使用固定开发集 640 个样本拟合。此前已有的保留集指标属于研究记录；本软件包不会重新计算这些指标。

模型只能在五类既有肿瘤表达类别中输出一个标签。数据没有健康对照，也没有纵向随访，因此结果不能用于患癌筛查、风险预测、诊断、疾病进展或治疗反应监测。输入数据必须与模型的基因定义、表达尺度和上游处理兼容；跨平台或不同归一化流程的兼容性未经验证。

数据集来源：Fiorini, S. (2016). *gene expression cancer RNA-Seq*. UCI Machine Learning Repository. DOI: [10.24432/C5R88H](https://doi.org/10.24432/C5R88H)。UCI 页面标示数据许可为 CC BY 4.0；使用或再分发数据及衍生物时，请保留署名并遵守[数据集页面](https://archive.ics.uci.edu/dataset/401/gene%2Bexpression%2Bcancer%2Brna%2Bseq)中的当前条款。

## 环境安装

发布工件记录并要求 Python **3.14.0**、NumPy **2.4.2**、Pandas **3.0.0**、scikit-learn **1.8.0**、joblib **1.5.3**。加载器会逐一检查版本与模型结构；未经验证的版本会被明确拒绝。Windows PowerShell 示例：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果系统没有 `py` 启动器，请使用本机 Python 3.14.0 可执行文件创建虚拟环境。Linux/macOS 使用 `python3.14 -m venv .venv`，随后激活 `.venv` 并安装同一 requirements 文件。该运行环境在 Windows 上完成实际验证；Linux/macOS 兼容性尚未实测。

## 输入格式

输入文件须为 UTF-8 或 UTF-8 with BOM 编码的 CSV，且恰好包含一行样本和 20,531 个唯一基因列：`gene_0` 至 `gene_20530`。可以增加一个 `sample_id` 列，也可以调整基因列顺序；程序按列名恢复模型顺序，并从模型输入中排除 `sample_id`。

校验器会拒绝缺失、重复或拼写不符的基因名，拒绝未声明的额外列、多行输入、空值、NaN、正负无穷和非数值表达。校验期间不自动填补缺失值、不做缩放或对数变换。`examples/sample_input.csv` 是全零合成占位输入，只用于检查格式和运行流程；它不是生物样本，预测结果没有生物学或性能含义。

## 命令行预测

在解压后的目录根部运行：

```powershell
python predict.py --input path\to\one_sample.csv --output prediction.json --verbose
```

Linux/macOS 可将路径写为 `path/to/one_sample.csv`。也可省略 `--output` 让程序仅在终端显示预测。

Python API：

```python
from predict import predict_single_sample

result = predict_single_sample("path/to/one_sample.csv")
print(result["predicted_class"])
```

JSON 返回样本 ID（如有）、类别、模型版本、输入及所选特征数、列重排状态和用途提示。分类器不输出校准概率，类别标签不得解释为患癌概率。

结构示例如下；示例类别来自全零占位输入，不是实验结果：

```json
{
  "sample_id": "synthetic_format_example",
  "predicted_class": "BRCA",
  "model_name": "ANOVA Top50 + LinearSVC",
  "model_version": "M1-anova50-linearsvc-1.0.0",
  "input_feature_count": 20531,
  "selected_feature_count": 50,
  "input_columns_reordered": false,
  "inference_status": "success",
  "probability_output": false
}
```

## 便携验证和自动化测试

安装运行依赖和测试依赖后，在发布包根目录执行：

```powershell
python -m pip install -r requirements-test.txt
python validate_portable.py
python -m pytest -q tests
python predict.py --input examples\sample_input.csv --output reports\sample_prediction.json
```

`validate_portable.py` 仅检查包内固定模型、元数据、特征清单、合成输入及 Pipeline/API/CLI 输出一致性。它不导入研究项目源码，不需要数据集，也不会访问保留测试集。`validate_deployment.py` 是旧命令的兼容入口，执行相同的便携验证。

完整研究项目另有 `research_tools/validate_full_project.py`，它需要根目录的 `config.py`、`data_loader.py` 和开发数据，只供原项目内部审计使用，未放入本发布包。

## 工件校验和安全

`model_loader.py` 会在反序列化前校验模型和 sidecar 元数据的 SHA-256，并检查 Python、NumPy、scikit-learn、joblib 版本、Pipeline 步骤、特征名和冻结参数。改变模型或元数据将导致拒绝加载。joblib 使用 pickle 序列化机制，可能在反序列化时执行代码；只加载本包提供且经固定摘要校验的模型，不要替换为不可信来源文件。

## 文件结构

```text
predict.py                     单样本 API 与 CLI
input_validator.py             输入校验和按基因名恢复列序
model_loader.py                工件摘要、版本和结构校验
validate_portable.py           独立便携验证
models/                        冻结 Pipeline、元数据和特征清单
examples/sample_input.csv      合成格式示例
examples/sample_prediction.json
tests/                         输入、工件、API、CLI及便携回归测试
requirements.txt               精确锁定的运行依赖
requirements-test.txt          精确锁定的pytest版本
reports/                       可复现的验证及基准记录
LICENSE_PENDING.md             许可证待所有者确认
```

## 常见问题

- **缺少或多出基因列**：CSV 必须提供完整的 20,531 个基因名；仅保留 Top50 列不能作为输入。
- **列顺序不同**：允许。程序根据列名按训练顺序重排。
- **编码错误**：请使用 UTF-8 或 UTF-8 with BOM。
- **出现非数值或非有限值**：请检查导出文件；预测器不会自动改写数值。
- **SHA-256 或版本不匹配**：使用完整发布包和精确版本依赖，不要编辑模型 sidecar。
- **中文路径**：Python 的路径按 Unicode 处理；请使用支持 UTF-8 的终端及文件编码。

## 开源与许可

当前候选包保留 `LICENSE_PENDING.md`，未代替所有者选择代码或模型许可。发布到公共仓库前，请确认代码、模型工件、数据衍生物和第三方依赖的许可范围，并添加正式许可证全文及所需数据引用。不要将本包的代码许可误认为 UCI 数据或模型衍生工件的自动许可。
