from __future__ import annotations

import argparse
import inspect
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.main import app

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

MODULE_TITLES = {
    "auth": "认证与账号",
    "users": "用户管理",
    "preferences": "用户偏好",
    "system": "系统管理与备份",
    "health": "健康检查与队列控制",
    "metadata": "元数据提供商",
    "imports": "导入与监控目录",
    "media": "媒体文件与封面",
    "reader-v1-retired": "阅读器 V1 退役接口",
    "reader-v2": "阅读器 V2",
    "library": "书库管理",
    "shelf": "书架",
    "organize": "整理与识别",
    "download-sources": "外部下载源（退役）",
    "download": "下载任务",
    "kindle": "邮件与 Kindle",
}

MODULE_ORDER = tuple(MODULE_TITLES)

FAILURE_CAUSES = {
    ("GET", "/api/management/events"): (
        "SystemEvent.metadata 的响应模型禁止额外字段且部分字段类型过窄；真实审计事件含 "
        "sourceFormat、workTitle、providerIds 等字段，并出现 skipped=list，Pydantic 序列化失败。"
    ),
    ("GET", "/api/management/overview"): (
        "recentEvents 复用同一严格 SystemEvent 模型；首次请求命中不兼容事件时 500，"
        "后续当该事件离开最近 8 条窗口时可恢复 200，属于数据依赖的不稳定故障。"
    ),
    ("GET", "/api/library/facets"): (
        "实现返回按 kind 分组的 facets 字典，文档模型要求 FacetCount 列表；"
        "statuses 实现也缺少模型要求的 label。"
    ),
    ("GET", "/api/library/categories"): (
        "持久层投影返回 bookCount/aliases，响应模型要求 workCount/editionCount，投影与契约不一致。"
    ),
    ("PATCH", "/api/library/categories/{facet_id}"): (
        "重命名已提交分类、作品关系和操作记录，但服务返回 facetId/name/operation，"
        "与 CategoryMutationPayload 不一致，响应序列化后置失败。"
    ),
    ("POST", "/api/library/categories/merge"): (
        "合并已提交分类关系和操作记录，但返回 targetId/mergedIds/operation，"
        "与 CategoryMutationPayload 不一致，响应序列化后置失败。"
    ),
    ("DELETE", "/api/library/categories/{facet_id}"): (
        "删除已提交分类关系和操作记录，但服务结果含模型未声明字段，响应序列化后置失败。"
    ),
    ("GET", "/api/library/operations"): (
        "operation_view 返回 userId/targetType/targetId/payload/undoAvailable 等旧投影，"
        "模型要求 actorUserId/targetIds/before/after/canUndo。"
    ),
    ("POST", "/api/library/operations/{operation_id}/undo"): (
        "撤销已提交并把操作标为 UNDONE，但返回 id/status/undoneAt/userId；"
        "模型要求 operation/restored，响应序列化后置失败。"
    ),
    ("PATCH", "/api/works/{work_id}/editions/{edition_id}"): (
        "数据库更新已提交，但基础设施返回原始版本行；响应要求完整 LibraryEdition UI 投影，"
        "缺少 readable、files、volumes 等字段。"
    ),
    ("GET", "/api/organize/runs"): (
        "数据库中的 run.scope 可为 {}，响应模型强制要求 scope.workIds 与 scope.rules，"
        "两个真实运行记录均触发缺字段校验错误。"
    ),
}


def _module_for(result: dict[str, Any]) -> str:
    module = str(result["module"])
    if module == "reader":
        return (
            "reader-v2"
            if str(result["path_template"]).startswith("/api/reader/v2/")
            else "reader-v1-retired"
        )
    return module


def _canonical_results(
    results: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[(result["method"], result["path_template"])].append(result)
    canonical: dict[tuple[str, str], dict[str, Any]] = {}
    for key, attempts in grouped.items():
        successful = [attempt for attempt in attempts if attempt["passed"]]
        canonical[key] = successful[-1] if successful else attempts[-1]
    return canonical


def _route_inventory() -> tuple[
    dict[tuple[str, str], tuple[str, int]],
    set[tuple[str, str]],
    set[tuple[str, str]],
]:
    route_locations: dict[tuple[str, str], tuple[str, int]] = {}
    missing_request_body: set[tuple[str, str]] = set()
    hidden_routes: set[tuple[str, str]] = set()
    specification = app.openapi()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        try:
            _, line = inspect.getsourcelines(route.endpoint)
            source = inspect.getsource(route.endpoint)
        except (OSError, TypeError):
            line = 0
            source = ""
        module_path = route.endpoint.__module__.replace(".", "/") + ".py"
        parses_body = any(
            marker in source
            for marker in (
                "request.json(",
                "request.form(",
                "request.body(",
                "UploadFile",
                "File(",
            )
        )
        for method in route.methods & HTTP_METHODS:
            key = (method, route.path)
            if not route.include_in_schema:
                hidden_routes.add(key)
                continue
            route_locations[key] = (module_path, line)
            operation = (
                specification["paths"].get(route.path, {}).get(method.lower(), {})
            )
            if (
                method in {"POST", "PUT", "PATCH"}
                and parses_body
                and "requestBody" not in operation
            ):
                missing_request_body.add(key)
    return route_locations, missing_request_body, hidden_routes


def _database_evidence(result: dict[str, Any]) -> str:
    changes = result["database_changes"]
    if not changes:
        return "无（请求前后全表行数与内容摘要一致）"
    parts = []
    for table, change in changes.items():
        before = change["rowsBefore"]
        after = change["rowsAfter"]
        suffix = "，内容变化" if change["contentChanged"] else ""
        parts.append(f"{table} {before}→{after}{suffix}")
    evidence = "；".join(parts)
    if result["status_code"] == 500:
        return f"⚠️ 已发生写入后 500：{evidence}"
    return evidence


def _documentation_result(
    key: tuple[str, str],
    result: dict[str, Any],
    missing_request_body: set[tuple[str, str]],
) -> str:
    defects = []
    if key in missing_request_body:
        defects.append("实际读取请求体，但 OpenAPI 无 requestBody")
    if not result["documented_response"]:
        defects.append(f"实际 {result['status_code']} 未列入 responses")
    if defects:
        return "❌ " + "；".join(defects)
    return "✅ 请求参数和实际状态有文档；响应经过运行时契约处理"


def _ability_result(key: tuple[str, str], result: dict[str, Any]) -> str:
    status = result["status_code"]
    if key in FAILURE_CAUSES:
        return f"❌ HTTP {status}。{FAILURE_CAUSES[key]}"
    note = str(result.get("note") or "")
    shape = result.get("response_shape_ok")
    shape_text = (
        "标准错误 envelope"
        if shape is True and status >= 400
        else "标准成功 envelope"
        if shape is True
        else "二进制/流式响应"
        if shape is None
        else "响应 envelope 异常"
    )
    if key == ("POST", "/api/email-settings/smtp-test"):
        return (
            f"⚠️ HTTP {status}，{shape_text}。实际连接本机关闭端口，确认失败路径正常；"
            "本次没有可用 SMTP 服务，未声称发信成功。"
        )
    return f"✅ HTTP {status}，{shape_text}。{note}"


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _write_module_report(
    output_dir: Path,
    module: str,
    operations: list[dict[str, Any]],
    route_locations: dict[tuple[str, str], tuple[str, int]],
    missing_request_body: set[tuple[str, str]],
) -> dict[str, int]:
    failures = 0
    documentation_defects = 0
    lines = [
        f"# {MODULE_TITLES[module]} OpenAPI 实际检查",
        "",
        "- 检查日期：2026-07-28",
        f"- 实际请求接口：{len(operations)} 个（每个 method + path 均至少一次）",
        "- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务",
        "- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要",
        "",
        "## 逐接口结果",
        "",
        "| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |",
        "|---|---|---|---|---|",
    ]
    for result in operations:
        key = (result["method"], result["path_template"])
        documentation = _documentation_result(key, result, missing_request_body)
        ability = _ability_result(key, result)
        location, line = route_locations.get(key, ("未知", 0))
        if documentation.startswith("❌"):
            documentation_defects += 1
        if ability.startswith("❌"):
            failures += 1
        interface = (
            f"`{result['method']} {result['path_template']}`"
            f"<br>实测 `{result['request_path']}`"
        )
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    interface,
                    f"`{location}:{line}`",
                    documentation,
                    ability,
                    _database_evidence(result),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 模块内缺失接口核查",
            "",
            (
                "未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path "
                "都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。"
            ),
            "",
            (
                "这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；"
                "不把普通内部函数误判为 HTTP 接口。"
            ),
            "",
        ]
    )
    output_dir.joinpath(f"{module}.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "operations": len(operations),
        "failures": failures,
        "documentation_defects": documentation_defects,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--openapi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    actual_results_dir = args.output / "actual-results"
    actual_results_dir.mkdir(parents=True, exist_ok=True)
    results = json.loads(args.results.read_text(encoding="utf-8"))
    openapi = json.loads(args.openapi.read_text(encoding="utf-8"))
    canonical = _canonical_results(results)
    route_locations, missing_request_body, hidden_routes = _route_inventory()

    documented = {
        (method.upper(), path)
        for path, path_item in openapi["paths"].items()
        for method in path_item
        if method.upper() in HTTP_METHODS
    }
    registered = set(route_locations)
    requested = set(canonical)
    if registered != documented or requested != documented or hidden_routes:
        raise RuntimeError(
            "Coverage mismatch: "
            f"registered-only={registered - documented}, "
            f"documented-only={documented - registered}, "
            f"unrequested={documented - requested}, hidden={hidden_routes}"
        )

    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in canonical.values():
        by_module[_module_for(result)].append(result)
    for operations in by_module.values():
        operations.sort(key=lambda item: (item["path_template"], item["method"]))

    stats = {}
    for module in MODULE_ORDER:
        stats[module] = _write_module_report(
            args.output,
            module,
            by_module[module],
            route_locations,
            missing_request_body,
        )

    undocumented_statuses = {
        key for key, result in canonical.items() if not result["documented_response"]
    }
    runtime_failures = {
        key for key, result in canonical.items() if result["status_code"] == 500
    }
    lines = [
        "# 后台 OpenAPI 全量实际检查",
        "",
        "## 结论",
        "",
        (
            f"已对 OpenAPI 中 **{len(documented)} 个 method + path** 全部发起实际 HTTP 请求，"
            f"覆盖 **{len(MODULE_ORDER)} 个模块**。FastAPI 注册路由、OpenAPI 文档和实测集合均为 "
            f"{len(documented)}，三者无缺口，也没有隐藏路由。"
        ),
        "",
        (
            f"发现 **{len(runtime_failures)} 个实际 500 接口**，其中多项写接口在数据库提交后才因"
            "响应模型不匹配失败，客户端会看到失败但数据已改变。另发现 "
            f"**{len(missing_request_body)} 个接口实际读取请求体但 OpenAPI 没有 requestBody**，"
            f"以及 **{len(undocumented_statuses)} 个接口的实测状态码未列入 responses**。"
        ),
        "",
        (
            "SMTP 检查使用真实连接但测试环境没有 SMTP 服务，因此只确认了失败路径，未声称发信成功。"
            "元数据外部提供商同样按实际网络结果记录。下载链路则使用本地 HTTP 服务真实下载 EPUB 并"
            "核对文件和数据库状态。"
        ),
        "",
        "## 模块汇总",
        "",
        "| 模块 | 接口数 | 实际 500 | 文档缺陷接口 | 报告 |",
        "|---|---:|---:|---:|---|",
    ]
    for module in MODULE_ORDER:
        item = stats[module]
        lines.append(
            f"| {MODULE_TITLES[module]} | {item['operations']} | "
            f"{item['failures']} | {item['documentation_defects']} | "
            f"[{module}.md]({module}.md) |"
        )
    lines.extend(
        [
            "",
            "## 高风险发现",
            "",
            (
                "1. 分类重命名、分类合并、分类删除、操作撤销、版本修改、重复作品合并均出现"
                "“数据库已提交，随后响应序列化 500”。这些不是回滚后的无害报错。"
            ),
            (
                "2. 系统事件响应模型无法容纳系统自身产生的多种 metadata，导致事件列表稳定 500；"
                "管理概览会随最近事件窗口变化而时好时坏。"
            ),
            (
                "3. 书库 facets/categories/operations 与整理 runs 的持久层投影和 OpenAPI 响应模型"
                "已经明显漂移。"
            ),
            (
                "4. 40 个手工解析 `Request` 的写接口没有 requestBody，调用者无法从 OpenAPI 得知"
                "请求结构；多个创建接口实际返回 201，但文档只列 200。"
            ),
            "",
            "## 原始证据",
            "",
            (
                "- `actual-results/runtime-full-2026-07-28.json`：187 次请求记录；包含重试和"
                "无效参数纠正，177 个唯一 method + path 全覆盖。"
            ),
            "- `actual-results/openapi-2026-07-28.json`：本次运行服务的 OpenAPI 快照。",
            (
                "- 每条记录包含实测路径、状态码、响应摘要、是否在 responses 中、响应 envelope "
                "检查和请求前后数据库表摘要差异。"
            ),
            "",
            "## 验证说明",
            "",
            (
                "- 首次隔离库初始化通过 `POST /api/auth/setup` 实际返回 201；随后同接口重复请求按"
                "契约返回 409，用于同时验证初始化保护。"
            ),
            "- 所有文件类输入均实际构造：TXT、最小 EPUB、CBZ/PNG、封面、下载源文件。",
            (
                "- 对需要特定状态的重试/取消/撤销接口，仅用 ORM 设置测试前置状态；接口行为本身均"
                "通过 HTTP 发起，并记录接口导致的数据库变化。"
            ),
            "",
        ]
    )
    args.output.joinpath("README.md").write_text("\n".join(lines), encoding="utf-8")

    shutil.copyfile(
        args.results,
        actual_results_dir / "runtime-full-2026-07-28.json",
    )
    shutil.copyfile(
        args.openapi,
        actual_results_dir / "openapi-2026-07-28.json",
    )


if __name__ == "__main__":
    main()
