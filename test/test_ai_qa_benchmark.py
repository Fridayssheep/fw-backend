from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


KNOWLEDGE_CASES: list[dict[str, Any]] = [
    {
        "id": 1,
        "question": "SLS单级单吸离心泵在正常工作时，对环境温度、海拔高度和相对湿度有什么具体要求？",
        "expected_tokens": ["40", "1000", "95"],
    },
    {
        "id": 2,
        "question": "SLW系列单级单吸卧式离心泵相比普通卧式泵，其占地面积大约能减少多少？",
        "expected_tokens": ["30%"],
    },
    {
        "id": 3,
        "question": "根据《建筑节能基本术语标准》（GB/T 51140-2015），如何定义“绿色建筑”？",
        "expected_tokens": ["全寿命期", "节约资源", "保护环境", "健康"],
    },
    {
        "id": 4,
        "question": "《智能服务 预测性维护 通用要求》（GB/T 40571-2021）中，将预测性维护的实施分为了哪三类？",
        "expected_tokens": ["基于状态", "基于预测", "全生命周期"],
    },
    {
        "id": 5,
        "question": "按照《民用建筑电气设计标准》（GB 51348-2019）的规定，符合哪些情况的用电负荷应被定为一级负荷？",
        "expected_tokens": ["人身伤害", "重大损失", "重大影响", "秩序严重混乱"],
    },
    {
        "id": 6,
        "question": "根据《民用建筑能耗分类及表示方法》（GB/T 34913-2017），建筑能耗按用途可划分为哪四大类？",
        "expected_tokens": ["北方城镇建筑供暖能耗", "公共建筑能耗", "城镇居住建筑能耗", "农村居住建筑能耗"],
    },
    {
        "id": 7,
        "question": "在《空调通风系统运行管理标准》（GB 50365-2019）中，如果采用称质量法检验通风管道的清洗效果，其残留尘粒量应达到什么标准才算合格？",
        "expected_tokens": ["1.0", "g/m²"],
    },
    {
        "id": 8,
        "question": "根据《设施管理 运作与维护指南》（GB/T 41474-2022），设施的维护按其工作组织可分为哪两种策略类型？",
        "expected_tokens": ["计划性维护", "非计划性维护"],
    },
    {
        "id": 9,
        "question": "按照《建筑电气与智能化通用规范》（GB 55024-2022），对于作为应急电源的蓄电池组，日常维护中应定期进行什么测试？",
        "expected_tokens": ["放电测试"],
    },
    {
        "id": 10,
        "question": "《建筑节能与可再生能源利用通用规范》（GB 55015-2021）实施后，要求新建居住建筑和公共建筑的平均碳排放强度分别下降多少？",
        "expected_tokens": ["6.8", "10.5"],
    },
    {
        "id": 11,
        "question": "在《建筑节能与可再生能源利用通用规范》中，甲类公共建筑的划分标准是什么？",
        "expected_tokens": ["300", "1000", "甲类公共建筑"],
    },
    {
        "id": 12,
        "question": "山东省《公共建筑节能设计标准》（DB37/T 5155-2025）要求，建筑面积达到多少且采用集中空调的公共建筑必须设置建筑设备监控系统？",
        "expected_tokens": ["2万", "集中空调", "建筑设备监控系统"],
    },
    {
        "id": 13,
        "question": "按照山东省《教育机构能源消耗定额标准》（DB37/T 2671-2019），教育机构夏季和冬季的室内空调温度设置分别有何限制？",
        "expected_tokens": ["26", "20"],
    },
    {
        "id": 14,
        "question": "山东省《教育机构能源消耗定额标准》中，数据中心能量利用效率（EUE）的约束值、基准值和引导值分别是多少？",
        "expected_tokens": ["2.2", "1.6", "1.3"],
    },
    {
        "id": 15,
        "question": "《供暖通风与空气调节术语标准》（GB/T 50155-2015）中，对“单位风量耗功率”是如何定义的？",
        "expected_tokens": ["设计工况", "单位风量", "电功率", "Ws"],
    },
]

SCENARIO_CASES: list[dict[str, Any]] = [
    {
        "name": "data_query_explicit_range",
        "payload": {
            "question": "帮我查 Bear_education_Bob 在 2017-01-01 到 2017-01-07 的日用电趋势，应该调用什么接口？",
        },
    },
    {
        "name": "fault_analysis_with_context",
        "payload": {
            "question": "请结合当前页面上下文分析这段时间的用电异常原因，并给我排查建议。",
            "context": {
                "building_id": "Bear_education_Bob",
                "meter": "electricity",
                "time_range": {
                    "start": "2017-01-01T00:00:00Z",
                    "end": "2017-01-07T00:00:00Z",
                },
            },
        },
    },
    {
        "name": "mixed_fault_knowledge",
        "payload": {
            "question": "请结合当前页面上下文分析这段时间的用电异常原因，并顺便告诉我教育机构空调温度的标准要求。",
            "context": {
                "building_id": "Bear_education_Bob",
                "meter": "electricity",
                "time_range": {
                    "start": "2017-01-01T00:00:00Z",
                    "end": "2017-01-07T00:00:00Z",
                },
            },
        },
    },
    {
        "name": "mixed_knowledge_data",
        "payload": {
            "question": "请根据山东省地方标准说明教育机构夏季室内空调温度要求，并告诉我如果想查最近7天某建筑电耗趋势该调用什么接口？",
        },
    },
    {
        "name": "knowledge_policy",
        "payload": {
            "question": "按照山东省《教育机构能源消耗定额标准》，教育机构夏季和冬季的室内空调温度设置分别有何限制？",
        },
    },
]


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def report_path() -> Path:
    return Path(__file__).resolve().parent / "ai_qa_benchmark_report.json"


def _token_matches(answer: str, expected_tokens: list[str]) -> dict[str, bool]:
    lowered_answer = answer.lower()
    return {
        token: token.lower() in lowered_answer
        for token in expected_tokens
    }


def run_knowledge_case(client: httpx.Client, backend_base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    payload = {"question": case["question"]}
    started = time.perf_counter()
    response = client.post(f"{backend_base_url}/ai/qa", json=payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = response.json()

    result: dict[str, Any] = {
        "id": case["id"],
        "question": case["question"],
        "expected_tokens": case["expected_tokens"],
        "status_code": response.status_code,
        "elapsed_ms_client": elapsed_ms,
    }

    if response.status_code != 200 or not isinstance(body, dict):
        result["error"] = body
        return result

    answer = str(body.get("answer") or "")
    matches = _token_matches(answer, case["expected_tokens"])
    result.update(
        {
            "question_type": body.get("question_type"),
            "used_tools": [item.get("tool_name") for item in body.get("used_tools", []) if isinstance(item, dict)],
            "reference_count": len((body.get("references") or {}).get("knowledge") or []),
            "answer": answer,
            "matches": matches,
            "matched_count": sum(1 for value in matches.values() if value),
            "all_matched": all(matches.values()),
            "stage_timings_ms": (body.get("meta") or {}).get("stage_timings_ms") or {},
        }
    )
    return result


def run_scenario_case(client: httpx.Client, backend_base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    payload = case["payload"]
    started = time.perf_counter()
    response = client.post(f"{backend_base_url}/ai/qa", json=payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = response.json()

    result: dict[str, Any] = {
        "name": case["name"],
        "status_code": response.status_code,
        "elapsed_ms_client": elapsed_ms,
    }
    if response.status_code != 200 or not isinstance(body, dict):
        result["error"] = body
        return result

    references = body.get("references") or {}
    result.update(
        {
            "question_type": body.get("question_type"),
            "used_tools": [item.get("tool_name") for item in body.get("used_tools", []) if isinstance(item, dict)],
            "reference_counts": {
                "knowledge": len(references.get("knowledge") or []),
                "data": len(references.get("data") or []),
                "history_cases": len(references.get("history_cases") or []),
            },
            "suggested_actions": [item.get("target") for item in body.get("suggested_actions", []) if isinstance(item, dict)],
            "answer": body.get("answer"),
            "stage_timings_ms": (body.get("meta") or {}).get("stage_timings_ms") or {},
        }
    )
    return result


def build_summary(knowledge_cases: list[dict[str, Any]], scenario_cases: list[dict[str, Any]]) -> dict[str, Any]:
    knowledge_http_200 = [item for item in knowledge_cases if item.get("status_code") == 200]
    scenario_http_200 = [item for item in scenario_cases if item.get("status_code") == 200]
    return {
        "knowledge_total": len(knowledge_cases),
        "knowledge_http_200": len(knowledge_http_200),
        "knowledge_all_matched": sum(1 for item in knowledge_http_200 if item.get("all_matched") is True),
        "knowledge_partial_or_better": sum(1 for item in knowledge_http_200 if int(item.get("matched_count") or 0) > 0),
        "knowledge_zero_match": sum(1 for item in knowledge_http_200 if int(item.get("matched_count") or 0) == 0),
        "knowledge_errors": len(knowledge_cases) - len(knowledge_http_200),
        "scenario_total": len(scenario_cases),
        "scenario_http_200": len(scenario_http_200),
        "scenario_errors": len(scenario_cases) - len(scenario_http_200),
    }


def main() -> None:
    backend_base_url = get_required_env("BACKEND_BASE_URL").rstrip("/")
    timeout_seconds = float(os.getenv("AI_QA_BENCHMARK_TIMEOUT_SECONDS", "240"))

    with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
        knowledge_results = [
            run_knowledge_case(client, backend_base_url, case)
            for case in KNOWLEDGE_CASES
        ]
        scenario_results = [
            run_scenario_case(client, backend_base_url, case)
            for case in SCENARIO_CASES
        ]

    report = {
        "generated_at": datetime.now().isoformat(),
        "knowledge_cases": knowledge_results,
        "scenario_cases": scenario_results,
        "summary": build_summary(knowledge_results, scenario_results),
    }

    out_path = report_path()
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["summary"]["knowledge_http_200"] != report["summary"]["knowledge_total"]:
        sys.exit(1)
    if report["summary"]["scenario_http_200"] != report["summary"]["scenario_total"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
