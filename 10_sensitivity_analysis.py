"""第十步：三种描述性敏感性检查，与05主方案分别对照。

本文件放项目根目录，10_sensitivity_details.sql放sql文件夹后点击运行。
复用04来源校验与07绘图样式，不修改数据库、原始CSV或01—09结果。
"""

import csv
import hashlib
import importlib.util
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT/'reports'
FIGURES = REPORTS/'figures'
DB = ROOT/'data/olist_marketing.sqlite3'
CHANNELS = ('organic_search', 'paid_search', 'social')
LABELS = {'organic_search': '自然搜索', 'paid_search': '付费搜索', 'social': '社交来源'}
SCENARIOS = {
    'baseline': {'label': '05主方案', 'exclude': False, 'minimum': 1, 'equal': False,
                 'target': '三来源共同月份的合并线索月份构成'},
    'exclude_date_issue': {'label': '排除日期异常', 'exclude': True, 'minimum': 1, 'equal': False,
                           'target': '仅排除异常整条MQL后，重新计算合并线索月份构成'},
    'min_month_n20': {'label': '每来源月内至少20条', 'exclude': False, 'minimum': 20, 'equal': False,
                      'target': '仅保留三来源各有至少20条线索的月份，重新计算合并权重'},
    'equal_months': {'label': '原共同月份等权', 'exclude': False, 'minimum': 1, 'equal': True,
                     'target': '沿用原共同月份，各月份同等重要，不按线索量加权'},
}
COLUMNS = ['scenario','contact_month','channel','lead_count','observed_won_count','date_issue_count',
           'pooled_lead_count','month_weight','observed_won_pct','weighted_contribution_pp']


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference(tables, stage04):
    deals = {r['mql_id']: r for r in tables[stage04.DEAL_FILE]}
    refs, scopes = {}, {}
    for scenario, setting in SCENARIOS.items():
        monthly = defaultdict(lambda: [0,0,0])
        source_months = set()
        for lead in tables[stage04.MQL_FILE]:
            channel = lead['origin'].strip() or '(未记录)'
            if channel not in CHANNELS:
                continue
            month = lead['first_contact_date'][:7]
            source_months.add(month)
            deal = deals.get(lead['mql_id'])
            issue = int(deal is not None and datetime.fromisoformat(deal['won_date']).date() < datetime.fromisoformat(lead['first_contact_date']).date())
            if setting['exclude'] and issue:
                continue
            values = monthly[(month,channel)]
            values[0] += 1
            values[1] += int(deal is not None)
            values[2] += issue
        common = sorted(month for month in source_months if all(monthly[(month, c)][0] >= setting['minimum'] for c in CHANNELS))
        if not common:
            raise ValueError(f'{scenario}没有符合规则的共同月份。')
        pooled = {m: sum(monthly[(m,c)][0] for c in CHANNELS) for m in common}
        total = sum(pooled.values())
        weights = {m: Fraction(1,len(common)) if setting['equal'] else Fraction(pooled[m],total) for m in common}
        if sum(weights.values()) != 1:
            raise ValueError('参考权重之和不是1。')
        scopes[scenario] = {'months': common, 'excluded_primary_source_months': sorted(source_months-set(common)),
                            'shared_weight_lead_count': total, 'month_weights': {m: float(weights[m]) for m in common},
                            'month_weight_sum': float(sum(weights.values()))}
        for month in common:
            for channel in CHANNELS:
                n, won, issues = monthly[(month,channel)]
                refs[(scenario,month,channel)] = {
                    'scenario':scenario,'contact_month':month,'channel':channel,'lead_count':n,
                    'observed_won_count':won,'date_issue_count':issues,'pooled_lead_count':pooled[month],
                    'month_weight':float(weights[month]),'observed_won_pct':float(100*Fraction(won,n)),
                    'weighted_contribution_pp':float(100*weights[month]*Fraction(won,n))}
    return refs, scopes


def run_sql(hashes, expected):
    path = ROOT/'sql/10_sensitivity_details.sql'
    text = path.read_text(encoding='utf-8-sig').strip()
    with closing(sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only = ON')
        metadata = dict(conn.execute('SELECT key,value FROM project_metadata'))
        if metadata.get('schema_version') != 'olist_stage02_v1' or any(metadata.get('sha256:'+k)!=v for k,v in hashes.items()):
            raise ValueError('数据库来源或版本不一致。')
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(text)
        if cursor.description is None or [x[0] for x in cursor.description] != COLUMNS:
            raise ValueError('10 SQL输出列名与协议不符。')
        rows = [dict(r) for r in cursor.fetchall()]
    seen = set()
    for row in rows:
        key = (row['scenario'],row['contact_month'],row['channel'])
        if key in seen or key not in expected:
            raise ValueError('10 SQL有重复或不符合规则的月份／来源。')
        seen.add(key)
        for field, value in expected[key].items():
            actual = row[field]
            if isinstance(value,float):
                if not isinstance(actual,(float,int)) or not math.isclose(actual,value,abs_tol=1e-10,rel_tol=1e-12):
                    raise ValueError(f'{key}的{field}与独立原始CSV计算不一致。')
            elif actual != value or (isinstance(value,int) and type(actual) is not int):
                raise ValueError(f'{key}的{field}与原始CSV不一致。')
    if seen != set(expected):
        raise ValueError('10 SQL遗漏了符合规则的组合。')
    return {'file':str(path),'sha256':sha256(path),'executed_sql':text,'rows':rows}


def summarize(rows, scopes):
    summaries = []
    for scenario, setting in SCENARIOS.items():
        rates, counts, wins = {}, {}, {}
        for channel in CHANNELS:
            subset = [r for r in rows if r['scenario']==scenario and r['channel']==channel]
            rates[channel] = math.fsum(r['weighted_contribution_pp'] for r in subset)
            counts[channel] = sum(r['lead_count'] for r in subset)
            wins[channel] = sum(r['observed_won_count'] for r in subset)
            if not math.isclose(math.fsum(r['month_weight'] for r in subset),1,abs_tol=1e-12):
                raise ValueError('某来源的月份权重之和不是1。')
        summaries.append({'scenario':scenario,'label':setting['label'],'target':setting['target'],**scopes[scenario],
                          'channel_lead_counts':counts,'channel_observed_won_counts':wins,
                          'standardized_won_pct':rates,
                          'paid_minus_organic_pp':rates['paid_search']-rates['organic_search'],
                          'descending_order':sorted(CHANNELS,key=lambda c:(-rates[c],c))})
    return summaries


def check_baseline(summaries, hashes):
    path = REPORTS/'05_month_standardization.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    if saved.get('stage') != '05_descriptive_month_standardization' or saved['source_sha256'] != hashes:
        raise ValueError('05结果来源不一致，请先核对05。')
    baseline = summaries[0]
    if baseline['months'] != saved['common_months'] or baseline['shared_weight_lead_count'] != saved['shared_weight_lead_count']:
        raise ValueError('10主方案月份或分母没有复现05。')
    for row in saved['queries']['summary']['rows']:
        if not math.isclose(baseline['standardized_won_pct'][row['channel']],row['standardized_won_pct'],abs_tol=1e-10):
            raise ValueError('10主方案数值没有复现05。')
    return sha256(path)


def draw_figure(summaries):
    plot = load_module('olist_style10','07_plot_project.py')
    family = plot.configure_style()
    fig, axes = plot.plt.subplots(1,2,figsize=(14,8.2),gridspec_kw={'width_ratios':[1.5,1]})
    fig.subplots_adjust(left=.17,right=.96,top=.78,bottom=.31,wspace=.36)
    fig.text(.055,.95,'稳健性检查：排序与差值如何随设定变化？',fontsize=20,weight='bold',va='top')
    fig.text(.055,.89,'05保留为主方案｜三项检查分别改变一个设定，不累计叠加｜全部为文件内描述性比较',fontsize=10.5,color=plot.MUTED)
    left,right = axes
    offsets = [-.18,0,.18]
    for channel,offset in zip(CHANNELS,offsets):
        values=[s['standardized_won_pct'][channel] for s in summaries]
        ys=[i+offset for i in range(len(summaries))]
        left.scatter(values,ys,color=plot.COLORS[channel],s=45,label=LABELS[channel])
    left.set_yticks(range(len(summaries)),[s['label'] for s in summaries])
    left.invert_yaxis(); left.set_xlim(0,16)
    left.set_xlabel('标准化已观察签约占比（%）')
    left.set_title('各来源占比',fontsize=12,weight='bold',pad=15)
    handles, legend_labels = left.get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc='upper left', bbox_to_anchor=(.17,.865), ncol=3, frameon=False, fontsize=9)
    plot.clean_axis(left)
    differences=[s['paid_minus_organic_pp'] for s in summaries]
    right.barh(range(len(summaries)),differences,color=['#426FA3']+['#A4B9C1']*3,height=.5)
    right.set_yticks(range(len(summaries)),[f"{len(s['months'])}个月 / {s['shared_weight_lead_count']:,}条" for s in summaries],fontsize=9)
    right.invert_yaxis(); right.set_xlim(0,max(differences)*1.45)
    right.set_xlabel('付费搜索减自然搜索（百分点）')
    right.set_title('差值与方案覆盖的线索量',fontsize=12,weight='bold',pad=15)
    for i,diff in enumerate(differences):right.text(diff+.025,i,f'+{diff:.2f}',va='center',fontsize=10)
    plot.clean_axis(right)
    stable=all(s['descending_order']==summaries[0]['descending_order'] for s in summaries)
    fig.text(.06,.17,'本次检查：三来源描述性排序保持一致。' if stable else '本次检查：描述性排序随设定变化，需按方案分别解释。',fontsize=12,weight='bold')
    fig.text(.06,.12,'月份等权改变了比较目标；20条门槛仅用于敏感性检查。数值变化不表示新增签约。',fontsize=10)
    fig.text(.06,.065,'这些检查不证明统计显著性、因果优势或完整随访下的最终签约率；原CSV、数据库及05主结果保持不变。',fontsize=9,color=plot.MUTED)
    FIGURES.mkdir(parents=True,exist_ok=True)
    stem=FIGURES/'10_01_sensitivity_comparison'
    fig.savefig(stem.with_suffix('.png'),dpi=180,metadata={'Software':'Olist descriptive sensitivity analysis'})
    fig.savefig(stem.with_suffix('.svg'),metadata={'Date':None})
    plot.plt.close(fig)
    return family,[stem.with_suffix('.png'),stem.with_suffix('.svg')]


def write_report(summaries, query):
    lines=['# 第十步：描述性稳健性分析','','## 固定的四种方案','',
        '05为保留的主方案；下面三项检查各自相对主方案改变一个设定，不依次叠加。方案在本脚本中固定；这是探索后的描述性敏感性检查，并非预注册或独立确认性检验。','',
        '1. 主方案：三来源都有至少1条线索的共同月份，按合并线索月份构成加权。',
        '2. 排除日期异常：只在本次计算中排除该整条MQL，分子与分母同时减少，再重算共同月份和权重；不把异常签约改成未签约，不删除原始记录。',
        '3. 每来源月内至少20条：该月三个来源分别达到门槛才进入汇总，只按线索分母筛选；20条并非统计充分性的保证，也不根据签约数挑月份。',
        '4. 原共同月份等权：使用主方案共同月份与原始记录，每月权重1／共同月份数，目标变为“各月份同等重要”。','',
        '## 结果对照','','| 方案 | 月份数 | 三来源合并线索数 | 自然搜索 | 付费搜索 | 社交来源 | 付费−自然（百分点） |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in summaries:
        rates=s['standardized_won_pct']
        lines.append('| '+' | '.join([s['label'],str(len(s['months'])),f"{s['shared_weight_lead_count']:,}"]+[f'{rates[c]:.2f}%' for c in CHANNELS]+[f"{s['paid_minus_organic_pp']:+.2f}"])+' |')
    stable=all(s['descending_order']==summaries[0]['descending_order'] for s in summaries)
    lines+=['', ('在所检查的三种设定中，描述性排序保持一致：'+ '＞'.join(LABELS[c] for c in summaries[0]['descending_order'])+'。') if stable else '排序随检查方案变化，需按方案分别解释。',
        '差值幅度会随比较范围与权重目标改变。不能由这些有限检查宣布“彻底稳健”、统计显著或渠道因果优势。','',
        '## 分母、月份与权重目标','']
    for s in summaries:
        lines += ['### '+s['label'],'',s['target']+'。',
                  '纳入月份：'+', '.join(s['months'])+'。',
                  '三来源中未纳入的月份：'+(', '.join(s['excluded_primary_source_months']) or '无')+'。',
                  '各来源分母：'+'；'.join(f"{LABELS[c]} {s['channel_lead_counts'][c]}条、匹配签约{s['channel_observed_won_counts'][c]}条" for c in CHANNELS)+'。','',
                  '| 月份 | 三来源共用权重 |','| --- | ---: |']
        lines += [f'| {m} | {w*100:.4f}% |' for m,w in s['month_weights'].items()]
        lines += ['', '未舍入权重之和为1；表中展示值舍入后可能不恰好合计100%。','']
    lines += ['## 对业务结论的影响','',
              '现阶段可说：在本次检查的设定下，三个来源的描述性排序没有改变；付费与自然搜索的差值大小依赖比较目标。仍需来源质量、全体线索跟进状态与真实成本数据，才能进一步讨论业务动作。',
              '原始文件中未匹配签约的记录不等于最终失败。月份标准化和这些敏感性检查都没有统一完整随访时长。', '',
              '## 图表','','![稳健性方案对照](figures/10_01_sensitivity_comparison.png)','',
              '## SQL学习重点','',
              '- settings用VALUES列出方案参数，CROSS JOIN让同一来源数据分别进入各方案。',
              '- HAVING同时检查三个来源是否都存在、月内最小分母是否达到门槛。',
              '- PARTITION BY scenario分别计算各方案的总量和月份数。',
              '- weighted_contribution_pp是每月对标准化百分比的贡献，按方案和来源求和得到最终结果。','',
              '实际SQL如下；10_sensitivity_details.csv和JSON保留全部方案×月份×来源明细及未舍入数值。','',
              '```sql',query['executed_sql'],'```','',
              '数据来源与许可见[data/raw/SOURCE.md](../data/raw/SOURCE.md)。原CSV、数据库、03练习SQL及01—09报告未改。','']
    path=REPORTS/'10_稳健性分析.md'; path.write_text('\n'.join(lines),encoding='utf-8')
    return path


def main():
    stage04=load_module('olist_stage04_for10','04_channel_metrics.py')
    tables,hashes=stage04.read_sources()
    if not DB.is_file():raise ValueError('请先运行02创建数据库。')
    protected=[DB]+list((ROOT/'data/raw').glob('*'))+list((ROOT/'sql').glob('*.sql'))
    protected += [p for p in REPORTS.rglob('*') if p.is_file() and not p.name.startswith('10_')]
    before={str(p):sha256(p) for p in protected if p.is_file()}
    expected,scopes=reference(tables,stage04)
    query=run_sql(hashes,expected)
    summaries=summarize(query['rows'],scopes)
    baseline_hash=check_baseline(summaries,hashes)
    family,images=draw_figure(summaries)
    report=write_report(summaries,query)
    csv_path=REPORTS/'10_sensitivity_details.csv'
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=COLUMNS);writer.writeheader();writer.writerows(query['rows'])
    if any(sha256(Path(p))!=digest for p,digest in before.items()):raise ValueError('原始文件或早期报告发生变化，请检查。')
    result={'stage':'10_descriptive_sensitivity_analysis','generated_at_utc':datetime.now(timezone.utc).isoformat(),
            'source_sha256':hashes,'database_sha256':sha256(DB),'baseline_stage05_sha256':baseline_hash,
            'baseline_reproduces_stage05':True,'sql_matches_independent_fraction_reference':True,
            'original_files_and_01_to_09_unchanged':True,'protocol':SCENARIOS,'summaries':summaries,'query':query,
            'font_family':family,'outputs':{p.relative_to(ROOT).as_posix():{'bytes':p.stat().st_size,'sha256':sha256(p)} for p in images+[report,csv_path]}}
    (REPORTS/'10_sensitivity_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('第十步完成：稳健性分析已生成，05主方案保持不变。')
    print('方案 | 月份数 | 三来源线索数 | 自然搜索 | 付费搜索 | 社交来源 | 付费减自然（百分点）')
    for s in summaries:
        rates=s['standardized_won_pct']
        print(f"{s['label']} | {len(s['months'])} | {s['shared_weight_lead_count']:,} | "+' | '.join(f'{rates[c]:.2f}%' for c in CHANNELS)+f" | {s['paid_minus_organic_pp']:+.2f}")
    print('三项检查各相对主方案单独变化，不累计叠加；等权方案改变了比较目标。')
    print('SQL结果与原始CSV独立计算一致；原CSV、数据库、03 SQL及01—09结果保持不变。')
    print(f'报告：{report}')
    print(f'图片：{images[0]}')
    print('请截图终端结果，之后只更新业务总结和GitHub展示包，不再增加分析项。')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,sqlite3.Error) as exc:
        raise SystemExit(f'第十步未完成：{exc}\n请检查04、05报告、07脚本及10 SQL文件是否齐全。') from exc
