"""CLI 入口：把命令行/JSON 请求转成 DocumentRequest、调用 generator、序列化结果。

退出码（产品方案 §11、CLAUDE.md "CLI 契约"，**稳定接口，禁止改**）：
- 0 = success
- 1 = error（阻断错误）
- 2 = 参数错误（CLI 参数不合法）
- 3 = needs_input

I/O 约定：
- `--json` 模式下 stdout **只输出 JSON**，所有日志/警告/进度走 stderr
- 非 `--json` 模式下输出人类可读摘要
- `--input request.json` 从 JSON 文件读取完整请求；其他 CLI 参数会**覆盖** JSON 中的同名字段
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import IO, Any

from ro_generator.errors import RoGeneratorError
from ro_generator.generator import generate
from ro_generator.models import DocumentRequest, GenerationResult, ValidationMessage
from ro_generator.source_index import SourceIndex

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NEEDS_INPUT = 3

VALID_DOCUMENT_TYPES = {"PI", "PO", "INVOICE", "PL"}
VALID_OUTPUT_FORMATS = {"xlsx", "zip"}
VALID_ON_CONFLICT = {"overwrite", "rename", "abort"}


# —————————————————————————————————————
# 公开入口
# —————————————————————————————————————


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """CLI 主入口。返回退出码（不调用 sys.exit，便于测试）。"""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse 在出错时自调 sys.exit；统一转 EXIT_USAGE
        return EXIT_USAGE if exc.code != 0 else EXIT_SUCCESS

    try:
        request = _build_request(args)
    except _UsageError as exc:
        print(f"[参数错误] {exc}", file=err)
        return EXIT_USAGE

    try:
        result = generate(request)
    except RoGeneratorError as exc:
        # generator 已捕获大多数情况，这里是兜底
        if args.json:
            payload = {
                "status": "error",
                "errors": [{"code": exc.code, "message": exc.message, "kind": "blocking_error"}],
            }
            print(json.dumps(payload, ensure_ascii=False), file=out)
        else:
            print(f"[错误] {exc.code}: {exc.message}", file=err)
        return EXIT_ERROR

    return _emit_result(result, json_output=args.json, stdout=out, stderr=err)


def cli_entry() -> None:
    """脚本入口（pyproject.toml `ro-generate = ro_generator.cli:cli_entry`）。"""
    sys.exit(main())


# —————————————————————————————————————
# 参数解析
# —————————————————————————————————————


class _UsageError(Exception):
    """CLI 参数错误，触发退出码 2。"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ro-generate",
        description="RO 单据装配工具：从 base 文件装配 PI / PO / Invoice / PL。",
    )
    parser.add_argument("--base", help="base xlsx 文件路径", default=None)
    parser.add_argument("--po", help="PO 号", default=None)
    parser.add_argument(
        "--docs",
        help="逗号分隔的单据类型，如 'invoice' 或 'pi,po,invoice,pl'",
        default=None,
    )
    parser.add_argument("--seller", default=None)
    parser.add_argument("--invoice-no", dest="invoice_no", default=None)
    parser.add_argument(
        "--output-format",
        dest="output_format",
        choices=sorted(VALID_OUTPUT_FORMATS),
        default=None,
    )
    parser.add_argument("--output-dir", dest="output_dir", default=None)
    parser.add_argument(
        "--on-conflict",
        dest="on_conflict",
        choices=sorted(VALID_ON_CONFLICT),
        default=None,
    )
    parser.add_argument(
        "--input",
        dest="input_file",
        help="读取 request.json 作为请求；与命令行参数合并，命令行优先",
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="启用 JSON stdout 模式（日志走 stderr，便于 Agent / 工作台后端调用）",
    )
    return parser


def _build_request(args: argparse.Namespace) -> DocumentRequest:
    raw: dict[str, Any] = {}
    if args.input_file:
        path = Path(args.input_file)
        if not path.exists():
            raise _UsageError(f"--input 文件不存在：{path}")
        try:
            with path.open(encoding="utf-8") as fp:
                raw = json.load(fp)
        except json.JSONDecodeError as exc:
            raise _UsageError(f"--input 文件 JSON 格式错误：{exc}") from exc
        if not isinstance(raw, dict):
            raise _UsageError("--input 的 JSON 根节点必须是对象")

    # buyer 由 _resolve_segment() 自动推导，输入中的 buyer 忽略
    raw.pop("buyer", None)

    # 命令行参数覆盖 JSON
    if args.base is not None:
        raw["base_file"] = args.base
    if args.po is not None:
        raw["po_no"] = args.po
    if args.docs is not None:
        raw["documents"] = [d.strip().upper() for d in args.docs.split(",") if d.strip()]
    if args.seller is not None:
        raw["seller"] = args.seller
    if args.invoice_no is not None:
        raw["invoice_no"] = args.invoice_no
    if args.output_format is not None:
        raw["output_format"] = args.output_format
    if args.output_dir is not None:
        raw["output_dir"] = args.output_dir
    if args.on_conflict is not None:
        raw["on_conflict"] = args.on_conflict

    # 必需字段
    if not raw.get("base_file"):
        raise _UsageError("缺少 --base 或 request.json.base_file")
    if not raw.get("po_no"):
        raise _UsageError("缺少 --po 或 request.json.po_no")
    documents = raw.get("documents")
    if not isinstance(documents, list) or not documents:
        raise _UsageError("缺少 --docs 或 request.json.documents")
    documents_upper = [str(d).upper() for d in documents]
    invalid = [d for d in documents_upper if d not in VALID_DOCUMENT_TYPES]
    if invalid:
        raise _UsageError(f"非法 documents 项：{invalid}；合法值：{sorted(VALID_DOCUMENT_TYPES)}")

    output_format = raw.get("output_format", "xlsx")
    if output_format not in VALID_OUTPUT_FORMATS:
        raise _UsageError(
            f"非法 output_format：{output_format!r}；合法值：{sorted(VALID_OUTPUT_FORMATS)}"
        )
    on_conflict = raw.get("on_conflict", "overwrite")
    if on_conflict not in VALID_ON_CONFLICT:
        raise _UsageError(f"非法 on_conflict：{on_conflict!r}；合法值：{sorted(VALID_ON_CONFLICT)}")

    return DocumentRequest(
        base_file=str(raw["base_file"]),
        po_no=str(raw["po_no"]),
        documents=tuple(documents_upper),  # type: ignore[arg-type]
        seller=_optional_str(raw.get("seller")),
        invoice_no=_optional_str(raw.get("invoice_no")),
        output_format=output_format,
        output_dir=str(raw.get("output_dir") or "outputs"),
        on_conflict=on_conflict,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# —————————————————————————————————————
# 结果输出
# —————————————————————————————————————


def _emit_result(
    result: GenerationResult,
    *,
    json_output: bool,
    stdout: IO[str],
    stderr: IO[str],
) -> int:
    if json_output:
        payload = _result_to_json_payload(result)
        print(json.dumps(payload, ensure_ascii=False, default=_json_default), file=stdout)
    else:
        _emit_human(result, stdout=stdout, stderr=stderr)

    return _exit_code_for(result.status)


def _exit_code_for(status: str) -> int:
    if status == "success":
        return EXIT_SUCCESS
    if status == "needs_input":
        return EXIT_NEEDS_INPUT
    return EXIT_ERROR


def _result_to_json_payload(result: GenerationResult) -> dict[str, Any]:
    """把 GenerationResult 转为可序列化 dict。

    `source_index` 序列化为 entries 列表，避免 SourceIndex 类型本身泄漏到 JSON 协议中。
    """
    payload: dict[str, Any] = {
        "status": result.status,
        "summary": result.summary,
        "files": list(result.files),
        "output_file": result.output_file,
        "errors": [_message_to_dict(m) for m in result.errors],
        "warnings": [_message_to_dict(m) for m in result.warnings],
        "missing_inputs": list(result.missing_inputs),
        "options": {k: list(v) for k, v in result.options.items()},
    }
    if isinstance(result.source_index, SourceIndex):
        payload["source_index"] = [
            {
                "doc_cell": cell,
                "source": {
                    "sheet": loc.sheet,
                    "row": loc.row,
                    "field": loc.field,
                    "is_computed": loc.is_computed,
                },
            }
            for cell, loc in result.source_index
        ]
    else:
        payload["source_index"] = []
    return payload


def _message_to_dict(message: ValidationMessage) -> dict[str, Any]:
    return asdict(message)


def _json_default(obj: Any) -> Any:
    """处理 Decimal、Path 等 json 不识别的类型。"""
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"unserializable type: {type(obj).__name__}")


def _emit_human(
    result: GenerationResult,
    *,
    stdout: IO[str],
    stderr: IO[str],
) -> None:
    """非 JSON 模式：人类可读输出。

    按状态用不同的语气，stderr 写警告/错误细节，stdout 写主要内容。
    """
    if result.status == "success":
        print("✓ 装配成功", file=stdout)
        if result.output_file:
            print(f"  输出文件：{result.output_file}", file=stdout)
        if result.summary:
            for k, v in result.summary.items():
                print(f"  {k}: {v}", file=stdout)
        if result.warnings:
            print(f"\n[警告] 共 {len(result.warnings)} 条：", file=stderr)
            for m in result.warnings:
                _print_message(m, file=stderr)
        return

    if result.status == "needs_input":
        print("需要补充信息：", file=stdout)
        for key in result.missing_inputs:
            opts = result.options.get(key, ())
            print(f"  {key}", file=stdout)
            for o in opts:
                value = o.get("value", "")
                label = o.get("label", "")
                print(f"    - {value}: {label}", file=stdout)
        return

    # error
    print(f"✗ 装配失败（{len(result.errors)} 条阻断错误）", file=stderr)
    for m in result.errors:
        _print_message(m, file=stderr)
    if result.warnings:
        print(f"\n并伴随 {len(result.warnings)} 条警告：", file=stderr)
        for m in result.warnings:
            _print_message(m, file=stderr)


def _print_message(m: ValidationMessage, *, file: IO[str]) -> None:
    location_parts = []
    if m.sheet:
        location_parts.append(f"sheet={m.sheet}")
    if m.row is not None:
        location_parts.append(f"row={m.row}")
    if m.field:
        location_parts.append(f"field={m.field}")
    location = " ".join(location_parts)
    severity = f" [{m.severity}]" if m.severity else ""
    print(f"  - {m.code}{severity}: {m.message}", file=file)
    if location:
        print(f"      ({location})", file=file)


__all__ = [
    "EXIT_ERROR",
    "EXIT_NEEDS_INPUT",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "cli_entry",
    "main",
]
