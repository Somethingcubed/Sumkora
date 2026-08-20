"""Create an original Grade 9 chemistry upload benchmark and checking guide."""

from __future__ import annotations

from pathlib import Path

import fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
TEMP_DIR = ROOT / "tmp" / "pdfs" / "chemistry-test-pack"
COMPLETED_PATH = OUTPUT_DIR / "sumkora-huke-2026-chemistry-completed-test.pdf"
GUIDE_PATH = OUTPUT_DIR / "sumkora-huke-2026-chemistry-checking-guide.pdf"
COMPLETED_VECTOR_PATH = TEMP_DIR / "completed-vector.pdf"
GUIDE_VECTOR_PATH = TEMP_DIR / "guide-vector.pdf"

NAVY = colors.HexColor("#111827")
SLATE = colors.HexColor("#64748B")
PURPLE = colors.HexColor("#5B4CF0")
PURPLE_PALE = colors.HexColor("#F4F2FF")
BLUE_PALE = colors.HexColor("#F2F7FF")
GREEN_PALE = colors.HexColor("#EFFAF3")
RED_PALE = colors.HexColor("#FFF3F2")
LINE = colors.HexColor("#DDE3EE")


QUESTIONS = [
    {
        "number": 1,
        "topic": "专题7 溶液",
        "marks": 4,
        "question": (
            "20 ℃时，将15 g氯化钠加入85 g水中，氯化钠完全溶解。"
            "<br/>(a) 写出溶质和溶剂。 [2]"
            "<br/>(b) 计算所得溶液中溶质的质量分数。 [2]"
        ),
        "student": (
            "(a) 溶质是NaCl，溶剂是H<sub>2</sub>O。"
            "<br/>(b) 15 ÷ (15 + 85) × 100% = 15%。"
        ),
        "score": 4,
        "guide": "(a) NaCl、H<sub>2</sub>O各1分。(b) 总质量100 g及15%各1分。学生答案完全正确。",
    },
    {
        "number": 2,
        "topic": "专题7 溶液",
        "marks": 4,
        "question": (
            "硝酸钾在50 ℃时的溶解度为80 g/100 g水，在20 ℃时为32 g/100 g水。"
            "将50 ℃时含100 g水的硝酸钾饱和溶液冷却到20 ℃。"
            "<br/>(a) 计算析出晶体的质量。 [3]"
            "<br/>(b) 判断并说明：温度升高时，所有固体物质的溶解度都会增大吗？ [1]"
        ),
        "student": (
            "(a) 80 - 32 = 48 g，所以析出48 g晶体。"
            "<br/>(b) 会。所有固体的溶解度都随温度升高而增大。"
        ),
        "score": 3,
        "guide": "(a) 48 g，3分。(b) “所有”错误；多数固体增大，但并非全部，0分。",
    },
    {
        "number": 3,
        "topic": "专题8 酸、碱、盐",
        "marks": 5,
        "question": (
            "三瓶无色溶液分别为稀盐酸、氢氧化钠溶液和氯化钠溶液。"
            "<br/>(a) 只用紫色石蕊试液鉴别三瓶溶液，写出现象。 [3]"
            "<br/>(b) 写出盐酸与氢氧化钠反应的化学方程式。 [2]"
        ),
        "student": (
            "(a) 使石蕊变红的是盐酸，变蓝的是氢氧化钠，不变色的是氯化钠。"
            "<br/>(b) HCl + NaOH → NaCl + H<sub>2</sub>O。"
        ),
        "score": 5,
        "guide": "三种现象各1分；方程式及配平、生成物正确共2分。",
    },
    {
        "number": 4,
        "topic": "专题8 酸、碱、盐",
        "marks": 4,
        "question": (
            "某农田土壤pH为4.5。"
            "<br/>(a) 应选熟石灰还是浓硫酸改良土壤？说明理由。 [2]"
            "<br/>(b) 铵态氮肥能否与熟石灰混合施用？说明理由。 [2]"
        ),
        "student": (
            "(a) 选浓硫酸，因为酸可以杀死土壤中的害虫。"
            "<br/>(b) 可以混合，碱会让植物更容易吸收氮元素。"
        ),
        "score": 0,
        "guide": "(a) 应选熟石灰中和酸性土壤。(b) 不能混用，会释放氨气并损失肥效。学生两问均错误。",
    },
    {
        "number": 5,
        "topic": "专题8 酸、碱、盐",
        "marks": 4,
        "question": (
            "向硫酸铜溶液中逐滴加入氢氧化钠溶液。"
            "<br/>(a) 描述现象。 [1]"
            "<br/>(b) 写出反应的化学方程式，并标出沉淀。 [3]"
        ),
        "student": (
            "(a) 产生蓝色沉淀。"
            "<br/>(b) CuSO<sub>4</sub> + 2NaOH → Cu(OH)<sub>2</sub>↓ + Na<sub>2</sub>SO<sub>4</sub>。"
        ),
        "score": 4,
        "guide": "蓝色沉淀1分；反应物、生成物、配平及沉淀符号共3分。",
    },
    {
        "number": 6,
        "topic": "专题9 化学反应的调控",
        "marks": 4,
        "question": (
            "(a) 写出燃烧通常需要的三个条件。 [3]"
            "<br/>(b) 燃气灶起火时先关闭燃气阀门，说明这一灭火方法的原理。 [1]"
        ),
        "student": (
            "(a) 可燃物、氧气、温度达到可燃物的着火点。"
            "<br/>(b) 关闭阀门可以移走或隔离可燃物。"
        ),
        "score": 4,
        "guide": "三个条件各1分；清除可燃物1分。",
    },
    {
        "number": 7,
        "topic": "专题9 化学反应的调控",
        "marks": 4,
        "question": (
            "将三枚相同铁钉分别放入：A，装有干燥剂的干燥空气；B，煮沸的水并覆盖油层；"
            "C，同时接触空气和水。"
            "<br/>(a) 哪一组铁钉最容易生锈？解释原因。 [3]"
            "<br/>(b) 写出一种防止自行车铁架生锈的方法。 [1]"
        ),
        "student": (
            "(a) A组，因为空气越干燥，铁与氧气反应越快。"
            "<br/>(b) 在铁架表面涂漆。"
        ),
        "score": 1,
        "guide": "(a) 应为C组，铁生锈需要氧气和水，学生错误。(b) 涂漆正确，1分。",
    },
    {
        "number": 8,
        "topic": "专题10 化学与人类社会进步",
        "marks": 4,
        "question": (
            "氢能是新能源研究的重要方向。"
            "<br/>(a) 写出氢气完全燃烧的化学方程式，并说明其燃烧产物为什么较清洁。 [2]"
            "<br/>(b) 写出氢能大规模应用面临的一个实际挑战。 [2]"
        ),
        "student": (
            "(a) 2H<sub>2</sub> + O<sub>2</sub> → 2H<sub>2</sub>O；产物只有水。"
            "<br/>(b) 氢气不能燃烧，而且很容易长期储存。"
        ),
        "score": 2,
        "guide": "(a) 方程式及清洁性正确，2分。(b) 陈述与事实相反，0分；可答储运、成本或制氢来源。",
    },
    {
        "number": 9,
        "topic": "专题10 化学与人类社会进步",
        "marks": 4,
        "question": (
            "(a) 人体缺铁可能导致什么健康问题？ [2]"
            "<br/>(b) 聚乙烯属于哪类材料？写出大量使用后可能带来的一个环境问题。 [2]"
        ),
        "student": (
            "(a) 缺铁会导致佝偻病。"
            "<br/>(b) 聚乙烯是合成材料；废弃后难以降解，可能造成白色污染。"
        ),
        "score": 2,
        "guide": "(a) 应答缺铁性贫血，0分。(b) 合成材料及难降解/白色污染各1分。",
    },
    {
        "number": 10,
        "topic": "专题10 化学与人类社会进步",
        "marks": 3,
        "question": (
            "(a) 航天器外壳选用铝合金而非纯铁，写出铝合金的两个适用性质。 [2]"
            "<br/>(b) 写出一项负责任处理废旧电池的行动。 [1]"
        ),
        "student": (
            "(a) 密度较小，并且耐腐蚀。"
            "<br/>(b) 投放到专门的电池回收点。"
        ),
        "score": 3,
        "guide": "低密度、耐腐蚀各1分；规范回收1分。",
    },
]


def styles():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCN",
            parent=base["Title"],
            fontName="STSong-Light",
            fontSize=22,
            leading=30,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCN",
            parent=base["Normal"],
            fontName="STSong-Light",
            fontSize=10,
            leading=16,
            textColor=SLATE,
            spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "SectionCN",
            parent=base["Heading2"],
            fontName="STSong-Light",
            fontSize=13,
            leading=19,
            textColor=PURPLE,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "question": ParagraphStyle(
            "QuestionCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=10.5,
            leading=18,
            textColor=NAVY,
            spaceAfter=2 * mm,
        ),
        "answer": ParagraphStyle(
            "AnswerCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=10.5,
            leading=18,
            textColor=colors.HexColor("#243B66"),
        ),
        "small": ParagraphStyle(
            "SmallCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.5,
            leading=13,
            textColor=SLATE,
        ),
        "center": ParagraphStyle(
            "CenterCN",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=10,
            leading=15,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
    }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(SLATE)
    canvas.drawString(18 * mm, 8.5 * mm, "Sumkora 原创课程测试材料")
    canvas.drawRightString(A4[0] - 18 * mm, 8.5 * mm, f"第 {canvas.getPageNumber()} 页")
    canvas.restoreState()


def document(path: Path):
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title="沪科版五四制九年级化学测试",
        author="Sumkora",
        subject="Original chemistry analysis benchmark",
    )


def label(text: str, style, background=PURPLE_PALE):
    table = Table([[Paragraph(text, style)]], colWidths=[174 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def build_completed(s):
    story = [
        Paragraph("沪科版（五四制）九年级化学", s["title"]),
        Paragraph("Sumkora 分析功能测试 - 已完成答卷", s["section"]),
        label(
            "上传说明：将本PDF作为“已完成的答卷”上传；无需另传题目或答案。"
            "在Sumkora中选择本课程，并把试卷满分填写为40分。",
            s["question"],
        ),
        Spacer(1, 4 * mm),
        Table(
            [
                [Paragraph("姓名：测试学生", s["center"]), Paragraph("满分：40分", s["center"])],
                [Paragraph("覆盖：专题7-10", s["center"]), Paragraph("题数：10题", s["center"])],
            ],
            colWidths=[87 * mm, 87 * mm],
            style=TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ]
            ),
        ),
        Spacer(1, 5 * mm),
    ]
    for item in QUESTIONS:
        block = [
            Paragraph(
                f"第{item['number']}题  <font color='#64748B'>{item['topic']}</font>  [{item['marks']}分]",
                s["section"],
            ),
            Paragraph(item["question"], s["question"]),
            label(f"<b>学生作答</b><br/>{item['student']}", s["answer"], BLUE_PALE),
            Spacer(1, 3.5 * mm),
        ]
        story.append(KeepTogether(block))
    document(COMPLETED_VECTOR_PATH).build(
        story, onFirstPage=footer, onLaterPages=footer
    )


def build_guide(s):
    total = sum(item["score"] for item in QUESTIONS)
    story = [
        Paragraph("沪科版（五四制）九年级化学", s["title"]),
        Paragraph("Sumkora 测试答案与人工核对指南", s["section"]),
        label(
            f"预期人工得分：{total}/40。此文件只供核对，不要上传到分析器。"
            "无官方评分细则时，AI结果在26-30分范围内可视为合理；题目覆盖应为10/10。",
            s["question"],
            GREEN_PALE,
        ),
        Spacer(1, 5 * mm),
    ]
    for item in QUESTIONS:
        background = GREEN_PALE if item["score"] == item["marks"] else RED_PALE
        story.append(
            KeepTogether(
                [
                    Paragraph(
                        f"第{item['number']}题 - {item['topic']} - {item['score']}/{item['marks']}分",
                        s["section"],
                    ),
                    label(item["guide"], s["question"], background),
                    Spacer(1, 3 * mm),
                ]
            )
        )
    story.extend(
        [
            Spacer(1, 5 * mm),
            Paragraph("验收清单", s["title"]),
            label(
                "1. 识别10道题，满分合计40分。<br/>"
                "2. 总分估计应接近28分，合理范围为26-30分。<br/>"
                "3. 专题7应较强；专题8有明显错误；专题9一强一弱；专题10表现中等。<br/>"
                "4. 每道题必须显示完整题干与学生答案证据。<br/>"
                "5. 化学式下标、方程式、中文反馈及下载报告应正常显示。",
                s["question"],
            ),
        ]
    )
    document(GUIDE_VECTOR_PATH).build(
        story, onFirstPage=footer, onLaterPages=footer
    )


def flatten_for_compatibility(source_path: Path, target_path: Path) -> None:
    """Rasterise pages so browser PDF viewers cannot drop CID-font text."""
    source = fitz.open(source_path)
    target = fitz.open()
    for source_page in source:
        pixmap = source_page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
        page = target.new_page(width=source_page.rect.width, height=source_page.rect.height)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    target.set_metadata(
        {
            "title": "沪科版五四制九年级化学测试",
            "author": "Sumkora",
            "subject": "Original chemistry analysis benchmark",
            "producer": "Sumkora compatible PDF renderer",
        }
    )
    target.save(target_path, garbage=4, deflate=True)
    target.close()
    source.close()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    s = styles()
    build_completed(s)
    build_guide(s)
    flatten_for_compatibility(COMPLETED_VECTOR_PATH, COMPLETED_PATH)
    flatten_for_compatibility(GUIDE_VECTOR_PATH, GUIDE_PATH)
    print(COMPLETED_PATH)
    print(GUIDE_PATH)


if __name__ == "__main__":
    main()
