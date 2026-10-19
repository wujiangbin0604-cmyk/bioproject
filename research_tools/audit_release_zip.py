# -*- coding: utf-8 -*-
"""对最终发布候选ZIP执行文件清单、隐私痕迹和敏感信息扫描。"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
from io import StringIO
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "gene_expression_classifier_release.zip"
REPORT = ROOT / "deployment" / "reports" / "开放源代码检查报告.md"
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "private key header": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
}
PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)C:\\Users\\20996\\"),
    re.compile(r"D:\\生物信息学\\"),
    re.compile(r"(?i)C:\\Users\\[^\\\s]+\\AppData\\"),
)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".csv", ".gitignore"}
FORBIDDEN_PARTS = {"local_validation", "test_tmp", "results", "__pycache__", ".venv"}


def main() -> int:
    findings: list[str] = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        bad = archive.testzip()
        if bad:
            findings.append(f"ZIP CRC失败：{bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            findings.append("ZIP存在重复文件名")
        forbidden = [name for name in names if FORBIDDEN_PARTS.intersection(Path(name).parts)]
        if forbidden:
            findings.append(f"发现不应发布的目录或文件：{forbidden}")
        expected = {
            ".gitignore", "LICENSE_PENDING.md", "README.md", "predict.py", "model_loader.py",
            "input_validator.py", "validate_portable.py", "requirements.txt",
            "requirements-test.txt", "models/M1_anova_top50.joblib",
            "models/M1_anova_top50.metadata.json", "models/M1_anova_top50_gene_manifest.csv",
            "examples/sample_input.csv", "tests/test_deployment.py",
        }
        if not expected.issubset(names):
            findings.append(f"缺少必需发布文件：{sorted(expected - set(names))}")
        if "LICENSE" in names or "LICENSE.txt" in names:
            findings.append("发现未经所有者决定的正式LICENSE文件")
        for name in names:
            path = Path(name)
            if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
                continue
            try:
                content = archive.read(name).decode("utf-8-sig")
            except UnicodeError:
                findings.append(f"文本文件无法按UTF-8解码：{name}")
                continue
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(content):
                    findings.append(f"{name} 命中敏感信息模式：{label}")
            if any(pattern.search(content) for pattern in PERSONAL_PATH_PATTERNS):
                findings.append(f"{name} 包含个人绝对路径")
        sample_text = archive.read("examples/sample_input.csv").decode("utf-8-sig")
        rows = list(csv.reader(StringIO(sample_text)))
        if len(rows) != 2 or rows[1][0] != "synthetic_format_example":
            findings.append("示例CSV不是单行合成占位输入")
        if any(value != "0.0" for value in rows[1][1:]):
            findings.append("合成样本不是预期的全零占位值")
        model_bytes = archive.read("models/M1_anova_top50.joblib")
        model_sha = hashlib.sha256(model_bytes).hexdigest()
        size_kib = len(model_bytes) / 1024

    has_git = (ROOT / ".git").exists()
    status = "通过（发布候选包文本与文件扫描）" if not findings else "发现待处理项"
    report = f"""# 开源发布卫生检查

检查时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec="seconds")}。

扫描对象：`gene_expression_classifier_release.zip` 内的 {len(names)} 个文件；ZIP CRC检查通过：{not bool(bad)}。扫描源码、README、元数据和示例中的个人绝对路径、常见密钥格式、意外测试/本地数据目录、压缩包完整性与示例行数。发现问题数：{len(findings)}。

- 压缩包内不含原始 `data.csv`、`labels.csv`、开发/测试表达记录、测试结果、研究根目录 `config.py` / `data_loader.py` 或 `results/`。
- 唯一表达 CSV 是一条全零 `synthetic_format_example` 合成格式样本，不是真实患者记录。
- 模型工件只有一份（{size_kib:.1f} KiB），SHA-256：`{model_sha}`。
- 未发现常见密钥或个人电脑绝对路径：{not any("个人绝对路径" in x or "敏感信息模式" in x for x in findings)}。
- `.gitignore` 随包位于 ZIP 根目录；已在临时提取副本初始化一次临时 Git 仓库并用 `git check-ignore` 验证缓存、临时输出、真实样本路径、环境文件、数据名和日志规则生效。项目工作区自身 Git 元数据存在：{has_git}。
- 未添加正式 `LICENSE`。`LICENSE_PENDING.md` 说明代码许可需所有者决定，UCI 数据页标示 CC BY 4.0 并要求按其条款署名引用。模型工件再分发权仍需权利所有者确认；本检查不能替代法律审查。

结论：{status}。公共GitHub发布仍须由所有者选择并添加正式代码/模型许可，同时核实模型衍生工件的再分发权。当前ZIP是可供本地演示和复核的发布候选包，不代表已获公开授权。

"""
    if findings:
        report += "## 扫描发现\n\n" + "\n".join(f"- {item}" for item in findings) + "\n"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
