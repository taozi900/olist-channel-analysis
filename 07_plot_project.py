"""第七步：从04／05／06已保存的JSON生成四张项目图。

先运行01至06。首次缺少Matplotlib时运行07_prepare_plotting.py。
只绘图，不重新执行SQL或更改已有报告；图片保存在reports/figures。
"""

import hashlib
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(ROOT / ".plot_cache")
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, ticker
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle
except ImportError as exc:
    raise SystemExit("当前环境缺少绘图库。请先打开07_prepare_plotting.py并运行一次，再运行本文件。") from exc

FIGURES = ROOT / "reports" / "figures"
INPUTS = {
    "04": ("04_channel_metrics.json", "04_observed_channel_and_month_metrics"),
    "05": ("05_month_standardization.json", "05_descriptive_month_standardization"),
    "06": ("06_time_diagnostics.json", "06_observed_won_time_and_record_coverage"),
}
CHANNELS = ("organic_search", "paid_search", "social")
COLORS = {"organic_search":"#168578", "paid_search":"#426FA3", "social":"#C17C3A"}
LABELS = {
    "organic_search":"自然搜索", "paid_search":"付费搜索", "social":"社交来源",
    "unknown":"未知标签 unknown", "direct_traffic":"直接访问", "email":"邮件来源",
    "referral":"推荐来源", "other":"其他", "display":"展示来源",
    "other_publicities":"其他宣传", "(未记录)":"来源未记录",
}
INK, MUTED, GRID = "#193641", "#617580", "#E4EBEE"
VERSION = "olist_figures_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_style():
    candidates = [Path(r"C:\Windows\Fonts\msyh.ttc"), Path(r"C:\Windows\Fonts\simhei.ttf")]
    font_path = next((p for p in candidates if p.is_file()), None)
    if font_path:
        font_manager.fontManager.addfont(str(font_path))
        family = font_manager.FontProperties(fname=str(font_path)).get_name()
    else:
        installed = {f.name for f in font_manager.fontManager.ttflist}
        family = next((name for name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"] if name in installed), None)
        if family is None:
            raise ValueError("找不到可用中文字体，请安装中文字体后重画；可先查看包内PNG。")
    plt.rcParams.update({
        "font.family":family, "font.size":11, "text.color":INK,
        "axes.labelcolor":MUTED, "xtick.color":MUTED, "ytick.color":INK,
        "axes.unicode_minus":False, "axes.edgecolor":GRID,
        "figure.facecolor":"white", "axes.facecolor":"white",
        "svg.fonttype":"none", "svg.hashsalt":VERSION,
        "savefig.facecolor":"white",
    })
    return family


def load_reports():
    reports, fingerprints = {}, {}
    for key, (name, stage) in INPUTS.items():
        path = ROOT / "reports" / name
        reports[key] = json.loads(path.read_text(encoding="utf-8"))
        if reports[key].get("stage") != stage:
            raise ValueError(f"{name}阶段标识不匹配，请先重新核对对应步骤。")
        fingerprints[f"reports/{name}"] = sha256(path)
    if not (reports["04"]["source_sha256"] == reports["05"]["source_sha256"] == reports["06"]["source_sha256"]):
        raise ValueError("04／05／06报告的数据来源不一致，不能混合绘图。")
    rows = reports["04"]["queries"]["channels"]["rows"]
    totals = reports["04"]["totals"]
    if len({r["channel"] for r in rows}) != len(rows) or sum(r["lead_count"] for r in rows) != totals["lead_count"] or sum(r["observed_won_count"] for r in rows) != totals["observed_won_count"]:
        raise ValueError("04渠道汇总计数不一致。")
    if {r["channel"] for r in reports["05"]["queries"]["summary"]["rows"]} != set(CHANNELS):
        raise ValueError("05比较来源与本图方案不一致。")
    valid = reports["06"]["duration_status_counts"]["valid_duration"]
    if sum(r["count"] for r in reports["06"]["duration_buckets"]) != valid or reports["06"]["coverage"]["observed_won_count"] != totals["observed_won_count"]:
        raise ValueError("06有效时长或匹配签约计数不能与前面步骤对齐。")
    return reports, fingerprints


def title(fig, main, subtitle):
    fig.text(.055,.95,main,fontsize=21,weight="bold",va="top")
    fig.text(.055,.895,subtitle,fontsize=10.8,color=MUTED,va="top")


def footer(fig, lines):
    for i, line in enumerate(lines):
        fig.text(.055,.088-i*.025,line,fontsize=9.2,color=MUTED,va="top")


def clean_axis(ax, grid="x"):
    ax.set_axisbelow(True)
    ax.grid(axis=grid,color=GRID,linewidth=.8)
    for side in ["top","right","left"]:
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="both",length=0,pad=7)


def save(fig, stem):
    paths = []
    for suffix in ["png","svg"]:
        path = FIGURES / f"{stem}.{suffix}"
        metadata = {"Date":None,"Creator":"Olist local plotting script"} if suffix=="svg" else {"Software":f"Matplotlib {matplotlib.__version__}"}
        fig.savefig(path,dpi=180,metadata=metadata)
        paths.append(path)
    plt.close(fig)
    return paths


def volume_rate_chart(reports):
    data = reports["04"]
    rows = sorted(data["queries"]["channels"]["rows"],key=lambda r:(-r["lead_count"],r["channel"]))
    y = list(range(len(rows)))
    fig = plt.figure(figsize=(14,8.4))
    totals = data["totals"]
    title(fig,"从线索规模到可见签约：各来源的样本表现",f"Olist抽样数据  |  {totals['lead_count']:,}条MQL线索记录，{totals['observed_won_count']:,}条匹配签约  |  来源包含未知标签与空值")
    left = fig.add_axes([.19,.19,.285,.61])
    right = fig.add_axes([.55,.19,.405,.61],sharey=left)
    colors = [COLORS.get(r["channel"],"#9BB0BA") for r in rows]
    bars = left.barh(y,[r["lead_count"] for r in rows],height=.55,color=colors)
    for i, (bar,row) in enumerate(zip(bars,rows)):
        if row["channel"] in {"unknown","(未记录)"}:
            bar.set_facecolor("#C8D0D5"); bar.set_hatch("///"); bar.set_edgecolor("#84949E")
        left.text(row["lead_count"]+40,i,f"{row['lead_count']:,}",va="center",fontsize=10.5)
        value = row["observed_won_pct"]
        right.scatter(value,i,s=52,color=colors[i] if row["channel"] not in {"unknown","(未记录)"} else "#788B95",marker="x" if row["channel"] in {"unknown","(未记录)"} else "o",zorder=3)
        right.text(value+.65,i,f"{value:.2f}%  ({row['observed_won_count']}/{row['lead_count']})",va="center",fontsize=10.2,color=INK)
    left.set_yticks(y,[LABELS.get(r["channel"],r["channel"]) for r in rows])
    left.invert_yaxis()
    left.set_xlim(0,max(r["lead_count"] for r in rows)*1.25)
    right.set_xlim(0,max(r["observed_won_pct"] for r in rows)+11)
    left.set_title("线索记录数",loc="left",fontsize=13,pad=15,weight="bold")
    right.set_title("已观察签约占比  ·  括号为签约数/线索数",loc="left",fontsize=12,pad=15,weight="bold")
    left.set_xlabel("条"); right.set_xlabel("记录内可见签约占比（%）")
    right.xaxis.set_major_locator(ticker.MultipleLocator(10))
    right.tick_params(labelleft=False)
    clean_axis(left); clean_axis(right)
    footer(fig,["占比＝匹配到签约记录的线索数÷该来源全部线索数；不代表最终签约率、因果效果或预算回报。",
                "灰色斜线/叉号：unknown和来源未记录是数据质量分类，不是可以直接追加预算的明确渠道。",
                "来源：Olist官方公开抽样数据，本地04汇总；统计单位为MQL记录，完整随访截止未知。"])
    return save(fig,"07_01_channel_volume_rate")


def standardized_chart(reports):
    data = reports["05"]
    lookup = {r["channel"]:r for r in data["queries"]["summary"]["rows"]}
    fig = plt.figure(figsize=(14,7.6))
    title(fig,"统一月份构成：原始占比与标准化占比",f"三来源共同的{len(data['common_months'])}个月  |  月份权重来自合并的{data['shared_weight_lead_count']:,}条线索  |  三来源共享同一套非等月权重")
    ax = fig.add_axes([.17,.31,.455,.40])
    positions = [2,1,0]
    for channel,y in zip(CHANNELS,positions):
        row=lookup[channel]
        a,b=row["all_observed_won_pct"],row["standardized_won_pct"]
        ax.plot([a,b],[y,y],color="#8C9DA5",linewidth=2,zorder=1)
        ax.scatter(a,y,s=82,facecolor="white",edgecolor="#7B8F99",linewidth=1.6,zorder=4)
        ax.scatter(b,y,s=53,marker="D",color=COLORS[channel],zorder=5)
        fy=.31+(y+.5)/3*.40
        fig.text(.735,fy,f"{a:.2f}%",ha="center",va="center",fontsize=15,color=MUTED)
        fig.text(.875,fy,f"{b:.2f}%",ha="center",va="center",fontsize=15,color=COLORS[channel],weight="bold")
    ax.set_ylim(-.5,2.5); ax.set_xlim(0,16)
    ax.set_yticks(positions,[LABELS[c] for c in CHANNELS])
    ax.set_xticks([0,4,8,12,16]); ax.set_xlabel("记录内可见签约占比（%）")
    clean_axis(ax)
    fig.text(.735,.76,"原始汇总",ha="center",fontsize=12,color=MUTED)
    fig.text(.875,.76,"月份标准化",ha="center",fontsize=12,color=MUTED)
    handles=[Line2D([],[],marker="o",linestyle="None",markerfacecolor="white",markeredgecolor="#7B8F99",label="原始汇总"),Line2D([],[],marker="D",linestyle="None",color=INK,label="相同月份权重")]
    fig.legend(handles=handles,loc="upper left",bbox_to_anchor=(.165,.835),ncol=2,frameon=False,fontsize=10.5)
    gap=lookup["paid_search"]["standardized_won_pct"]-lookup["organic_search"]["standardized_won_pct"]
    fig.add_artist(Rectangle((.055,.135),.90,.095,transform=fig.transFigure,facecolor="#EFF4F6",edgecolor="none"))
    fig.text(.075,.195,f"付费搜索 − 自然搜索：标准化后约 {gap:+.2f} 个百分点",fontsize=12,va="center",weight="bold")
    fig.text(.075,.158,"仅为描述性差值；未进行显著性检验，不能据此确认渠道优劣。",fontsize=10.5,color=MUTED,va="center")
    footer(fig,["标准化只改变汇总权重，没有新增线索或签约；同一月份在三个来源中使用相同权重。",
                "来源：本地05方案；共同月份按分母选择。月份构成调整不等于统一随访，也不等于因果识别。"])
    return save(fig,"07_02_month_standardization")


def monthly_chart(reports):
    data=reports["05"]
    months=data["common_months"]
    cells={(r["contact_month"],r["channel"]):r for r in data["queries"]["details"]["rows"]}
    if set(cells)!={(m,c) for m in months for c in CHANNELS}:
        raise ValueError("05月份明细缺少共同月份单元，不能补零绘图。")
    fig=plt.figure(figsize=(14,8.4))
    title(fig,"看同一个月：可见签约占比与线索构成",f"按首次联系月份归组  |  {months[0]}至{months[-1]}  |  上图分母为当月该来源全部线索")
    top=fig.add_axes([.10,.49,.84,.32])
    bottom=fig.add_axes([.10,.19,.84,.21],sharex=top)
    x=list(range(len(months)))
    for channel in CHANNELS:
        top.plot(x,[cells[(m,channel)]["observed_won_pct"] for m in months],label=LABELS[channel],color=COLORS[channel],linewidth=2.2,marker="o",markersize=4)
    top.set_ylim(0,math.ceil(max(r["observed_won_pct"] for r in cells.values())/5)*5+1)
    top.set_ylabel("月内可见签约占比（%）")
    top.yaxis.set_major_locator(ticker.MultipleLocator(5))
    top.tick_params(labelbottom=False)
    clean_axis(top,grid="y")
    bases=[0]*len(months)
    for channel in CHANNELS:
        values=[cells[(m,channel)]["lead_count"] for m in months]
        bottom.bar(x,values,bottom=bases,width=.62,color=COLORS[channel],edgecolor="white",linewidth=.6)
        bases=[a+b for a,b in zip(bases,values)]
    for i,value in enumerate(bases):
        bottom.text(i,value+20,f"{value:,}",ha="center",va="bottom",fontsize=9.4)
    bottom.set_ylim(0,max(bases)*1.22)
    bottom.set_xticks(x,months,rotation=0,fontsize=9.3)
    bottom.set_ylabel("三来源线索数（条）")
    bottom.set_xlabel("首次联系月份")
    clean_axis(bottom,grid="y")
    handles,labels=top.get_legend_handles_labels()
    fig.legend(handles,labels,loc="upper left",bbox_to_anchor=(.095,.865),ncol=3,frameon=False,fontsize=10.7)
    footer(fig,["下图是三个指定来源的线索数堆积，柱顶是当月合计；不是全部来源样本量，也不是签约数。",
                "只显示三个来源均有线索的共同月份；零签约占比可为0，未给没有线索的组合补0。小分母月份需谨慎解读。",
                "来源：本地05月度明细；签约可发生在后续月份，完整随访截止未知。"])
    return save(fig,"07_03_monthly_comparison")


def duration_chart(reports):
    data=reports["06"]
    rows=data["duration_buckets"]
    valid=data["duration_status_counts"]["valid_duration"]
    negative=data["duration_status_counts"].get("negative_interval",0)
    summaries={r["channel"]:r for r in data["duration_summaries"]}
    overall=summaries["all_channels"]
    fig=plt.figure(figsize=(14,7.8))
    title(fig,"仅有效已签约者：日历时长区间分布",f"全部来源  |  文件内已观察签约且日期有效的{valid:,}条记录  |  {negative}条负时长单列")
    ax=fig.add_axes([.15,.24,.425,.54])
    y=list(range(len(rows)))
    ax.barh(y,[r["count"] for r in rows],height=.55,color="#528D9F")
    for i,row in enumerate(rows):
        ax.text(row["count"]+7,i,f"{row['count']}  ({row['share_pct']:.2f}%)",va="center",fontsize=11)
    ax.set_yticks(y,[r["bucket"] for r in rows]); ax.invert_yaxis()
    ax.set_xlim(0,max(r["count"] for r in rows)*1.38)
    ax.set_xlabel("可见签约记录数（条）")
    clean_axis(ax)
    fig.add_artist(Rectangle((.655,.23),.295,.56,transform=fig.transFigure,facecolor="#EFF4F6",edgecolor="none"))
    fig.text(.675,.75,f"这{valid:,}条有效记录",fontsize=13,weight="bold")
    fig.text(.675,.69,f"中位数：{overall['median_days']:g} 天",fontsize=19,weight="bold")
    fig.text(.675,.63,f"90%分位数：{overall['p90_days']:g} 天",fontsize=13)
    fig.text(.675,.545,"指定来源",fontsize=10.5,color=MUTED)
    fig.text(.82,.545,"有效数",ha="center",fontsize=10.5,color=MUTED)
    fig.text(.92,.545,"中位天数",ha="center",fontsize=10.5,color=MUTED)
    for i,channel in enumerate(CHANNELS):
        row=summaries[channel]; fy=.485-i*.065
        fig.text(.675,fy,LABELS[channel],fontsize=11,color=COLORS[channel])
        fig.text(.82,fy,str(row["valid_duration_count"]),ha="center",fontsize=11)
        fig.text(.92,fy,f"{row['median_days']:g}",ha="center",fontsize=11)
    fig.text(.675,.275,"以上只描述已经观察到签约者。",fontsize=10.5,color=MUTED)
    footer(fig,["分母仅为日期有效的已观察签约者；未匹配线索不补0天，异常记录仍保留在前面04/05的匹配签约计数中。",
                "日期相减是日历天数，0天表示同日。区间宽度不同，条长表示记录数，不表示单位天密度。",
                "来源：本地06诊断；不能据此代表全部线索的销售效率，也不能用P90确定完整随访窗口。"])
    return save(fig,"07_04_observed_won_duration")


def write_readme(reports):
    text="""# 第七步：图表与阅读顺序

1. **07_01_channel_volume_rate.png**：左边看来源线索量，右边看文件内已观察签约占比。未知标签与空来源单列，不能当预算赢家。
2. **07_02_month_standardization.png**：比较三个来源的原始占比与相同月份权重后的占比；数值变化不是实际新增签约。
3. **07_03_monthly_comparison.png**：上图看各首次联系月份内的可见签约占比，下图看三来源内的样本线索量构成。下图柱高是数量，不是百分比。
4. **07_04_observed_won_duration.png**：只看日期有效的已观察签约者的日历时长；没有把未签约者当作0天。

PNG适合放进简历作品集、PPT和GitHub。SVG可放大，使用中文字体；跨设备展示优先PNG。

## 如何本机重画

- 所有脚本放在项目根目录；先完成04、05、06，确保reports中对应JSON存在。
- 当前环境没有Matplotlib时，先运行根目录07_prepare_plotting.py。它只在本项目虚拟环境中安装，使用requirements-plotting.txt，关闭pip下载缓存，并将安装临时目录及绘图缓存放在项目内。首次安装需要联网；是否能安装成功取决于本机网络与包源。
- 再运行07_plot_project.py。输入是04/05/06 JSON；不重新执行SQL、训练模型或改变源报告。
- 绘图结果写入当前reports/figures。图不会自动弹窗；在VS Code左侧展开reports→figures，点击PNG即可查看。
- 目录中的07_figure_manifest.json记录生成环境、输入报告SHA256和输出文件SHA256。包内图片是助手先生成的预览；本机重跑后会更新为本机生成信息。

## 口径

- 可见签约占比＝该组匹配到签约记录的MQL数÷该组全部MQL记录数，不是最终签约率或因果效果。
- 观察单位是抽样MQL记录，不能自动当作独立商家。完整随访截止未知，缺少成本与利润；本阶段没有显著性检验，不报告最优预算或ROI提升。
- 05权重来自三个指定来源共同月份的合并线索量；不是每月等权，也不是全企业构成。
- 来源中文名是对原始标签的阅读辅助，不替代发布方的业务采集定义。
- 数据及图中统计取自Olist官方匿名化抽样数据及本地04/05/06结果。数据原始许可和来源见data/raw/SOURCE.md。
"""
    path=FIGURES/"07_图表阅读与复现.md"
    path.write_text(text,encoding="utf-8")
    return path


def main():
    reports,fingerprints=load_reports()
    family=configure_style()
    FIGURES.mkdir(parents=True,exist_ok=True)
    files=[]
    for plot in [volume_rate_chart,standardized_chart,monthly_chart,duration_chart]:
        files.extend(plot(reports))
    files.append(write_readme(reports))
    if any(sha256(ROOT/rel)!=value for rel,value in fingerprints.items()):
        raise ValueError("绘图期间输入报告发生变化，请检查后再运行。")
    manifest={
        "version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "matplotlib_version":matplotlib.__version__,"font_family":family,
        "input_sha256":fingerprints,"source_sha256":reports["04"]["source_sha256"],
        "source_reports_unchanged":True,
        "outputs":{p.relative_to(ROOT).as_posix():{"bytes":p.stat().st_size,"sha256":sha256(p)} for p in files},
    }
    (FIGURES/"07_figure_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("第七步完成：四张项目图已生成，04／05／06输入报告保持不变。")
    print(f"图片目录：{FIGURES}")
    for path in files:
        if path.suffix==".png":
            print("  "+path.name)
    print("在VS Code左侧展开reports→figures，先点击07_01_channel_volume_rate.png。")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError) as exc:
        raise SystemExit(f"绘图未完成：{exc}\n请先确认04、05、06已运行成功。") from exc
