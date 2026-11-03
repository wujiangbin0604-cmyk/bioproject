# GeneScope 2.0 数据集指南

数量来自本机实际矩阵导入、标签核验与纳入筛选，保存在各版本metadata.json。

| 数据集 | 来源记录 | 实际纳入 | 特征数 | 实际类别分布 |
|---|---|---:|---:|---|
| PANCAN | 官方801，原固定640/161 | 640开发样本 | 20,531 | BRCA240、KIRC116、LUAD113、PRAD109、COAD62 |
| GSE4290 | Matrix 180 | 176 | 54,613 | 胶质母细胞瘤77、少突胶质细胞瘤50、星形细胞瘤26、非肿瘤23 |
| GSE44076 | Matrix 246 | 246 | 49,386 | 肿瘤98、癌旁98、健康供者50 |
| GSE45827 | Matrix 155 | 130 | 29,873 | Basal/TN41、HER2 30、Luminal A29、Luminal B30 |

## 来源、标签和表达尺度

- [UCI Dataset 401](https://archive.ics.uci.edu/dataset/401/gene+expression+cancer+rna+seq)：Illumina HiSeq处理表达量，保留源数值。gene_*为匿名ID，不解释为真实基因符号。原始归档、固定split继续复用原config.py、data_loader.py。
- [GSE4290](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE4290)：GPL570，characteristics的Histopathological diagnostic提供诊断/grade。4例官方诊断为空，明确排除并保留GSM及原因，绝不猜测其为GBM。astrocytoma的2/3级合并，oligodendroglioma的2/3级合并。源值是GCOS/MAS5全局归一化强度（目标500），适配器逐元素log2(1+x)，不估计跨样本参数。
- [GSE44076](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE44076)：GPL13667。sample type中Tumor映射肿瘤、Normal映射癌旁、Mucosa映射健康供者。individual id识别148个供者：98对癌旁/肿瘤、50健康供者。使用StratifiedGroupKFold，分组缺失时拒绝训练。源RMA处理值不重复log转换。
- [GSE45827](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE45827)：GPL570。以tumor subtype的Basal、Her2、Luminal A、Luminal B四个官方值建标签；保留Basal并注明队列TN命名，不根据编号或受体状态猜测标签。排除11正常组织和14细胞系。源处理含GC-RMA、混合模型批次/杂交校正、技术重复取均值与表达过滤，保留原处理矩阵、不再次log。源处理使用整队列，内部CV仅为探索性评价。

GEO保留原探针ID及官方GPL注释来源；未自动映射成基因符号，不混合平台或共用不同数据集模型。

## 下载和导入

```powershell
python backend/download_geo.py all
# 可分别指定gse4290、gse44076、gse45827，脚本只访问固定官方URL
$py="$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$env:PYTHONPATH=(Resolve-Path backend/.vendor314).Path
$env:PYTHONUTF8='1'
& $py -m backend.import_datasets all
# 可分别指定pancan、gse4290、gse44076、gse45827
```

网页/datasets支持本地已下载文件导入/刷新、官方源下载、上传Series Matrix，返回真实后台任务ID。网页不接受任意服务器路径。

官方手动下载：

- [GSE4290 Matrix](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE4nnn/GSE4290/matrix/GSE4290_series_matrix.txt.gz)
- [GSE44076 Matrix](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE44nnn/GSE44076/matrix/GSE44076_series_matrix.txt.gz)
- [GSE45827 Matrix](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE45nnn/GSE45827/matrix/GSE45827_series_matrix.txt.gz)

将文件放到datasets/<id>/raw/<ACCESSION>_series_matrix.txt.gz，或网页上传.txt/.txt.gz（≤100MiB，解压≤600MiB）。CEL、SOFT或任意CSV不能冒充Series Matrix。若无表达表，需先核验官方processed矩阵结构后新增受控适配器，不自动造数。

下载失败记录URL、时间、错误；未有可用版本时保持pending，重试不会自动生成数据。失败导入不覆盖已有ready版本。缓存记录matrix.npy与samples.json摘要，读取时再次校验。所有标签从官方字段匹配，未知标签或缺失患者分组拒绝训练。

## 本次官方文件SHA-256

| 数据集 | SHA-256 |
|---|---|
| GSE4290 | d5c2c6deb425a3e198b9b79532ed5f75930aa6afe1117e86195c03873ceabe45 |
| GSE44076 | 096db6c83516d01e39a8c1e3b84b2b3759d9edb133e0ce40807251a69b2671bb |
| GSE45827 | 741184cd3b3354ed3ea45fc6a428ed36401cadc20505e5cc5fb381d8aed0ad35 |

PANCAN开发指纹为23413d45a8bad213a2190d0bde01d5030ebcc8370c34397f88277c4b4fc69da5；固定划分摘要仍由deployment/lab_registry.py的SPLIT_SHA验证。新增输出不写正式研究results。

## 单样本CSV

一行，列名匹配所选模型完整输入特征，可额外有sample_id，顺序可不同。预测页可下载特征清单。数值尺度须与导入后一致：GSE4290为log2(1+MAS5强度)，另外两GEO为官方处理矩阵值。模型不猜测是否需再次转换。原冻结M1只接受PANCAN，继续校验原工件及运行环境。
