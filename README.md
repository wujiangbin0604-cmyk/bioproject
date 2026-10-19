# 高维基因表达特征选择与癌症分类实验

## 单样本预测部署包

项目包含冻结的 M1（ANOVA Top50 + StandardScaler + LinearSVC）单样本研究型预测接口、输入校验、模型工件校验、自动化测试和中文部署说明。安装与使用见 [`deployment/README.md`](deployment/README.md)，从项目根目录运行 `python deployment\predict.py --input <单样本CSV> --output prediction.json`。预测只在五类已患癌样本之间分类，不表示患癌风险、早筛或临床诊断。

项目已扩展为**完整开发集 RQ1/RQ2/RQ3 实验**，包括六个 K 的三种分类流程、30 次共享分层子采样稳定性和联合分析。使用新增入口 `full_feature_ablation.py`；原 `main.py` 仍保留阶段一行为，历史命令和记录不变。本轮固定 C=1，未执行 C 网格搜索，161 个保留测试样本仍不使用。

## 特征互补性与融合消融实验（新增）

```powershell
python feature_fusion.py --n-jobs 1
```

自动执行31个预先固定方案的共享5折×20轮CV、原RQ2的30组子采样稳定性、七类330DPI PNG/PDF、中文报告及无分类器重训的验收。`results/latest_feature_fusion.json`指向结果目录，恢复运行：

```powershell
python feature_fusion.py --resume "results/feature_fusion/运行时间目录" --n-jobs 1
```

支持`--phase classification`、`stability`和`report`。`--n-jobs`为可配置正整数，默认1；内存允许可设2。Python3.14的多进程资源跟踪器要求ASCII临时路径，本入口自动把joblib临时内存映射放在系统英文TEMP目录，数据和输出仍使用原项目中文路径。

- `fusion_selection.py`：可克隆的`FusionSelector`，31方案定义、纯集合规则、当前训练折评分缓存、Pipeline实际fit输入追踪。
- `feature_fusion.py`：严格开发行读取、核验历史400个单方法拟合、冻结规则、并行与断点、总调度。
- `fusion_results.py`：逐折/逐轮OOF、逐癌种、混淆矩阵、基因名单、原30组子采样的重新评分及Jaccard/频率。
- `fusion_analysis.py`：同折性能差、患者救回与新增错误、数量匹配对照及中文报告。
- `fusion_visualization.py`：只读取真实CSV生成七类图。
- `verify_feature_fusion.py`：独立重建集合规则，核对排名范围、预测统计、配额、M匹配、患者变化及图片。

固定K=20/50时比较ANOVA、高方差和三种融合。75%配额按最近整数、半数向上取整，K50为38+12，K20为15+5；等比例为25+25或10+10。先取主方法规定配额，再沿辅助方法**完整训练折排名**补足未入选基因，最终恰好K个。交集、并集和独有集合允许数量变化且单独报告；并集每折实际大小M分别配对ANOVA Top-M和高方差Top-M。逐步补充固定为ANOVA50增加高方差未入选前10/20/30个，并以单方法60/70/80作为相同数量对照。

评分只在当前512个训练样本计算；缓存以完整训练数值、标签顺序的SHA256及样本ID绑定，Pipeline选择器fit时再次核对。每次新分类拟合重新初始化选择器、StandardScaler和固定C=1的LinearSVC。原始表达方差ddof=1；ANOVA常数基因NaN保留诊断并在排名副本置负无穷，其他异常停止。最终输入始终按原基因列位置排序。空集合明确记录`skipped_empty`，不填补或拟合，相关折/轮缺失也保留记录。

```text
results/feature_fusion/<运行时间>/
├── fusion_cv_fold_results.csv        # 31方案×100折，含实际数量和状态
├── fusion_cv_round_results.csv       # 31方案×20轮OOF
├── fusion_cv_summary.csv             # 折均值/样本SD/分位数及轮OOF描述统计
├── fusion_oof_predictions.csv
├── fusion_per_class_metrics.csv
├── fusion_confusion_matrices.csv     # 逐折和逐轮的长表
├── fusion_selected_features.csv
├── fusion_feature_overlap.csv
├── fusion_feature_stability.csv      # 固定和可变预算标记分开
├── fusion_feature_frequency.csv      # 每方案所有20531基因，含零频率
├── fusion_sample_errors.csv
├── fusion_paired_summary.csv
├── fusion_prediction_transitions.csv # 同一验证患者：救回和新增错误
├── fusion_experiment_summary.json
├── fusion_experiment_report.md
├── checkpoints/                     # 每折指标、预测、基因、审计和内容哈希
├── scores_cv/                       # 100个当前训练折排名与异常诊断
├── scores_subsamples/               # 原30组子采样重新计算的评分
├── stability/                       # 435对Jaccard、索引和集合原始记录
├── figures/                         # 七张PNG及对应PDF
└── logs/                            # 冻结方案、环境、复用证据、异常和源码快照
```

`fit_seconds`记录Pipeline实际调用时间；共享评分准备不重复分摊给每个模型，历史时间也是原运行测量，因此不能据此比较独立从头运行的端到端算法效率。三种配额和新增数量均预先固定，不根据验证结果再调整。100折/20轮/435个集合配对都有相关性，仅作描述，不做普通独立样本显著性检验。

“不同基因集合均可分类”不直接证明信息互补；并集增加数量后的成绩需结合匹配M对照。患者错误分析同时保留救回和退化案例。稳定性与分类性能是不同维度；变量数量集合的Jaccard不能与固定K混合排名。此次不修改以前的正式实验、不自动选择融合方案为最终模型，161个测试样本继续隔离。

## 完整开发集实验（本次新增）

在本目录打开 PowerShell，安装依赖后执行：

```powershell
python -m pip install -r requirements.txt
python full_feature_ablation.py --n-jobs 1
```

默认连续完成分类、稳定性、联合报告、七张 330 DPI PNG/PDF 及独立验收。`results/latest_full_feature_ablation.json` 指向本次结果目录。默认单进程、每进程数值线程为 1；`--n-jobs` 可调整，但启动时会根据当前可用内存拒绝过大的并行数。

恢复已有运行，不会重新拟合已验证的断点：

```powershell
python full_feature_ablation.py --resume "results/full_feature_ablation/运行时间目录" --n-jobs 1
```

也可在恢复目录上使用 `--phase classification`、`--phase stability` 或 `--phase report`。`report` 只读取完整结果、生成图文并验收；不会训练分类器。最后阶段缺失必要记录会明确失败，不会用模拟值或静默删除缺失折。

本机验证环境为 Python 3.14.0。请在干净环境中安装项目锁定的依赖；如果 `python` 指向其他解释器，先激活对应虚拟环境再运行命令。

新增模块的职责：

- `full_feature_ablation.py`：冻结协议、严格开发行读取、硬件限制、进度、断点恢复和总调度。
- `ablation_engine.py`：复用既有 Pipeline 工厂，逐步骤追踪 fit 实际输入，核对训练折方差/ANOVA、标准化器及预测；验证历史结果后复用。
- `ablation_stability.py`：30 次共享 512/640 分层子采样；方差、ANOVA、全特征 SVM 系数 L2 排名；每次只拟合一个系数模型，再截取六个 K。
- `ablation_results.py`：从原子断点生成逐折、每轮 OOF、逐癌种、特征、审计、错误分析 CSV。
- `ablation_report.py`：连接真实对应的性能和稳定性指标，按预先固定 delta=0.005 规则标记候选 K，生成中文研究报告。
- `ablation_visualization.py`：只读实际 CSV 绘图。
- `verify_full_feature_ablation.py`：不重训模型，独立核对预测指标、索引、训练折排名、435 个相关集合比较及图片分辨率。

```text
results/full_feature_ablation/<运行时间>/
├── classification/  # 19配置×100折；含全特征基线、完整OOF、每轮混淆矩阵、每患者错误频率
│   ├── checkpoints/ # 每折 JSON + NPZ；完整训练/验证预测、选中基因、分数、审计、内容哈希
│   └── training_scores/ # 当前训练折的独立数值核对缓存，绝不使用验证/测试行
├── stability/       # 18方法/K组合，每组30集合、435对Jaccard、完整基因频率
│   └── checkpoints/ # 每子采样排名、系数矩阵、标准化统计、原子完成标记
├── analysis/        # 联合表、候选K、逐癌种错误、JSON汇总、中文报告、验收清单
├── figures/         # 七张PNG与对应PDF
└── logs/            # 冻结协议、数据质量、环境、历史复用证据、源码和进度日志
```

范围和解释：仅固定640开发样本。TAR顺序扫描仅核对保留行ID，不解析其表达/标签。每折特征筛选和标准化都在训练512样本内拟合；不会使用探索性热力图的全开发集特征名单。ANOVA常数列的实际分数保留NaN，排名副本置负无穷；其他异常停止。Logistic Regression 为 lbfgs 多分类和 L2（本机sklearn1.8以`l1_ratio=0`表达），迭代上限50000，收敛警告记入日志并停止失败折。

三个RQ2选择器使用同一30组分层子样本；SVM重要性为多类别系数沿类别轴的L2范数。该系数排名没有Top-K重训分类成绩，绝不配对到其他方法的分数。RQ2新子采样Jaccard与历史重复CV训练折的Jaccard属于不同协议。跨K的Jaccard受机会重合影响，补充Kuncheva指标；100折、20轮、435对都相互相关，只做描述性分析，不进行独立样本显著性检验。

候选最小K按预先固定的`abs(全特征平均Macro-F1 − 当前平均Macro-F1) <= 0.005`判定，分别在三种流程内取预设列表最小值。它是开发集探索性候选，不是全局最优数量；用于选K的CV均值不能作为无偏泛化估计。后续最终模型和独立测试需另行执行。

全特征基线的每折基因均为`classification/gene_catalog.csv`中的全部列；无特征筛选。完整训练预测保留在每折NPZ，不重复写入巨大的汇总训练预测CSV。历史结果的训练/预测时间保留历史实测值，不用于本轮公平速度比较。完整报告为`analysis/experiment_report.md`。

## 目录与模块作用

```text
癌症基因表达机器学习实验/
├── config.py                # 种子、K/C、CV、数值线程及相对数据路径
├── data_loader.py           # pandas读取、按ID匹配、质量检查、固定80/20划分
├── baseline.py              # 全特征 StandardScaler → LinearSVC 工厂
├── feature_selection.py     # 第二阶段 ANOVA Pipeline / GridSearchCV 工厂，未fit
├── cross_validation.py      # 标准/重复CV、折内拟合、分数和索引记录
├── repeated_cv.py           # 固定全特征5×20扩展及可选标签置乱负对照
├── stability.py             # 共享子采样、ANOVA/系数排名、Jaccard和频率组件
├── evaluation.py            # Macro-F1、Balanced Accuracy、开发集OOF报告
├── visualization.py         # 本阶段图表和后续三类结果绘图接口
├── main.py                  # 默认只执行第一阶段；其余阶段显式拒绝
├── verify_stage1.py         # 基于真实数据和产出文件核验第一阶段
├── verify_repeated_cv.py    # 不重训，独立复算100折及20轮结果
├── requirements.txt
├── requirements.lock.txt    # 本次实际环境版本，由验收生成
├── data/
│   ├── README.md
│   └── split_manifest.json  # 首次运行固定，后续必须一致
└── results/
    ├── latest_stage1.json   # 指向最近一次成功运行的相对目录
    └── stage1_baseline/<运行时间>/
        ├── config.json
        ├── environment.json
        ├── data_quality.json
        ├── class_distribution.csv
        ├── gene_columns.csv
        ├── split_manifest.json
        ├── cv_fold_indices.json
        ├── cv_fold_details.csv
        ├── cv_summary.csv
        ├── fold_fit_audit.csv
        ├── development_oof_predictions.csv
        ├── development_oof_metrics.json
        ├── development_oof_classification_report.csv
        ├── development_oof_confusion_matrix.csv
        ├── stage_status.json
        ├── warnings.json
        ├── verification.json
        ├── 阶段一结果说明.md
        └── figures/
            ├── 阶段一_基线交叉验证性能.png / .pdf
            └── 阶段一_开发集折外混淆矩阵.png / .pdf
```

## 安装与运行

Python 3.10 或更新版本，`scikit-learn>=1.3`（使用 `LinearSVC(dual='auto')`）。在项目目录运行：

```powershell
python -m pip install -r requirements.txt
python main.py --stage 1
python verify_stage1.py
```

默认读取相邻可视化项目中的**原始 TAR**，不读取其 PCA、标准化值、方差排序或差异基因列表。也支持：

```powershell
python main.py --stage 1 --data-dir "包含两份CSV的目录"
python main.py --stage 1 --archive "实际数据包路径.tar"
```

本机已有完整依赖的 Python 3.14，可使用以下命令：

```powershell
python main.py --stage 1
python verify_stage1.py
```

每次运行独立保存，避免覆盖历史结果；`results/latest_stage1.json` 指向最近的成功结果。`requirements.lock.txt` 记录实际依赖版本，跨机器复现还应匹配 Python 和数值计算环境。计时随机器负载变化，固定种子不保证跨版本/硬件逐比特一致。

## 第一阶段每一步的作用

1. **读取和检查。** 用 pandas 从两个 CSV 或 TAR 任意层级读取；识别 `sample_*` 主键，按ID重排标签。检查维度、缺失、无穷、非数值列、重复ID、完全相同表达谱和类别分布。保留所有原始 `gene_*` 列名。遇到异常明确停止，不根据全数据自动填补、删基因或变换表达量。
2. **先划分。** 使用 `train_test_split(test_size=0.2, stratify=y, random_state=42)`，得到640个开发样本和161个保留测试样本；数据指纹和两组ID保存为固定清单。全数据的格式/完整性检查与按标签分层不等于在全数据拟合预处理。测试集只记录样本分配和必要的类别计数，不计算预测性能。
3. **向开发流程只传开发集。** `DevelopmentData` 不含测试表达矩阵或测试标签，防止把全数据误传进CV。第五阶段的测试加载和评估接口尚未启用。
4. **建立事先固定的基线。** 使用 `Pipeline(StandardScaler(), LinearSVC(C=1.0, dual='auto', random_state=42))`。`class_weight=None`、L2惩罚和 squared_hinge 损失；最大迭代50000。第一阶段不调C，第二阶段才预留K/C调参。
5. **只在开发集做5折验证。** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`；每折512个训练样本、128个验证样本。每折新克隆Pipeline，标准化仅对512个训练样本调用fit，随后变换该折验证集。全特征基线不会删除常数基因或使用全数据特征排序。
6. **记录指标及差距。** 每折分别计算训练和验证 Macro-F1、Balanced Accuracy，记录训练减验证的差值、拟合时间和迭代次数。均值和标准差来自5个验证分数，标准差用 `ddof=1`，不将其当成独立实验的置信区间。
7. **生成开发集折外报告。** 每个开发样本恰好获得一次未用于该折模型训练的预测。OOF报告有明确的 development 名称，不能冒充最终保留测试报告；合并OOF指标与5折分数平均可能略有不同。
8. **核查拟合范围。** 保存每折ID，验证三类集合的交集为零，并核对标准化器的均值、方差和样本计数与当折训练数据一致。若求解器未收敛，实验停止并保留警告，不能把未收敛结果当成有效结果。

## 两种交叉验证模式

`config.py` 的 `CV_MODE` 默认为 `standard`，所有开发CV仅接收开发集。无需训练就能查看两种设计：

```powershell
python main.py --describe-cv --cv-mode standard
python main.py --describe-cv --cv-mode repeated
```

- **模式A**：5折分层CV，是第一阶段默认方案及未来GridSearchCV的划分器。
- **模式B**：`RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=42)`，即100次验证评估，**不是100折**。阶段一扩展现已开放固定全特征基线的运行入口。

`evaluate_fixed_pipeline` 的 repeated 模式必须传入由 `frozen_pipeline_record` 记录的完整固定模型配置，并核对所有步骤和参数。当前CLI不启用通用第六阶段，而是启用下述阶段一扩展。100个相关分数仅用于描述固定配置的性能波动，不能当作100个独立样本计算普通标准误、t检验或置信区间；也不能利用它们重新选参数后，又称这些分数为无偏性能。

## 阶段一扩展：全特征重复交叉验证

执行用户已确定的配置，不搜索参数，不读取旧EDA特征排名：

```powershell
python main.py --stage 1 --cv-mode repeated
python verify_repeated_cv.py
```

也可使用 `python repeated_cv.py`，等价于上述重复CV入口。要求先存在成功的原五折基线和 `data/split_manifest.json`；扩展入口直接使用原清单中的**相同640个开发ID及其顺序**，不再次划分。原文件物理上包含801行，读取后立即截取开发行；保留的161个样本不进入表达统计、模型拟合、预测、评分或调参。扩展加载器仅检查保留ID以审计隔离，不再统计保留标签分布。

固定 `StandardScaler → LinearSVC(C=1.0, dual='auto', random_state=42, max_iter=50000)`，与原基线相同，保留20,531个基因。每折重新克隆Pipeline，对512个训练样本fit；128个验证样本只predict。审计同时核验scaler的样本计数、均值、方差和模型实际特征数。每轮保存检查点；失败运行明确标记 `failed`，不会更新成功指针。

结果位于 `results/stage1_repeated_cv/<运行时间>/`，`results/latest_repeated_cv.json` 指向最近成功运行；不覆盖标准基线。

| 文件 | 内容 |
|---|---|
| repeated_cv_fold_results.csv | 100行：训练/验证Macro-F1、Balanced Accuracy、差距、拟合及预测耗时、迭代次数 |
| repeated_cv_round_summary.csv | 20行：每轮五折指标的均值、样本标准差、最小/最大、5%/25%/50%/75%/95%分位数，以及合并OOF分数和错误数 |
| repeated_cv_summary.json | 完整配置、整体描述统计、错误计数、原基线首轮对照和解释边界 |
| repeated_cv_oof_predictions.csv | 12,800行：轮次、折号、样本ID、真实/预测标签及是否错误 |
| training_predictions.csv | 51,200行训练折预测，便于独立复算训练分数；不能当作泛化评价 |
| sample_prediction_stability.csv | 640行：每个样本20次OOF的错误次数、错误比例及预测类别计数 |
| repeated_cv_confusion_matrix.csv | 20轮5×5矩阵长表；额外round=0为12,800次相关预测的汇总，不是新增患者 |
| round_oof/ | 每轮单独保存640条OOF预测，按原开发ID顺序排列 |
| round_confusion_matrices/ | 每轮单独保存5×5混淆矩阵 |
| repeated_cv_fit_audit.csv | 100折隔离与拟合范围审计 |
| repeated_cv_performance.png / .pdf | 330 DPI图与矢量PDF：逐折性能、每轮OOF表现和样本错误次数 |
| cv_fold_indices.json | 每折训练/验证ID，支持完全重建划分 |
| frozen_pipeline.json、config.json、environment.json | 完整流水线参数、实验配置和实际环境 |
| source_snapshot/、source_sha256.json | 本次运行源码快照和SHA-256指纹 |
| verification.json | 独立复算与验收报告；验收本身不拟合模型 |
| 重复交叉验证结果说明.md | 真实运行后生成的中文结果解释 |

同一个样本20轮中每轮只验证一次，所以每个样本错误比例为 `error_count/20`。每轮OOF指标是先合并640条预测再计算，可能与五折指标的均值略有不同。所有标准差使用 `ddof=1`；分位数使用线性插值。拟合计时包含整条Pipeline的fit，预测计时为训练与验证predict的合计，均不包含后续审计/评分/磁盘写入。

**首轮重合须披露：** 同为种子42时，重复CV首轮通常与原标准五折的成员一致；程序实际比较并记录结果。因此，重现首轮不是全新的独立证据，其余19轮才增加了新的随机划分，但仍共享同一640个开发样本。100个折分数以及20轮合并OOF分数均有关联。没有观测到错误也不能证明真实错误率为零，不能据此认定跨机构外部队列同样有效。本扩展的“稳定性”指固定模型对内部数据划分的性能稳定性；特征集合始终为全特征，尚未研究RQ2的特征选择稳定性。

### 可选：标签置乱负对照（默认关闭）

本次真实标签扩展不会自动运行负对照。只有显式指定以下参数才启动另一项100次训练的实验：

```powershell
python main.py --stage 1 --cv-mode repeated --permute-labels --permutation-seed 42
python verify_repeated_cv.py --permutation
```

只对固定开发集640个标签用 `numpy.random.default_rng(42).permutation` 置乱一次，保留类别计数，所有轮次复用这一置乱标签向量，并按置乱标签重新分层；原基因矩阵、样本ID和保留测试标签均不更改。置乱映射、种子和配置独立保存至 `results/stage1_repeated_cv_label_permutation/<运行时间>/`，指针为 `latest_repeated_permutation.json`。负对照不会覆盖真实标签结果。

负对照用于检查失去真实表达—标签关联后是否仍有异常高验证分数，若出现需进一步排查ID泄漏、数据重复或代码错误。单次置乱不是正式的置换检验，不产生置换p值；正常的负对照表现也不能单独证明不存在所有泄漏或外部偏倚。`--permute-labels` 搭配标准CV会明确报错，防止意外改动原基线。

## 后续阶段如何接续

| 阶段 | 当前已提供的组件 | 未来需要执行的内容 |
|---|---|---|
| 2：RQ1 | ANOVA→Scaler→SVM/LR Pipeline；标准CV的GridSearchCV工厂 | 只对开发集搜索K和C，保存每候选/每折分数，与全特征基线用相同折对照 |
| 3：RQ2 | 共享30次分层80%子采样索引；两种排名；Jaccard与入选频率 | 在每个开发子样本内部重新拟合选择器，两方法及所有K共享索引 |
| 4：RQ3 | 性能/稳定性按选择方法和K连接的绘图接口 | 联合分析已经实际完成的实验表，不能为缺失的模型组合编造性能 |
| 5：最终测试 | 明确隔离的未启用入口 | 冻结选择器、K、C及其他设置后，在全开发集重拟合，再仅执行最终测试 |
| 6：鲁棒性 | 重复CV划分器、固定配置核对和每轮/每折记录 | 对已固定方案执行5×20评估；不再依据这些分数选配置 |

第二阶段参数网格预设 `K=[20,50,100,300,500,1000]`、`C=[0.01,0.1,1,10]`。`GridSearchCV(refit='macro_f1', scoring=...)` 的最佳分数是用于选择配置的**开发CV分数**，存在选择带来的乐观性；不能把它当作无偏独立测试性能。阶段一的C=1基线并未执行这个网格。

稳定性比较中，LinearSVC先在当前子样本拟合StandardScaler，再用五类系数绝对值的平均值排名；同一子样本的方法只拟合一次排名再取多个K。30个选择集合有435对Jaccard，其平均值仍是描述统计。不同K的Jaccard会受集合大小影响，跨K比较应结合随机重合水平讨论。

RQ3需匹配**同一选择方法与K**：ANOVA稳定性可与ANOVA+SVM、ANOVA+LR性能对照；系数选择器若没有独立的折内性能实验，就不能借用ANOVA或全特征模型的分数来作对应点。基因入选频率高也不等于因果重要性。

## 开发集探索性热图（不训练分类模型）

另提供独立的**640人开发集探索性热图**入口：

```powershell
python exploratory_heatmaps.py
python verify_development_heatmaps.py
```

它直接复用固定开发ID及原始20,531个基因，输出方差与五分类ANOVA F-score的完整排名、各自Top50、五类原尺度表达均值、重合数及Jaccard。结果独立保存在 `results/development_heatmaps/<运行时间>/`，成功指针为 `results/latest_development_heatmaps.json`；不会启动RQ1模型训练、交叉验证或测试集评估。

四张主图包括两种Top50各自的患者级热图和癌种均值热图：先以640人为基准计算逐基因Z-score(ddof=0)，再按癌种求Z-score均值，因此两种图的标准化基准一致。方差排名使用提供的原表达值(ddof=1)，F排名使用 `f_classif`。患者列按预设 `BRCA→KIRC→COAD→LUAD→PRAD` 排序，组内保留固定开发顺序，图中明确注明这不是聚类结果；全部640列保留，不抽样、不平滑。两张附加热图另用**癌种内逐基因Z-score**显示个体相对偏离，不能与主图混用或用来比较癌种均值。图输出330 DPI PNG与PDF，完整未裁剪矩阵也保存为CSV。

`分析结果/全部基因统计与双排名.csv` 包含 `gene_id`、`variance`、`variance_rank`、`anova_f_score`、`anova_rank`、`mean_BRCA`等五类原尺度均值，以及组间/组内变异信息。另存两份完整排名、两组Top50、重合基因、显示列ID和组内SD/IQR。恒定基因的F未定义，保持空值并排末尾，不能解读为F=0。完整排名中存在非常接近的分数，复核时应以 `pd.read_csv(..., float_precision='round_trip')` 保留浮点往返精度，不按四舍五入显示值重排。

**本次全640人探索得到的ANOVA Top50不能作为后续CV的固定特征集合。** 虽然保留测试样本没有参与，但探索排名已使用未来CV验证折的标签。正式CV仍须在每一训练折内重新拟合 `SelectKBest(f_classif) → StandardScaler → 分类器`，不读取这些EDA名单。热图按标签选基因并预设排序后呈现的分块不是独立验证，不能由此推断分类准确率、因果作用或外部泛化。两种Top50的Jaccard只反映筛选准则间的一致性，不是RQ2的子采样稳定性。完整说明见每次输出的 `开发集热图分析说明.md`。

## 尚未生成的结果

当前另开放一项**固定K=50的受控对照实验**，不启动完整RQ1网格、其他K或最终测试：

```powershell
python top50_comparison.py
python verify_top50_comparison.py
```

实验复用 `ExperimentConfig`、固定开发集清单、`make_cv`、既有ANOVA Pipeline工厂、指标与拟合审计。新文件 `variance_topk.py` 提供可clone的 `VarianceTopK(k=50)`；两个Pipeline都在512人训练折内先筛选，再标准化，再拟合 `LinearSVC(C=1.0, dual='auto')`。100组相同的5×20划分中各拟合两个模型，合计200次；全特征基线读取既有结果，不重训。默认种子42、数值线程1、最大迭代50000，参数无搜索。

此入口启用 `load_existing_development_data(..., strict_rows_only=True)`：顺序遍历CSV/TAR字节时只核对保留行首列ID，**保留行的表达值和标签不解析**；仅640行开发内容交给pandas数值解析。没有重新划分。它不会读取 `development_heatmaps/` 的基因名单、评分、Z-score或图形结果。仅数据格式与既有Dataset 401一致时继续，格式不符则停止检查。

方差筛选使用原表达尺度的训练样本方差(ddof=1)，同方差按原列号从小到大选取；输出变换列保留原列顺序。ANOVA严格使用原版 `SelectKBest(f_classif,k=50)`；其并列处理按已记录scikit-learn实现。每折恒定基因的NaN评分保留诊断，只有所选50列评分全部有限才继续；非恒定NaN、无穷值或负分数会报错。选择器、标准化器、分类器的实际fit调用输入均被核验，确保没有验证或保留样本参与拟合。

结果在 `results/top50_comparison/<运行时间>/`，成功指针为 `results/latest_top50_comparison.json`，图片位于该次运行的 `生成图片/`：

| 文件 | 内容 |
|---|---|
| top50_comparison_fold_results.csv | 两方法各100折的训练/验证指标、差距、时间及维度 |
| top50_comparison_round_results.csv | 两方法各20轮合并640人OOF指标及当轮折分数统计 |
| top50_comparison_summary.csv | 全特征基线与两种Top50的完整描述统计 |
| top50_per_class_metrics.csv | 折、轮、重复OOF汇总三个层级的各类Precision/Recall/F1及支持记录数 |
| top50_selected_features_by_fold.csv | 200组实际Top50、变换列位置、选择排名、训练方差和F-score |
| top50_feature_overlap.csv | 相同训练折中两种Top50的交集、并集和Jaccard |
| top50_feature_selection_frequency.csv | 两方法全部20,531个基因各自的100折入选次数/频率，包含从未入选者 |
| top50_sample_error_frequency.csv | 每方法640人的20轮错误次数、比例及误判轮次 |
| top50_cv_fit_audit.csv | 200次Pipeline各步骤fit调用和输入范围核验 |
| top50_paired_fold_differences.csv / top50_paired_round_differences.csv | 同折/同轮性能差值，明确列出被减方法和参考方法 |
| top50_within_method_pairwise_jaccard.csv | 各方法100个集合的4950个相关集合对及训练样本重叠数 |
| top50_feature_stability_summary.csv | 方法内Jaccard描述统计、曾入选及总是入选的基因数量 |
| top50_errors_by_cancer.csv / top50_error_predictions.csv | 分癌种错误次数/比例、真实误判记录 |
| top50_oof_predictions.csv / top50_training_predictions.csv | 全部25,600条验证预测与102,400条训练预测 |
| training_fold_feature_scores.npz | 每次fit的全部20,531个训练折特征评分，支持独立复核 |
| baseline_identity_audit.json / cv_fold_indices.json | 原基线配对资格与共享100组索引 |
| config.json / frozen_pipelines.json / environment.json | 固定参数、完整Pipeline和实际环境 |
| experiment.log / warnings.json / source_snapshot/ | 实验日志、警告及运行时源码快照 |
| verification.json / Top50对照实验报告.md | 独立验收以及七个研究问题的真实结果回答 |

五张图同时输出330 DPI PNG和PDF：Macro-F1、Balanced Accuracy、五类F1、特征重合/一致性、癌种错误分布。前两图分别显示100个折和20轮合并OOF的分布；逐类F1图用20轮均值±SD，不是置信区间。错误次数会对同一患者重复计数，图中同时展示按类别预测次数归一化的错误率。

只有原基线的开发数据指纹、样本顺序、100组训练/验证ID及参数全部核对一致，才加入原基线的逐折差值；否则只作描述性汇总比较。两种Top50之间始终使用同一组索引。所有差值、标准差和Jaccard仅作描述，不对100个相关分数或4950个相关集合对作普通独立样本显著性检验。本次方法内Jaccard不能替代RQ2的30次分层子采样；较高的选择一致性也不自动代表较高分类性能或生物学重要性。

本阶段不会生成不同K性能曲线、Jaccard曲线、性能/稳定性关系图、最终测试报告/混淆矩阵或最终模型文件。这些输出必须等待相应真实实验完成，不创建虚假的占位数据。固定全特征模型的100次重复CV得分由上述扩展实验单独生成。

## 仅分析既有Top50记录的稳定性与重合

```powershell
python analyze_top50_stability.py
```

此命令只读取最近一次已完成对照实验的选中特征、重合、频率和分类成绩CSV，以及最初数据读取阶段导出的 `gene_columns.csv`。不打开表达矩阵或标签文件、不读保留样本记录、不重新计算ANOVA/基因方差，也不训练模型。可用 `--source-run` 和 `--gene-catalog` 显式指定已有结果位置；缺失或矛盾记录会报错，不补造集合。

每方法100个训练折记录各含50个唯一基因；方法内计算全部4950个不同训练折的无序对，保留基因组成相同的集合对。方法间只按相同 `repeat_id`、`fold_id` 计算100次Jaccard，不作不同折的跨方法比较。原文件的 `round`、`fold` 会明确映射到这两个字段。集合交集另用二值入选矩阵复核，原始频率表及同折重合表也逐项核对。

输出位于 `results/jaccard_analysis/<运行时间>/`，成功指针为 `results/latest_jaccard_analysis.json`。四份指定CSV为 `jaccard_stability_summary.csv`、`jaccard_within_method_pairs.csv`、`jaccard_between_methods_by_fold.csv`、`feature_selection_frequency_summary.csv`；三张指定PNG和PDF直接位于该目录，另附完整分析报告、课程论文简洁结论和 `analysis_audit.json`。

Top20按入选次数降序、同频按原始列序展示，不按F-score或方差打破频率并列，也不代表生物学重要性。当前ANOVA和高方差分别有40、41个基因在全部100折中入选，因此两组Top20均并列100%；应结合完整Top50集合的Jaccard理解可变部分。4950个集合对高度相关，不作独立样本显著性推断，不替代RQ2的30次分层子采样实验。

## 三模型等权硬投票与错误互补性实验

```powershell
python hard_voting.py
```

此入口只使用固定640人开发集、原有5折×20轮划分。A为ANOVA Top50+LinearSVC，B为高方差Top50+LinearSVC，C为已有配置的ANOVA Top50+LogisticRegression（C=1、lbfgs、L2、max_iter=50000、class_weight=None）。三个完整Pipeline在原训练折独立拟合；标准化位于筛选之后。三者预测全不同时固定采用A，规则在读取投票成绩之前冻结。不使用概率、权重搜索、软投票或保留测试评估。

本次使用Python 3.14和scikit-learn 1.8.0。精确主要依赖见 `requirements_hard_voting.lock.txt`，可用 `python -m pip install -r requirements_hard_voting.lock.txt` 安装；全项目最低约束已同步要求sklearn 1.8。软件版本不符时不复用旧预测。

默认检查已有消融实验的300份断点：开发数值/标签/原基因列序指纹、640人顺序、100组有序训练/验证ID、完整参数、环境版本、逐条OOF身份、文件哈希和原拟合审计必须一致，才整体复用三组历史预测。若任一基础模型不满足复用条件，则整体重新执行300次完整Pipeline拟合，绝不混配不同折预测。原基因预算融合实验中同折Top-M和并集SVM的旧成绩用于描述性比较，实际每折预算必须与投票并集完全一致。

结果保存至 `results/hard_voting_ensemble/<时间>/`，成功指针为 `results/latest_hard_voting_ensemble.json`。主要文档是 `ensemble_report.md` 和 `图表与结果索引.md`。指定CSV均位于该运行目录，七组330 DPI PNG/PDF位于 `figures/`；额外保存逐折/逐轮配对差值、逐患者20轮错误频率、实际基因清单及并集、同预算对照、诊断警告、完整源码快照、软件版本和 `verification.json`。

```powershell
python hard_voting.py --resume "results/hard_voting_ensemble/<时间>"
python verify_hard_voting.py --run "results/hard_voting_ensemble/<时间>"
python ensemble_visualization.py --run "results/hard_voting_ensemble/<时间>"
```

`--source-run` / `--budget-run` 可指定已有结果；`--force-refit` 明确重训三模型。恢复时配置、源码、数据指纹和源预测哈希须保持一致，改变后应新建运行。不要把三模型分别使用50个基因理解为整个系统只测50个基因；应查看每折并集。纠错/新增错误按参考模型分别统计，同一患者在20轮中会重复出现，不能累加成独立患者数。100个折和20轮成绩相关，只做描述性分析；历史耗时复用或求和不等同于新测部署延迟。该实验不确定最终模型、不访问161名保留患者，也不能支持癌症筛查或风险评估结论。

## 研究解释与数据泄漏边界

- 此前对801个样本的全数据探索已覆盖当前保留测试样本。因此，应披露这段历史；当前设计保证后续拟合与调参在开发集内完成，但不能把这161例称作从未接触过的外部独立验证集。
- 不使用此前全样本方差Top50、差异表达结果或PCA坐标当作建模输入。
- UCI数据是已提供的连续表达值，精确预处理来源有待核实；本阶段不额外做全数据Log变换或假定它是原始计数。
- 数据只含五类癌症，不能将分类表现外推到健康对照、癌症筛查、其他癌种或临床诊断。
- 首阶段高分只能说明本次开发CV的表现；不能预设少量基因同样有效，RQ1至RQ3仍需后续实验回答。

依据：[UCI Dataset 401](https://archive.ics.uci.edu/dataset/401/gene%2Bexpression%2Bcancer%2Brna%2Bseq)、[scikit-learn防泄漏与Pipeline](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)、[LinearSVC](https://scikit-learn.org/stable/modules/generated/sklearn.svm.LinearSVC.html)、[RepeatedStratifiedKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.RepeatedStratifiedKFold.html)。

## 五癌种分类错误分歧与动态仲裁实验

```powershell
python dynamic_arbitration.py
```

实验复用已冻结的开发集、三种 Top50 Pipeline 和原有 5 折×20 轮外层拆分，在每个外层训练集内再做分层 5 折 OOF，只用内层预测训练仲裁规则。验证集标签不进入规则学习；过滤、标准化和分类器都在各训练折拟合。固定C为1，不调参、不使用161例保留集。默认利用完整检查点恢复同一实验：

```powershell
python dynamic_arbitration.py --resume "results/dynamic_arbitration/<运行目录>"
python verify_dynamic_arbitration.py "results/dynamic_arbitration/<运行目录>"
python dynamic_arbitration_visualization.py --run "results/dynamic_arbitration/<运行目录>"
```

最近一次完成的运行位于 `results/dynamic_arbitration/20261017_193651_363015/`，中文完整报告为 `dynamic_arbitration_report.md`，图表与结果索引为 `图表与结果索引.md`，独立隔离审计见 `verification.json`。结果包含1800次 Pipeline 拟合的审计、内外层OOF、规则选择、预测变化、基因并集和8张330 DPI PNG/PDF。该次训练集内规则在100折都回退模型A；固定历史分歧规则仅作事后探索，不能据此主张泛化改善。重复折和患者事件相关，报告只作描述性比较，不执行普通独立样本显著性检验。

此前对全体801样本的探索性可视化涉及161例，因此即使本次运行没有读取其表达值或标签，也不能把它们称为从未接触的外部验证集。结果仅限五类已患癌肿瘤样本的表达分类，不支持早筛或患癌风险判断。

## 最终回顾性保留集评价

```powershell
python final_holdout.py --preflight-only
python final_holdout.py
```

前置检查只读取既有数据划分、开发集实验清单和历史审计记录，不读取161例保留集表达值或标签。完整命令会在 `results/final_holdout_evaluation/` 已不存在时，先冻结M0–M5配置，再仅用640例开发集拟合六个Pipeline；模型和161例预测先保存，之后才读取标签计算一次最终指标。目录存在时脚本拒绝重跑，避免重复打开保留集。模型文件在 `models/`，所选基因在 `final_selected_features.csv`，图表在 `figures/`（PNG 330 DPI及PDF），完整审计与论文结果见 `final_research_report.md` 和 `final_paper_conclusions.md`。

若首轮模型预测已经冻结、但报告生成被中断，只有在 `final_evaluation_audit.json` 状态为 `all_predictions_frozen_before_test_labels` 时，`python finalize_holdout.py` 才会从冻结快照恢复汇总。完成后再次运行该命令只会根据已保存的指标重绘图例排版，不重新读取表达矩阵或标签，也不重新拟合/预测。成功状态、结果指针和输出哈希会写入审计文件。完整运行结束后 `python final_holdout.py` 会拒绝重跑；不得在查看测试结果后变更模型或重新评价。此次161例属于同来源回顾性保留集，且项目早期全样本可视化曾涉及这些样本，不能称为完全未查看的外部验证队列。

## 仓库版本与发布范围

当前源码版本为 **0.1.0**（见 [`VERSION`](VERSION) 和 [`CHANGELOG.md`](CHANGELOG.md)）。部署模型另有独立版本号 `M1-anova50-linearsvc-1.0.0`，以模型元数据为准。公开仓库地址：[wujiangbin0604-cmyk/bioproject](https://github.com/wujiangbin0604-cmyk/bioproject)。

仓库保留研究代码、必要的固定划分清单、审计文档，以及不包含原始表达记录的便携部署包。原始 `data.csv`、`labels.csv`、TAR 压缩包、`results/` 中的高维结果与逐样本预测、本机真实验证样本和临时日志均不纳入版本控制。复现实验需要用户依据 UCI Dataset 401 的适用条款自行获取数据，并放入 `data/` 或通过命令行提供 TAR 路径。

主要目录：

- 根目录 Python 模块：数据检查、交叉验证、特征筛选、集成与最终评价实验。
- `data/`：固定划分清单和数据放置说明，不含表达矩阵与标签。
- `deployment/`：冻结的单样本推理 Pipeline、输入校验、合成示例与自动化测试。
- `research_tools/`：发布包构建、校验及项目审计辅助工具。
- `gene_expression_classifier_release.zip`：可独立解压运行的部署发布包；其模型版本不随源码版本自动改变。

提交代码时请遵循 [`CONTRIBUTING.md`](CONTRIBUTING.md) 中的版本、注释和数据边界约定。仓库没有正式 `LICENSE`，`LICENSE_PENDING.md` 记录了代码、模型工件与上游数据许可仍需分别确认；公开可见不等于授予再分发或商用许可。
