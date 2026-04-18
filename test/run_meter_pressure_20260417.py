from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen


@dataclass(frozen=True)
class EndpointCase:
    name: str
    method: str
    path_template: str
    params: dict[str, Any]
    expected_statuses: tuple[int, ...]
    weight: int


@dataclass(frozen=True)
class Stage:
    name: str
    duration_sec: int
    concurrency: int


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * ratio)
    return ordered[index]


def compact_json(payload: object, max_len: int = 160) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def safe_json_loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def call_api(
    *,
    base_url: str,
    method: str,
    path: str,
    params: dict[str, Any] | None,
    timeout_sec: int,
) -> dict[str, Any]:
    query = urlencode(params or {}, doseq=True)
    url = f"{base_url}{path}" + (f"?{query}" if query else "")
    request = Request(url=url, method=method.upper())

    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            raw = response.read()
            status = int(response.status)
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
    except URLError as exc:
        return {
            "status": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "body": None,
            "json": None,
            "content_type": None,
            "network_error": str(exc),
            "url": url,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "body": None,
            "json": None,
            "content_type": None,
            "network_error": str(exc),
            "url": url,
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    body = raw.decode("utf-8", errors="replace") if raw else ""

    return {
        "status": status,
        "duration_ms": elapsed_ms,
        "body": body,
        "json": safe_json_loads(body) if body else None,
        "content_type": content_type,
        "network_error": None,
        "url": url,
    }


def bootstrap_context(base_url: str, timeout_sec: int) -> dict[str, str]:
    health = call_api(base_url=base_url, method="GET", path="/health", params=None, timeout_sec=timeout_sec)
    if health.get("status") != 200:
        raise RuntimeError(f"Health check failed: {health}")

    buildings = call_api(
        base_url=base_url,
        method="GET",
        path="/buildings",
        params={"page": 1, "page_size": 5},
        timeout_sec=timeout_sec,
    )
    if buildings.get("status") != 200:
        raise RuntimeError(f"Bootstrap /buildings failed: {buildings}")

    building_items = (buildings.get("json") or {}).get("items") or []
    if not building_items:
        raise RuntimeError("No building returned by /buildings")
    building_id = str(building_items[0].get("building_id") or "").strip()
    if not building_id:
        raise RuntimeError("Invalid building_id in /buildings response")

    meters = call_api(
        base_url=base_url,
        method="GET",
        path="/meters",
        params={"building_id": building_id, "page": 1, "page_size": 5},
        timeout_sec=timeout_sec,
    )
    if meters.get("status") != 200:
        raise RuntimeError(f"Bootstrap /meters failed: {meters}")

    meter_items = (meters.get("json") or {}).get("items") or []
    if not meter_items:
        meters = call_api(
            base_url=base_url,
            method="GET",
            path="/meters",
            params={"page": 1, "page_size": 5},
            timeout_sec=timeout_sec,
        )
        meter_items = (meters.get("json") or {}).get("items") or []
    if not meter_items:
        raise RuntimeError("No meter returned by /meters")

    meter_id = str(meter_items[0].get("meter_id") or "").strip()
    meter_type = str(meter_items[0].get("meter_type") or "electricity").strip() or "electricity"
    if not meter_id:
        raise RuntimeError("Invalid meter_id in /meters response")

    return {
        "building_id": building_id,
        "meter_id": meter_id,
        "meter_type": meter_type,
    }


def build_cases(ctx: dict[str, str]) -> list[EndpointCase]:
    building_id = ctx["building_id"]
    meter_id = ctx["meter_id"]
    meter_type = ctx["meter_type"]

    return [
        EndpointCase(
            name="meters_list_default",
            method="GET",
            path_template="/meters",
            params={"page": 1, "page_size": 20},
            expected_statuses=(200,),
            weight=20,
        ),
        EndpointCase(
            name="meters_list_by_building",
            method="GET",
            path_template="/meters",
            params={"building_id": building_id, "page": 1, "page_size": 20},
            expected_statuses=(200,),
            weight=10,
        ),
        EndpointCase(
            name="meters_list_by_type",
            method="GET",
            path_template="/meters",
            params={"meter_type": meter_type, "page": 1, "page_size": 20},
            expected_statuses=(200,),
            weight=8,
        ),
        EndpointCase(
            name="meter_detail_valid",
            method="GET",
            path_template="/meters/{meterId}",
            params={},
            expected_statuses=(200,),
            weight=18,
        ),
        EndpointCase(
            name="meter_alarms_valid",
            method="GET",
            path_template="/meters/{meterId}/alarms",
            params={"page": 1, "page_size": 20},
            expected_statuses=(200,),
            weight=14,
        ),
        EndpointCase(
            name="meter_maintenance_valid",
            method="GET",
            path_template="/meters/{meterId}/maintenance-records",
            params={"page": 1, "page_size": 20},
            expected_statuses=(200,),
            weight=12,
        ),
        EndpointCase(
            name="meter_detail_invalid_format",
            method="GET",
            path_template="/meters/invalid-meter-id",
            params={},
            expected_statuses=(422,),
            weight=2,
        ),
        EndpointCase(
            name="meter_detail_not_found",
            method="GET",
            path_template="/meters/NO_SUCH_BUILDING_404::electricity",
            params={},
            expected_statuses=(404,),
            weight=2,
        ),
        EndpointCase(
            name="meters_list_invalid_page",
            method="GET",
            path_template="/meters",
            params={"page": 0, "page_size": 20},
            expected_statuses=(422,),
            weight=2,
        ),
    ]


def resolve_path(path_template: str, meter_id: str) -> str:
    return path_template.replace("{meterId}", quote(meter_id, safe=""))


def summarize_stage(stage_name: str, rows: list[dict[str, Any]], elapsed_sec: float) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["name"]].append(row)

    endpoint_stats: list[dict[str, Any]] = []
    for name, items in grouped.items():
        durations = [float(item["duration_ms"]) for item in items]
        success_count = sum(1 for item in items if item["ok"])
        status_dist: dict[str, int] = defaultdict(int)
        for item in items:
            status_dist[str(item.get("status"))] += 1

        errors = [item for item in items if not item["ok"]][:5]
        endpoint_stats.append(
            {
                "name": name,
                "calls": len(items),
                "success_rate": round(success_count / len(items), 4),
                "avg_ms": round(statistics.mean(durations), 2),
                "p50_ms": round(percentile(durations, 0.50), 2),
                "p95_ms": round(percentile(durations, 0.95), 2),
                "p99_ms": round(percentile(durations, 0.99), 2),
                "min_ms": round(min(durations), 2),
                "max_ms": round(max(durations), 2),
                "status_distribution": dict(status_dist),
                "error_samples": [
                    {
                        "status": err.get("status"),
                        "error": err.get("error"),
                        "body_preview": (err.get("body") or "")[:180],
                        "url": err.get("url"),
                    }
                    for err in errors
                ],
            }
        )

    endpoint_stats.sort(key=lambda item: item["avg_ms"], reverse=True)

    all_durations = [float(row["duration_ms"]) for row in rows]
    total_calls = len(rows)
    total_success = sum(1 for row in rows if row["ok"])
    return {
        "stage": stage_name,
        "elapsed_sec": round(elapsed_sec, 2),
        "total_calls": total_calls,
        "success_calls": total_success,
        "success_rate": round((total_success / total_calls), 4) if total_calls else 0.0,
        "qps": round(total_calls / elapsed_sec, 2) if elapsed_sec > 0 else 0.0,
        "avg_ms": round(statistics.mean(all_durations), 2) if all_durations else 0.0,
        "p95_ms": round(percentile(all_durations, 0.95), 2) if all_durations else 0.0,
        "p99_ms": round(percentile(all_durations, 0.99), 2) if all_durations else 0.0,
        "endpoints": endpoint_stats,
    }


def run_stage(
    *,
    base_url: str,
    stage: Stage,
    cases: list[EndpointCase],
    meter_id: str,
    timeout_sec: int,
    progress_interval_sec: int,
) -> dict[str, Any]:
    weighted_cases: list[EndpointCase] = []
    for case in cases:
        weighted_cases.extend([case] * case.weight)

    stop_at = time.time() + stage.duration_sec
    records: list[dict[str, Any]] = []
    lock = threading.Lock()

    def worker(seed: int) -> None:
        rng = random.Random(seed)
        while time.time() < stop_at:
            case = rng.choice(weighted_cases)
            path = resolve_path(case.path_template, meter_id)
            response = call_api(
                base_url=base_url,
                method=case.method,
                path=path,
                params=case.params,
                timeout_sec=timeout_sec,
            )
            status = response.get("status")
            ok = status in case.expected_statuses
            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "stage": stage.name,
                "name": case.name,
                "method": case.method,
                "path": path,
                "params": case.params,
                "expected_statuses": case.expected_statuses,
                "status": status,
                "ok": ok,
                "duration_ms": response.get("duration_ms"),
                "error": response.get("network_error"),
                "body": response.get("body") or "",
                "url": response.get("url"),
            }
            with lock:
                records.append(record)

    threads = [threading.Thread(target=worker, args=(index + int(time.time()),), daemon=True) for index in range(stage.concurrency)]

    started = time.time()
    for thread in threads:
        thread.start()

    while any(thread.is_alive() for thread in threads):
        elapsed = int(time.time() - started)
        with lock:
            total = len(records)
            success = sum(1 for item in records if item["ok"])
            recent = records[-200:] if records else []
        success_rate = (success / total * 100.0) if total else 0.0
        recent_avg = statistics.mean([float(item["duration_ms"]) for item in recent]) if recent else 0.0
        print(
            f"[STAGE_PROGRESS] stage={stage.name} elapsed={elapsed}s total={total} success={success_rate:.2f}% recent_avg_ms={recent_avg:.2f}",
            flush=True,
        )
        time.sleep(min(progress_interval_sec, 5))
        if elapsed >= stage.duration_sec and not any(thread.is_alive() for thread in threads):
            break

    for thread in threads:
        thread.join(timeout=5)

    elapsed_sec = max(time.time() - started, 0.001)
    summary = summarize_stage(stage.name, records, elapsed_sec)
    return {
        "stage": {
            "name": stage.name,
            "duration_sec": stage.duration_sec,
            "concurrency": stage.concurrency,
        },
        "summary": summary,
        "details": records,
    }


def render_markdown(meta: dict[str, Any], stages: list[dict[str, Any]], global_summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Meter 接口专项压测报告")
    lines.append("")
    lines.append("## 1. 测试配置")
    lines.append(f"- 生成时间: {meta['generated_at']}")
    lines.append(f"- Base URL: {meta['base_url']}")
    lines.append(f"- 请求超时: {meta['timeout_sec']} 秒")
    lines.append(f"- 测试阶段数: {len(stages)}")
    lines.append(f"- 目标接口: /meters, /meters/{{meterId}}, /meters/{{meterId}}/alarms, /meters/{{meterId}}/maintenance-records")
    lines.append("")

    lines.append("## 2. 全局汇总")
    lines.append(f"- 总请求: {global_summary['total_calls']}")
    lines.append(f"- 总成功率: {global_summary['success_rate'] * 100:.2f}%")
    lines.append(f"- 全局 QPS: {global_summary['qps']}")
    lines.append(f"- 全局平均响应: {global_summary['avg_ms']} ms")
    lines.append(f"- 全局 P95/P99: {global_summary['p95_ms']} / {global_summary['p99_ms']} ms")
    lines.append("")

    lines.append("## 3. 分阶段结果")
    lines.append("| 阶段 | 并发 | 时长(s) | 调用数 | 成功率 | QPS | avg(ms) | p95(ms) | p99(ms) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for stage in stages:
        stage_meta = stage["stage"]
        stage_sum = stage["summary"]
        lines.append(
            f"| {stage_meta['name']} | {stage_meta['concurrency']} | {stage_meta['duration_sec']} | {stage_sum['total_calls']} | {stage_sum['success_rate'] * 100:.2f}% | {stage_sum['qps']} | {stage_sum['avg_ms']} | {stage_sum['p95_ms']} | {stage_sum['p99_ms']} |"
        )
    lines.append("")

    lines.append("## 4. 端点明细（按平均耗时降序）")
    for stage in stages:
        stage_meta = stage["stage"]
        lines.append(f"### {stage_meta['name']} (concurrency={stage_meta['concurrency']})")
        lines.append("| 场景 | 调用 | 成功率 | avg | p50 | p95 | p99 | max | 状态码分布 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for endpoint in stage["summary"]["endpoints"]:
            lines.append(
                f"| `{endpoint['name']}` | {endpoint['calls']} | {endpoint['success_rate'] * 100:.2f}% | {endpoint['avg_ms']} | {endpoint['p50_ms']} | {endpoint['p95_ms']} | {endpoint['p99_ms']} | {endpoint['max_ms']} | `{endpoint['status_distribution']}` |"
            )
        lines.append("")

    lines.append("## 5. 失败样本（最多每阶段 8 条）")
    for stage in stages:
        failed_rows = [item for item in stage["details"] if not item.get("ok")][:8]
        lines.append(f"### {stage['stage']['name']}")
        if not failed_rows:
            lines.append("- 无失败样本。")
            lines.append("")
            continue
        for row in failed_rows:
            lines.append(
                f"- `{row['name']}` status={row['status']} expected={row['expected_statuses']} error={row['error']} body={compact_json((row.get('body') or '')[:180])}"
            )
        lines.append("")

    return "\n".join(lines)


def build_global_summary(stage_results: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    total_elapsed = 0.0
    for stage in stage_results:
        all_rows.extend(stage.get("details", []))
        total_elapsed += float(stage["summary"]["elapsed_sec"])

    durations = [float(row["duration_ms"]) for row in all_rows]
    success_count = sum(1 for row in all_rows if row.get("ok"))
    total_calls = len(all_rows)
    return {
        "total_calls": total_calls,
        "success_rate": round((success_count / total_calls), 4) if total_calls else 0.0,
        "qps": round(total_calls / total_elapsed, 2) if total_elapsed > 0 else 0.0,
        "avg_ms": round(statistics.mean(durations), 2) if durations else 0.0,
        "p95_ms": round(percentile(durations, 0.95), 2) if durations else 0.0,
        "p99_ms": round(percentile(durations, 0.99), 2) if durations else 0.0,
        "elapsed_sec": round(total_elapsed, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Meter endpoint comprehensive pressure test")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--timeout-sec", type=int, default=12)
    parser.add_argument("--progress-interval-sec", type=int, default=15)
    parser.add_argument("--tag", default=now_tag())
    parser.add_argument("--stage1-duration", type=int, default=60)
    parser.add_argument("--stage2-duration", type=int, default=90)
    parser.add_argument("--stage3-duration", type=int, default=120)
    parser.add_argument("--stage4-duration", type=int, default=180)
    parser.add_argument("--stage1-concurrency", type=int, default=8)
    parser.add_argument("--stage2-concurrency", type=int, default=16)
    parser.add_argument("--stage3-concurrency", type=int, default=32)
    parser.add_argument("--stage4-concurrency", type=int, default=24)
    args = parser.parse_args()

    out_dir = Path(__file__).resolve().parent
    json_path = out_dir / f"meter_pressure_results_{args.tag}.json"
    md_path = out_dir / f"meter_pressure_report_{args.tag}.md"

    context = bootstrap_context(args.base_url, args.timeout_sec)
    print(f"[BOOTSTRAP] building_id={context['building_id']} meter_id={context['meter_id']} meter_type={context['meter_type']}", flush=True)

    cases = build_cases(context)
    stages = [
        Stage(name="ramp_8", duration_sec=args.stage1_duration, concurrency=args.stage1_concurrency),
        Stage(name="ramp_16", duration_sec=args.stage2_duration, concurrency=args.stage2_concurrency),
        Stage(name="stress_32", duration_sec=args.stage3_duration, concurrency=args.stage3_concurrency),
        Stage(name="soak_24", duration_sec=args.stage4_duration, concurrency=args.stage4_concurrency),
    ]

    stage_results: list[dict[str, Any]] = []
    for stage in stages:
        print(
            f"[STAGE_START] name={stage.name} duration={stage.duration_sec}s concurrency={stage.concurrency}",
            flush=True,
        )
        stage_result = run_stage(
            base_url=args.base_url,
            stage=stage,
            cases=cases,
            meter_id=context["meter_id"],
            timeout_sec=args.timeout_sec,
            progress_interval_sec=args.progress_interval_sec,
        )
        stage_results.append(stage_result)
        stage_summary = stage_result["summary"]
        print(
            f"[STAGE_DONE] name={stage.name} calls={stage_summary['total_calls']} success={stage_summary['success_rate']*100:.2f}% qps={stage_summary['qps']} p95={stage_summary['p95_ms']}ms",
            flush=True,
        )

    global_summary = build_global_summary(stage_results)
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "timeout_sec": args.timeout_sec,
        "context": context,
        "stages": [stage.__dict__ for stage in stages],
        "global_summary": global_summary,
    }

    payload = {
        "meta": meta,
        "stage_results": [
            {
                "stage": stage["stage"],
                "summary": stage["summary"],
                "details": stage["details"],
            }
            for stage in stage_results
        ],
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(meta, stage_results, global_summary), encoding="utf-8")

    print(f"[DONE] JSON_REPORT={json_path}")
    print(f"[DONE] MD_REPORT={md_path}")


if __name__ == "__main__":
    main()
