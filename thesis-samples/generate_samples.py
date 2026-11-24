"""Generate synthetic thesis DOCX samples for the thesis-mode parser.

The samples contain no real student text or personal data.  They are used by
the parser/rule tests and the M0 demo.  Regenerate with:

    python thesis-samples/generate_samples.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent
A4 = (21.0, 29.7)
LETTER = (21.59, 27.94)


def _set_east_asian(style, name: str, size: float | None = None) -> None:
    style.font.name = name
    if size is not None:
        style.font.size = Pt(size)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


def _base_styles(doc: DocumentType) -> None:
    _set_east_asian(doc.styles["Normal"], "宋体", 12)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.5
    for level, size in ((1, 16), (2, 14), (3, 12)):
        style = doc.styles[f"Heading {level}"]
        _set_east_asian(style, "黑体", size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(6)


def _page(
    doc: DocumentType,
    *,
    size: tuple[float, float] = A4,
    margins: tuple[float, float, float, float] = (2.5, 2.5, 3.0, 2.5),
) -> None:
    section = doc.sections[0]
    section.page_width = Cm(size[0])
    section.page_height = Cm(size[1])
    top, bottom, left, right = margins
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.5)


def _page_number_footer(doc: DocumentType) -> None:
    """Add a real PAGE field so the page-number rule sees a valid footer."""
    paragraph = doc.sections[0].footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), " PAGE ")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


REFERENCES = [
    "[1] 示例作者. 示例文献题名一[J]. 示例期刊, 2022, 1(1): 1-10.",
    "[2] 示例作者. 示例文献题名二[M]. 示例出版社, 2023.",
    "[3] 示例作者. 示例学位论文[D]. 示例大学, 2024.",
    "[4] 示例作者. 示例会议论文[C]. 示例会议, 2025.",
    "[5] 示例作者. 示例文献题名五[J]. 示例期刊, 2026, 2(3): 20-30.",
]


def _references(doc: DocumentType, entries: list[str] = REFERENCES) -> None:
    _heading(doc, "参考文献", 1)
    for entry in entries:
        _body(doc, entry, indent=False)


def _title(doc: DocumentType, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(text)
    run.bold = True
    run.font.name = "黑体"
    run.font.size = Pt(18)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")


def _body(doc: DocumentType, text: str, *, indent: bool = True) -> None:
    paragraph = doc.add_paragraph(text)
    paragraph.paragraph_format.line_spacing = 1.5
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.74)


def _heading(doc: DocumentType, text: str, level: int) -> None:
    doc.add_heading(text, level=level)


def _caption(doc: DocumentType, text: str) -> None:
    paragraph = doc.add_paragraph(text)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(6)


def _table(doc: DocumentType) -> None:
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    values = [
        ("模块", "输入", "输出"),
        ("解析器", "DOCX", "文档模型"),
        ("规则引擎", "文档模型", "问题清单"),
    ]
    for row_index, row_values in enumerate(values):
        for column_index, value in enumerate(row_values):
            table.cell(row_index, column_index).text = value


def _common_body(doc: DocumentType) -> None:
    _title(doc, "毕业论文（设计）")
    _heading(doc, "摘要", 1)
    _body(doc, "本文使用合成文本演示论文模式的结构解析、格式检查与问题定位。")
    _body(doc, "关键词：论文格式；文档解析；规则引擎")
    doc.add_page_break()

    _heading(doc, "1 绪论", 1)
    _heading(doc, "1.1 研究背景", 2)
    _heading(doc, "1.1.1 问题定义", 3)
    _body(doc, "学生在提交论文前通常需要反复检查页边距、标题层级、图表题注与参考文献格式[1]。")
    _body(doc, "人工检查容易遗漏，且不同学校的模板存在差异，因此需要一个可解释的检查工具[2]。")

    _heading(doc, "2 相关技术", 1)
    _heading(doc, "2.1 文档解析", 2)
    _body(doc, "DOCX 本质上是包含 OOXML 的压缩包，可以从中读取段落、样式、节属性与表格[3]。")
    _body(doc, "解析结果应保留原文，以便把问题定位回具体的段落或页面[4]。")

    _heading(doc, "3 系统设计", 1)
    _heading(doc, "3.1 总体架构", 2)
    _heading(doc, "3.1.1 数据流", 3)
    _body(doc, "系统先解析文档，再运行确定性规则，最后生成带证据的问题清单。")
    _caption(doc, "表 1 系统模块说明")
    _table(doc)

    _heading(doc, "4 结论", 1)
    _body(doc, "本文给出了一个面向毕业论文的格式检查流程，后续将继续完善引用核验与报告导出[5]。")

    _heading(doc, "致谢", 1)
    _body(doc, "感谢示例导师与同学对本文写作的帮助。本文全部内容为合成样例。")

    _references(doc)


def build_clean(path: Path) -> None:
    doc = Document()
    _base_styles(doc)
    _page(doc)
    _page_number_footer(doc)
    _common_body(doc)
    doc.save(str(path))


def build_format_problem(path: Path) -> None:
    doc = Document()
    _base_styles(doc)
    _page(doc, size=LETTER, margins=(3.5, 2.0, 2.0, 3.0))
    _page_number_footer(doc)
    _common_body(doc)
    doc.save(str(path))


def build_structure_problem(path: Path) -> None:
    doc = Document()
    _base_styles(doc)
    _page(doc)
    _page_number_footer(doc)
    _title(doc, "毕业论文（设计）")
    _heading(doc, "摘要", 1)
    _body(doc, "本文使用合成文本演示标题层级与样式问题。")
    doc.add_page_break()

    _heading(doc, "1 绪论", 1)
    _heading(doc, "2.1 研究背景", 2)
    _body(doc, "这里的二级标题编号与一级标题不一致，属于内容层面的问题，规则只提示结构风险。")

    _heading(doc, "3 方法", 1)
    _heading(doc, "3.1.1 实验设计", 3)
    _body(doc, "这里从一级标题直接跳到三级标题，检查器应当提示层级跳跃。")

    _body(doc, "4.1 讨论")
    _body(doc, "这一行看起来像标题，但使用了正文样式，检查器应当提示可能漏设标题样式。")

    _heading(doc, "5 结论", 1)
    _body(doc, "本文用于验证结构规则。")

    _references(doc, ["[1] 示例作者. 示例文献题名[J]. 示例期刊, 2026, 1(1): 1-10."])
    doc.save(str(path))


def build_citation_problem(path: Path) -> None:
    doc = Document()
    _base_styles(doc)
    _page(doc)
    _page_number_footer(doc)
    _title(doc, "毕业论文（设计）")
    _heading(doc, "摘要", 1)
    _body(doc, "本文用于演示引用编号不一致、重复条目与缺号等问题。")
    doc.add_page_break()

    _heading(doc, "1 绪论", 1)
    _heading(doc, "1.1 研究背景", 2)
    _body(doc, "先引用文献[2]，再引用文献[1]，首次出现顺序不是升序。")
    _body(doc, "后文引用了并不存在的文献[3]。")
    _body(doc, "最后引用文献[4]。")

    _heading(doc, "2 结论", 1)
    _body(doc, "本文用于验证引用 L1 规则。")

    _heading(doc, "致谢", 1)
    _body(doc, "感谢示例导师。本文全部内容为合成样例。")

    _references(doc, [
        "[1] 示例作者. 示例文献题名一[J]. 示例期刊, 2022, 1(1): 1-10.",
        "[2] 示例作者. 示例文献题名二[M]. 示例出版社, 2023.",
        "[2] 示例作者. 示例文献题名二[M]. 示例出版社, 2023.",
        "[4] 示例作者. 示例会议论文[C]. 示例会议, 2025.",
    ])
    doc.save(str(path))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {
        "clean-sample.docx": build_clean,
        "format-problem.docx": build_format_problem,
        "structure-problem.docx": build_structure_problem,
        "citation-problem.docx": build_citation_problem,
    }
    for filename, builder in targets.items():
        path = OUT / filename
        builder(path)
        print(f"wrote {path.relative_to(OUT.parent)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
