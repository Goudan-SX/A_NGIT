"""可选：把本地 ONNX 文本模型动态量化为 INT8。

当前 Guardian-AI 的本地快速路径是 AC 自动机 + 规则引擎，不需要量化；
如果后续接入本地 Transformer/ONNX 语义模型，可用本脚本压缩：

    python backend/ml/quantize_onnx_int8.py --input local_model.onnx --output local_model_int8.onnx

依赖：
    pip install onnxruntime onnx
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="local_model_int8.onnx")
    args = parser.parse_args()
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("请先安装 onnxruntime 和 onnx：pip install onnxruntime onnx") from exc
    source = Path(args.input)
    target = Path(args.output)
    if not source.exists():
        raise SystemExit(f"模型不存在：{source}")
    quantize_dynamic(str(source), str(target), weight_type=QuantType.QInt8)
    print(f"INT8 模型已输出：{target}")


if __name__ == "__main__":
    main()
