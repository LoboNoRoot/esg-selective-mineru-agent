from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


pdfmetrics.registerFont(TTFont("SimHei", r"C:\Windows\Fonts\simhei.ttf"))
pdfmetrics.registerFont(TTFont("FangSong", r"C:\Windows\Fonts\simfang.ttf"))

FONT = "FangSong"
BOLD = "SimHei"
W, H = A4
OUT = Path("output/pdf")
OUT.mkdir(parents=True, exist_ok=True)
PHOTO = "output/resume_work/photo_crop_rgb.png"


base_projects_after = [
    {
        "title": "基金公告数据要素智能识别与可视化系统",
        "role": "负责人",
        "date": "2025.09 - 2025.11",
        "bullets": [
            "针对基金公告分散、人工查询效率低的问题，搭建公告采集、PDF解析、字段抽取及规范化存储的一体化数据处理工作流，采集成功率提升至98%以上，字段抽取准确率超80%。",
            "使用PyMuPDF与正则表达式清洗非结构化公告文本，抽取基金名称、管理人、托管人、运作方式及费率等核心字段，构建结构化基金要素数据集。",
            "开发基金查询与可视化Web系统，支持多维条件筛选、多基金横向对比及PDF动态解析，形成从公告采集到分析展示的完整产品闭环。",
        ],
    },
    {
        "title": "面向数智医疗的AI智能诊断仿真系统",
        "role": "负责人",
        "date": "2025.12 - 至今",
        "bullets": [
            "整合并清洗多类疾病miRNA表达数据，完成缺失值处理、特征筛选与数据标准化，构建疾病诊断分析数据集。",
            "使用SVM等机器学习算法建立疾病分类模型，提取关键miRNA特征，并配合分子计算仿真软件完成多疾病并行诊断模拟。",
            "系统并行诊断准确率达到97%以上，验证机器学习模型与分子计算结合应用于疾病诊断的可行性。",
        ],
    },
]

product_esg = {
    "title": "ESG报告智能抽取与复核系统",
    "role": "负责人",
    "date": "2026.03 - 至今",
    "bullets": [
        "主导拆解企业ESG报告数据生产场景，围绕“报告解析-指标抽取-证据追溯-人工复核-结果导出”设计产品闭环，覆盖3大支柱、16个主题、44个关键指标与60项底层字段。",
        "定义结构化结果字段与复核口径，将指标值、单位、年份、证据原文、页码、表格区域、置信度统一映射至评级Schema，提升结果可解释性和人工校验效率。",
        "设计选择性解析策略，按文本质量、数字密度、表格线索和ESG关键词识别高价值页面，仅对重点页调用MinerU/VLM，降低不必要视觉模型调用约60%（估算）。",
        "推动原型跑通多份A股ESG报告样例，完成42/60项核心指标抽取，覆盖率达70%，并沉淀JSON/CSV结果用于人工复核与后续分析。",
    ],
}

agent_esg = {
    "title": "ESG报告RAG抽取Agent系统",
    "role": "负责人",
    "date": "2026.03 - 至今",
    "bullets": [
        "设计并实现“PDF快扫-重点页解析-RAG证据召回-LLM结构化抽取-CSV复核输出”的文档智能Agent工作流，支持60项ESG底层字段抽取。",
        "构建MinerU+PyMuPDF混合解析链路，将PDF转换为包含文本、表格、页码及BBox坐标的统一DocModel，并通过整页OCR降级机制提升异构文档解析稳定性。",
        "实现多路线抽取策略：结构化表格抽取、定性文本检索、缺失指标视觉补充，并设计跨来源一致性校验、表格质量评分与局部VLM仲裁机制，减少不必要视觉模型调用约60%（估算）。",
        "基于FAISS实现字段级混合检索与证据追溯，为抽取结果保留原文、页码、表格区域及来源路线，最终完成42/60项核心指标抽取，覆盖率达70%。",
    ],
}


def sw(text: str, size: float, font: str = FONT) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def wrap(text: str, size: float, width: float, font: str = FONT) -> list[str]:
    lines: list[str] = []
    cur = ""
    for ch in text:
        if sw(cur + ch, size, font) <= width:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_text(c, text, x, y, size=9, leading=12, width=150 * mm, bullet=False, font=FONT):
    prefix = "·  " if bullet else ""
    lines = wrap(text, size, width - (sw(prefix, size, font) if bullet else 0), font)
    for i, line in enumerate(lines):
        c.setFont(font, size)
        c.drawString(x, y, (prefix if i == 0 else "   ") + line if bullet else line)
        y -= leading
    return y


def section(c, title, y):
    c.setFont(BOLD, 13)
    c.setFillColor(colors.black)
    c.drawString(18 * mm, y, title)
    y -= 4
    c.setStrokeColor(colors.grey)
    c.line(17 * mm, y, 193 * mm, y)
    return y - 13


def project(c, item, y):
    left = 19 * mm
    right = 191 * mm
    mid = 101 * mm
    c.setFont(BOLD, 10.8)
    c.drawString(left, y, item["title"])
    c.drawCentredString(mid, y, item["role"])
    c.drawRightString(right, y, item["date"])
    y -= 12
    for bullet in item["bullets"]:
        y = draw_text(c, bullet, left + 1 * mm, y, 8.85, 12.3, right - left - 1 * mm, True, FONT)
        y -= 0.7
    return y - 2.5


def make(path: Path, esg: dict, target: str):
    c = canvas.Canvas(str(path), pagesize=A4)
    left = 18 * mm

    c.setFont(BOLD, 22)
    c.drawString(left, H - 23 * mm, "鄂泓旭")
    c.setFont(FONT, 11.5)
    y = H - 33 * mm
    for item in ["中共党员", "(+86) 199-6963-5324", "ehongxv152@163.com", "可接受实习6个月，每周到岗5日，可近期到岗"]:
        c.drawString(left, y, item)
        y -= 7.5 * mm
    c.drawImage(PHOTO, 160 * mm, H - 44 * mm, 27 * mm, 34 * mm)

    y = section(c, "教育背景", H - 79 * mm)
    c.setFont(BOLD, 11.2)
    c.drawString(left, y, "上海工程技术大学")
    c.drawCentredString(105 * mm, y, "统计学（硕士）")
    c.drawRightString(191 * mm, y, "2024.09 - 2027.06")
    y -= 12
    y = draw_text(c, "相关课程：时间序列分析、机器学习、矩阵论、计量经济学、数学建模等", left, y, 9.2, 12, 170 * mm)

    y = section(c, "项目经历", y - 2)
    y = project(c, esg, y)
    for p in base_projects_after:
        y = project(c, p, y)

    y = section(c, "荣誉奖励", y + 2)
    for award in [
        "校级奖学金（6次）、三好学生",
        "2025年第二届大学生数据要素素质大赛省级二等奖",
        "2026年“正大杯”第十六届全国大学生市场调查与分析大赛省级二等奖",
    ]:
        y = draw_text(c, award, left + 1 * mm, y, 8.85, 11.2, 170 * mm, True)

    y = section(c, "技能", y + 1)
    if target == "product":
        skills = [
            "AI产品与大模型应用：熟悉RAG、Agent工作流、Prompt设计、结构化输出约束、结果校验与基础评测，使用过Codex、Coze、Dify进行原型开发。",
            "数据产品能力：能够拆解业务指标、设计字段Schema、构建数据处理链路，使用Python、Pandas、NumPy完成数据清洗、字段映射和统计分析。",
            "文档解析与数据采集：使用过PyMuPDF、MinerU处理PDF文本及表格，能够使用Selenium、BeautifulSoup和正则表达式完成网页采集与字段抽取。",
            "系统与可视化：能够使用FastAPI开发基础接口，使用SQLite/PostgreSQL进行数据存储与查询，具备HTML、JavaScript及Chart.js可视化开发经验。",
            "英语与办公：大学英语六级；熟练使用Excel的VLOOKUP等功能，可完成数据处理、可视化分析与自动化报表制作。",
        ]
    else:
        skills = [
            "大模型应用：使用RAG与Agent工作流完成多路线信息抽取，掌握Prompt设计、JSON结构化输出约束、证据追溯、结果校验与简单评测。",
            "Agent/RAG工程：熟悉工具调用型工作流、字段级检索、FAISS混合检索、VLM兜底、解析策略路由与LLM幻觉抑制思路。",
            "Python与文档解析：使用Python、Pandas、NumPy、PyMuPDF、MinerU处理PDF文本/表格，能够构建字段映射、检索召回和抽取结果落盘流程。",
            "系统开发：能够使用FastAPI开发基础接口，使用SQLite/PostgreSQL进行数据存储与查询，具备基础HTML、JavaScript及Chart.js开发经验。",
            "英语与办公：大学英语六级；熟练使用Excel的VLOOKUP等功能，可完成数据处理、可视化分析与自动化报表制作。",
        ]
    for skill in skills:
        y = draw_text(c, skill, left + 1 * mm, y, 8.35, 10.6, 170 * mm, True)

    c.setFont(FONT, 8)
    c.setFillColor(colors.grey)
    c.drawCentredString(W / 2, 7 * mm, "1")
    c.save()


make(OUT / "resume_product_pm.pdf", product_esg, "product")
make(OUT / "resume_ai_agent.pdf", agent_esg, "agent")
