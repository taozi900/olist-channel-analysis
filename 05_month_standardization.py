"""第五步：比较三来源在相同月份构成下的可见签约占比。

与04脚本同级；两个05开头的SQL放入sql文件夹，点击运行即可。
只用标准库。先按协议确定比较来源与共同月份，再执行SQL。
"""

import hashlib
import importlib.util
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "olist_marketing.sqlite3"
REPORTS = ROOT / "reports"
CHANNELS = ("organic_search", "paid_search", "social")
PROTOCOL = {
    "channels": list(CHANNELS),
    "common_month_rule": "共同首次联系月份：三个指定来源分别都有至少1条线索；不按签约数筛选。",
    "weight_target": "共同月份内三个指定来源合并后的样本月份构成；不代表全企业或全来源。",
    "weight_formula": "该月三个来源合并线索数 / 所有共同月份三个来源合并线索数",
    "standardization_formula": "SUM(同一套月份权重 * 该来源该月记录内可见签约占比)",
    "date_anomaly_policy": "沿用04：日期冲突记录保留在匹配签约与线索计数中，另列标记。",
    "scope": "描述性月份构成调整；不统一随访时长、不解释为因果效果、不进行显著性检验。",
}
FILES = {"summary": "05_month_standardization.sql", "details": "05_month_weights.sql"}


def load_stage04():
    spec = importlib.util.spec_from_file_location("olist_stage04", ROOT / "04_channel_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_reference(stage04, tables):
    counts = stage04.reference_counts(tables)
    monthly = counts["channel_months"]
    month_sets = [{month for (month, channel), values in monthly.items() if channel == target and values[0] > 0} for target in CHANNELS]
    common = sorted(set.intersection(*month_sets))
    if not common:
        raise ValueError("三个来源没有共同且都有线索的月份，不能进行本方案的标准化。")
    all_source_months = sorted({month for month, _ in monthly})
    excluded = [month for month in all_source_months if month not in common]
    pooled = {month: sum(monthly[(month, channel)][0] for channel in CHANNELS) for month in common}
    pooled_total = sum(pooled.values())
    weights = {month: Fraction(n, pooled_total) for month, n in pooled.items()}
    summaries = {}
    for channel in CHANNELS:
        all_n, all_won, _ = counts["channels"][(channel,)]
        common_n = sum(monthly[(month, channel)][0] for month in common)
        common_won = sum(monthly[(month, channel)][1] for month in common)
        common_issues = sum(monthly[(month, channel)][2] for month in common)
        standardized = sum((weights[month] * Fraction(monthly[(month, channel)][1], monthly[(month, channel)][0]) for month in common), Fraction())
        summaries[channel] = {
            "channel": channel,
            "all_lead_count": all_n,
            "all_won_count": all_won,
            "all_observed_won_pct": float(100 * Fraction(all_won, all_n)),
            "common_lead_count": common_n,
            "common_won_count": common_won,
            "common_observed_won_pct": float(100 * Fraction(common_won, common_n)),
            "standardized_won_pct": float(100 * standardized),
            "common_month_count": len(common),
            "shared_weight_lead_count": pooled_total,
            "common_date_issue_count": common_issues,
        }
    details = {}
    for month in common:
        for channel in CHANNELS:
            n, won, issues = monthly[(month, channel)]
            details[(month, channel)] = {
                "contact_month": month,
                "channel": channel,
                "lead_count": n,
                "observed_won_count": won,
                "observed_won_pct": float(100 * Fraction(won, n)),
                "pooled_lead_count": pooled[month],
                "month_weight": float(weights[month]),
                "weighted_contribution_pp": float(100 * weights[month] * Fraction(won, n)),
                "date_issue_count": issues,
            }
    return common, excluded, pooled, pooled_total, summaries, details


def execute_queries(stage04, hashes):
    results = {}
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        metadata = dict(conn.execute("SELECT key, value FROM project_metadata"))
        if metadata.get("schema_version") != "olist_stage02_v1" or any(metadata.get(f"sha256:{name}") != value for name, value in hashes.items()):
            raise ValueError("数据库来源或版本与当前原始CSV不一致。")
        conn.row_factory = sqlite3.Row
        for key, filename in FILES.items():
            path = ROOT / "sql" / filename
            data = path.read_bytes()
            sql = data.decode("utf-8-sig").strip()
            cursor = conn.execute(sql)
            if cursor.description is None:
                raise ValueError(f"{filename}必须返回查询结果。")
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError(f"{filename}结果超过1000行，请检查分组。")
            results[key] = {"file": str(path), "sha256": hashlib.sha256(data).hexdigest(), "executed_sql": sql, "rows": [dict(row) for row in rows]}
    return results


def verify_rows(rows, expected, keys):
    seen = set()
    for row in rows:
        group_tuple = tuple(row.get(key) for key in keys)
        group = group_tuple[0] if len(keys) == 1 else group_tuple
        if group not in expected or group in seen:
            raise ValueError("SQL中出现重复或不符合协议的来源／月份。")
        seen.add(group)
        reference = expected[group]
        if set(row) != set(reference):
            raise ValueError("SQL输出字段与本练习协议不一致。")
        for field, value in reference.items():
            actual = row[field]
            if type(value) is float:
                if not isinstance(actual, (int, float)) or not math.isclose(actual, value, rel_tol=1e-11, abs_tol=1e-10):
                    raise ValueError(f"{group}的{field}与独立原始计数计算不一致。")
            elif actual != value:
                raise ValueError(f"{group}的{field}与独立原始计数计算不一致。")
    if seen != set(expected):
        raise ValueError("SQL遗漏了本方案要求的来源／共同月份。")


def fmt(value, places="0.01"):
    return str(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def write_report(result):
    common = result["common_months"]
    rows = result["queries"]["summary"]["rows"]
    lookup = {row["channel"]: row for row in rows}
    before = lookup["paid_search"]["common_observed_won_pct"] - lookup["organic_search"]["common_observed_won_pct"]
    after = lookup["paid_search"]["standardized_won_pct"] - lookup["organic_search"]["standardized_won_pct"]
    lines = [
        "# 第五步：对齐月份构成后比较可见签约占比", "",
        "本步把自然搜索、付费搜索和社交的月内可见签约占比，按同一套月份权重重新汇总。这是描述性比较指标，不是实际签约量增加，也不是最终签约率或因果效果。", "",
        "## 固定的比较规则", "",
    ]
    for key, value in PROTOCOL.items():
        lines.append(f"- {key}：{', '.join(value) if isinstance(value, list) else value}")
    lines.extend([
        "", f"共同月份：{common[0]}至{common[-1]}，共{len(common)}个月。权重来自这些月份内三个来源合并的{result['shared_weight_lead_count']:,}条线索。", "",
        "没有按签约结果筛选月份。某月只有在三个来源分别都有线索时才进入比较；早期月份即使零签约，只要满足分母规则也保留。", "",
        f"原始文件中未纳入共同月份的月份：{', '.join(result['excluded_source_months']) or '无'}（未同时满足三个来源各有线索的规则）。", "",
        "## 调整前后", "",
        "| 来源 | 全样本线索数 | 全样本可见签约数 | 原始占比 | 共同月份占比 | 相同月份权重后的占比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in rows:
        lines.append(f"| {row['channel']} | {row['all_lead_count']} | {row['all_won_count']} | {fmt(row['all_observed_won_pct'])}% | {fmt(row['common_observed_won_pct'])}% | {fmt(row['standardized_won_pct'])}% |")
    lines.extend([
        "", "原始占比＝该来源可见签约数÷该来源线索数。共同月份占比仍用签约数合计÷线索数合计，不能直接平均月度百分比。此数据中三个来源的全部线索均在共同月份，所以前两种占比相同。", "",
        "标准化占比＝各月的同一套权重×该来源该月可见签约占比，再把各月贡献相加。标准化后没有新增线索或签约，不能把数值变化当作营销效果提升。", "",
        f"付费搜索减自然搜索：共同月份原始差值{before:+.4f}个百分点；月份构成标准化后差值{after:+.4f}个百分点（展示约{after:+.2f}个百分点）。", "",
        "在本方案下，调整月份构成后这两来源的描述性差异仍然存在。4月的排序与整体不同，不能单凭该月推断整体排序会逆转。本步没有置信区间或显著性检验，不能据此确认渠道优劣。", "",
        "## 共同月份权重", "",
        "| 首次联系月份 | 三来源合并线索数 | 三来源共同使用的月份权重 |",
        "| --- | ---: | ---: |",
    ])
    for month in common:
        n = result["pooled_month_counts"][month]
        lines.append(f"| {month} | {n} | {fmt(100 * n / result['shared_weight_lead_count'], '0.0001')}% |")
    lines.extend(["", "未舍入权重合计为1（100%），展示值因四舍五入可能不恰好合计100%。权重目标只代表这三个来源合并后的样本月份构成。", "",
                  "## 每月贡献明细", "",
                  "| 月份 | 来源 | 线索数 | 可见签约数 | 月内占比 | 共同月份权重 | 对最终占比贡献（百分点） | 日期冲突数 |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in result["queries"]["details"]["rows"]:
        lines.append(f"| {row['contact_month']} | {row['channel']} | {row['lead_count']} | {row['observed_won_count']} | {fmt(row['observed_won_pct'])}% | {fmt(100 * row['month_weight'], '0.0001')}% | {fmt(row['weighted_contribution_pp'], '0.0001')} | {row['date_issue_count']} |")
    lines.extend([
        "", "## 这一步解决和保留的问题", "",
        "三个来源使用相同的月份构成进行汇总，而不是各自使用自己的月份占比。月份只是一种分层，月内线索特征、日期、销售分配、记录覆盖和跟进情况仍可能不同。", "",
        "本步没有确认统一数据抽取截止、没有统一随访时长，也没有把最大签约日期当作已知完整观察截止。月份标准化不能补回未被记录的签约。", "",
        "日期冲突记录按04规则保留，不能据此声称日期问题已修复。不同合理权重定义会对应不同的比较目标；此处不按结果更换主方案。缺少成本与利润，仍不计算ROI或最优预算。", "",
        "## 学习重点", "",
        "- WITH：为查询中的中间结果起名，逐层计算。",
        "- HAVING COUNT(*)：在按月份分组后，保留三来源都有线索的月份。",
        "- SUM(...) OVER ()：得到月份合并线索数的总和，用于计算共同权重。",
        "- SUM(月份权重×月内占比)：计算标准化指标；先保留未舍入数，最后再格式化展示。", "",
        "## 实际执行的SQL", "",
    ])
    for query in result["queries"].values():
        lines.extend([f"### {Path(query['file']).name}", "", "```sql", query["executed_sql"], "```", ""])
    lines.extend([
        "## 方法参考", "",
        "[CDC：直接标准化中的固定权重加权原理](https://www.cdc.gov/nchs/hus/sources-definitions/age-adjustment.htm)。CDC原文讨论年龄标准化；本项目借用相同的分层加权形式，将分层变量定义为首次联系月份。具体来源选择、共同月份规则和权重目标是本项目的描述性分析设定，不是CDC对这批营销数据的结论。",
    ])
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "05_月份构成对齐.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "05_month_standardization.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    stage04 = load_stage04()
    tables, hashes = stage04.read_sources()
    common, excluded, pooled, total, summaries, details = build_reference(stage04, tables)
    if not DB.is_file():
        raise ValueError("找不到数据库，请先运行02_build_database.py。")
    db_hash = stage04.sha256(DB)
    queries = execute_queries(stage04, hashes)
    verify_rows(queries["summary"]["rows"], summaries, ["channel"])
    verify_rows(queries["details"]["rows"], details, ["contact_month", "channel"])
    # 每月权重在明细里重复三次，核对权重合计时每个月只取一次。
    actual_weights = {row["contact_month"]: row["month_weight"] for row in queries["details"]["rows"]}
    if not math.isclose(sum(actual_weights.values()), 1.0, abs_tol=1e-12):
        raise ValueError("月份权重合计不等于1。")
    if stage04.sha256(DB) != db_hash or any(stage04.sha256(stage04.RAW / name) != value for name, value in hashes.items()):
        raise ValueError("运行期间数据库或原始CSV发生变化。")
    result = {
        "stage": "05_descriptive_month_standardization",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": PROTOCOL,
        "common_months": common,
        "excluded_source_months": excluded,
        "pooled_month_counts": pooled,
        "shared_weight_lead_count": total,
        "month_weight_sum": sum(actual_weights.values()),
        "database_sha256": db_hash,
        "source_sha256": hashes,
        "database_and_raw_csv_unchanged": True,
        "sql_matches_independent_exact_fraction_calculation": True,
        "queries": queries,
    }
    write_report(result)
    print("第五步完成：三个来源已按相同月份构成汇总。")
    print(f"共同月份：{common[0]}至{common[-1]}，共{len(common)}个月。")
    print(f"权重来自三个来源合并的{total:,}条线索，月份权重合计100%。")
    print("\n来源 | 原始可见签约占比 | 共同月份占比 | 相同月份权重后的占比")
    for row in queries["summary"]["rows"]:
        print(f"  {row['channel']} | {fmt(row['all_observed_won_pct'])}% | {fmt(row['common_observed_won_pct'])}% | {fmt(row['standardized_won_pct'])}%")
    print("这只是月份构成调整，没有新增签约；完整随访和因果效果仍未确认。")
    print(f"报告：{REPORTS / '05_月份构成对齐.md'}")
    print("请截图上面的调整前后结果，下一步一起解读。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f"第五步未完成：{exc}\n请确认04脚本和两个05开头的SQL都已放在正确位置。") from exc
