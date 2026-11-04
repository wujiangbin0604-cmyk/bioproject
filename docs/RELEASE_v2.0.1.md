# GeneScope 2.0.1 本地客户端

**线上网站打不开时，仍可下载到自己的电脑运行。**

请下载附件 **`GeneScope2-local-v2.0.1.zip`** 和同名`.sha256`，完整解压。附件包含前端成品，运行时不需要Node、Docker或云服务器；GitHub自动生成的“Source code”归档是开发源码，需另行构建前端。

## 使用

1. 安装Python **3.14.0**，以完整使用原冻结模型。
2. Windows双击`start_local.cmd`；macOS/Linux执行`sh start_local.sh`。
3. 首次安装项目独立依赖后，打开`http://127.0.0.1:8787`。

命令行启动：

```bash
python genescope.py setup
python genescope.py
```

首次安装依赖需要网络；依赖和官方数据准备好后可离线运行。完全离线安装的wheelhouse方法、端口调整和常见问题见[本地使用指南](https://github.com/wujiangbin0604-cmyk/bioproject/blob/v2.0.1/docs/LOCAL_USE.md)。

## 包含内容

- 浅色React工作台、DNA与真实交互动效、ECharts图表。
- 原FastAPI、真实实验进程、SSE监控、模型注册与预测，在本机同一端口运行。
- 六个原冻结M0–M5工件及M1命令行预测；继续执行原摘要、结构与运行版本检查。
- 官方数据导入入口、科研源码、文档、逐文件完整性清单。
- Git中冻结元数据与固定划分清单按原始字节保存，修复跨平台换行导致的摘要不匹配。

不包含原始表达矩阵、个人缓存或他人动态实验/模型。首次打开数据集“待导入”、现场实验与注册模型为0是正常状态。先导入官方GEO Matrix，再创建自己的实验。原研究历史面板需要另行准备已保存的合规汇总结果。

校验、诊断及命令行示例：

```bash
python genescope.py verify
python genescope.py doctor
python genescope.py data gse45827 --download
python genescope.py predict --input deployment/examples/sample_input.csv --output prediction.json
```

自带CSV是合成格式示例，输出没有生物学意义。真实推理需要匹配模型的数据集、特征列和表达尺度。

已在全新解压目录安装独立依赖验证本地运行；科研工件和原实验边界保持原状。代码及工件许可状态仍见`LICENSE_PENDING.md`。
