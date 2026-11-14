#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《Ollama Metrics Monitor 产品手册》DOCX"""

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ---------- 设计常量 ----------
INK = RGBColor(0x11, 0x14, 0x18)
MUTED = RGBColor(0x56, 0x5E, 0x65)
FAINT = RGBColor(0x6E, 0x76, 0x7D)
ACCENT = RGBColor(0xC2, 0x41, 0x0C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

CJK = "Microsoft YaHei"
LATIN = "Calibri"
MONO = "Consolas"


# ---------- 底层工具 ----------
def set_run_fonts(run, latin=LATIN, cjk=CJK, size=None, bold=None, color=None):
    run.font.name = latin
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), latin)
    rFonts.set(qn("w:hAnsi"), latin)
    rFonts.set(qn("w:eastAsia"), cjk)
    rFonts.set(qn("w:cs"), latin)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade_paragraph(p, hex_fill):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pPr.append(shd)


def shade_cell(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def para_border(p, edge="bottom", color="D8DCDE", sz=8, space=1):
    pPr = p._p.get_or_add_pPr()
    pbdr = pPr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        pPr.append(pbdr)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    pbdr.append(el)


def keep_with_next(p):
    p.paragraph_format.keep_with_next = True


# ---------- 文档级样式 ----------
def setup_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = LATIN
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.45
    pf.space_after = Pt(6)

    specs = {
        "Heading 1": (15, ACCENT, 16, 8),
        "Heading 2": (12, INK, 12, 5),
        "Heading 3": (10.5, MUTED, 9, 4),
    }
    for name, (size, color, before, after) in specs.items():
        st = doc.styles[name]
        st.font.name = LATIN
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = color
        st.element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True
        st.paragraph_format.line_spacing = 1.3


def setup_page(doc):
    for s in doc.sections:
        s.page_width = Cm(21.0)
        s.page_height = Cm(29.7)
        s.top_margin = Cm(2.2)
        s.bottom_margin = Cm(2.0)
        s.left_margin = Cm(2.3)
        s.right_margin = Cm(2.3)


def add_footer(doc, text):
    for section in doc.sections:
        p = section.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text + "    ")
        set_run_fonts(r, size=8, color=FAINT)
        # PAGE 域
        r1 = p.add_run()
        fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
        r1._r.append(fld1)
        r2 = p.add_run()
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
        instr.text = " PAGE "
        r2._r.append(instr)
        r3 = p.add_run()
        fld3 = OxmlElement("w:fldChar"); fld3.set(qn("w:fldCharType"), "end")
        r3._r.append(fld3)
        r4 = p.add_run(" 页")
        for rr in (r1, r2, r3, r4):
            set_run_fonts(rr, size=8, color=FAINT)


# ---------- 内容构件 ----------
def body(doc, text, size=10.5, color=INK, space_after=6, indent=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    r = p.add_run(text)
    set_run_fonts(r, size=size, color=color)
    return p


def bullet(doc, text, level=0, marker="·"):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6 + 0.6 * level)
    p.paragraph_format.first_line_indent = Cm(-0.45)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(f"{marker} ")
    set_run_fonts(r, size=10.5, color=ACCENT, bold=True)
    r2 = p.add_run(text)
    set_run_fonts(r2, size=10.5, color=INK)
    return p


def numbered(doc, idx, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75)
    p.paragraph_format.first_line_indent = Cm(-0.75)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(f"{idx}. ")
    set_run_fonts(r, size=10.5, color=MUTED, bold=True)
    r2 = p.add_run(text)
    set_run_fonts(r2, size=10.5)
    return p


def code_block(doc, text, fill="F4F5F6"):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.3)
    pf.space_before = Pt(3)
    pf.space_after = Pt(8)
    pf.line_spacing = 1.25
    pf.keep_together = True
    shade_paragraph(p, fill)
    for i, line in enumerate(text.strip("\n").split("\n")):
        run = p.add_run(line)
        set_run_fonts(run, latin=MONO, cjk=CJK, size=8.8, color=INK)
        if i < len(text.strip("\n").split("\n")) - 1:
            run.add_break()
    return p


def callout(doc, label, text, fill="FDF0E7", label_color=ACCENT):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(8)
    shade_paragraph(p, fill)
    r = p.add_run(f"{label}  ")
    set_run_fonts(r, size=9.5, bold=True, color=label_color)
    r2 = p.add_run(text)
    set_run_fonts(r2, size=9.5, color=INK)
    return p


def make_table(doc, headers, rows, widths=None, font_size=9, header_fill="111418"):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        r = p.add_run(h)
        set_run_fonts(r, size=font_size, bold=True, color=WHITE)
        shade_cell(hdr[i], header_fill)

    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.line_spacing = 1.25
            # 支持 *强调* 标记
            txt = str(val)
            if txt.startswith("**") and txt.endswith("**"):
                r = p.add_run(txt[2:-2])
                set_run_fonts(r, size=font_size, bold=True, color=ACCENT)
            else:
                r = p.add_run(txt)
                set_run_fonts(r, size=font_size)

    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)

    # 禁止行内跨页断行
    for row in t.rows:
        trPr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        trPr.append(cant)
    return t


def caption(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_run_fonts(r, size=8.5, color=FAINT)
    return p


def section_head(doc, num, title):
    h = doc.add_heading(level=1)
    r = h.add_run(f"{num}  {title}")
    set_run_fonts(r, size=15, bold=True, color=ACCENT)
    para_border(h, "bottom", "E3E6E8", 6, 4)
    return h


def sub_head(doc, title):
    h = doc.add_heading(level=2)
    r = h.add_run(title)
    set_run_fonts(r, size=12, bold=True, color=INK)
    return h


# ============================================================
#  开始构建
# ============================================================
doc = Document()
setup_styles(doc)
setup_page(doc)
add_footer(doc, "Ollama Metrics Monitor · 产品手册 v1.0.0 · 第")

# ---------------- 封面 ----------------
sp = doc.add_paragraph()
sp.paragraph_format.space_before = Pt(70)
r = sp.add_run("产 品 手 册")
set_run_fonts(r, size=10, bold=True, color=ACCENT)

tp = doc.add_paragraph()
tp.paragraph_format.space_before = Pt(6)
tp.paragraph_format.space_after = Pt(2)
r = tp.add_run("Ollama Metrics Monitor")
set_run_fonts(r, size=30, bold=True, color=INK)

sub = doc.add_paragraph()
sub.paragraph_format.space_after = Pt(14)
r = sub.add_run("本地大模型调用监控与用量统计系统")
set_run_fonts(r, size=13, color=MUTED)

rule = doc.add_paragraph()
rule.paragraph_format.space_after = Pt(16)
para_border(rule, "bottom", "111418", 14, 1)

line = doc.add_paragraph()
r = line.add_run("给本地 Ollama 加一块仪表盘和一本账本。")
set_run_fonts(r, size=13.5, bold=True, color=ACCENT)

body(doc,
     "谁调了哪个模型、花了多少 token、慢在哪一步、GPU 当时忙不忙 —— 一眼看清；"
     "数据可导出，能开机自启，能分享给朋友看。",
     size=10.5, color=MUTED, space_after=26)

# 适用对象框
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
shade_paragraph(p, "F4F5F6")
r = p.add_run("适用对象  ")
set_run_fonts(r, size=9.5, bold=True, color=INK)
r = p.add_run("个人开发者 · 小团队 · 需要为算力／预算申请提供数据依据的人")
set_run_fonts(r, size=9.5, color=MUTED)

p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
shade_paragraph(p, "F4F5F6")
r = p.add_run("运行环境  ")
set_run_fonts(r, size=9.5, bold=True, color=INK)
r = p.add_run("macOS · Ollama · Python 3 · 无需 Node / Docker / 外部数据库")
set_run_fonts(r, size=9.5, color=MUTED)

vp = doc.add_paragraph()
vp.paragraph_format.space_before = Pt(120)
r = vp.add_run("版本 1.0.0        2026 年 11 月")
set_run_fonts(r, size=9, color=FAINT)

doc.add_page_break()

# ---------------- 目录 ----------------
h = doc.add_paragraph()
h.paragraph_format.space_before = Pt(4)
h.paragraph_format.space_after = Pt(10)
r = h.add_run("目  录")
set_run_fonts(r, size=18, bold=True, color=INK)

toc = [
    ("1", "产品简介"),
    ("2", "架构与工作原理"),
    ("3", "安装部署"),
    ("4", "配置说明"),
    ("5", "界面使用指南"),
    ("6", "指标字典"),
    ("7", "客户端接入"),
    ("8", "数据管理"),
    ("9", "公网分享"),
    ("10", "运维与排错"),
    ("11", "卸载"),
    ("12", "已知限制"),
    ("13", "附录"),
]
for num, title in toc:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.left_indent = Cm(0.2)
    r = p.add_run(f"{num}")
    set_run_fonts(r, size=10.5, bold=True, color=ACCENT)
    r = p.add_run(f"      {title}")
    set_run_fonts(r, size=10.5, color=INK)

body(doc, "提示：本手册按“先装起来 → 会用 → 会读数据 → 会排错”的顺序编写，"
          "首次使用建议只读第 3、5、7 三章即可上手。",
     size=9.5, color=FAINT, space_after=0)

doc.add_page_break()

# ============================================================
# 1 产品简介
# ============================================================
section_head(doc, "1", "产品简介")

sub_head(doc, "1.1 它是什么")
body(doc,
     "Ollama Metrics Monitor 是一个跑在本地的小型监控服务，位于你的客户端与 Ollama 之间。"
     "它做三件事：把请求原样转发给 Ollama；把每次调用的 token、耗时、客户端信息记进本地数据库；"
     "提供一个网页看板，把这些数据画出来。")

body(doc,
     "它不修改 Ollama，不替换模型，不依赖云端。停掉它，Ollama 照常工作，只是这段时间的调用不会被记账。")

sub_head(doc, "1.2 它解决什么问题")
body(doc, "本地跑大模型的人通常会遇到四个盲区：")
make_table(doc,
           ["盲区", "后果", "本产品的解法"],
           [
               ["不知道调了多少", "想申请算力或预算，拿不出数据", "累计请求数、token 数、费用估算，可导出 CSV"],
               ["不知道慢在哪", "只看到“这次很慢”，说不清是加载慢、首字慢还是生成慢", "把耗时拆成 TTFT / Token 生成 / 其他开销三段"],
               ["不知道谁在占资源", "多个客户端混用，说不清是哪个模型、哪个应用在消耗", "按模型分组统计；请求级明细带客户端 IP"],
               ["不知道 GPU 忙不忙", "只看得到显存占用，看不出负载高低", "GPU 利用率滚动基线（μ±2σ）＋ EMA 平滑曲线"],
           ],
           widths=[3.6, 5.6, 7.0])
caption(doc, "表 1-1  四个盲区与本产品的对应解法")

sub_head(doc, "1.3 设计原则")
body(doc, "整个产品的取舍集中在一句话：数字优先，装饰让位。")
bullet(doc, "全站只有一种强调色（铜橙），且只用于“需要注意的地方”：异常、失败、焦点、主趋势线。")
bullet(doc, "卡片用 1 像素边框区分层级，不用阴影堆叠；阴影只留给浮层（弹窗、提示）。")
bullet(doc, "所有数字使用等宽数字（tabular-nums），刷新时不左右跳动；单位与货币符号小一号、降一级色。")
bullet(doc, "中文标签不加宽字距、不转大写；字号只用 11/12/13/16/28/40 六档。")
bullet(doc, "自动刷新不弹提示；只在失败或复制成功时提示一次。顶栏常驻“更新于 hh:mm:ss”。")

sub_head(doc, "1.4 适用与不适用")
body(doc, "适合：")
bullet(doc, "本地跑 Ollama，想搞清楚“到底用了多少、慢在哪”。")
bullet(doc, "要向上级或自己证明“该不该加显卡”。")
bullet(doc, "多个客户端（DSH、WorkBuddy、脚本、朋友）共用一台机器，需要区分来源。")
body(doc, "不适合：")
bullet(doc, "多机集群、Kubernetes、需要 Prometheus 生态的团队（建议直接用 ollama-exporter + Grafana）。")
bullet(doc, "需要按 API Key 做计费或租户隔离的商业场景（本产品无鉴权、无多租户）。")
bullet(doc, "Windows / Linux 桌面用户当前需手动用 python3 启动（安装脚本仅支持 macOS）。")

doc.add_page_break()

# ============================================================
# 2 架构
# ============================================================
section_head(doc, "2", "架构与工作原理")

sub_head(doc, "2.1 三个组件")
make_table(doc,
           ["组件", "端口", "职责", "是否必须"],
           [
               ["Ollama", "11434", "真正的推理引擎", "必须（前置条件）"],
               ["Metrics Proxy", "11437", "转发请求、解析指标、写数据库、提供看板与 OpenAI 兼容层", "必须"],
               ["ngrok", "4040", "把 11437 映射到固定公网域名，供外部查看", "可选"],
           ],
           widths=[3.4, 2.0, 8.4, 2.4])
caption(doc, "表 2-1  三个组件")

sub_head(doc, "2.2 数据流")
code_block(doc, """
客户端 (DSH / WorkBuddy / 脚本 / 朋友)
        │
        │  ① OpenAI 兼容：POST /v1/chat/completions
        │  ② Ollama 原生：POST /api/chat
        ▼
┌───────────────────────────────────────────┐
│  Metrics Proxy          :11437            │
│  ─────────────────────────────────────    │
│  ③ 转发到 Ollama                          │
│  ④ 解析响应里的 prompt_eval_count /       │
│     eval_count / *_duration              │
│  ⑤ 计算 TTFT、Tokens/s、P95，写 SQLite    │
│  ⑥ 同一进程顺带提供 /dashboard.html       │
└───────────────────┬───────────────────────┘
                    │  ⑦ POST /api/chat
                    ▼
              ┌───────────────┐
              │ Ollama  :11434│
              └───────────────┘

  ⑧ 浏览器打开 /dashboard.html → 前端每 30 秒拉一次 /metrics
  ⑨ 外部访问 → ngrok 隧道 → 同一个 11437
""")

sub_head(doc, "2.3 三个关键设计决策")

body(doc, "决策一：代理不复用 11434，而是换到 11437。", space_after=2)
body(doc,
     "Ollama 默认只监听 11434，且改动端口需要设置环境变量并重启，成本高、易出错。"
     "让客户端的 Base URL 从 11434 改成 11437，只需改一处配置，风险更低。"
     "这也是本产品对所有客户端唯一的要求。", size=9.8, color=MUTED)

body(doc, "决策二：旁路设计，不做网关。", space_after=2)
body(doc,
     "代理只做“转发 + 记录”，不缓存、不改写响应、不做鉴权、不做限流。"
     "这样即使监控服务挂掉，你只需把 Base URL 改回 11434，业务立刻恢复。"
     "代价是它不能替代生产级 API 网关。", size=9.8, color=MUTED)

body(doc, "决策三：趋势图用 2 小时 / 5 分钟粒度，而不是 24 小时 / 1 小时。", space_after=2)
body(doc,
     "小时级会把突发流量抹平成平均值，看不出“14:25 突然来了 7 个请求”这种形状；"
     "秒级则几乎全是噪点。5 分钟是“看得出峰形”与“不至于全是噪声”的折中。"
     "更长的历史仍然保留在数据库里，可通过导出查看。", size=9.8, color=MUTED)

sub_head(doc, "2.4 数据存储")
body(doc, "单个 SQLite 文件，默认位于程序目录下的 ollama_metrics.db，可用 config.env 改到任意路径。")
make_table(doc,
           ["表名", "内容", "写入时机", "保留策略"],
           [
               ["request_logs", "逐条请求：模型、token、耗时、TTFT、客户端 IP、成功与否", "每次调用后", "永久（可手动清除）"],
               ["cumulative_stats", "单行累计值：总请求、总 token、总耗时、错误数", "每次调用后增量更新", "永久"],
               ["five_min_stats", "5 分钟窗口聚合：请求数、均值、峰值、P95", "每次调用后实时更新当前窗口", "24 小时"],
               ["hourly_stats", "小时级聚合", "每次调用后", "永久"],
               ["gpu_stats", "GPU 采样：利用率、显存、温度、Z 分数、EMA", "每 5 秒", "24 小时"],
           ],
           widths=[3.6, 7.0, 4.2, 2.6])
caption(doc, "表 2-2  数据库表结构")

callout(doc, "注意",
        "五张表都在同一个 SQLite 文件中，导出与备份只需复制这一个文件（建议同时复制 -wal 与 -shm 两个附带文件）。")

doc.add_page_break()

# ============================================================
# 3 安装
# ============================================================
section_head(doc, "3", "安装部署")

sub_head(doc, "3.1 前置条件")
make_table(doc,
           ["条件", "要求", "检查命令"],
           [
               ["操作系统", "macOS（安装脚本依赖 launchd）", "uname"],
               ["Ollama", "已安装并至少拉过一个模型", "ollama list"],
               ["Python", "3.8 及以上", "python3 --version"],
               ["Homebrew", "可选，用于安装 ngrok", "brew --version"],
           ],
           widths=[3.2, 8.0, 5.4])
caption(doc, "表 3-1  前置条件")

body(doc, "首次使用请先拉一个模型：")
code_block(doc, "ollama pull qwen2.5:7b")

sub_head(doc, "3.2 一键安装")
code_block(doc, "unzip ollama-metrics-monitor-v1.0.0.zip\ncd ollama-metrics-monitor\n./install.sh")

body(doc, "安装脚本会依次完成六步：")
numbered(doc, 1, "环境检查：确认 macOS、python3、ollama 均已就位。")
numbered(doc, 2, "Ollama 服务：若未运行则尝试启动，并统计已下载模型数量。")
numbered(doc, 3, "Python 依赖：默认创建 .venv 并装入 fastapi / uvicorn / requests，不动系统 Python（加 --no-venv 可跳过）。")
numbered(doc, 4, "端口检查：端口空闲、或被本程序旧进程占用（会自动重启）才继续；被其他程序占用则明确报错。")
numbered(doc, 5, "开机自启：生成两个 launchd 配置（代理、隧道）。")
numbered(doc, 6, "启动自检：轮询健康接口，成功后打印访问地址。")

sub_head(doc, "3.3 仅本机使用")
body(doc, "不需要公网访问时，加参数跳过隧道：")
code_block(doc, "./install.sh --no-tunnel")
body(doc, "这样只在本机或局域网可用，不经过任何第三方。")

sub_head(doc, "3.4 安装完成后的输出")
code_block(doc, """  本机看板   : http://localhost:11437/dashboard.html
  OpenAI 接口: http://localhost:11437/v1
  公网看板   : https://your-name.ngrok-free.app/dashboard.html""")

sub_head(doc, "3.5 验收：四条命令")
body(doc, "装完不确定是否真的可用，依次执行：")
code_block(doc, """# 1. 三个组件状态
./start-monitor.sh

# 2. 代理健康
curl -s http://localhost:11437/health

# 3. 模型清单
curl -s http://localhost:11437/v1/models

# 4. 发一次请求，确认入账
curl -s -X POST http://localhost:11437/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
curl -s http://localhost:11437/metrics""")
callout(doc, "通过标准",
        "第 2 条返回 status: ok；第 3 条列出你已下载的全部模型；第 4 条 total_requests 比之前多 1。")

sub_head(doc, "3.6 目录结构")
code_block(doc, """ollama-metrics-monitor/
├── install.sh                 一键安装（生成开机自启）
├── uninstall.sh               卸载（--purge 连数据一起删）
├── start-monitor.sh           日常运维：status / restart / logs
├── ollama-monitor-proxy.py    核心服务
├── dashboard.html             看板页面（单文件，无构建）
├── config.env                 你的配置（安装时生成）
├── config.env.example         配置模板
├── ollama_metrics.db          SQLite 数据（自动创建）
└── README.md                  手册正文""")

doc.add_page_break()

# ============================================================
# 4 配置
# ============================================================
section_head(doc, "4", "配置说明")

body(doc, "全部配置集中在 config.env，改完执行 ./start-monitor.sh restart 生效。")

make_table(doc,
           ["键", "默认值", "说明"],
           [
               ["PROXY_PORT", "11437", "代理监听端口。所有客户端都填这个端口"],
               ["OLLAMA_BASE_URL", "http://localhost:11434", "上游 Ollama 地址；Ollama 换端口时才需要改"],
               ["DB_PATH", "（留空）", "留空则使用程序目录下 ollama_metrics.db；可填绝对路径换盘"],
               ["ACCESS_CODE", "安装时随机生成", "访问口令：页面登录 + API Bearer Token；留空则关闭鉴权"],
               ["BIND_HOST", "127.0.0.1", "监听地址；改 0.0.0.0 才允许局域网直连（同样无鉴权）"],
               ["MAX_BODY_BYTES", "8388608", "单请求体上限，超出返回 413"],
               ["LOG_LEVEL", "INFO", "DEBUG 可看到更细的转发日志"],
               ["TUNNEL_ENABLED", "true", "是否启用公网隧道；改为 false 即只本机/局域网"],
               ["NGROK_DOMAIN", "（示例域名）", "ngrok 固定域名；留空则每次启动使用随机域名"],
           ],
           widths=[4.2, 4.6, 7.4])
caption(doc, "表 4-1  配置项")

sub_head(doc, "4.1 三个常见改法")

body(doc, "改端口（11437 被占用时）：", space_after=2)
code_block(doc, """# config.env
PROXY_PORT=11450
# 保存后
./start-monitor.sh restart""")

body(doc, "数据换到外置盘：", space_after=2)
code_block(doc, """# config.env
DB_PATH=/Volumes/Data/ollama/ollama_metrics.db""")

body(doc, "关闭公网访问：", space_after=2)
code_block(doc, """# config.env
TUNNEL_ENABLED=false""")

callout(doc, "为什么不把代理端口设成 11434",
        "Ollama 只认 11434。若让代理抢占该端口，Ollama 反而无法启动。"
        "所以约定：Ollama 保持 11434，代理另开一个端口，只改客户端。")

doc.add_page_break()

# ============================================================
# 5 界面
# ============================================================
section_head(doc, "5", "界面使用指南")

body(doc, "页面从上到下按“先学会用 → 再看结论 → 最后查个案”排列，共 7 块：")
make_table(doc,
           ["顺序", "区块", "回答什么问题"],
           [
               ["1", "怎么用这个看板", "客户端要连哪个地址、代码怎么写"],
               ["2", "叙事条", "系统现在到底正不正常"],
               ["3", "KPI 四格条", "大盘的量级：请求数、token、费用、延迟"],
               ["4", "请求趋势", "2 小时内有没有突发、GPU 跟不跟得上"],
               ["5", "模型排名", "哪个模型在被用、用得贵不贵"],
               ["6", "最近请求", "具体哪一次有问题（按异常分置顶）"],
               ["7", "GPU 资源监控", "硬件是跑满还是空转"],
           ],
           widths=[1.4, 5.0, 9.8])
caption(doc, "表 5-1  页面结构")

callout(doc, "接入指引默认展开",
        "第 1 块默认展开，因为首次打开最需要的是“怎么接”。会用了之后可以点标题收起，"
        "把首屏让给数据。")

body(doc, "展开后是一张“照着填”的对照表，四个字段各自的答案都直接给出：")
bullet(doc, "接口地址：填 Base URL 即可；如果客户端表单只接受完整路径，就填到 /v1/chat/completions。")
bullet(doc, "API Key：随便填（如 ollama），本地不做校验。")
bullet(doc, "模型名称：必须是 ollama list 里的全名，冒号不能漏。")
bullet(doc, "命令行：一行 curl，复制即用，适合先验证连通性。")


sub_head(doc, "5.1 叙事条（最顶部一行）")
body(doc, "自动生成的一句话结论，三种状态：")
make_table(doc,
           ["颜色", "含义", "触发条件", "该不该管"],
           [
               ["绿", "系统正常", "无异常窗口、延迟在阈值内", "不用管"],
               ["黄", "流量突增 / 延迟偏高", "某窗口请求数超均值 2 倍；或 P95 > 5 秒", "看一眼峰值来源"],
               ["红", "GPU 异常", "GPU 利用率 Z 分数 > 2 且绝对值 > 10%", "查是否有并发堆积"],
           ],
           widths=[1.8, 4.0, 6.6, 3.8])
caption(doc, "表 5-2  叙事条的三种状态")

callout(doc, "设计说明",
        "故意忽略“低负载异常”（Z < −2）。模型空转时利用率掉到 0.5% 是好事，不是告警。"
        "只报警“异常地高”，不报警“异常地闲”。")

sub_head(doc, "5.2 KPI 四格条")
body(doc, "总请求数、总 Tokens、估算费用、P95/P99 延迟四项并排。")
body(doc, "这四项用于“汇报进度”和“看量级”，不适合用来下判断 —— 判断请看下面的趋势图与请求表。", size=9.8, color=MUTED)

sub_head(doc, "5.3 请求趋势（近 2 小时，5 分钟粒度）")
make_table(doc,
           ["元素", "含义"],
           [
               ["黑色柱子", "每 5 分钟的请求数（左轴）"],
               ["橙色折线", "GPU 利用率 EMA，α=0.3（右轴，0–100%）"],
               ["红色圆点", "被判定为异常峰值的窗口（超过均值 2 个标准差）"],
               ["底部摘要", "峰值 X 次/5min · 平均响应 Yms"],
           ],
           widths=[3.6, 12.6])
caption(doc, "表 5-3  趋势图元素")

body(doc, "为什么用 EMA 而不是原始值：原始 GPU 曲线抖动剧烈，肉眼读不出趋势；"
          "EMA 保留走势、滤掉毛刺，更容易看出“是在持续攀升还是只是单点尖峰”。",
     size=9.8, color=MUTED)

sub_head(doc, "5.4 模型排名")
body(doc, "横向条形，每行依次是：模型名 · 请求量条 · 请求次数 · 平均生成速度（tok/s）。")
body(doc, "副指标用 tok/s 而不是平均耗时：不同模型的输出长度差别很大，平均耗时放在一起比没有意义；"
          "tok/s 与输出长度无关，才是可比的性能口径。鼠标悬停可以看到该模型的平均耗时。")
callout(doc, "unknown 不参与排名",
        "模型名为 unknown 表示“响应里没解析出模型名”（通常是失败或探测请求），它不是一个模型，"
        "所以既不出现在排名里，也不占用请求表的位置——表格标题旁会统一提示已隐藏多少条。")

sub_head(doc, "5.5 最近请求（按异常分数排序）")
body(doc, "六列，回答四个问题：什么时候、哪个模型跑了多少、跑得多快、为什么被标出来。")
make_table(doc,
           ["列", "回答什么", "读法"],
           [
               ["时间", "多久以前", "相对时间；悬停看精确时刻"],
               ["模型", "谁跑的", "mono 标签，超长省略"],
               ["输出", "生成了多少 token", "与耗时一起看才知道是「多」还是「慢」"],
               ["耗时", "总共等了多久", "<1 秒显示毫秒，否则显示秒"],
               ["tok/s", "生成速度", "**这一列才能横向比较不同长度的请求**"],
               ["判定", "为什么被标出来", "正常 / 生成慢 / 排队 / 首字慢 / 失败"],
           ],
           widths=[2.4, 5.0, 9.2])
caption(doc, "表 5-4  最近请求的六列")

body(doc, "判定规则（按顺序命中第一条）：")
make_table(doc,
           ["判定", "触发条件", "意味着"],
           [
               ["失败", "请求失败", "看错误信息"],
               ["生成慢", "每 token 耗时高于**同模型**常态 P95（该模型样本 ≥3 才判）", "模型变慢了，不是输出长"],
               ["排队", "其他开销占比 > 40% 且 > 1 秒", "在等模型加载或并发排队"],
               ["首字慢", "首字延迟 > 2 秒", "冷启动或 prompt 太长"],
               ["正常", "以上都不满足", "—"],
           ],
           widths=[2.6, 8.0, 6.0])
caption(doc, "表 5-5  判定规则")

callout(doc, "为什么用「同模型」做基线",
        "7B 和 14B 的生成速度本来就差一倍。拿全局 P99 去比，小模型会把阈值拉低，"
        "大模型每次都被误判成「慢」。所以只在同一模型有 3 条以上样本时才判生成速度，"
        "样本不足不给结论。")

body(doc, "排序仍按内部异常分（失败 5 分、生成慢 3 分、排队 2 分、首字慢 1 分），"
          "所以有问题的行永远在最上面。模型名为 unknown 且 token 为 0 的无效探测会被折叠，"
          "标题旁提示「已隐藏 N 条」，不占位置。", size=9.8, color=MUTED)

callout(doc, "为什么不用绝对响应时间打分",
        "同样 15 秒，输出 30 个 token 说明每 token 要 500ms（真慢），输出 600 个 token 只说明"
        "生成得多（正常）。绝对耗时会随输出长度线性放大，用它打分必然误伤长输出。"
        "所以打分只看每 token 耗时（与长度无关）与“其他开销”占比；绝对耗时只用于展示。")

body(doc, "分数 ≥ 3 的行会带淡橙底色。")
body(doc, "纯超时噪声（模型名为 unknown、耗时约 300 秒、token 为 0）会被自动折叠，"
          "只在标题旁提示“已隐藏 N 条”，不占用注意力。", size=9.8, color=MUTED)

sub_head(doc, "5.6 最慢的 5 次请求 · 耗时拆解")
body(doc, "把最慢的五次请求的总耗时拆成五段，用来回答“到底慢在哪”：")
make_table(doc,
           ["分段", "来源", "意味着"],
           [
               ["输出生成", "eval_duration", "模型真的在算——这段长是模型/硬件本身的极限"],
               ["模型加载", "load_duration", "冷启动把模型读进显存，第一次或切换模型后常见"],
               ["排队/网络", "代理耗时 − 上游耗时", "在等前面的请求、等隧道、或客户端网络慢"],
               ["输入处理", "prompt_eval_duration", "prompt 太长；这段长就该考虑缩短上下文"],
               ["其他", "上游总计 − 上述三段", "通常很小"],
           ],
           widths=[3.0, 5.0, 9.0])
caption(doc, "表 5-6  耗时拆解的五个分段")

callout(doc, "怎么用它判断“是不是 GPU 不行”",
        "输出生成占比高 → 是模型或硬件慢，换更强的卡/更小的模型；"
        "加载或排队占比高 → 与算力无关，优化预热或减少并发就够了。"
        "这两者的处置方式完全相反，所以必须先拆开看。")

body(doc, "资源卡片下方还有一行汇总：平均利用率、峰值、活跃占比（利用率 >10% 的采样占多少）、峰值内存。"
          "活跃占比的分母是窗口内的采样数，阈值 10% 写死在页面上，避免口径含糊。",
     size=9.8, color=MUTED)

sub_head(doc, "5.7 GPU 资源监控")
make_table(doc,
           ["线条", "含义", "怎么读"],
           [
               ["原始值（细线）", "每 5 秒的真实采样", "看毛刺与瞬时尖峰"],
               ["EMA 平滑（橙线）", "指数移动平均", "看趋势方向"],
               ["μ+2σ / μ−2σ（黄虚线）", "滚动均值 ± 2 倍标准差", "正常波动带"],
           ],
           widths=[4.6, 5.6, 6.0])
caption(doc, "表 5-6  GPU 图的三层信息")

body(doc, "横轴是采样时间（HH:MM，每 5 秒一个点，最多保留 30 分钟）；"
          "标题右侧实时显示“当前值 / 基线 / Z 分数 / 已采集时长”，"
          "鼠标悬停可看到精确到秒的采样时刻。")

callout(doc, "判读口诀",
        "落在虚线带内 = 正常；连续跑出上界 = 资源真的紧，考虑扩显存或降并发；"
        "一直贴着下界 = 模型基本空转，不需要加卡。")

sub_head(doc, "5.8 单次请求详情")
body(doc, "点击请求表中任意一行，弹出该次请求的完整画像：")
bullet(doc, "耗时分解条形图：TTFT / Token 生成 / 其他开销 三段占比，直接看出瓶颈在哪一段。")
bullet(doc, "上下文对比：本次 vs 近 2 小时平均，自动生成“慢 4.8 倍 ⚠️”这类判断。")
bullet(doc, "资源快照：该请求发生时刻的 GPU 利用率、显存占用、Z 分数。")
bullet(doc, "请求元信息：客户端 IP、端点、每 token 耗时、生成速度。")
body(doc, "按 Esc 或点击遮罩关闭。")

sub_head(doc, "5.9 顶栏与主题")
make_table(doc,
           ["控件", "作用"],
           [
               ["更新于 hh:mm:ss", "显示最后一次成功拉取数据的时间；超过 90 秒未更新会转黄并标注“数据过期”"],
               ["刷新", "手动拉取一次；刷新过程中按钮禁用，避免重复点击"],
               ["导出", "下载 CSV 明细（详见第 8 章）"],
               ["清除", "清空全部统计数据，开始新一轮统计"],
               ["主题", "浅色 / 深色切换，偏好保存在浏览器本地"],
           ],
           widths=[4.6, 11.6])
caption(doc, "表 5-7  顶栏控件")

body(doc, "页面不可见时自动暂停轮询，切回前台立即拉取一次 —— 避免后台标签页堆积请求。")

sub_head(doc, "5.10 手机上怎么看")
body(doc, "窄屏（≤640 像素）下布局会自动收缩，不需要横向滚动：")
bullet(doc, "顶栏只留标题与按钮，更新时间隐藏；标题过长时省略。")
bullet(doc, "KPI 从四格变两行两列，字号同步收小。")
bullet(doc, "请求表只保留「模型 / 耗时 / 状态」三列，其余列隐藏而不是挤压。")
bullet(doc, "长 URL 只在斜杠处换行，模型名不会从中间被拆开。")
bullet(doc, "图表高度降到 210 像素，刻度自动减少。")

doc.add_page_break()

# ============================================================
# 6 指标字典
# ============================================================
section_head(doc, "6", "指标字典")

body(doc, "给需要看数字的人。每个指标都写清“怎么算”“什么算好”“拿它做什么判断”。")

make_table(doc,
           ["指标", "计算方式", "参考区间", "用途"],
           [
               ["TTFT\n首字延迟", "load_duration + prompt_eval_duration", "< 500ms 好\n> 2s 偏慢", "用户感知“卡不卡”的第一指标；冷启动时含模型加载"],
               ["TPOT\n每 token 耗时", "eval_duration ÷ eval_count", "随模型与硬件变化", "比平均吞吐更能反映生成速度"],
               ["Tokens/s", "eval_count ÷ (eval_duration ÷ 1e9)", "7B 约 30–60\n14B 约 15–35", "吞吐能力"],
               ["P50 / P95 / P99", "对已记录响应时间求分位数", "P99 与 P50 差距越大越不稳", "看整体容量；受输出长度影响"],
               ["GPU 利用率", "macOS: 进程 CPU% 之和\nLinux: nvidia-smi", "> 30% 有余量\n持续 > 80% 需扩容", "判断是否真的跑满"],
               ["VRAM 占用", "macOS: 进程 RSS 之和", "接近物理上限要警惕", "决定能否再加载一个模型"],
               ["每 token P95/P99", "对 time_per_token_ms 求分位数", "与输出长度无关", "判断“是否真的变慢”的正确口径"],
               ["Z 分数", "(当前值 − 滚动均值) ÷ 滚动标准差", "|Z| > 2 视为异常", "脱离分布的绝对值没有意义"],
               ["EMA", "α·当前 + (1−α)·上次，α=0.3", "—", "平滑曲线，滤掉毛刺"],
               ["估算费用", "按每 1K token 单价累加", "—", "参考价，可自行修改单价"],
               ["异常分", "见表 5-4 的加分规则", "≥ 3 需关注", "决定请求表排序"],
           ],
           widths=[3.4, 5.8, 3.6, 3.4], font_size=8.5)
caption(doc, "表 6-1  指标字典")

sub_head(doc, "6.1 为什么强调 P95 / P99")
body(doc,
     "举例：10 次请求里 9 次用 1 秒、1 次用 30 秒。平均值是 3.9 秒 —— 既不像 1 秒那样让人满意，"
     "也不像 30 秒那样暴露出问题，是最没用的一档数字。")
body(doc,
     "P95 告诉你“绝大多数情况下最坏会多慢”，P99 告诉你“几乎最坏会多慢”。"
     "向人解释“需要多强的硬件”时，这两个数比平均值有说服力得多。")

sub_head(doc, "6.2 GPU 指标从哪来")
make_table(doc,
           ["平台", "数据来源", "能拿到", "拿不到"],
           [
               ["macOS\n(Apple Silicon)", "IOAccelerator 的 PerformanceStatistics\n（ioreg，无需 root）",
                "Device Utilization %（真实 GPU 利用率）\nGPU 占用内存、物理内存总量",
                "温度、功率、按进程分摊"],
               ["macOS\n(读不到计数器时)", "llama-server 的 CPU 时间差",
                "CPU 核利用率（近似）", "GPU 相关一切"],
               ["Linux + NVIDIA", "nvidia-smi", "利用率、显存、温度、功率", "按进程分摊"],
           ],
           widths=[3.4, 5.4, 5.4, 3.4], font_size=8.5)
caption(doc, "表 6-2  GPU 指标的数据来源")

callout(doc, "实测对照",
        "同一台 M5 Pro 上：空闲时 Device Utilization 约 32%，推理时升到 98–99%。"
        "所以这个数字是真实的 GPU 占用，不是 CPU 代理值。")
callout(doc, "口径切换会自动重建基线",
        "当数据来源在「硬件计数器」和「CPU 近似」之间切换时，旧样本的量纲完全不同，"
        "混在一起会算出虚假的 Z 分数。程序检测到切换会清空 GPU 历史并写一行告警日志，基线从零重建。")

body(doc, "仍然拿不到的两项：")
bullet(doc, "功率与累计耗电：需要 powermetrics，必须 root，不适合常驻服务。")
bullet(doc, "按模型分摊 GPU 时间：硬件只有整卡计数器，没有按进程/模型的计量。"
            "任何「某模型占 GPU 的百分之多少」都只能是估算，页面不提供这类数字。")
body(doc,
     "在 Linux + NVIDIA 环境下会自动改用 nvidia-smi，拿到真实的 utilization、memory、temperature、power。"
     "两个平台的口径不同，跨平台对比趋势可以，横向比较绝对值不严谨。", size=9.8, color=MUTED)

sub_head(doc, "6.3 费用估算怎么改")
body(doc, "打开 ollama-monitor-proxy.py，找到 MODEL_PRICING，按“每 1K tokens”的单位改单价：")
code_block(doc, """MODEL_PRICING = {
    "qwen3":   {"prompt": 0.002, "completion": 0.006},
    "qwen2.5": {"prompt": 0.002, "completion": 0.006},
    "llama3":  {"prompt": 0.003, "completion": 0.009},
    "default": {"prompt": 0.002, "completion": 0.006},
}""")
body(doc, "这只是估算，不等于真实账单。若用云厂商 API，建议直接拿官方价目表替换。", size=9.8, color=MUTED)

doc.add_page_break()

# ============================================================
# 7 客户端接入
# ============================================================
section_head(doc, "7", "客户端接入")

callout(doc, "唯一需要记住的规则",
        "把原来的 http://localhost:11434 换成 http://127.0.0.1:11437。其余参数、模型名、请求格式全部不变。")

body(doc, "代理同时提供两套协议，客户端用哪套都可以：")
make_table(doc,
           ["协议", "端点", "适用"],
           [
               ["OpenAI 兼容", "POST /v1/chat/completions\nGET /v1/models", "绝大多数客户端与 SDK 使用这套"],
               ["Ollama 原生", "POST /api/chat\nPOST /api/generate\nGET /api/tags\nGET /api/ps", "原生 Ollama SDK、curl 调试"],
           ],
           widths=[3.6, 6.6, 6.0])
caption(doc, "表 7-1  两套协议")

sub_head(doc, "7.1 DSH（DeepSeek Harness）")
body(doc, "编辑 ~/.dsh/profiles/desktop/cordis.patch.yml，找到 ollama 这个 provider：")
code_block(doc, """      ollama:
        displayName: 本地 Ollama
        api: openai-completions
        baseURL: http://127.0.0.1:11437/v1      # ← 关键：指向代理
        headers:
          Authorization: Bearer ollama
        compat:
          supportsStore: false
          supportsDeveloperRole: false
          supportsReasoningEffort: false
          supportsStrictMode: false
        models:
          - id: qwen2.5:7b                      # ← 必须与 ollama list 完全一致
            name: Qwen2.5 7B (本地)
            contextWindow: 32768
            maxTokens: 8192
            input: [text]
            reasoningEfforts: false
          - id: qwen3:14b
            name: Qwen3 14B (本地)
            contextWindow: 40960
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}
          - id: qwen3:14b-abliterated
            name: Qwen3 14B Abliterated (本地)
            contextWindow: 40960
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}
          - id: deepseek-r1:14b
            name: DeepSeek R1 14B (本地)
            contextWindow: 131072
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}""")

body(doc, "本地模型上下文窗口小，还必须补 compaction-basic 的余量，"
          "否则切换模型时会报 MODEL_SWITCH_COMPACTION_FAILED：")
code_block(doc, """- id: compaction-basic
  name: "@deepseek-ai/dsh-compaction-basic"
  config:
    modelPolicies:
      - {provider: ollama, model: "qwen2.5:7b",            headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "qwen3:14b",             headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "qwen3:14b-abliterated", headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "deepseek-r1:14b",       headroomTokens: 4096, maxTokens: 4096}""")

callout(doc, "改完必须重启 DSH",
        "配置在启动时加载。重启后在输入框右下角的模型选择器里即可看到四个本地模型，选哪个都会被记账。")

callout(doc, "本机客户端不需要 Token",
        "上面这份配置用的是 127.0.0.1，属于本机直连，代理会直接放行，API Key 留空即可。"
        "只有从别的设备或公网访问时才需要 ACCESS_CODE，并把它填进 API Key 字段。")

sub_head(doc, "7.2 Python")
code_block(doc, """import requests

r = requests.post(
    "http://127.0.0.1:11437/v1/chat/completions",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer <ACCESS_CODE>",     # 本机调用可省略
        "ngrok-skip-browser-warning": "true",        # 经 ngrok 时必须
    },
    json={
        "model": "qwen2.5:7b",
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0.7,
        "max_tokens": 512,
    },
    timeout=600,
)
data = r.json()
print(data["choices"][0]["message"]["content"])
print(data["usage"])   # prompt_tokens / completion_tokens / total_tokens""")

sub_head(doc, "7.3 JavaScript")
code_block(doc, """const r = await fetch("http://127.0.0.1:11437/v1/chat/completions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "qwen2.5:7b",
    messages: [{ role: "user", content: "你好" }],
  }),
});
console.log(await r.json());""")

sub_head(doc, "7.4 cURL")
code_block(doc, """curl -X POST http://127.0.0.1:11437/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"你好"}]}'""")

sub_head(doc, "7.5 其他图形客户端（WorkBuddy / Cherry Studio / Open WebUI 等）")
make_table(doc,
           ["字段", "填什么"],
           [
               ["Base URL / API 地址", "http://127.0.0.1:11437/v1"],
               ["API Key", "本机调用随便填；从别的设备访问填 ACCESS_CODE"],
               ["模型名", "ollama list 里的名字，四个任选"],
           ],
           widths=[5.6, 10.6])
caption(doc, "表 7-2  图形客户端配置")

sub_head(doc, "7.6 查询可用模型")
code_block(doc, "curl -s http://127.0.0.1:11437/v1/models | python3 -m json.tool")

sub_head(doc, "7.7 关于超时设置")
body(doc,
     "代理自身的上游超时为 300 秒。但大模型并发排队时，单个请求可能超过 5 分钟，"
     "所以建议客户端 timeout 设为 600 秒（Python requests 的 timeout、curl 的 --max-time 同理）。")
body(doc, "若频繁出现 300 秒整的超时记录，说明并发已超过本机承载，应减少并发或增加显存。",
     size=9.8, color=MUTED)

doc.add_page_break()

# ============================================================
# 8 数据管理
# ============================================================
section_head(doc, "8", "数据管理")

sub_head(doc, "8.1 导出")
body(doc, "看板右上角「导出」按钮，或直接请求接口：")
code_block(doc, """# 逐条明细（Excel / Numbers 直接打开，带 BOM，中文不乱码）
curl -O http://127.0.0.1:11437/export?format=csv

# 完整快照（累计 + 分模型 + 趋势 + GPU 时序 + 明细）
curl -O http://127.0.0.1:11437/export?format=json""")

body(doc, "CSV 十四列：")
code_block(doc, """id, timestamp, model, endpoint,
prompt_tokens, completion_tokens, total_tokens,
response_time_ms, ttft_ms, time_per_token_ms, tokens_per_second,
success, error_message, client_ip""")

body(doc, "JSON 顶层字段：exported_at、cumulative、by_model、hourly_stats、"
          "five_min_stats、request_logs、latency_percentiles。")

sub_head(doc, "8.2 清零（开始新一轮统计）")
body(doc, "看板右上角「清除」按钮 → 二次确认。会清空请求记录、趋势窗口、GPU 采样，累计值归零。")
callout(doc, "不可恢复",
        "清除是物理删除，没有回收站。需要留档请先导出 CSV 或 JSON。")
body(doc, "典型用法：")
numbered(doc, 1, "导出上一轮数据（CSV）存档。")
numbered(doc, 2, "点「清除」。")
numbered(doc, 3, "跑下一组实验，得到互不污染的数据。")
numbered(doc, 4, "对比两轮 CSV，看出模型/配置差异。")

sub_head(doc, "8.3 直接查库")
body(doc, "SQLite 文件可直接用命令行查，适合做自定义分析：")
code_block(doc, """# 各模型用量
sqlite3 ollama_metrics.db \\
  "SELECT model, COUNT(*) AS n, SUM(total_tokens) AS tok, \\
          AVG(response_time_ms) AS avg_ms \\
   FROM request_logs GROUP BY model ORDER BY tok DESC;"

# 最慢的 10 次请求
sqlite3 ollama_metrics.db \\
  "SELECT model, response_time_ms, total_tokens, timestamp \\
   FROM request_logs ORDER BY response_time_ms DESC LIMIT 10;"

# 按小时看请求量
sqlite3 ollama_metrics.db \\
  "SELECT substr(timestamp,1,13) AS hour, COUNT(*) \\
   FROM request_logs GROUP BY hour ORDER BY hour DESC LIMIT 24;\"""")

sub_head(doc, "8.4 备份建议")
body(doc,
     "最简单可靠的方式：停服务 → 复制 ollama_metrics.db（连同 .db-wal、.db-shm）→ 启服务。"
     "或者在运行中直接用导出的 JSON 作为快照，它包含全部聚合结果。")
body(doc, "若不希望数据库无限增长，可定期导出旧数据后清除；"
          "五张表中只有 request_logs 会持续增长，其余都有 24 小时保留策略。",
     size=9.8, color=MUTED)

doc.add_page_break()

# ============================================================
# 9 公网分享
# ============================================================
section_head(doc, "9", "公网分享")

body(doc, "三种方式，按“是否需要朋友远程访问、是否愿意经过第三方”选择。")

sub_head(doc, "9.1 局域网（最快、最安全）")
body(doc, "适用于朋友与你在同一个 WiFi 下。")
code_block(doc, """ipconfig getifaddr en0          # 会输出你的局域网 IP""")
body(doc, "把 http://<你的局域网IP>:11437/dashboard.html 发给对方即可。")
body(doc, "零配置、零延迟、不经过任何第三方，也不消耗 ngrok 额度。", size=9.8, color=MUTED)

sub_head(doc, "9.2 ngrok（默认，适合远程临时分享）")
numbered(doc, 1, "注册 ngrok 账号，复制 authtoken。")
numbered(doc, 2, "终端执行 ngrok config add-authtoken <你的 token>。")
numbered(doc, 3, "在 ngrok 后台 Domains 页面申请一个免费固定域名（免费账号 1 个）。")
numbered(doc, 4, "把域名填进 config.env 的 NGROK_DOMAIN。")
numbered(doc, 5, "执行 ./install.sh 或 ./start-monitor.sh restart。")
body(doc, "分享地址形如 https://your-name.ngrok-free.app/dashboard.html。")
make_table(doc,
           ["现象", "原因", "处理"],
           [
               ["浏览器先显示提示页", "ngrok 免费版对浏览器有拦截", "点 Visit Site 即可"],
               ["代码调用返回提示页", "同上", "请求头加 ngrok-skip-browser-warning: true"],
               ["域名打不开", "免费隧道掉线或被回收", "./start-monitor.sh restart；到 ngrok 后台看 Tunnels"],
           ],
           widths=[4.4, 6.0, 5.8])
caption(doc, "表 9-1  ngrok 常见现象")

sub_head(doc, "9.3 Cloudflare Tunnel（长期稳定，需要自有域名）")
code_block(doc, """brew install cloudflared
cloudflared tunnel --url http://localhost:11437""")
body(doc, "会打印一个 https://xxx.trycloudflare.com 地址。")
callout(doc, "注意",
        "快速隧道每次重启都会换 URL。想要固定 URL，需要把自有域名接入 Cloudflare 后创建命名隧道。")

sub_head(doc, "9.5 访问口令")
body(doc, "安装时会自动生成一串口令写进 config.env 的 ACCESS_CODE。它同时是两件事的凭据：")
bullet(doc, "看板登录口令：未登录访问会被重定向到登录页，输入后得到 30 天有效的 cookie。")
bullet(doc, "API Token：请求头 `Authorization: Bearer <口令>`，缺失或错误返回 401。")
body(doc, "登录后会直接落在「接入指引」页签，那里有口令本身和一个复制按钮，转给朋友即可，不需要另外分发。")
body(doc, "登录表单用 fetch 提交并附带 ngrok-skip-browser-warning 头。这是必要的：ngrok 免费版会给浏览器表单 POST 插入警告页，"
          "导致“点进入没反应”。用 fetch 可以绕过这层拦截。")
body(doc, "本机直连（127.0.0.1，不经隧道）免口令，DSH 与本地脚本不受影响。")
callout(doc, "撤销与更换",
        "改 config.env 里的 ACCESS_CODE 后执行 ./start-monitor.sh restart。旧的 cookie 立即失效，"
        "所有已登录的浏览器需要重新输入；客户端里的 Bearer 也要同步改。")

sub_head(doc, "9.4 安全须知")
body(doc, "公网暴露的是“只读看板 + 可调用的 OpenAI 接口”。"
          "任何人拿到域名都能调用你的模型、消耗你的算力与电费。")
bullet(doc, "只是给几个朋友看：可以接受，但不要把域名贴到公开渠道。")
bullet(doc, "要长期公开：给隧道加 OAuth 或 IP 白名单（ngrok 付费功能），或只开放局域网。")
bullet(doc, "不分享时：把 TUNNEL_ENABLED 改为 false 并重启，公网立即失效。")
bullet(doc, "导出与清除仅限本机：公网打开时按钮不显示，直接调 /export、/reset 返回 403。")
bullet(doc, "不挂载项目目录：早期版本用 StaticFiles 挂整个目录，/static/ollama_metrics.db 可被公网下载，现已移除。")
bullet(doc, "本产品自身没有鉴权、没有速率限制，不要当成生产 API 网关使用。")

doc.add_page_break()

# ============================================================
# 10 运维与排错
# ============================================================
section_head(doc, "10", "运维与排错")

sub_head(doc, "10.1 日常命令")
code_block(doc, """./start-monitor.sh            # 查看三个组件状态
./start-monitor.sh restart    # 重启代理与隧道
./start-monitor.sh logs       # 跟踪日志（Ctrl+C 退出）""")

sub_head(doc, "10.2 日志位置")
make_table(doc,
           ["文件", "内容"],
           [
               ["~/Library/Logs/ollama-monitor/proxy.log", "HTTP 转发记录、状态码"],
               ["~/Library/Logs/ollama-monitor/proxy.err.log", "Python 异常栈、启动信息"],
               ["~/Library/Logs/ollama-monitor/ngrok.log", "隧道生命周期"],
               ["~/Library/Logs/ollama-monitor/ngrok.err.log", "隧道错误"],
           ],
           widths=[6.0, 10.2])
caption(doc, "表 10-1  日志文件")

sub_head(doc, "10.3 服务自愈机制")
body(doc, "代理与隧道各由 launchd 独立监管，采用“直接前台运行 + 非正常退出时重启”的策略：")
bullet(doc, "进程被 kill 或崩溃 → 约 10 秒内自动拉起（实测 kill -9 后 8 秒恢复）。")
bullet(doc, "重启间隔受 ThrottleInterval 限制，避免“崩溃—重启”死循环打满 CPU。")
bullet(doc, "开机自动启动，无需登录后手动运行脚本。")
body(doc,
     "常见的错误做法是“用脚本启动 + launchd 监护脚本”，脚本每次启动都先 pkill 旧进程，"
     "结果与监护机制互相残杀，表现为服务反复掉线。本产品已避开该模式。",
     size=9.8, color=MUTED)

sub_head(doc, "10.4 故障对照表")
make_table(doc,
           ["现象", "最可能的原因", "处理"],
           [
               ["看板显示 HTTP 404", "代理没起来，或隧道指向错误端口", "./start-monitor.sh restart；curl localhost:11437/health 验证"],
               ["有页面但数字不涨", "客户端仍在连 11434，绕过代理", "把客户端 Base URL 改为 127.0.0.1:11437"],
               ["DSH 报 Connection error", "代理挂了或端口写错", "./start-monitor.sh 看是否三行全绿"],
               ["DSH 报 400 括号未闭合", "旧版本代理读取请求体被截断", "升级到当前版本并重启代理"],
               ["请求大量记为 unknown", "上游报错且旧版本拿不到模型名", "升级；新版会用请求体里的模型名回填"],
               ["一堆 300 秒超时", "并发超出本机承载，排队超时", "已自动折叠；减少并发或加显存"],
               ["GPU 图是一条直线", "macOS 读取方式限制", "属正常，见 6.2 说明"],
               ["切模型时 compaction 报错", "本地窗口小，压缩余量算成负数", "补 compaction-basic 的 modelPolicies"],
               ["端口被占用无法启动", "另一个程序占了 PROXY_PORT", "改 config.env 的 PROXY_PORT 后重启"],
           ],
           widths=[4.4, 5.6, 6.2], font_size=8.5)
caption(doc, "表 10-2  故障对照表")

sub_head(doc, "10.5 单独排查某个环节")
code_block(doc, """# 上游 Ollama 是否健康
curl -s http://localhost:11434/api/tags

# 代理是否健康（含上游连通性）
curl -s http://localhost:11437/health

# 代理的 OpenAI 兼容层是否正常
curl -s http://localhost:11437/v1/models

# 隧道是否在线、指向哪个端口
curl -s http://localhost:4040/api/tunnels

# launchd 是否在监管
launchctl list | grep ollama""")

doc.add_page_break()

# ============================================================
# 11 卸载
# ============================================================
section_head(doc, "11", "卸载")

code_block(doc, """./uninstall.sh            # 停止服务、移除开机自启，保留数据库
./uninstall.sh --purge    # 连数据库与日志一起删除""")

body(doc, "卸载不会影响 Ollama 本身，也不删除你已下载的模型。")
body(doc, "卸载后如仍需使用，把客户端的 Base URL 改回 http://127.0.0.1:11434 即可。")

# ============================================================
# 12 已知限制
# ============================================================
section_head(doc, "12", "已知限制")

body(doc, "写在这里是为了避免误解，不是待办清单。")
numbered(doc, 1, "macOS 拿不到真实 GPU 硬件指标（利用率 / 温度 / 功耗），当前用进程 CPU% 与 RSS 近似。"
                 "Linux + NVIDIA 会走 nvidia-smi 拿准确值。")
numbered(doc, 2, "流式请求的耗时统计是“整段完成时间”，不是逐 token 时间线。"
                 "TTFT 可从 prompt_eval_duration 精确计算，但没有“首 token 到末 token”的实时曲线。")
numbered(doc, 3, "并发超过 GPU 承载时会排队，表现为单请求耗时暴涨、部分请求超时。"
                 "这是 Ollama 自身行为，本产品只如实记录并把纯超时噪声折叠。")
numbered(doc, 4, "费用是估算值，单价写死在代码常量里，不是真实账单。")
numbered(doc, 5, "公网只读但没有鉴权与限流，分享范围需自行控制。")
numbered(doc, 6, "安装脚本仅支持 macOS。其他系统可手动执行 python3 ollama-monitor-proxy.py 启动，"
                 "但开机自启需自行配置（systemd / 任务计划）。")
numbered(doc, 7, "同一时刻只支持一个 Ollama 实例作为上游；多机场景不在设计范围内。")

# ============================================================
# 13 附录
# ============================================================
section_head(doc, "13", "附录")

sub_head(doc, "附录 A  文件清单")
make_table(doc,
           ["文件", "作用"],
           [
               ["install.sh", "一键安装：查环境、装依赖、生成开机自启、自检"],
               ["uninstall.sh", "卸载；--purge 同时删数据"],
               ["start-monitor.sh", "运维：status / restart / logs"],
               ["ollama-monitor-proxy.py", "核心服务：转发、记账、看板、OpenAI 兼容层、导出"],
               ["dashboard.html", "看板页面，无构建"],
               ["chart.umd.min.js", "Chart.js 本地副本（由 /chart.js 提供，不依赖 CDN）"],
               ["config.env", "当前配置（安装时从模板生成）"],
               ["config.env.example", "配置模板"],
               ["ollama_metrics.db", "SQLite 数据（自动创建）"],
               ["README.md", "手册正文（Markdown 版）"],
           ],
           widths=[5.2, 11.0])
caption(doc, "表 A-1  文件清单")

sub_head(doc, "附录 B  接口清单")
make_table(doc,
           ["方法", "路径", "说明"],
           [
               ["GET", "/dashboard.html", "看板页面"],
               ["GET", "/metrics", "看板数据（累计、明细、趋势、GPU、分位数）"],
               ["GET", "/export?format=csv", "导出逐条明细"],
               ["GET", "/export?format=json", "导出完整快照"],
               ["POST", "/reset", "清空全部统计数据"],
               ["GET", "/health", "健康检查（含上游连通性）"],
               ["GET", "/v1/models", "OpenAI 格式模型列表"],
               ["POST", "/v1/chat/completions", "OpenAI 格式对话，支持流式（SSE，转发至 /api/chat）"],
               ["POST", "/v1/completions", "OpenAI 格式文本补全，支持流式（SSE，转发至 /api/generate）"],
               ["*", "/api/*", "Ollama 原生接口透明代理"],
           ],
           widths=[2.0, 5.6, 8.6])
caption(doc, "表 B-1  HTTP 接口")

sub_head(doc, "附录 C  术语表")
make_table(doc,
           ["术语", "含义"],
           [
               ["TTFT", "Time To First Token，首字延迟；用户发出请求到看到第一个字的等待时间"],
               ["TPOT", "Time Per Output Token，平均每个输出 token 的生成耗时"],
               ["P95 / P99", "分位数：95% / 99% 的请求都快于该值"],
               ["EMA", "指数移动平均，一种给近期数据更高权重的平滑算法"],
               ["Z 分数", "当前值偏离均值多少个标准差，用于判断“这次是否真的异常”"],
               ["Proxy", "代理；本产品中指位于客户端与 Ollama 之间的转发与记录服务"],
               ["launchd", "macOS 的系统级服务管理机制，负责开机自启与崩溃拉起"],
               ["旁路", "不改变主链路行为的附加组件；本产品的代理可随时停用而不影响推理"],
           ],
           widths=[3.4, 12.8])
caption(doc, "表 C-1  术语表")

# 结尾
end = doc.add_paragraph()
end.paragraph_format.space_before = Pt(24)
para_border(end, "top", "E3E6E8", 6, 6)
r = end.add_run("Ollama Metrics Monitor  v1.0.0        产品手册        2026 年 11 月")
set_run_fonts(r, size=8.5, color=FAINT)

OUT = "Ollama-Metrics-Monitor-产品手册.docx"
doc.save(OUT)
print("saved:", OUT)
