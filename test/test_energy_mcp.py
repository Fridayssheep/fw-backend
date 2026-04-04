from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
MCP_SERVER_PATH = BASE_DIR / 'ai' / 'mcp' / 'server.py'
REPORT_JSON_PATH = BASE_DIR / 'test' / 'energy_mcp_smoke_report.json'
REPORT_MD_PATH = BASE_DIR / 'test' / 'energy_mcp_smoke_report.md'
BACKEND_BASE_URL = 'http://127.0.0.1:8000'
TIME_START = '2017-01-01T00:00:00+00:00'
TIME_END = '2017-01-07T00:00:00+00:00'


def load_mcp_module():
    spec = importlib.util.spec_from_file_location('energy_mcp_server', MCP_SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Failed to load MCP module from {MCP_SERVER_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_get(path: str, **params: Any) -> dict[str, Any]:
    with httpx.Client(base_url=BACKEND_BASE_URL, timeout=30.0) as client:
        response = client.get(path, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()


def find_building_candidates() -> dict[str, str]:
    buildings = http_get('/buildings', page=1, page_size=120).get('items', [])
    electricity_buildings: list[str] = []
    cop_building: str | None = None
    for building in buildings:
        building_id = building['building_id']
        detail = http_get(f'/buildings/{building_id}')
        available_meters = {
            item['meter'] for item in detail.get('meters', []) if item.get('available')
        }
        if 'electricity' in available_meters:
            electricity_buildings.append(building_id)
        if (
            'electricity' in available_meters
            and 'chilledwater' in available_meters
            and cop_building is None
        ):
            cop_payload = http_get(
                '/energy/cop',
                building_id=building_id,
                start_time=TIME_START,
                end_time=TIME_END,
                granularity='day',
            )
            if cop_payload.get('points'):
                cop_building = building_id
        if len(electricity_buildings) >= 2 and cop_building is not None:
            break
    if len(electricity_buildings) < 2:
        raise RuntimeError('Failed to find at least two buildings with electricity meter support')
    if cop_building is None:
        cop_building = electricity_buildings[0]
    return {
        'building_1': electricity_buildings[0],
        'building_2': electricity_buildings[1],
        'cop_building': cop_building,
    }


def run_tool(name: str, func, *args, **kwargs) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    try:
        result = func(*args, **kwargs)
        return {
            'tool': name,
            'ok': True,
            'started_at': started_at,
            'finished_at': datetime.now().isoformat(),
            'summary': result.get('summary'),
            'highlights': result.get('highlights', []),
            'warnings': result.get('warnings', []),
            'next_actions': result.get('next_actions', []),
            'request_context': result.get('request_context', {}),
            'data_preview': {
                'keys': sorted((result.get('data') or {}).keys()),
                'data': result.get('data'),
            },
        }
    except Exception as exc:
        return {
            'tool': name,
            'ok': False,
            'started_at': started_at,
            'finished_at': datetime.now().isoformat(),
            'error_type': type(exc).__name__,
            'error': str(exc),
        }


def build_markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('# Energy MCP Smoke Test Report')
    lines.append('')
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Backend: `{report['backend_base_url']}`")
    lines.append(f"- Building 1: `{report['candidates']['building_1']}`")
    lines.append(f"- Building 2: `{report['candidates']['building_2']}`")
    lines.append(f"- COP building: `{report['candidates']['cop_building']}`")
    lines.append('')
    lines.append('## Results')
    lines.append('')
    for item in report['results']:
        status = 'PASS' if item['ok'] else 'FAIL'
        lines.append(f"### {item['tool']} - {status}")
        lines.append('')
        if item['ok']:
            lines.append(f"- Summary: {item.get('summary', '')}")
            highlights = item.get('highlights', [])
            if highlights:
                lines.append('- Highlights:')
                for highlight in highlights:
                    lines.append(f"  - {highlight}")
            warnings = item.get('warnings', [])
            if warnings:
                lines.append('- Warnings:')
                for warning in warnings:
                    lines.append(f"  - {warning}")
        else:
            lines.append(f"- Error: `{item.get('error_type')}` - {item.get('error')}")
        lines.append('')
    passed = sum(1 for item in report['results'] if item['ok'])
    total = len(report['results'])
    lines.append('## Summary')
    lines.append('')
    lines.append(f'- Passed: `{passed}/{total}`')
    return '\n'.join(lines) + '\n'


def main() -> None:
    mcp_module = load_mcp_module()
    health = http_get('/health')
    candidates = find_building_candidates()
    b1 = candidates['building_1']
    b2 = candidates['building_2']
    cop_building = candidates['cop_building']

    results = [
        run_tool('backend_health', mcp_module.backend_health),
        run_tool(
            'energy_query',
            mcp_module.energy_query,
            building_ids=[b1],
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
            granularity='day',
            aggregation='sum',
        ),
        run_tool(
            'energy_trend',
            mcp_module.energy_trend,
            building_ids=[b1],
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
            granularity='day',
        ),
        run_tool(
            'energy_compare',
            mcp_module.energy_compare,
            building_ids=[b1, b2],
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
            metric='sum',
        ),
        run_tool(
            'energy_rankings',
            mcp_module.energy_rankings,
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
            metric='sum',
            order='desc',
            limit=5,
        ),
        run_tool(
            'energy_cop_demo',
            mcp_module.energy_cop_demo,
            building_id=cop_building,
            start_time=TIME_START,
            end_time=TIME_END,
            granularity='day',
        ),
        run_tool(
            'energy_weather_correlation',
            mcp_module.energy_weather_correlation,
            building_id=b1,
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
        ),
        run_tool(
            'energy_anomaly_analysis',
            mcp_module.energy_anomaly_analysis,
            building_id=b1,
            meter='electricity',
            start_time=TIME_START,
            end_time=TIME_END,
            granularity='hour',
            include_weather_context=True,
        ),
    ]

    report = {
        'generated_at': datetime.now().isoformat(),
        'backend_base_url': BACKEND_BASE_URL,
        'backend_health': health,
        'candidates': candidates,
        'results': results,
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    REPORT_MD_PATH.write_text(build_markdown_report(report), encoding='utf-8')

    passed = sum(1 for item in results if item['ok'])
    total = len(results)
    print(json.dumps({'passed': passed, 'total': total, 'report_json': str(REPORT_JSON_PATH), 'report_md': str(REPORT_MD_PATH)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
