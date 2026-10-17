"""第六步：检查记录日期覆盖与有效已签约者的日历时长。

与04脚本同级，配套三个06开头SQL放进sql文件夹后点击运行。
只用标准库、只读数据库；负时长保留标记，不改变04／05计数。
"""

import hashlib
import importlib.util
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "olist_marketing.sqlite3"
REPORTS = ROOT / "reports"
FILES = {
    "coverage": "06_date_coverage.sql",
    "won_months": "06_won_months.sql",
    "durations": "06_won_calendar_days.sql",
}
CHANNELS = ("organic_search", "paid_search", "social")
BUCKETS = [("0–7天", 0, 7), ("8–30天", 8, 30), ("31–60天", 31, 60), ("61–90天", 61, 90), ("91–180天", 91, 180), ("181天及以上", 181, None)]


def load_stage04():
    spec = importlib.util.spec_from_file_location("olist_stage04", ROOT / "04_channel_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_reference(stage04, tables):
    leads = {r["mql_id"]: r for r in tables[stage04.MQL_FILE]}
    deals = tables[stage04.DEAL_FILE]
    records = []
    for deal in deals:
        if deal["mql_id"] not in leads:
            raise ValueError("有签约记录找不到对应线索，请先检查01。")
        lead = leads[deal["mql_id"]]
        try:
            days = (datetime.fromisoformat(deal["won_date"]).date() - datetime.fromisoformat(lead["first_contact_date"]).date()).days
            status = "negative_interval" if days < 0 else "valid_duration"
        except ValueError:
            days, status = None, "invalid_date"
        records.append({
            "mql_id": deal["mql_id"],
            "channel": lead["origin"].strip() or "(未记录)",
            "first_contact_date": lead["first_contact_date"],
            "won_date": deal["won_date"],
            "calendar_days_to_won": days,
            "duration_status": status,
        })
    contact_dates = [r["first_contact_date"] for r in leads.values()]
    won_dates = [r["won_date"] for r in deals]
    last_contact = max(contact_dates)
    coverage = {
        "lead_count": len(leads),
        "observed_won_count": len(deals),
        "unmatched_won_count": len(leads) - len(deals),
        "first_contact_min": min(contact_dates),
        "first_contact_max": last_contact,
        "won_min": min(won_dates),
        "won_max": max(won_dates),
        "date_issue_count": sum(r["duration_status"] == "negative_interval" for r in records),
        "won_after_last_contact_date_count": sum(datetime.fromisoformat(value).date().isoformat() > last_contact for value in won_dates),
    }
    months = Counter(value[:7] for value in won_dates)
    return coverage, sorted(records, key=lambda r: r["mql_id"]), months


def query_sql(hashes):
    result = {}
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        metadata = dict(conn.execute("SELECT key, value FROM project_metadata"))
        if metadata.get("schema_version") != "olist_stage02_v1" or any(metadata.get(f"sha256:{name}") != value for name, value in hashes.items()):
            raise ValueError("数据库来源或版本与当前原始数据不一致。")
        conn.row_factory = sqlite3.Row
        for key, filename in FILES.items():
            path = ROOT / "sql" / filename
            raw = path.read_bytes()
            sql = raw.decode("utf-8-sig").strip()
            cursor = conn.execute(sql)
            if cursor.description is None:
                raise ValueError(f"{filename}没有返回查询结果。")
            rows = cursor.fetchmany(10001)
            if len(rows) > 10000:
                raise ValueError(f"{filename}结果超过本步预期，请检查查询。")
            result[key] = {"sql_file": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "executed_sql": sql, "rows": [dict(r) for r in rows]}
    return result


def quantile(values, q):
    """线性插值：索引位置=(n-1)*q，允许分位数不是整数天。"""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    left = math.floor(position)
    right = math.ceil(position)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def duration_summary(records, channel=None):
    selected = [r for r in records if channel is None or r["channel"] == channel]
    days = [r["calendar_days_to_won"] for r in selected if r["duration_status"] == "valid_duration"]
    status = Counter(r["duration_status"] for r in selected)
    return {
        "channel": channel or "all_channels",
        "matched_won_count": len(selected),
        "valid_duration_count": len(days),
        "negative_interval_count": status["negative_interval"],
        "invalid_date_count": status["invalid_date"],
        "min_days": min(days) if days else None,
        "p25_days": quantile(days, 0.25),
        "median_days": quantile(days, 0.5),
        "p75_days": quantile(days, 0.75),
        "p90_days": quantile(days, 0.9),
        "max_days": max(days) if days else None,
    }


def number(value):
    return "—" if value is None else f"{value:.2f}".rstrip("0").rstrip(".")


def write_reports(result):
    coverage = result["coverage"]
    status = result["duration_status_counts"]
    lines = [
        "# 第六步：记录覆盖与已签约者时长诊断", "",
        "## 数据记录了哪些日期", "",
        f"- 首次联系日期：{coverage['first_contact_min']}至{coverage['first_contact_max']}。",
        f"- 可见签约时间：{coverage['won_min']}至{coverage['won_max']}。",
        f"- 全部线索{coverage['lead_count']:,}条，匹配签约{coverage['observed_won_count']:,}条，未匹配签约{coverage['unmatched_won_count']:,}条。",
        f"- 有{coverage['won_after_last_contact_date_count']}条签约的日历日期晚于样本最后首次联系日期。不能把线索采样末日当成签约记录的截止。", "",
        "首个可见签约晚于最早首次联系，只能说明文件中事件时间覆盖不同，不能直接证明早期记录被漏掉。最大签约时间也只是最后可见事件，不是已证实的统一随访截止；未匹配者不自动成为失单或已知右删失。", "",
        "## 时长定义与异常处理", "",
        "日历时长＝签约日期减首次联系日期。先去掉时分秒再相减；0天表示同日，不表示零小时。首次联系没有时间信息，因此不报告精确小时耗时。", "",
        f"全部{coverage['observed_won_count']}条匹配签约记录中，有效日历时长{status.get('valid_duration', 0)}条、负时长{status.get('negative_interval', 0)}条、无法解析日期{status.get('invalid_date', 0)}条。",
        "负时长与无法解析记录仅在本步时长分布中单列，不删原始记录；04／05的匹配签约计数不变。未观察签约的线索没有可用签约时长，不填0天。", "",
        "## 仅在日期有效、文件内已观察签约者中统计", "",
        "| 范围 | 匹配签约数 | 有效时长数 | 负时长数 | 最短 | P25 | 中位数 | P75 | P90 | 最长（天） |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["duration_summaries"]:
        cols = [row["channel"], str(row["matched_won_count"]), str(row["valid_duration_count"]), str(row["negative_interval_count"])] + [number(row[k]) for k in ["min_days", "p25_days", "median_days", "p75_days", "p90_days", "max_days"]]
        lines.append("| " + " | ".join(cols) + " |")
    lines.extend([
        "", "all_channels包含全部来源；其他三行为指定来源的已观察签约者子集。分位数使用索引(n−1)×q线性插值，14.5等小数可以是两条记录之间的插值，不一定对应某条实际记录。", "",
        "这些是已观察签约者的有条件分布，不能当作全部线索最终签约耗时、生存分布或整体销售效率；也不能凭P90推断某个随访窗口已经足够成熟。渠道之间时长差异可能包含线索与记录选择差异，不作为渠道因果快慢结论。", "",
        "## 全部来源、有效已观察签约者的日历时长分布", "",
        "| 日历时长范围 | 可见签约者数 | 占有效已观察签约者比例 |", "| --- | ---: | ---: |",
    ])
    for row in result["duration_buckets"]:
        lines.append(f"| {row['bucket']} | {row['count']} | {number(row['share_pct'])}% |")
    lines.extend(["", "每一条有效时长只进入一个区间；这里的分母是日期有效的已观察签约者，不是全部8,000条线索。", "",
                  "## 按签约发生月份统计可见记录", "", "| 签约发生月份 | 可见签约数（含日期冲突原记录） |", "| --- | ---: |"])
    for row in result["won_months"]:
        lines.append(f"| {row['won_month']} | {row['observed_won_count']} |")
    lines.extend(["", "此表按照签约发生月份归组；04表按照首次联系月份归组。它们是不同问题，不能混用为同一个月度签约率。", "",
                  "## 日期异常记录", "", "| 线索ID | 来源 | 首次联系日期 | 签约时间 | 日历差 | 状态 |", "| --- | --- | --- | --- | ---: | --- |"])
    for row in result["duration_anomalies"]:
        lines.append(f"| {row['mql_id']} | {row['channel']} | {row['first_contact_date']} | {row['won_date']} | {row['calendar_days_to_won']} | {row['duration_status']} |")
    lines.extend(["", "## 实际执行SQL", ""])
    for query in result["query_provenance"].values():
        lines.extend([f"### {Path(query['sql_file']).name}", "", "```sql", query["executed_sql"], "```", ""])
    lines.extend([
        "## 本阶段可以写入报告的边界", "",
        "1. 渠道已观察签约占比与已签约者时长，是两个分母不同的指标。",
        "2. 对齐首次联系月份构成，并没有自动对齐随访完整性。",
        "3. 当前缺少逐线索的最后跟进日期、失单状态、完整抽取截止及渠道成本。下一步以现有描述性指标做图和报告，并列出需要补采的数据；不强行计算全体线索30／60／90天最终转化率或生存模型。",
    ])
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "06_时间与记录覆盖诊断.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "06_time_diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    stage04 = load_stage04()
    tables, hashes = stage04.read_sources()
    expected_coverage, expected_records, expected_months = source_reference(stage04, tables)
    if not DB.is_file():
        raise ValueError("请先运行02_build_database.py创建数据库。")
    db_hash = stage04.sha256(DB)
    queries = query_sql(hashes)
    records = queries["durations"]["rows"]
    if queries["coverage"]["rows"] != [expected_coverage]:
        raise ValueError("SQL日期覆盖结果与原始CSV不一致。")
    if sorted(records, key=lambda r: r.get("mql_id", "")) != expected_records:
        raise ValueError("SQL逐条日历差或状态与原始CSV重算不一致。")
    months = queries["won_months"]["rows"]
    if months != [{"won_month": month, "observed_won_count": count} for month, count in sorted(expected_months.items())]:
        raise ValueError("签约发生月计数与原始CSV不一致。")
    if stage04.sha256(DB) != db_hash or any(stage04.sha256(stage04.RAW / name) != value for name, value in hashes.items()):
        raise ValueError("运行期间数据库或原始CSV发生变化。")
    statuses = dict(Counter(r["duration_status"] for r in records))
    summaries = [duration_summary(records)] + [duration_summary(records, channel) for channel in CHANNELS]
    valid_days = [r["calendar_days_to_won"] for r in records if r["duration_status"] == "valid_duration"]
    buckets = []
    for label, low, high in BUCKETS:
        count = sum(low <= days and (high is None or days <= high) for days in valid_days)
        buckets.append({"bucket": label, "count": count, "share_pct": 100 * count / len(valid_days) if valid_days else None})
    if sum(row["count"] for row in buckets) != len(valid_days):
        raise ValueError("时长分箱合计与有效时长记录数不一致。")
    provenance = {}
    for key, query in queries.items():
        provenance[key] = {field: value for field, value in query.items() if field != "rows"}
        provenance[key]["row_count"] = len(query["rows"])
        provenance[key]["result_sha256"] = hashlib.sha256(json.dumps(query["rows"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    result = {
        "stage": "06_observed_won_time_and_record_coverage",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_definition": "DATE(won_date) - DATE(first_contact_date)，单位日历天；仅已观察签约且日期有效者进入时长分布。",
        "followup_cutoff": "未知；最大可见签约时间不是已证实的完整随访截止。",
        "database_sha256": db_hash,
        "source_sha256": hashes,
        "database_and_raw_csv_unchanged": True,
        "sql_dates_and_record_counts_match_raw": True,
        "coverage": queries["coverage"]["rows"][0],
        "duration_status_counts": statuses,
        "duration_summaries": summaries,
        "duration_buckets": buckets,
        "won_months": months,
        "duration_anomalies": [r for r in records if r["duration_status"] != "valid_duration"],
        "query_provenance": provenance,
    }
    write_reports(result)
    coverage = result["coverage"]
    print("第六步完成：日期记录覆盖与已签约者日历时长已核对。")
    print(f"首次联系：{coverage['first_contact_min']}至{coverage['first_contact_max']}。")
    print(f"可见签约：{coverage['won_min']}至{coverage['won_max']}。")
    print(f"匹配签约{coverage['observed_won_count']}条；有效时长{len(valid_days)}条；负时长{statuses.get('negative_interval',0)}条单独标记。")
    print("\n范围 | 有效已签约者数 | 中位日历天数 | P90日历天数")
    for row in summaries:
        print(f"  {row['channel']} | {row['valid_duration_count']} | {number(row['median_days'])} | {number(row['p90_days'])}")
    print("时长分母仅为日期有效的已观察签约者，不能代表全部线索的销售效率。")
    print("最大签约时间不是已知完整随访截止；前面04／05的签约计数保持不变。")
    print(f"报告：{REPORTS / '06_时间与记录覆盖诊断.md'}")
    print("请截图运行结果，下一步整理图表。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f"第六步未完成：{exc}\n请确认04脚本与三个06开头的SQL都已放在正确位置。") from exc
