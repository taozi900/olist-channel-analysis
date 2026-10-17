"""第四步：运行渠道与月份SQL，建立可见签约指标表。

与01、02、03脚本同级，配套SQL放在sql文件夹。点击运行即可。
只用标准库、只读打开数据库；原CSV、03练习SQL及早期报告不修改。
"""

import csv
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "olist_marketing.sqlite3"
RAW = ROOT / "data" / "raw"
REPORTS = ROOT / "reports"
MQL_FILE = "olist_marketing_qualified_leads_dataset.csv"
DEAL_FILE = "olist_closed_deals_dataset.csv"
QUERIES = {
    "channels": ("04_channel_metrics.sql", ["channel"]),
    "channel_months": ("04_channel_month_metrics.sql", ["contact_month", "channel"]),
}
METRICS = ["lead_count", "observed_won_count", "unmatched_won_count", "observed_won_pct", "date_issue_count"]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct_text(won, leads):
    # SQL保留未舍入比例；显示用精确计数四舍五入到两位。
    return str((Decimal(won) * 100 / Decimal(leads)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def read_sources():
    manifest = json.loads((RAW / "source_manifest.json").read_text(encoding="utf-8"))
    tables = {}
    hashes = {}
    for name in [MQL_FILE, DEAL_FILE]:
        path = RAW / name
        hashes[name] = sha256(path)
        if hashes[name] != manifest["files"][name]["sha256"]:
            raise ValueError(f"{name}与下载清单不一致，请先检查原始数据。")
        with path.open(encoding="utf-8-sig", newline="") as f:
            tables[name] = list(csv.DictReader(f))
    for name, rows in tables.items():
        keys = [row["mql_id"] for row in rows]
        if len(set(keys)) != len(keys) or any(not key.strip() for key in keys):
            raise ValueError(f"{name}的线索ID存在重复或空值，请先检查01报告。")
    return tables, hashes


def reference_counts(tables):
    # 独立核对来源CSV；最终展示的各组结果来自实际SQL执行。
    deals = {row["mql_id"]: row for row in tables[DEAL_FILE]}
    lead_ids = {row["mql_id"] for row in tables[MQL_FILE]}
    if set(deals) - lead_ids:
        raise ValueError("签约表中存在找不到对应线索的ID。")
    expected = {key: defaultdict(lambda: [0, 0, 0]) for key in QUERIES}
    for lead in tables[MQL_FILE]:
        channel = lead["origin"].strip() or "(未记录)"
        month = lead["first_contact_date"][:7]
        deal = deals.get(lead["mql_id"])
        won = int(deal is not None)
        date_issue = int(deal is not None and datetime.fromisoformat(deal["won_date"]).date() < datetime.fromisoformat(lead["first_contact_date"]).date())
        for key, group in [("channels", (channel,)), ("channel_months", (month, channel))]:
            values = expected[key][group]
            values[0] += 1
            values[1] += won
            values[2] += date_issue
    return expected


def run_queries(hashes):
    if not DB.is_file():
        raise ValueError("找不到数据库，请先运行02_build_database.py。")
    results = {}
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        metadata = dict(conn.execute("SELECT key, value FROM project_metadata"))
        if metadata.get("schema_version") != "olist_stage02_v1" or any(metadata.get(f"sha256:{name}") != value for name, value in hashes.items()):
            raise ValueError("数据库的版本或来源与当前CSV不一致。")
        conn.row_factory = sqlite3.Row
        for key, (filename, group_columns) in QUERIES.items():
            path = ROOT / "sql" / filename
            sql_bytes = path.read_bytes()
            sql = sql_bytes.decode("utf-8-sig").strip()
            cursor = conn.execute(sql)
            columns = [item[0] for item in cursor.description] if cursor.description else []
            if columns != group_columns + METRICS:
                raise ValueError(f"{filename}的输出列名不符合当前练习口径，请检查SELECT。")
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError(f"{filename}结果超过1000行，请检查分组。")
            results[key] = {
                "sql_file": str(path),
                "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(),
                "executed_sql": sql,
                "rows": [dict(row) for row in rows],
            }
    return results


def verify_results(results, expected):
    for key, (_, group_columns) in QUERIES.items():
        seen = set()
        for row in results[key]["rows"]:
            group = tuple(row[c] for c in group_columns)
            if group in seen or group not in expected[key]:
                raise ValueError(f"{key}出现重复或不符合来源的分组。")
            seen.add(group)
            leads, won, issues = expected[key][group]
            counts = [row[c] for c in ["lead_count", "observed_won_count", "unmatched_won_count", "date_issue_count"]]
            if any(type(value) is not int for value in counts) or counts != [leads, won, leads - won, issues]:
                raise ValueError(f"{key}分组{group}的计数与原始CSV不一致。")
            value = row["observed_won_pct"]
            if not isinstance(value, (float, int)) or not math.isclose(value, 100 * won / leads, abs_tol=1e-10, rel_tol=1e-12):
                raise ValueError(f"{key}分组{group}的签约占比公式不正确。")
        if seen != set(expected[key]):
            raise ValueError(f"{key}遗漏了原始数据中的分组。")
    for metric in ["lead_count", "observed_won_count", "unmatched_won_count", "date_issue_count"]:
        if sum(r[metric] for r in results["channels"]["rows"]) != sum(r[metric] for r in results["channel_months"]["rows"]):
            raise ValueError("月度分组与渠道汇总的计数不能对齐。")


def table_lines(rows, include_month=False):
    header = (["首次联系月份"] if include_month else []) + ["来源", "线索数", "匹配签约数", "未匹配签约数", "已观察签约占比", "日期冲突数"]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        cells = ([row["contact_month"]] if include_month else []) + [row["channel"], str(row["lead_count"]), str(row["observed_won_count"]), str(row["unmatched_won_count"]), pct_text(row["observed_won_count"], row["lead_count"]) + "%", str(row["date_issue_count"])]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def write_reports(result):
    totals = result["totals"]
    lines = [
        "# 第四步：渠道与月份的可见签约指标", "",
        "## 先固定指标定义", "",
        "已观察签约占比＝发布文件内匹配到签约记录的MQL数÷该组全部MQL记录数。统计单位是线索记录，不是消费者订单或已验证的独立商家。", "",
        "观察范围是这批文件中的全部可见签约记录；没有把今天或最大签约日期当作统一随访截止，也没有承诺所有线索都被完整跟踪相同时长。本表是描述性快照，不是最终签约率或渠道因果效果。", "",
        f"整体：{totals['lead_count']:,}条线索，{totals['observed_won_count']:,}条匹配签约，{totals['unmatched_won_count']:,}条未匹配；已观察签约占比{pct_text(totals['observed_won_count'], totals['lead_count'])}%。", "",
        f"日期冲突{totals['date_issue_count']}条仍保留在分母与匹配签约计数中，并单独标记。此步不计算签约时长。", "",
        "## 各来源汇总", "",
    ]
    lines.extend(table_lines(result["queries"]["channels"]["rows"]))
    lines.extend([
        "", "占比显示时四舍五入到两位小数；SQL及JSON保留未舍入值。当前按线索量排序，表格顺序不代表效果优劣。", "",
        "- (未记录)表示原CSV空渠道；unknown是原始文本标签，二者分别保留。",
        "- 空来源和unknown不是可以直接追加预算的明确营销渠道。",
        "- 线索多不等于签约占比高；占比高也不能直接推断投入产出更好。小分母的占比更容易波动。",
        "- 未匹配签约记录不等于最终失单或流失；本步不计算失单率。", "",
        "## 按首次联系月份×来源拆分", "",
        "每一行是同月首次联系、同来源的一组线索。签约可以发生在更晚月份，所以此处不是按签约发生月份计数。只显示有线索的组合；没有线索的组合不补成0%签约占比。", "",
    ])
    lines.extend(table_lines(result["queries"]["channel_months"]["rows"], include_month=True))
    lines.extend(["", "## 实际执行的两条SQL", ""])
    for key in QUERIES:
        query = result["queries"][key]
        lines.extend([f"### {Path(query['sql_file']).name}", "", "```sql", query["executed_sql"], "```", ""])
    lines.extend([
        "## 本步SQL怎么读", "",
        "- COUNT(*)：该组有多少条线索。",
        "- SUM(has_observed_won)：把匹配标志的1相加，得到匹配签约的线索数。",
        "- 100.0 * SUM(has_observed_won) / COUNT(*)：计算百分比；100.0保留小数运算。",
        "- GROUP BY first_contact_month, origin_group：同时按月份和来源分组。", "",
        "## 先回答三个业务问题", "",
        "1. 自然搜索和付费搜索，哪个线索更多？哪个已观察签约占比更高？",
        "2. 为什么不能因为空来源的占比高，就建议给它追加预算？",
        "3. 若两个渠道进入的月份构成不同，直接比较整体占比可能遗漏什么？", "",
        "下一步再讨论月份构成、可见签约记录的时间分布与观察窗口限制。本表尚未校正这些差异，也未完成成本、ROI或预算优化分析。",
    ])
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "04_渠道签约指标.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "04_channel_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    tables, hashes = read_sources()
    expected = reference_counts(tables)
    if not DB.is_file():
        raise ValueError("找不到数据库，请先运行02_build_database.py。")
    db_hash = sha256(DB)
    queries = run_queries(hashes)
    verify_results(queries, expected)
    if sha256(DB) != db_hash or any(sha256(RAW / name) != value for name, value in hashes.items()):
        raise ValueError("运行期间数据库或原始CSV发生变化，请先检查。")
    totals = {metric: sum(row[metric] for row in queries["channels"]["rows"]) for metric in ["lead_count", "observed_won_count", "unmatched_won_count", "date_issue_count"]}
    result = {
        "stage": "04_observed_channel_and_month_metrics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metric_definition": "发布文件内匹配到签约记录的MQL数 / 该组全部MQL记录数",
        "observation_scope": "可见记录快照；完整随访截止未知，未统一观察时长。",
        "database_sha256": db_hash,
        "source_sha256": hashes,
        "database_and_raw_csv_unchanged": True,
        "sql_counts_match_independent_raw_counts": True,
        "totals": totals,
        "queries": queries,
    }
    write_reports(result)
    print("第四步完成：渠道与月份签约指标已核对。")
    print("指标：文件内已观察签约数 ÷ 该组全部线索数；不是最终签约率。")
    print("\n来源 | 线索数 | 匹配签约 | 已观察签约占比")
    for row in queries["channels"]["rows"]:
        print(f"  {row['channel']} | {row['lead_count']:,} | {row['observed_won_count']:,} | {pct_text(row['observed_won_count'], row['lead_count'])}%")
    print(f"整体：{totals['lead_count']:,}条线索，{totals['observed_won_count']:,}条匹配签约，占比{pct_text(totals['observed_won_count'], totals['lead_count'])}%。")
    print(f"首次联系月份×来源：{len(queries['channel_months']['rows'])}个有线索的组合；与渠道汇总核对一致。")
    print(f"空渠道、unknown分别保留；日期冲突{totals['date_issue_count']}条保留标记，不据此宣布渠道赢家。")
    print(f"报告：{REPORTS / '04_渠道签约指标.md'}")
    print("请截图渠道汇总结果，下一步一起解读指标与月份构成。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f"第四步未完成：{exc}\n请确认已运行01、02，且本文件和配套sql文件都放在正确位置。") from exc
