"""PDF 解析：正文段落、章节、Figure caption 与引用段落、裁切区域、公式候选。

这一层只负责定位证据（页码、bbox、caption、候选正文），不做解释。
解释交给 analyzer.py 调用的本地模型。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, asdict
from core.api import paths__WorkspacePath as Path

try:  # PyMuPDF >= 1.24 同时提供 pymupdf 和 fitz 两个名字
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


# ---------------------------------------------------------------- 正则

FIG_LABEL_RE = re.compile(
    r"^\s*(?:fig(?:ure)?s?)\.?\s*(\d+)\s*(?:\(([a-zA-Z])\)|([a-zA-Z]))?\s*([.:)\]|–—]?)", re.I
)
FIG_REF_HEAD_RE = re.compile(r"\b(?:fig(?:ure)?s?)\.?\s+|\bfig(?:ure)?s?\s*\.\s*", re.I)
TABLE_REF_HEAD_RE = re.compile(r"\btables?\s*\.?\s*", re.I)
SENTENCE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")
EQ_LABEL_ONLY_RE = re.compile(r"^\(\s*([A-Z]?\d{1,3})\s*\)$")
EQ_LABEL_TAIL_RE = re.compile(r"\(\s*([A-Z]?\d{1,3})\s*\)\s*$")
EQ_REF_RE = re.compile(r"\b(?:eqs?|equations?)\.?\s*\(?\s*([A-Z]?\d{1,3})\s*\)?|公式\s*\(?\s*([A-Z]?\d{1,3})\s*\)?", re.I)
REF_TAIL_RE = re.compile(
    r"^\s*\d+\s*[a-zA-Z]?\s*(?:(?:,|;|&|\band\b|\bto\b|\bthrough\b|\s)\s*(?:-|–|—)?\s*\d+\s*[a-zA-Z]?\s*)*",
    re.I,
)
RANGE_RE = re.compile(r"(\d+)\s*(?:-|–|—|\bto\b|\bthrough\b)\s*(\d+)", re.I)
LOWER_VERB_RE = re.compile(
    r"^(?:\([a-zA-Z]\))?\s*(?:shows?|presents?|depicts?|displays?|illustrates?|indicates?|"
    r"reveals?|demonstrates?|gives?|reports?|plots?|summari[sz]es?|compares?|is|are|was|were|we|"
    r"the|in|for|as|and|also|both|there)\b",
    re.I,
)

SECTION_PATTERNS = [
    (re.compile(r"^(?:abstract|a\s*b\s*s\s*t\s*r\s*a\s*c\s*t)$", re.I), "Abstract"),
    (re.compile(r"^(?:introduction|intro)\b", re.I), "Introduction"),
    (re.compile(r"^results?\s*(?:and|&)\s*discussions?\b", re.I), "Results and Discussion"),
    (re.compile(r"^results?\b", re.I), "Results"),
    (re.compile(r"^discussions?\b", re.I), "Discussion"),
    (re.compile(r"^(?:conclusions?|concluding\s+remarks?|summary)\b", re.I), "Conclusion"),
    (
        re.compile(
            r"^(?:materials?\s+and\s+methods?|methods?|methodology|experimental(?:\s+section)?|"
            r"experimental\s+details?|computational\s+(?:methods?|details?)|theory|models?\s+and\s+methods?)\b",
            re.I,
        ),
        "Methods",
    ),
    (re.compile(r"^(?:references?|bibliography)\b", re.I), "References"),
    (re.compile(r"^(?:acknowledg(?:e)?ments?|funding|author\s+contributions)\b", re.I), "Acknowledgments"),
    (re.compile(r"^(?:supplementary|supporting\s+information)\b", re.I), "Supplementary"),
]
HEADING_NUMBER_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|[A-Z]\.)\s*")
HEADING_NOISE_RE = re.compile(r"^(?:page|fig|figure|table|eq|equation|doi|http|www)\b", re.I)

MATH_CHARS = set("∑∫∂±≈≤≥√·×÷∝∞⟨⟩∇αβγδεζηθικλμνξπρστυφχψω")
# 只有运算符/关系符才算“像公式”的强信号；希腊字母（α、β…）单独出现不算，否则物性表头会被误判
MATH_OPERATORS = set("≡∑∫∂±≈≤≥√·×÷∝∞⟨⟩∇^/")
EQUATION_NUMBER_RE = re.compile(r"[\(\[]\s*([A-Z]?\d{1,3})\s*[\)\]]\s*$")


# ---------------------------------------------------------------- 数据模型


@dataclass
class Paragraph:
    index: int
    page: int  # 0-based
    bbox: list[float]
    text: str
    size: float = 0.0
    bold: bool = False
    is_heading: bool = False
    is_caption: bool = False
    role: str = "body"  # body / heading / caption / noise / equation

    def cite(self, paper_title: str = "") -> str:
        return f"[p.{self.page + 1}] {self.text}"


@dataclass
class Section:
    name: str
    heading: str
    page: int
    start: int  # 段落 index
    end: int = 0
    detected: bool = True

    @property
    def text_span(self) -> tuple[int, int]:
        return (self.start, self.end)


@dataclass
class Figure:
    number: int
    label: str
    sublabel: str | None
    caption: str
    caption_page: int
    caption_bbox: list[float]
    caption_start: int = -1  # caption 起始段落在 paragraphs 中的下标
    caption_strict: bool = True  # 图号后面是否紧跟 . : ) 这类图注标志
    caption_confidence: str = "high"
    crop_page: int = 0
    crop_bbox: list[float] = field(default_factory=list)
    crop_confidence: str = "low"
    crop_note: str = ""
    graphics_found: bool = False
    image_path: str | None = None
    candidates: list[dict] = field(default_factory=list)
    related_note: str = ""
    sections_of_related: list[str] = field(default_factory=list)

    @property
    def folder_name(self) -> str:
        return f"Fig_{self.number}"


@dataclass
class Equation:
    label: str
    number: int | str | None
    page: int
    bbox: list[float]
    text: str  # 文字层读到的公式文本，仅供参考，不用来还原公式
    source_note: str = ""
    confidence: str = "high"  # high = 带编号；medium = 无编号，自动识别
    image_path: str | None = None
    # 公式组信息：只填在每组的第一个成员上（单条公式就是长度为 1 的组）
    group_label: str = ""
    group_numbers: list[int | str] = field(default_factory=list)
    group_bbox: list[float] = field(default_factory=list)
    members: list[dict] = field(default_factory=list)
    context: list[dict] = field(default_factory=list)
    source_geometry: dict = field(default_factory=dict)

    @property
    def folder_name(self) -> str:
        from read.api import evidence_identity__equation_folder as equation_folder
        number=self.group_numbers[0] if self.group_numbers else self.number
        return equation_folder(number,self.page+1,self.evidence_id)

    @property
    def evidence_id(self) -> str:
        from read.api import evidence_identity__equation_identity as equation_identity
        return equation_identity(self.page+1,self.group_bbox or self.bbox)


@dataclass
class ParsedPaper:
    pdf_path: str
    page_count: int
    page_sizes: list[list[float]]
    page_texts: list[str]
    paragraphs: list[Paragraph]
    sections: list[Section]
    figures: list[Figure]
    equations: list[Equation]
    metadata: dict
    warnings: list[str] = field(default_factory=list)
    extraction_audit: dict = field(default_factory=dict)

    def paragraph_text(self, index: int) -> str:
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index].text
        return ""

    def section_of(self, paragraph_index: int) -> str:
        current = "正文"
        for sec in self.sections:
            if paragraph_index >= sec.start:
                current = sec.name
            else:
                break
        return current

    def section_at(self, page: int, y: float) -> str:
        """某个页面位置所属章节：取该位置上方最近段落的章节。"""
        anchor = None
        for para in self.paragraphs:
            if para.page != page:
                continue
            if para.bbox[1] <= y and (anchor is None or para.bbox[1] > anchor.bbox[1]):
                anchor = para
        return self.section_of(anchor.index) if anchor else "正文"

    def section_text(self, name: str, max_chars: int | None = None) -> str:
        chunks = []
        matched = False
        for sec in self.sections:
            if sec.name != name:
                continue
            matched = True
            for para in self.paragraphs[sec.start : sec.end]:
                if para.role in ("body",):
                    chunks.append(para.text)
        if not matched and name == "Abstract":
            # 很多期刊不把 Abstract 作为独立标题块，摘要通常就是 Introduction 之前的正文
            first_start = min((sec.start for sec in self.sections), default=0)
            chunks = [
                para.text
                for para in self.paragraphs[:first_start]
                if para.role == "body" and len(para.text) > 200
            ]
        text = "\n".join(chunks).strip()
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n…（正文过长，已截断）"
        return text

    def full_text(self, max_chars: int | None = None) -> str:
        chunks = [p.text for p in self.paragraphs if p.role in ("body", "heading", "caption")]
        text = "\n".join(chunks)
        if max_chars and len(text) > max_chars:
            text = text[:max_chars]
        return text

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


# ---------------------------------------------------------------- 基础提取


def _line_text(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def _join_lines(lines: list[str]) -> str:
    """拼接段落内的行，处理行尾连字符断词。"""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        elif out.endswith(" ") or line.startswith(" "):
            out += line
        else:
            out += " " + line
    return re.sub(r"\s+", " ", out).strip()


def _iter_blocks(page: "fitz.Page"):
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        lines = [ln for ln in block.get("lines", []) if _line_text(ln).strip()]
        if not lines:
            continue
        text = _join_lines([_line_text(ln) for ln in lines])
        if not text:
            continue
        sizes = [span.get("size", 0.0) for ln in lines for span in ln.get("spans", [])]
        size = max(sizes) if sizes else 0.0
        bold = any(span.get("flags", 0) & 16 for ln in lines for span in ln.get("spans", []))
        yield {
            "bbox": list(block.get("bbox", (0, 0, 0, 0))),
            "text": text,
            "size": float(size),
            "bold": bold,
        }


def _normalise(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))[:80]


def _drop_headers_footers(
    pages_blocks: list[list[dict]], page_count: int, page_sizes: list[list[float]]
) -> tuple[list[list[dict]], list[tuple[float, float]]]:
    """去掉重复出现在多数页面上的页眉 / 页脚 / 页码，并给出每页的正文带范围。"""
    counter: dict[str, set[int]] = {}
    for pno, blocks in enumerate(pages_blocks):
        for block in blocks:
            if len(block["text"]) <= 200:
                counter.setdefault(_normalise(block["text"]), set()).add(pno)
    threshold = max(2, __import__("math").ceil(page_count * 0.4))
    repeated = {key for key, pages in counter.items() if len(pages) >= threshold}

    cleaned: list[list[dict]] = []
    bands: list[tuple[float, float]] = []
    for pno, blocks in enumerate(pages_blocks):
        height = page_sizes[pno][1]
        width = page_sizes[pno][0]
        kept: list[dict] = []
        dropped: list[dict] = []
        for block in blocks:
            text = block["text"]
            bx0, _, bx1, _ = block["bbox"]
            y0,y1=block["bbox"][1],block["bbox"][3]
            if len(text) <= 200 and _normalise(text) in repeated and (y1<height*.08 or y0>height*.92):
                dropped.append(block)
                continue
            if re.fullmatch(r"[\s\d\.\-–—/]+", text) and (y1<height*.05 or y0>height*.95):  # 页码必须在页边
                dropped.append(block)
                continue
            # 页边竖排水印（下载来源、期刊名）等窄条
            if bx1 <= width * 0.03 or bx0 >= width * 0.97:
                dropped.append(block)
                continue
            kept.append(block)
        cleaned.append(kept)
        header_bottom = max((b["bbox"][3] for b in dropped if b["bbox"][3] < height * 0.25), default=0.0)
        footer_top = min((b["bbox"][1] for b in dropped if b["bbox"][1] > height * 0.75), default=height)
        bands.append((round(header_bottom, 2), round(footer_top, 2)))
    return cleaned, bands


def _columns(blocks: list[dict], page_width: float) -> list[tuple[float, float]]:
    """按 x 方向聚类出分栏范围，返回按 x 排序的 (x0, x1) 列表。

    只拿窄块做聚类：横跨整页的表格/大图会把两栏粘在一起，导致跨栏段落顺序错乱。
    """
    if not blocks:
        return []
    narrow = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) < page_width * 0.62]
    spans = sorted(
        ((b["bbox"][0], b["bbox"][2]) for b in (narrow or blocks)), key=lambda s: s[0]
    )
    tolerance = max(8.0, page_width * 0.015)
    merged: list[list[float]] = []
    for x0, x1 in spans:
        if merged and x0 <= merged[-1][1] + tolerance:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return [(a, b) for a, b in merged]


def _column_index(columns: list[tuple[float, float]], x_center: float) -> int:
    if not columns:
        return 0
    best, best_dist = 0, None
    for i, (x0, x1) in enumerate(columns):
        if x0 <= x_center <= x1:
            return i
        dist = min(abs(x_center - x0), abs(x_center - x1))
        if best_dist is None or dist < best_dist:
            best, best_dist = i, dist
    return best


def _looks_like_table_row(text: str) -> bool:
    """表格行（大量数字、几乎不成句）不适合当正文段落。"""
    stripped = text.strip()
    if len(stripped) < 12:
        return False
    words = re.findall(r"[A-Za-z]{2,}", stripped)
    digits = sum(1 for ch in stripped if ch.isdigit())
    if digits / max(len(stripped), 1) > 0.25 and len(words) <= 12:
        return True
    numeric_tokens = re.findall(r"\d+\.\d+|\b\d+\b", stripped)
    return len(numeric_tokens) >= 5 and len(words) <= 10


def _reading_order(pages_blocks: list[list[dict]], page_sizes: list[list[float]]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    index = 0
    for pno, blocks in enumerate(pages_blocks):
        width = page_sizes[pno][0]
        columns = _columns(blocks, width)
        positioned = []
        for block in blocks:
            bbox = block["bbox"]
            x_center = (bbox[0] + bbox[2]) / 2
            positioned.append((_column_index(columns, x_center), bbox[1], block))
        positioned.sort(key=lambda item: (item[0], round(item[1], 1)))
        for _, _, block in positioned:
            paragraphs.append(
                Paragraph(
                    index=index,
                    page=pno,
                    bbox=[round(v, 2) for v in block["bbox"]],
                    text=block["text"],
                    size=block["size"],
                    bold=block["bold"],
                    role="table" if _looks_like_table_row(block["text"]) else "body",
                )
            )
            index += 1
    return paragraphs


# ---------------------------------------------------------------- 章节


def _body_font_size(paragraphs: list[Paragraph]) -> float:
    sizes = []
    for para in paragraphs:
        if len(para.text) >= 40:
            sizes.extend([para.size] * min(len(para.text), 200))
    return statistics.median(sizes) if sizes else 10.0


def _detect_sections(paragraphs: list[Paragraph], body_size: float) -> list[Section]:
    sections: list[Section] = []
    for para in paragraphs:
        text = para.text.strip()
        if not text or len(text) > 90 or text.endswith("."):
            continue
        core = HEADING_NUMBER_RE.sub("", text).strip().rstrip(":").strip()
        if not core or HEADING_NOISE_RE.match(core):
            continue
        is_big = (para.size >= body_size * 1.03 or (para.bold and para.size >= body_size * 0.98)
                  or (core.isupper() and len(core.split())<=12 and para.size>=body_size*.9))
        if not is_big:
            continue
        for pattern, name in SECTION_PATTERNS:
            if pattern.match(core):
                para.role = "heading"
                para.is_heading = True
                sections.append(Section(name=name, heading=text, page=para.page, start=para.index + 1))
                break
    # 去掉重复的章节标题（同名只保留第一次出现，References 之后的同名保留）
    seen: dict[str, int] = {}
    deduped: list[Section] = []
    for sec in sections:
        if sec.name in seen and sec.name not in ("Results", "Methods"):
            prior=deduped[seen[sec.name]]
            if sec.name=='Conclusion' and sec.start>len(paragraphs)//2:
                deduped.remove(prior)
                seen={item.name:i for i,item in enumerate(deduped)}
            else:continue
        seen[sec.name] = len(deduped)
        deduped.append(sec)
    deduped.sort(key=lambda s: s.start)
    for i, sec in enumerate(deduped):
        sec.end = deduped[i + 1].start - 1 if i + 1 < len(deduped) else len(paragraphs)
    return deduped


# ---------------------------------------------------------------- Figure


def _looks_like_caption(text: str, match: re.Match) -> bool:
    """区分真正的图注和正文里以 “Fig. 3” 开头的引用句。"""
    tail = text[match.end() :].strip()
    if not tail:
        return False
    if LOWER_VERB_RE.match(tail) and not match.group(4):
        return False
    return True


def _extract_caption(
    paragraphs: list[Paragraph], start: int, pages_blocks: list[list[dict]], max_chars: int = 1800
) -> tuple[str, int]:
    """图注可能是多个连续的 block，拼接 caption 起始段落后面的续行。"""
    para = paragraphs[start]
    text = para.text.strip()
    end = start
    page_blocks = pages_blocks[para.page]
    x_center = (para.bbox[0] + para.bbox[2]) / 2
    width = para.bbox[2] - para.bbox[0]
    y_bottom = para.bbox[3]
    for nxt in paragraphs[start + 1 :]:
        if nxt.page != para.page:
            break
        if len(text) > max_chars:
            break
        nx0, nx1 = nxt.bbox[0], nxt.bbox[2]
        overlap = min(nx1, para.bbox[2]) - max(nx0, para.bbox[0])
        if overlap < 0.5 * max(width, 1) or not (nx0 - 8 <= x_center <= nx1 + 8):
            break
        if FIG_LABEL_RE.match(nxt.text) or nxt.is_heading or nxt.role == "heading":
            break
        if nxt.bbox[1] - y_bottom > 14:  # 垂直间距过大，说明不是同一段
            break
        if text.endswith(".") and nxt.size < para.size * 0.95:
            break
        text = f"{text} {nxt.text}".strip()
        y_bottom = nxt.bbox[3]
        end = nxt.index
    return text, end


def _graphics_boxes(page: "fitz.Page") -> list[list[float]]:
    boxes: list[list[float]] = []
    try:
        for info in page.get_image_info():
            boxes.append(list(info.get("bbox", (0, 0, 0, 0))))
    except Exception:
        pass
    try:
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is not None:
                boxes.append([rect.x0, rect.y0, rect.x1, rect.y1])
    except Exception:
        pass
    return boxes


def _intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _overlap_ratio(a: list[float], b: list[float], axis: str = "x") -> float:
    if axis == "x":
        overlap = min(a[2], b[2]) - max(a[0], b[0])
        span = min(a[2] - a[0], b[2] - b[0])
    else:
        overlap = min(a[3], b[3]) - max(a[1], b[1])
        span = min(a[3] - a[1], b[3] - b[1])
    return overlap / span if span > 0 else 0.0


def _cluster_boxes(boxes: list[list[float]], gap: float = 25.0) -> list[list[float]]:
    """把垂直方向靠近的图形框合并成一块，得到图形区域的整体范围。"""
    clusters: list[list[float]] = []
    for box in sorted(boxes, key=lambda b: b[1]):
        if clusters and box[1] - clusters[-1][3] <= gap:
            cur = clusters[-1]
            cur[0] = min(cur[0], box[0])
            cur[1] = min(cur[1], box[1])
            cur[2] = max(cur[2], box[2])
            cur[3] = max(cur[3], box[3])
        else:
            clusters.append(list(box))
    return clusters


def _figure_region_from_graphics(
    graphics: list[list[float]],
    caption_bbox: list[float],
    band: tuple[float, float],
    page_rect: list[float],
    body_bottom: float,
) -> list[float] | None:
    """由图形（矢量图 / 位图）自身范围推出图区，避免被图内的坐标轴标签截断。"""
    cap = caption_bbox
    selected = []
    for box in graphics:
        if box[3] > cap[1] + 2 or box[3] < band[0] or box[1] > band[1]:
            continue
        if (box[2] - box[0]) * (box[3] - box[1]) < 6:
            continue
        if _overlap_ratio(box, cap, "x") < 0.15:
            continue
        selected.append(box)
    if not selected:
        return None
    clusters = _cluster_boxes(selected)
    clusters.sort(key=lambda b: b[3])
    chosen = [clusters[-1]]
    for box in reversed(clusters[:-1]):
        if chosen[0][1] - box[3] <= 45:  # 与已选区域之间的空隙很小，属于同一张图
            chosen.insert(0, box)
        else:
            break
    region = [
        min(b[0] for b in chosen),
        min(b[1] for b in chosen),
        max(b[2] for b in chosen),
        max(b[3] for b in chosen),
    ]
    # 图区至少覆盖 caption 的宽度，避免只裁到半个图
    region[0] = min(region[0], cap[0])
    region[2] = max(region[2], cap[2])
    region[1] = max(region[1], body_bottom, band[0])
    region[3] = cap[1]
    return [round(v, 2) for v in region]


def _clip(box: list[float], page_rect: list[float], pad: float = 4.0) -> list[float] | None:
    x0 = max(box[0] - pad, page_rect[0])
    y0 = max(box[1] - pad, page_rect[1])
    x1 = min(box[2] + pad, page_rect[2])
    y1 = min(box[3] + pad, page_rect[3])
    if x1 - x0 < 24 or y1 - y0 < 24:
        return None
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def _region_has_graphics(boxes: list[list[float]], clipped: list[float]) -> bool:
    """判断裁切区域内是否有图像或矢量图形；矢量图常由许多细线组成，所以放宽判定。"""
    hits = [g for g in boxes if _intersects(clipped, g)]
    if not hits:
        return False
    region_w = max(clipped[2] - clipped[0], 1.0)
    region_h = max(clipped[3] - clipped[1], 1.0)
    for g in hits:
        overlap_w = min(clipped[2], g[2]) - max(clipped[0], g[0])
        overlap_h = min(clipped[3], g[3]) - max(clipped[1], g[1])
        if overlap_w > 0 and overlap_h > 0 and overlap_w * overlap_h > 400:
            return True
        if overlap_w > 0.5 * region_w or overlap_h > 0.5 * region_h:  # 贯穿区域的坐标轴 / 曲线
            return True
    return len(hits) >= 8


def _choose_crop(
    doc: "fitz.Document",
    fig: Figure,
    paragraphs: list[Paragraph],
    pages_blocks: list[list[dict]],
    bands: list[tuple[float, float]],
) -> tuple[int, list[float], str, str, bool]:
    """猜图区：优先用 caption 上方图形的真实范围，其次相邻栏底部、上一页最后一栏底部。"""
    caption_page = fig.caption_page
    cap = fig.caption_bbox
    page_rect = [doc[caption_page].rect.x0, doc[caption_page].rect.y0, doc[caption_page].rect.x1, doc[caption_page].rect.y1]
    band = bands[caption_page]

    def page_rect_of(page_no: int) -> list[float]:
        target = doc[page_no]
        return [target.rect.x0, target.rect.y0, target.rect.x1, target.rect.y1]

    def paragraph_bottom(page_no: int, cap_box: list[float], floor: float) -> float:
        """caption 上方最后一个真正的正文段落底部，作为图区上边界。"""
        bottom = floor
        for block in pages_blocks[page_no]:
            if block["bbox"][3] > cap_box[1] + 2 or len(block["text"]) < 120:
                continue
            if _overlap_ratio(block["bbox"], cap_box, "x") < 0.3:
                continue
            bottom = max(bottom, block["bbox"][3])
        return bottom

    def text_chars_in(page_no: int, region: list[float]) -> int:
        total = 0
        for block in pages_blocks[page_no]:
            if len(block["text"]) < 60:
                continue
            if _intersects(block["bbox"], region) and _overlap_ratio(block["bbox"], region, "x") > 0.3:
                total += len(block["text"])
        return total

    candidates: list[tuple[str, int, list[float], float]] = []

    # 1) caption 同栏上方，用图形自身范围定界
    body_bottom = paragraph_bottom(caption_page, cap, band[0])
    region = _figure_region_from_graphics(_graphics_boxes(doc[caption_page]), cap, band, page_rect, body_bottom)
    if region is not None:
        candidates.append(("caption-above", caption_page, region, body_bottom))
    else:
        candidates.append(("caption-above-text", caption_page, [cap[0], body_bottom, cap[2], cap[1]], body_bottom))

    # 2) 同一页左侧一栏的底部（图在左栏、caption 在右栏顶部的排版）
    left_blocks = [b for b in pages_blocks[caption_page] if b["bbox"][2] <= cap[0] - 5]
    if left_blocks:
        left_x0 = min(b["bbox"][0] for b in left_blocks)
        left_x1 = max(b["bbox"][2] for b in left_blocks)
        left_bottom = max(b["bbox"][3] for b in left_blocks)
        if left_bottom < band[1] - 40:
            candidates.append(
                ("left-column", caption_page, [left_x0, left_bottom, left_x1, band[1]], left_bottom)
            )

    # 3) 上一页最后一栏的底部（图跨到上一页底部）
    if caption_page > 0:
        prev_rect = page_rect_of(caption_page - 1)
        prev_band = bands[caption_page - 1]
        prev_columns = _columns(pages_blocks[caption_page - 1], prev_rect[2] - prev_rect[0])
        if prev_columns:
            last_col = prev_columns[-1]
            prev_blocks = [
                b
                for b in pages_blocks[caption_page - 1]
                if _overlap_ratio(b["bbox"], [last_col[0], 0, last_col[1], 1], "x") > 0.5
            ]
            if prev_blocks:
                prev_bottom = max(b["bbox"][3] for b in prev_blocks)
                if prev_bottom < prev_band[1] - 40:
                    candidates.append(
                        ("prev-page", caption_page - 1, [last_col[0], prev_bottom, last_col[1], prev_band[1]], prev_bottom)
                    )

    best = None
    for name, page_no, box, floor in candidates:
        clipped = _clip(box, page_rect_of(page_no))
        if clipped is None:
            continue
        clipped[1] = max(clipped[1], round(floor, 2))  # 不要把上方正文裁进来
        graphics = _region_has_graphics(_graphics_boxes(doc[page_no]), clipped)
        text_chars = text_chars_in(page_no, clipped)
        score = (1 if graphics else 0, -text_chars)
        if best is None or score > best[0]:
            best = (score, name, page_no, clipped, graphics, text_chars)

    if best is None:
        fallback = _clip([cap[0], band[0], cap[2], cap[1]], page_rect)
        if fallback is None:
            fallback = [page_rect[0], page_rect[1], page_rect[2], cap[1]]
        return caption_page, fallback, "low", "无法定位图区，退化为 caption 上方整块区域", False

    _, name, page_no, box, graphics, text_chars = best
    if graphics:
        confidence = "high" if text_chars < 300 else "medium"
        note = "" if confidence == "high" else f"裁剪区域内含 {text_chars} 个正文字符，可能包含多余文字"
        if name != "caption-above":
            note = (note + "；" if note else "") + f"图区判定为 {name}（图与图注不在同一栏/页）"
    else:
        confidence = "low"
        note = "裁剪区域内未检测到图像或矢量图形，图区可能不准，请人工确认"
    return page_no, box, confidence, note, graphics


def _find_figures(parsed_paragraphs: list[Paragraph], pages_blocks: list[list[dict]]) -> list[Figure]:
    figures: list[Figure] = []
    for para in parsed_paragraphs:
        match = FIG_LABEL_RE.match(para.text)
        if not match or para.role in ("heading",):
            continue
        if not _looks_like_caption(para.text, match):
            continue
        number = int(match.group(1))
        if number <= 0:
            continue
        strict = bool(match.group(4))
        caption, _end = _extract_caption(parsed_paragraphs, para.index, pages_blocks)
        if len(caption) < 20:
            continue
        label = f"Fig. {number}"
        existing = next((f for f in figures if f.number == number), None)
        if existing is not None:
            # 同一编号出现多次：优先“图号后有 . : ) 标点”的、更长的候选
            if (strict, len(caption)) > (existing.caption_strict, len(existing.caption)):
                existing.caption = caption
                existing.caption_page = para.page
                existing.caption_bbox = para.bbox
                existing.caption_start = para.index
                existing.caption_strict = strict
                para.is_caption = True
                para.role = "caption"
            continue
        figures.append(
            Figure(
                number=number,
                label=label,
                sublabel=match.group(2) or match.group(3),
                caption=caption,
                caption_page=para.page,
                caption_bbox=para.bbox,
                caption_start=para.index,
                caption_strict=strict,
            )
        )
        para.is_caption = True
        para.role = "caption"
    figures.sort(key=lambda f: (f.caption_page, f.caption_bbox[1]))
    return figures


def _numbers_after(text: str, head_re: re.Pattern) -> set[int]:
    numbers: set[int] = set()
    for match in head_re.finditer(text):
        cluster = REF_TAIL_RE.match(text[match.end() : match.end() + 60])
        if not cluster or not cluster.group(0).strip():
            continue
        chunk = cluster.group(0)
        for a, b in RANGE_RE.findall(chunk):
            a, b = int(a), int(b)
            if 0 < b - a <= 12:
                numbers.update(range(a, b + 1))
        for value in re.findall(r"\d+", chunk):
            number = int(value)
            if 0 < number <= 60:
                numbers.add(number)
    return numbers


def collect_refs(text: str) -> dict[str, list[int]]:
    """一段正文里同时出现的 Figure 与 Table 编号（一句/一段可引用多个）。"""
    return {
        "figures": sorted(_numbers_after(text, FIG_REF_HEAD_RE)),
        "tables": sorted(_numbers_after(text, TABLE_REF_HEAD_RE)),
    }


def collect_figure_refs(text: str) -> set[int]:
    """从一段正文里找出它引用了哪些 Figure 编号。"""
    return set(collect_refs(text)["figures"])


def _ref_sentences(text: str, number: int) -> list[str]:
    """段落中真正提到这张图的那几句话，作为候选的“引用句”。"""
    hits = [s.strip() for s in SENTENCE_RE.findall(text) if number in collect_figure_refs(s)]
    return [s for s in hits if s][:2]


REF_SOURCE_DIRECT = "直接引用"
REF_SOURCE_NEIGHBOR = "相邻段落"
REF_SOURCE_AFTER_CAPTION = "caption 后续段落"


def _collect_candidates(parsed: ParsedPaper, max_chars: int) -> None:
    """为每张 Figure 生成候选正文窗口：引用句所在段落 + 前后相邻段落。

    只做候选收集，是否与这张图相关交给模型判断（analyzer 的判定步骤）。
    """
    by_number: dict[int, list[int]] = {}
    for para in parsed.paragraphs:
        if para.role != "body":
            continue
        if _is_display_equation_text(para.text):  # 公式行不适合作为解释证据
            continue
        for number in collect_figure_refs(para.text):
            by_number.setdefault(number, []).append(para.index)

    for fig in parsed.figures:
        picked: dict[int, str] = {}
        for pid in sorted(set(by_number.get(fig.number, []))):
            home_section = parsed.section_of(pid)
            for offset, role in ((0, REF_SOURCE_DIRECT), (-1, REF_SOURCE_NEIGHBOR), (1, REF_SOURCE_NEIGHBOR)):
                candidate_index = pid + offset
                if not 0 <= candidate_index < len(parsed.paragraphs):
                    continue
                para = parsed.paragraphs[candidate_index]
                if para.role != "body" or candidate_index in picked:
                    continue
                if _is_display_equation_text(para.text):
                    continue
                if role == REF_SOURCE_NEIGHBOR and parsed.section_of(candidate_index) != home_section:
                    continue
                picked[candidate_index] = role
        note = ""
        if not picked and fig.caption_start >= 0:
            for para in parsed.paragraphs[fig.caption_start + 1 : fig.caption_start + 3]:
                if para.role == "body":
                    picked[para.index] = REF_SOURCE_AFTER_CAPTION
            note = "没有找到明确引用这张图的正文，退化为 caption 后续段落"

        candidates: list[dict] = []
        budget = 0
        omitted=[]
        for pid in sorted(picked,key=lambda i:(picked[i]!=REF_SOURCE_DIRECT,i)):
            para = parsed.paragraphs[pid]
            if budget + len(para.text) > max_chars:
                omitted.append(pid);continue
            refs = collect_refs(para.text)
            candidates.append(
                {
                    "index": pid,
                    "page": para.page + 1,
                    "section": parsed.section_of(pid),
                    "source": picked[pid],
                    "text": para.text,
                    "refs": refs,
                    "sentences": _ref_sentences(para.text, fig.number),
                    "label": "",
                    "reason": "",
                }
            )
            budget += len(para.text)
        if omitted:parsed.extraction_audit.setdefault("context_omissions",[]).append({"item":fig.label,"paragraphs":omitted,"stage":"figure_context"})
        fig.candidates = sorted(candidates,key=lambda c:c["index"])
        fig.related_note = note if note else (
            "" if candidates else "没有找到与这张图相关的候选正文段落"
        )
        fig.sections_of_related = sorted({c["section"] for c in candidates})


# ---------------------------------------------------------------- Equation（尽力而为）


def _is_display_equation_text(text: str) -> bool:
    """判断一个块像不像独立成行的公式（排除表格行、正文句子）。"""
    stripped = text.strip()
    # URLs contain '/' and '-' but publisher notices and bibliographic links
    # are not equations. Reject before the generic operator heuristic.
    if re.search(r"https?://|www\.|\bdoi\s*:|[\w.+-]+@[\w.-]+", stripped, re.I):
        return False
    if not 3 <= len(stripped) <= 2000:
        return False
    if re.match(r'^\([a-z]\)\s*',stripped):return False
    # Short index lists and repeated parameter/unit labels are not displays.
    if len(stripped)<20 and ',' in stripped and not re.search(r'[∑∫∂+−*/^]',stripped):return False
    if len(re.findall(r'=\s*[\d.]+\s*(?:nm|eV|meV|K|cm|mm)\b',stripped))>=2:return False
    if _looks_like_table_row(stripped):
        return False
    if stripped.endswith("."):  # 正文句子常以句号结尾，公式不会
        return False
    if re.match(r"^(?:where|and|the|with|for|as|in|when|if|then|thus|hence|note)\b", stripped, re.I):
        return False
    if "=" not in stripped and not any(ch in stripped for ch in MATH_OPERATORS):
        return False
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    symbol_ratio = sum(1 for ch in stripped if not ch.isalnum() and not ch.isspace()) / len(stripped)
    if len(words) > 14 and symbol_ratio < 0.18:
        return False
    return True


def _blocks_left_of(blocks: list[dict], label_block: dict) -> list[dict]:
    """编号左侧、同一行带里的块就是公式主体（可能被拆成多个块）。"""
    ly0, ly1 = label_block["bbox"][1], label_block["bbox"][3]
    height = max(ly1 - ly0, 1.0)
    body = []
    for block in blocks:
        if block is label_block:
            continue
        bx0, by0, bx1, by1 = block["bbox"]
        overlap = min(ly1, by1) - max(ly0, by0)
        if overlap < 0.5 * height:
            continue
        if bx1 <= label_block["bbox"][0] + 2:
            body.append(block)
    if body:
        low=min(b['bbox'][1] for b in body);high=max(b['bbox'][3] for b in body)
        x0=min(b['bbox'][0] for b in body)
        remaining=[b for b in blocks if b is not label_block and b not in body
                   and b['bbox'][0]>=x0-10 and b['bbox'][2]<=label_block['bbox'][0]+2]
        for _ in range(8):
            additions=[b for b in remaining if (0<=low-b['bbox'][3]<=12 or 0<=b['bbox'][1]-high<=12)
                       and _is_display_equation_text(b['text']) and not EQ_LABEL_TAIL_RE.search(b['text'])]
            if not additions:break
            body.extend(additions);remaining=[b for b in remaining if b not in additions]
            low=min(b['bbox'][1] for b in body);high=max(b['bbox'][3] for b in body)
    return body


def _union_bbox(blocks: list[dict]) -> list[float]:
    return [
        min(b["bbox"][0] for b in blocks),
        min(b["bbox"][1] for b in blocks),
        max(b["bbox"][2] for b in blocks),
        max(b["bbox"][3] for b in blocks),
    ]


def _find_display_equations(pages_blocks: list[list[dict]]) -> list[Equation]:
    """找出独立成行的 display equation：带编号的优先，没有编号的也收（标为自动识别）。

    行内公式不产生独立文字块，天然被排除。
    """
    equations: list[Equation] = []
    seen_numbers: set[int] = set()
    seen_boxes: list[tuple[int,list[float]]] = []

    def add(page: int, box: list[float], text: str, note: str, number: int | None) -> None:
        box = [round(v, 2) for v in box]
        if any(page==seen_page and abs(box[0] - b[0]) < 2 and abs(box[1] - b[1]) < 2 for seen_page,b in seen_boxes):
            return
        if number is not None:
            if number in seen_numbers:
                return
            seen_numbers.add(number)
        seen_boxes.append((page,box))
        equations.append(
            Equation(
                label=f"Eq. ({number})" if number is not None else f"Eq. (p.{page + 1} 无编号)",
                number=number,
                page=page,
                bbox=box,
                text=re.sub(r"\s+", " ", text).strip(),
                source_note=note,
                confidence="high" if number is not None else "medium",
            )
        )

    for pno, blocks in enumerate(pages_blocks):
        # A) 编号单独成块：左侧同行的块是公式主体
        for block in blocks:
            match = EQ_LABEL_ONLY_RE.match(block["text"].strip())
            if not match:
                continue
            body = _blocks_left_of(blocks, block)
            if not body:
                continue
            text = " ".join(b["text"] for b in sorted(body, key=lambda b: b["bbox"][1]))
            if not _is_display_equation_text(text):continue
            add(pno, _union_bbox(body + [block]), text, "编号单独成块", equation_number(match.group(1)))
        # B) 编号写在公式块末尾
        for block in blocks:
            text = block["text"].strip()
            match = EQ_LABEL_TAIL_RE.search(text)
            if match and _is_display_equation_text(EQ_LABEL_TAIL_RE.sub("", text).strip() or text):
                add(pno, block["bbox"], text, "编号跟在公式末尾", equation_number(match.group(1)))
        # C) 没有编号，但独立成行、像公式
        for block in blocks:
            text = block["text"].strip()
            if EQ_LABEL_TAIL_RE.search(text) or EQ_LABEL_ONLY_RE.match(text):
                continue
            if any(page==pno and box[0]<=block['bbox'][0] and box[1]<=block['bbox'][1]
                   and box[2]>=block['bbox'][2] and box[3]>=block['bbox'][3] for page,box in seen_boxes):continue
            if not _is_display_equation_text(text):
                continue
            if "=" not in text and not any(ch in text for ch in MATH_OPERATORS):  # 表头行常只有连字符/希腊字母
                continue
            add(pno, block["bbox"], text, "无编号，独立成行", None)
    equations.sort(key=lambda eq: (eq.page, eq.bbox[1]))
    return equations


def equation_number(value):
    value=str(value).strip().upper()
    return int(value) if value.isdigit() else value


def equation_sort_key(value):
    match=re.fullmatch(r'([A-Z]?)(\d+)',str(value))
    return (match.group(1),int(match.group(2))) if match else ('~',0)


def _equation_refs(text: str) -> set[int | str]:
    numbers = set()
    for match in EQ_REF_RE.finditer(text):
        value = match.group(1) or match.group(2)
        if value:
            numbers.add(equation_number(value))
    return numbers


def _group_label(numbers: list[int], page: int) -> str:
    if not numbers:
        return f"Eq. 组 (p.{page + 1} 无编号)"
    if len(numbers) == 1:
        return f"Eq. ({numbers[0]})"
    if all(isinstance(n,int) for n in numbers) and numbers == list(range(numbers[0], numbers[0] + len(numbers))):
        return f"Eq. ({numbers[0]})–({numbers[-1]})"
    return "Eq. " + ", ".join(f"({n})" for n in numbers)


def _paragraphs_between(parsed: ParsedPaper, first: Equation, second: Equation) -> int:
    pages = {first.page, second.page}
    count = 0
    for para in parsed.paragraphs:
        if para.page not in pages or para.role != "body":
            continue
        if (para.page, para.bbox[1]) > (first.page, first.bbox[3]) and (
            para.page,
            para.bbox[1],
        ) < (second.page, second.bbox[1]):
            count += 1
    return count


def _group_equations(parsed: ParsedPaper, equations: list[Equation], max_gap_paragraphs: int = 1) -> None:
    """把连续、中间最多隔一段说明文字的公式合成一组（同一推导/模型）。

    每组的第一个成员上写入组信息；没有编号的公式单独成组时也保留。
    """
    if not equations:
        return
    groups: list[list[Equation]] = []
    current: list[Equation] = [equations[0]]
    for previous, item in zip(equations, equations[1:]):
        same_page = item.page == previous.page
        gap = item.bbox[1] - previous.bbox[3]
        between = _paragraphs_between(parsed, previous, item)
        same_section = parsed.section_at(previous.page, previous.bbox[1]) == parsed.section_at(
            item.page, item.bbox[1]
        )
        if same_page and gap <= 120 and between <= max_gap_paragraphs and same_section:
            current.append(item)
        else:
            groups.append(current)
            current = [item]
    groups.append(current)

    for group in groups:
        head = group[0]
        numbers = [item.number for item in group if item.number is not None]
        head.group_label = _group_label(numbers, head.page)
        head.group_numbers = numbers
        head.group_bbox = [round(v, 2) for v in _union_bbox([{"bbox": item.bbox} for item in group])]
        head.members = [
            {
                "label": item.label,
                "number": item.number,
                "page": item.page + 1,
                "source_note": item.source_note,
                "confidence": item.confidence,
                "text": item.text,
                "bbox": item.bbox,
                "index": equations.index(item),
            }
            for item in group
        ]
        for item in group:
            item.group_label = head.group_label


def _attach_equation_context(parsed: ParsedPaper, equations: list[Equation], max_chars: int) -> None:
    """公式组上下文 = 组前 1–2 段 + 组后 1–2 段 + 正文中引用组内任一编号的段落。"""
    for eq in equations:
        if not eq.members:  # 只处理每组的第一条
            continue
        group = eq.members
        first_box = group[0]["bbox"]
        last_box = group[-1]["bbox"]
        first_page = group[0]["page"] - 1
        last_page = group[-1]["page"] - 1
        picked: dict[int, str] = {}

        anchor_before = None
        for para in parsed.paragraphs:
            if para.page != first_page or para.role != "body":
                continue
            if para.bbox[1] <= first_box[1] and (
                anchor_before is None or para.bbox[1] > anchor_before.bbox[1]
            ):
                anchor_before = para
        if anchor_before is not None:
            for offset in (-2, -1):
                index = anchor_before.index + offset
                if 0 <= index < len(parsed.paragraphs) and parsed.paragraphs[index].role == "body":
                    picked.setdefault(index, "公式组前")

        anchor_after = None
        for para in parsed.paragraphs:
            if para.page != last_page or para.role != "body":
                continue
            if para.bbox[1] >= last_box[3] and (anchor_after is None or para.bbox[1] < anchor_after.bbox[1]):
                anchor_after = para
        if anchor_after is not None:
            for offset in (1, 2):
                index = anchor_after.index + offset
                if 0 <= index < len(parsed.paragraphs) and parsed.paragraphs[index].role == "body":
                    picked.setdefault(index, "公式组后")

        numbers = {n for n in eq.group_numbers}
        for para in parsed.paragraphs:
            if para.role != "body" or not numbers:
                continue
            if numbers & _equation_refs(para.text):
                picked[para.index] = "引用该公式组"

        context: list[dict] = []
        budget = 0
        omitted=[]
        for index in sorted(picked, key=lambda i: (picked[i]!="引用该公式组",parsed.paragraphs[i].page, parsed.paragraphs[i].bbox[1])):
            para = parsed.paragraphs[index]
            if budget + len(para.text) > max_chars:
                omitted.append(index);continue
            context.append(
                {
                    "index": index,
                    "page": para.page + 1,
                    "section": parsed.section_of(index),
                    "source": picked[index],
                }
            )
            budget += len(para.text)
        if omitted:parsed.extraction_audit.setdefault("context_omissions",[]).append({"item":eq.group_label or eq.label,"paragraphs":omitted,"stage":"equation_context"})
        eq.context = context


# ---------------------------------------------------------------- 渲染


def render_region(doc: "fitz.Document", page_no: int, bbox: list[float], out_path: str | Path, dpi: int = 150) -> str | None:
    page = doc[page_no]
    clip = fitz.Rect(bbox) & page.rect
    if clip.is_empty or clip.width < 8 or clip.height < 8:
        return None
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    return str(out)


def render_page_image(doc: "fitz.Document", page_no: int, out_path: str | Path, dpi: int = 110) -> str:
    page = doc[page_no]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    return str(out)


# ---------------------------------------------------------------- 主入口


def parse_pdf(pdf_path: str | Path, config: dict | None = None) -> ParsedPaper:
    config = config or {}
    dpi = int(config.get("render_dpi", 150))
    max_context_chars = int(config.get("max_context_chars", 6000))
    max_figures = int(config.get("max_figures", 20))
    pdf_path = str(pdf_path)

    doc = fitz.open(pdf_path)
    if doc.needs_pass:
        doc.close();raise ValueError("加密PDF需要先解密；未调用模型")
    warnings: list[str] = []
    pages_blocks: list[list[dict]] = []
    page_texts: list[str] = []
    page_sizes: list[list[float]] = []
    for page in doc:
        blocks = list(_iter_blocks(page))
        pages_blocks.append(blocks)
        page_texts.append(page.get_text("text"))
        page_sizes.append([round(page.rect.width, 2), round(page.rect.height, 2)])

    if sum(len(t.strip()) for t in page_texts) < 200:
        warnings.append("这份 PDF 几乎没有文字层，可能是扫描件；V1 不做 OCR，结果会不可靠。")
    pages_blocks, content_bands = _drop_headers_footers(pages_blocks, len(page_texts), page_sizes)

    paragraphs = _reading_order(pages_blocks, page_sizes)
    body_size = _body_font_size(paragraphs)
    sections = _detect_sections(paragraphs, body_size)
    if not sections:
        warnings.append("没有识别到标准章节标题（Abstract / Introduction / Conclusion 等），前言与总结可能为空。")

    caption_signals=[]
    for page_no,blocks in enumerate(pages_blocks):
        for block in blocks:
            m=FIG_LABEL_RE.match(block["text"])
            if m and _looks_like_caption(block["text"],m):
                caption_signals.append({"number":int(m.group(1)),"page":page_no+1,"bbox":block["bbox"]})
    figures = _find_figures(paragraphs, pages_blocks)
    detected_figures=len(figures)
    if len(figures) > max_figures:
        warnings.append(f"识别到 {len(figures)} 张 Figure，超过上限 {max_figures}，只处理前 {max_figures} 张。")
        figures = figures[:max_figures]
    if not figures:
        warnings.append("没有识别到 Figure caption，可能是扫描件或排版特殊。")

    parsed = ParsedPaper(
        pdf_path=pdf_path,
        page_count=len(page_texts),
        page_sizes=page_sizes,
        page_texts=page_texts,
        paragraphs=paragraphs,
        sections=sections,
        figures=figures,
        equations=[],
        metadata={k: v for k, v in (doc.metadata or {}).items() if v},
        warnings=warnings,
        extraction_audit={"caption_candidates":caption_signals,"figure_limit_exceeded":detected_figures>max_figures,
          "sparse_text_pages":[i+1 for i,t in enumerate(page_texts) if len(t.strip())<40],"context_omissions":[]},
    )

    for fig in figures:
        page_no, bbox, confidence, note, graphics = _choose_crop(
            doc, fig, paragraphs, pages_blocks, content_bands
        )
        fig.crop_page = page_no
        fig.crop_bbox = bbox
        fig.crop_confidence = confidence
        fig.crop_note = note
        fig.graphics_found = graphics
        if confidence == "low":
            warnings.append(f"{fig.label} 的图区自动裁切不可靠：{note}")

    _collect_candidates(parsed, max_context_chars)

    if config.get("enable_equations", True):
        parsed.equations = _find_display_equations(pages_blocks)
        _group_equations(parsed, parsed.equations)
        max_groups = int(config.get("max_equation_groups", 8))
        heads = [eq for eq in parsed.equations if eq.members]
        parsed.extraction_audit["equation_limit_exceeded"]=len(heads)>max_groups
        if len(heads) > max_groups:
            keep = {id(eq) for eq in heads[:max_groups]}
            parsed.equations = [eq for eq in parsed.equations if not eq.members or id(eq) in keep]
            warnings.append(f"识别到 {len(heads)} 组公式，超过上限 {max_groups}，只处理前 {max_groups} 组。")
        _attach_equation_context(parsed, parsed.equations, max_context_chars)
        heads = [eq for eq in parsed.equations if eq.members]
        numbered = sum(1 for eq in heads if eq.group_numbers)
        if heads:
            warnings.append(
                f"识别到 {len(heads)} 组 display equation（其中 {numbered} 组带编号），行内公式已忽略。"
            )
        else:
            warnings.append("没有识别到独立成行的公式，已跳过公式部分。")

    doc.close()
    return parsed


def render_figures(
    parsed: ParsedPaper,
    out_dir: str | Path,
    dpi: int = 150,
    equation_dpi: int = 300,
) -> None:
    """把每张 Figure / 公式的裁切区域渲染成图片；公式用更高分辨率。"""
    doc = fitz.open(parsed.pdf_path)
    out_dir = Path(out_dir)
    for fig in parsed.figures:
        try:
            path = render_region(doc, fig.crop_page, fig.crop_bbox, out_dir / fig.folder_name / "figure.png", dpi)
            fig.image_path = path
        except Exception as exc:  # 单张图失败不影响整篇
            fig.image_path = None
            fig.crop_note = f"{fig.crop_note}；渲染失败：{exc}".strip("；")
    for eq in parsed.equations:
        if not eq.members:  # 每组只渲染一张组截图（成员并集）
            continue
        try:
            eq.image_path = render_region(
                doc, eq.page, eq.group_bbox or eq.bbox, out_dir / eq.folder_name / "equation.png", equation_dpi
            )
        except Exception:
            eq.image_path = None
    doc.close()


if __name__ == "__main__":  # 手动调试：python3 parser.py 某篇.pdf
    import json
    import sys

    target = sys.argv[1]
    result = parse_pdf(target)
    print(
        json.dumps(
            {
                "pages": result.page_count,
                "paragraphs": len(result.paragraphs),
                "sections": [(s.name, s.start, s.end) for s in result.sections],
                "figures": [
                    (f.label, f.caption_page + 1, f.crop_confidence, len(f.candidates)) for f in result.figures
                ],
                "equations": [(e.label, e.confidence) for e in result.equations],
                "warnings": result.warnings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def prepare_evidence(parsed,config):
    from read.api import evidence_preparation__repair_sections as repair_sections, evidence_preparation__recover_split_figures as recover_split_figures, evidence_preparation__recover_caption_text as recover_caption_text, evidence_preparation__complete_column_captions as complete_column_captions, evidence_preparation__recover_numbered_equations as recover_numbered_equations, evidence_preparation__include_adjacent_definitions as include_adjacent_definitions, evidence_preparation__filter_equation_candidates as filter_equation_candidates, evidence_preparation__expand_unnumbered_relation_lines as expand_unnumbered_relation_lines
    repair_sections(parsed,__import__(__name__,fromlist=['*']))
    reader=__import__(__name__,fromlist=['*'])
    recover_split_figures(parsed,reader);recover_caption_text(parsed,reader)
    complete_column_captions(parsed);recover_numbered_equations(parsed,reader)
    # Reject headers, table text and plot labels before expanding math crops;
    # those candidates must not become pseudoequations in the owner API.
    filter_equation_candidates(parsed)
    expand_unnumbered_relation_lines(parsed,reader)
    # Expanded glyph regions can reveal that an initially external plot label
    # belongs to the figure. Recheck geometry after expansion, before rendering.
    filter_equation_candidates(parsed)
    parsed.equations=[e for e in parsed.equations if e.members]
    parsed.figures.sort(key=lambda f:f.number)
    _collect_candidates(parsed,config.get('max_context_chars',12000))
    _attach_equation_context(parsed,parsed.equations,config.get('max_context_chars',12000))
    include_adjacent_definitions(parsed,config.get('max_context_chars',12000))
    from read.api import pdf_geometry__prepare_geometry as prepare_geometry
    prepare_geometry(parsed,config)
    return parsed

def prepare_pdf(source,config=None):
    config=config or {}
    return prepare_evidence(parse_pdf(source,config),config)

# Stable owner APIs for evidence preparation. Private names remain compatibility aliases.
join_lines=_join_lines
iter_blocks=_iter_blocks
columns=_columns
column_index=_column_index
choose_crop=_choose_crop
group_equations=_group_equations
drop_headers_footers=_drop_headers_footers
collect_candidates=_collect_candidates
attach_equation_context=_attach_equation_context
