"""第一步：检查Olist营销线索与签约记录。仅使用Python标准库。

在VS Code打开本文件，点击右上角“运行Python文件”。
原始数据放在同目录data/raw；输出写入reports，不改动原始CSV。
"""

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
REPORTS = ROOT / "reports"
MQL_FILE = "olist_marketing_qualified_leads_dataset.csv"
DEAL_FILE = "olist_closed_deals_dataset.csv"
EXPECTED_COLUMNS = {
    MQL_FILE: ["mql_id", "first_contact_date", "landing_page_id", "origin"],
    DEAL_FILE: [
        "mql_id", "seller_id", "sdr_id", "sr_id", "won_date",
        "business_segment", "lead_type", "lead_behaviour_profile",
        "has_company", "has_gtin", "average_stock", "business_type",
        "declared_product_catalog_size", "declared_monthly_revenue",
    ],
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_table(name):
    with (RAW / name).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        if columns != EXPECTED_COLUMNS[name]:
            raise ValueError(f"{name}的表头与本版本不一致：{columns}")
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"{name}存在列数不一致的记录，请检查原始文件。")
    return columns, rows


def profile(columns, rows):
    n = len(rows)
    key_counts = Counter(r["mql_id"] for r in rows if r["mql_id"].strip())
    return {
        "rows": n,
        "columns": columns,
        "distinct_nonempty_mql_ids": len(key_counts),
        "empty_mql_id_rows": sum(not r["mql_id"].strip() for r in rows),
        "duplicate_mql_id_values": sum(c > 1 for c in key_counts.values()),
        "extra_rows_from_duplicate_mql_ids": sum(c - 1 for c in key_counts.values()),
        "exact_duplicate_extra_rows": n - len({tuple(r[c] for c in columns) for r in rows}),
        "field_profile": {
            c: {
                "empty_rows": sum(not r[c].strip() for r in rows),
                "empty_pct": round(100 * sum(not r[c].strip() for r in rows) / n, 3) if n else None,
                "distinct_nonempty_values": len({r[c] for r in rows if r[c].strip()}),
            }
            for c in columns
        },
    }


def date_profile(rows, field):
    parsed = {}
    invalid_rows = []
    missing_rows = []
    for row_number, row in enumerate(rows, start=2):
        value = row[field].strip()
        if not value:
            missing_rows.append(row_number)
            continue
        try:
            parsed[row_number] = datetime.fromisoformat(value)
        except ValueError:
            invalid_rows.append(row_number)
    values = list(parsed.values())
    summary = {
        "field": field,
        "parsed_rows": len(values),
        "missing_rows": len(missing_rows),
        "invalid_rows": len(invalid_rows),
        "invalid_csv_row_numbers_first_10": invalid_rows[:10],
        "min": min(values).isoformat(sep=" ") if values else None,
        "max": max(values).isoformat(sep=" ") if values else None,
    }
    return summary, parsed


def run_audit():
    manifest = json.loads((RAW / "source_manifest.json").read_text(encoding="utf-8"))
    before = {name: sha256(RAW / name) for name in EXPECTED_COLUMNS}
    for name, digest in before.items():
        if digest != manifest["files"][name]["sha256"]:
            raise ValueError(f"{name}与下载时的SHA256不同，请保留文件，先检查原因。")

    mql_columns, leads = read_table(MQL_FILE)
    deal_columns, deals = read_table(DEAL_FILE)
    mql_profile = profile(mql_columns, leads)
    deal_profile = profile(deal_columns, deals)
    lead_dates, parsed_lead_dates = date_profile(leads, "first_contact_date")
    deal_dates, parsed_deal_dates = date_profile(deals, "won_date")

    # 先检查连接键，避免重复键造成连接后行数膨胀。
    keys_ok = all(
        p["empty_mql_id_rows"] == 0 and p["extra_rows_from_duplicate_mql_ids"] == 0
        for p in [mql_profile, deal_profile]
    )
    lead_ids = {r["mql_id"] for r in leads if r["mql_id"].strip()}
    deal_ids = {r["mql_id"] for r in deals if r["mql_id"].strip()}
    origin_counts = Counter(r["origin"] if r["origin"].strip() else "(未记录)" for r in leads)
    seller_counts = Counter(r["seller_id"] for r in deals if r["seller_id"].strip())
    join_summary = {
        "mql_key_is_nonempty_and_unique_in_both_tables": keys_ok,
        "matched_distinct_mql_ids": len(lead_ids & deal_ids),
        "unmatched_lead_ids": len(lead_ids - deal_ids),
        "deal_ids_missing_from_leads": len(deal_ids - lead_ids),
        "distinct_nonempty_seller_ids_in_deals": len(seller_counts),
        "duplicate_seller_id_values_in_deals": sum(c > 1 for c in seller_counts.values()),
        "grain": "MQL线索记录；不把mql_id自动解释为唯一自然人或唯一商家。",
        "unmatched_meaning": "未匹配到签约记录；不等于确定失单。",
    }

    interval_check = {
        "checked_matched_rows": 0,
        "won_before_contact_calendar_date_rows": 0,
        "anomalies_first_10": [],
    }
    if keys_ok:
        first_contact_by_id = {
            r["mql_id"]: parsed_lead_dates[i]
            for i, r in enumerate(leads, start=2) if i in parsed_lead_dates
        }
        for i, row in enumerate(deals, start=2):
            first_contact = first_contact_by_id.get(row["mql_id"])
            won = parsed_deal_dates.get(i)
            if first_contact is not None and won is not None:
                interval_check["checked_matched_rows"] += 1
                if won.date() < first_contact.date():
                    interval_check["won_before_contact_calendar_date_rows"] += 1
                    if len(interval_check["anomalies_first_10"]) < 10:
                        interval_check["anomalies_first_10"].append({
                            "mql_id": row["mql_id"],
                            "first_contact_date": first_contact.date().isoformat(),
                            "won_date": won.isoformat(sep=" "),
                            "handling": "仅标记，原始记录保留；后续时长分析单独处理。",
                        })

    checks = {
        "csv_hashes_match_download_manifest": True,
        "join_keys_nonempty_and_unique": keys_ok,
        "all_won_records_have_lead_match": not (deal_ids - lead_ids),
        "all_dates_present_and_parseable": all(p["missing_rows"] == 0 and p["invalid_rows"] == 0 for p in [lead_dates, deal_dates]),
        "no_won_before_contact_calendar_date": interval_check["won_before_contact_calendar_date_rows"] == 0,
    }
    after = {name: sha256(RAW / name) for name in EXPECTED_COLUMNS}
    checks["raw_csv_unchanged"] = before == after
    result = {
        "stage": "01_source_and_structure_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": manifest,
        "tables": {MQL_FILE: mql_profile, DEAL_FILE: deal_profile},
        "dates": {"first_contact_date": lead_dates, "won_date": deal_dates},
        "join": join_summary,
        "date_order_check": interval_check,
        "origin_lead_counts": dict(sorted(origin_counts.items(), key=lambda x: (-x[1], x[0]))),
        "declared_monthly_revenue_zero_rows": sum(r["declared_monthly_revenue"].strip() in {"0", "0.0"} for r in deals),
        "checks": checks,
        "all_structure_checks_passed": all(checks.values()),
        "observation_cutoff": "发布说明未给出每条线索的完整随访截止；最大won_date不是已知完整观察截止。",
        "scope": "仅结构与覆盖审计；未选择渠道赢家、未计算ROI或归因贡献。",
    }
    return result


def render_readme(result):
    tables = result["tables"]
    join = result["join"]
    dates = result["dates"]
    lines = [
        "# 第一阶段：数据检查结果", "",
        f"- 营销线索：{tables[MQL_FILE]['rows']:,}条，{len(tables[MQL_FILE]['columns'])}列。",
        f"- 签约记录：{tables[DEAL_FILE]['rows']:,}条，{len(tables[DEAL_FILE]['columns'])}列。",
        f"- 匹配到签约记录的线索ID：{join['matched_distinct_mql_ids']:,}个。",
        f"- 未匹配签约记录的线索ID：{join['unmatched_lead_ids']:,}个；不能直接称为失单。",
        f"- 签约表中找不到线索的ID：{join['deal_ids_missing_from_leads']:,}个。", "",
        "## 日期范围", "",
        f"- 首次联系：{dates['first_contact_date']['min']} 至 {dates['first_contact_date']['max']}。",
        f"- 签约：{dates['won_date']['min']} 至 {dates['won_date']['max']}。",
        "- 首次联系只有日期，签约有时分秒；本阶段只检查签约是否早于首次联系的日历日期。",
        "- 这些是文件中出现的日期范围，不代表每条未签约线索都被完整追踪到最大签约日。", "",
        "## 结构检查", "",
    ]
    for name, ok in result["checks"].items():
        lines.append(f"- {name}：{'通过' if ok else '需要检查'}")
    lines.extend([
        "", "## 发现的日期冲突", "",
        f"签约日期早于首次联系日期：{result['date_order_check']['won_before_contact_calendar_date_rows']}条。仅标记，未删行、未改日期。",
    ])
    for anomaly in result["date_order_check"]["anomalies_first_10"]:
        lines.append(f"- mql_id `{anomaly['mql_id']}`：首次联系 {anomaly['first_contact_date']}，签约 {anomaly['won_date']}。")
    lines.extend(["", "## 字段缺失", "", "空字符串或只含空白记为缺失；数值0与False不会自动当作缺失。", ""])
    for name, table in tables.items():
        lines.extend([f"### {name}", "", "| 字段 | 缺失条数 | 缺失比例 |", "| --- | ---: | ---: |"])
        for field, info in table["field_profile"].items():
            lines.append(f"| {field} | {info['empty_rows']} | {info['empty_pct']:.3f}% |")
        lines.append("")
    lines.append(f"签约表的declared_monthly_revenue有{result['declared_monthly_revenue_zero_rows']}条为0；非空不代表收入记录完整可靠。\n")
    lines.extend([
        "## 现在先理解三件事", "",
        "1. 一条MQL是营销线索记录；签约表记录商家入驻的销售赢单，不是消费者下单。",
        "2. 先检查mql_id是否唯一，下一步再用线索表LEFT JOIN签约表，保留未匹配线索。",
        "3. 渠道名缺失应保留并单独统计；赢单表独有属性不能当作全体线索均已知的获客前特征。", "",
        "下一步：把两表导入SQLite，用SQL核对行数、连接和渠道线索分布。", "",
        "本阶段不计算渠道转化排名，不据此调整预算。",
    ])
    return "\n".join(lines) + "\n"


def main():
    result = run_audit()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "01_data_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "01_数据检查结果.md").write_text(render_readme(result), encoding="utf-8")
    print("第一步完成：已检查原始数据。")
    print(f"营销线索：{result['tables'][MQL_FILE]['rows']:,}条；签约记录：{result['tables'][DEAL_FILE]['rows']:,}条。")
    print(f"成功匹配：{result['join']['matched_distinct_mql_ids']:,}条；未匹配签约记录：{result['join']['unmatched_lead_ids']:,}条。")
    print("两表线索ID唯一且非空：" + ("是。" if result["join"]["mql_key_is_nonempty_and_unique_in_both_tables"] else "否，请先看报告。"))
    print(f"日期冲突：{result['date_order_check']['won_before_contact_calendar_date_rows']}条；已标记并保留原始数据。")
    print(f"渠道字段：空值{result['tables'][MQL_FILE]['field_profile']['origin']['empty_rows']}条，unknown文本{result['origin_lead_counts'].get('unknown', 0)}条，分别保留。")
    print("注意：未匹配不等于确定失单；这是商家入驻签约，不是消费者购买。")
    print(f"检查报告：{REPORTS / '01_数据检查结果.md'}")
    print("请把这段运行结果截图；下一步用SQL连接两张表。")
    # 审计发现的数据问题写入报告；发现异常不等于程序运行失败。
    # 文件缺失、内容变更等导致无法可靠审计的错误，则由下方异常处理终止。


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        raise SystemExit(f"数据检查未完成：{exc}") from exc
