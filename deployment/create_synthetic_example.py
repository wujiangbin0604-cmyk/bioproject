# -*- coding: utf-8 -*-
"""生成仅用于CSV格式校验的合成示例，不包含真实患者表达记录。"""
from __future__ import annotations

import csv
from pathlib import Path


def main() -> Path:
    destination = Path(__file__).resolve().parent / "examples" / "sample_input.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    genes = [f"gene_{index}" for index in range(20531)]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", *genes])
        writer.writerow(["synthetic_format_example", *(["0.0"] * len(genes))])
    print(f"已生成格式校验用合成示例：{destination}")
    print("所有表达值为占位值；由模型产生的类别不具有生物学或性能评价意义。")
    return destination


if __name__ == "__main__":
    main()
