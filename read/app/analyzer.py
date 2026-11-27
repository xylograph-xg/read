"""资料卡生成：调用 Ollama 本地模型解释 parser.py 定位到的证据。

原则：Python 找证据，模型解释证据。这里不把整篇论文丢给模型去猜图与正文的对应关系。
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import asdict, dataclass, field
from core.api import paths__WorkspacePath as Path
from string import Template
from typing import Callable

import requests

from read.api import parser__ParsedPaper as ParsedPaper, parser__Paragraph as Paragraph, parser__render_figures as render_figures
from read.api import evidence_identity__equation_folder as equation_folder
from read.api import generation_state__METADATA_STAGES as METADATA_STAGES, generation_state__GENERATION_SCHEMA_VERSION as GENERATION_SCHEMA_VERSION, generation_state__metadata_complete as metadata_complete
from read.api import context_budget__estimate_tokens as estimate_tokens, context_budget__input_limit as input_limit, context_budget__fit_fields as fit_fields
from read.api import evidence_quotes__verify_quotes as verify_quotes

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
PROMPT_DIR = PROJECT_ROOT / "prompts"

SECTION_MARKERS = ["图面信息", "量清单", "正文总结", "详细解释", "结果", "一句话结果", "原文依据"]
MARKER_RE = re.compile(r"^[ \t]*(?:(?:###[ \t]+)?===(?P<equals>" + "|".join(SECTION_MARKERS) + r")===|###[ \t]+(?P<markdown>" + "|".join(SECTION_MARKERS) + r"))[ \t]*$", re.M)

ProgressCb = Callable[[str], None]


# ---------------------------------------------------------------- 配置


def load_config(path: str | Path | None = None) -> dict:
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    config = json.loads(Path(target).read_text(encoding="utf-8"))
    config.setdefault("ollama_base_url", "http://127.0.0.1:11434")
    config.setdefault("ollama_model", "gpt-oss:20b")
    config.setdefault("ollama_timeout_seconds", 900)
    config.setdefault("ollama_think", False)
    config.setdefault("ollama_options", {"temperature": 0.2, "num_ctx": 8192})
    config.setdefault("workspace_dir", "workspace")
    config.setdefault("render_dpi", 150)
    config.setdefault("max_context_chars", 6000)
    config.setdefault("max_figures", 20)
    config.setdefault("enable_equations", True)
    return config


# ---------------------------------------------------------------- 提示词


def _load_prompt(name: str, prompt_dir: Path | str = PROMPT_DIR) -> Template:
    return Template((Path(prompt_dir) / f"{name}.md").read_text(encoding="utf-8"))


def _render_prompt(name: str, values: dict, prompt_dir: Path | str = PROMPT_DIR) -> str:
    return _load_prompt(name, prompt_dir).safe_substitute(values)


# ---------------------------------------------------------------- Ollama


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, config: dict):
        self.base_url = str(config["ollama_base_url"]).rstrip("/")
        self.model = config["ollama_model"]
        self.timeout = int(config.get("ollama_timeout_seconds", 900))
        self.options = dict(config.get("ollama_options") or {})
        self.telemetry = []
        self.think = config.get("ollama_think")
        self.system = _load_prompt("system").template.strip()
        profile=config.get('domain_prompt')
        if profile:
            if not re.fullmatch(r'domain_[a-z0-9_]+',profile):raise ValueError('领域提示配置不合法')
            self.system+='\n'+_load_prompt(profile).template.strip()
        self.schedule_config=config.get('schedule_config') or {'catalog_path':str(PROJECT_ROOT.parents[1]/'data/catalog.sqlite3')}

    def health(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=8)
            resp.raise_for_status()
        except Exception as exc:
            return False, f"无法连接 Ollama（{self.base_url}）：{exc}"
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if self.model not in names:
            return False, f"Ollama 中没有模型 {self.model}；当前有：{', '.join(names) or '无'}"
        return True, f"已连接 {self.base_url}，使用模型 {self.model}"

    def chat(self, user_prompt: str, images: list[str | Path] | None = None, retries: int = 2) -> str:
        import sys
        root=str(PROJECT_ROOT.parents[1])
        if root not in sys.path:sys.path.append(root)
        from core.api import model_schedule__require_allowed as require_allowed
        require_allowed(self.schedule_config)
        budget=input_limit(self.options,self.system,images)
        if estimate_tokens(user_prompt)>budget:
            raise ValueError('输入超过保守上下文预算；禁止服务器静默截断证据')
        message: dict = {"role": "user", "content": user_prompt}
        if images:
            encoded = []
            for path in images:
                image_path = Path(path)
                if image_path.exists():
                    encoded.append(base64.b64encode(image_path.read_bytes()).decode())
            if encoded:
                message["images"] = encoded
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system},
                message,
            ],
            "stream": False,
            "options": self.options,
        }
        if self.think is not None:
            # Select thinking through task configuration, without changing prompts.
            payload["think"] = bool(self.think)
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                from read.api import ollama_transport__chat as chat
                request_started=time.monotonic()
                response=chat(self.base_url,payload,self.timeout,self.schedule_config)
                metrics={k:response.get(k) for k in ('prompt_eval_count','eval_count','prompt_eval_duration','eval_duration','total_duration','done_reason')}
                metrics.update(wall_seconds=round(time.monotonic()-request_started,3),
                               input_estimated_tokens=estimate_tokens(user_prompt),
                               has_images=bool(images),attempt=attempt+1)
                self.telemetry.append(metrics)
                count=response.get('prompt_eval_count')
                if isinstance(count,int) and count+int(self.options.get('num_predict',4096))>int(self.options.get('num_ctx',32768)):
                    raise ValueError('实际输入token与输出预留超过上下文预算，禁止发布完整结果')
                if response.get('done_reason')=='length':raise ValueError('模型输出达到长度上限，禁止把截断响应作为完整结果')
                content = (response.get("message") or {}).get("content", "").strip()
                if not content:
                    raise OllamaError("模型返回空内容")
                return content
            except Exception as exc:
                from core.api import model_schedule__ModelWindowClosed as ModelWindowClosed
                if isinstance(exc,(ModelWindowClosed,ValueError)):raise
                last_error = exc
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        raise OllamaError(f"调用模型失败：{last_error}")


# ---------------------------------------------------------------- 资料卡模型


@dataclass
class FigureCard:
    number: int
    label: str
    caption: str
    candidates: list[dict] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    image_path: str | None = None
    caption_page: int = 0
    crop_page: int = 0
    crop_confidence: str = "low"
    crop_note: str = ""
    note: str = ""
    classify_note: str = ""
    classification_status: str = "pending"
    figure_info: str = ""
    summary: str = ""
    detail: str = ""
    result: str = ""
    one_line: str = ""
    status: str = "pending"  # pending / ok / failed
    error: str | None = None
    raw_response: str = ""
    evidence_quote: str = ""
    evidence_status: str = "pending"

    @property
    def folder_name(self) -> str:
        return f"Fig_{self.number}"

    @property
    def heading(self) -> str:
        if self.status == "failed":
            return f"{self.label} — 处理失败"
        return f"{self.label} — {plain_text(self.one_line) or '（未生成一句话结果）'}"


@dataclass
class EquationCard:
    label: str
    evidence_id: str = ""
    numbers: list[int | str] = field(default_factory=list)
    members: list[dict] = field(default_factory=list)  # 组内每条公式：label/number/page/source_note/confidence/text
    equation_text: str = ""  # 文字层读到的内容，仅供参考
    source_geometry: dict = field(default_factory=dict)
    source_note: str = ""
    image_path: str | None = None
    page: int = 0
    context: list[dict] = field(default_factory=list)  # 上下文指针：{index,page,section,source}
    latex: str = ""
    latex_status: str = ""
    latex_raw_response: str = ""
    quantities: str = ""
    summary: str = ""
    detail: str = ""
    result: str = ""
    one_line: str = ""
    status: str = "pending"
    error: str | None = None
    raw_response: str = ""
    evidence_quote: str = ""
    evidence_status: str = "pending"

    @property
    def folder_name(self) -> str:
        return equation_folder(self.numbers[0] if self.numbers else None,self.page,self.evidence_id)

    @property
    def heading(self) -> str:
        if self.status == "failed":
            return f"{self.label} — 解释未生成（截图与上下文已保留）"
        return f"{self.label} — {plain_text(self.one_line) or '（未生成一句话结果）'}"

    @property
    def unnumbered(self) -> bool:
        return not self.numbers or any(str(m.get("confidence")) == "medium" for m in self.members)


@dataclass
class PaperCard:
    title: str
    info: dict[str, str] = field(default_factory=dict)
    info_raw: str = ""
    key_findings: str = ""
    one_line_summary: str = ""
    intro_summary: str = ""
    conclusion_summary: str = ""
    figures: list[FigureCard] = field(default_factory=list)
    equations: list[EquationCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PaperCard":
        def known(klass, item: dict) -> dict:
            return {k: v for k, v in item.items() if k in klass.__dataclass_fields__}

        figures = [FigureCard(**known(FigureCard, fig)) for fig in data.get("figures", [])]
        equations = [EquationCard(**known(EquationCard, eq)) for eq in data.get("equations", [])]
        payload = known(cls, data)
        payload.pop("figures", None)
        payload.pop("equations", None)
        payload.setdefault("title", "")
        return cls(figures=figures, equations=equations, **payload)


# ---------------------------------------------------------------- 输出解析

INFO_KEYS = ["标题", "作者", "期刊", "年份", "DOI", "研究对象", "主要方法", "关键词"]
INFO_ALIASES = {
    "标题": ("标题", "题目", "title"),
    "作者": ("作者", "通讯", "author"),
    "期刊": ("期刊", "杂志", "发表", "journal"),
    "年份": ("年份", "year"),
    "DOI": ("doi",),
    "研究对象": ("对象", "体系", "材料", "研究主体"),
    "主要方法": ("方法", "手段", "技术"),
    "关键词": ("关键词", "关键字", "keyword"),
}


def _canonical_info_key(key: str) -> str:
    lowered = key.strip().lower()
    for canonical, aliases in INFO_ALIASES.items():
        if lowered == canonical.lower() or lowered in aliases:
            return canonical
    return key.strip()


def parse_info(text: str) -> dict[str, str]:
    raw: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = re.sub(r"^[#*\-\s]+", "", line).strip()
        if not cleaned:
            continue
        match = re.match(r"^(?:\*\*)?([^：:*]{1,12})(?:\*\*)?\s*[：:]\s*(.*)$", cleaned)
        if not match:
            continue
        key = _canonical_info_key(match.group(1))
        if key not in INFO_KEYS or key in raw:
            continue
        value = re.sub(r"^\*\*\s*|\s*\*\*$", "", match.group(2).strip()).strip()
        if value:
            raw[key] = value
    ordered = {key: raw.pop(key) for key in INFO_KEYS if key in raw}
    ordered.update(raw)
    return ordered


LATEX_SYMBOLS = {
    "tau": "τ", "Delta": "Δ", "delta": "δ", "beta": "β", "alpha": "α", "gamma": "γ",
    "phi": "φ", "Phi": "Φ", "lambda": "λ", "mu": "μ", "nu": "ν", "pi": "π", "sigma": "σ",
    "theta": "θ", "omega": "ω", "Omega": "Ω", "times": "×", "approx": "≈", "to": "→", "propto": "∝",
    "leq": "≤", "geq": "≥", "pm": "±", "infty": "∞", "prime": "′", "circ": "°",
    "sum": "∑", "int": "∫", "cdot": "·", "sqrt": "√", "text": "", "mathrm": "", "hspace": "",
}
CHATTER_RE = re.compile(r"(以下|如下).*(资料卡|整理|提供|片段)|^(核心结论|关键结论|论文信息|前言与总结)$")


def plain_text(text: str) -> str:
    """折叠空白；保留数学命令、上下标与定界符供显示和后续核验。"""
    return re.sub(r"\s+", " ", text).strip()


def _strip_separators(lines: list[str]) -> str:
    kept = [line for line in lines if line.strip() not in ("---", "***", "___")]
    return "\n".join(kept).strip()


def parse_one_line(text: str) -> tuple[str, str]:
    """从核心结论里拆出“一句话总结”，兼容 markdown 粗体、列表符号和标签独占一行的情况。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        plain = re.sub(r"^[\s>*+\-#]+", "", line)
        match = re.match(r"^(?:一句话总结|一句话结果)[\s*#]*[：:]\s*(.*)$", plain)
        if not match:
            continue
        same_line = re.sub(r"[\s*#]+$", "", match.group(1)).strip()
        if same_line:
            del lines[i]
            return _strip_separators(lines), plain_text(same_line)
        for j in range(i + 1, len(lines)):  # 标签独占一行，内容在下一行
            content = lines[j].strip()
            if not content or content in ("---", "***", "___"):
                continue
            del lines[i : j + 1]
            return _strip_separators(lines), plain_text(content)
        del lines[i]
        return _strip_separators(lines), ""
    return text.strip(), ""


def clean_findings(text: str) -> str:
    """去掉模型在核心结论前加的开场白、重复标题和分隔线。"""
    lines = text.strip().splitlines()
    while lines:
        plain = re.sub(r"^[\s>*+\-#]+|[\s*]+$", "", lines[0])
        if not plain:
            lines.pop(0)
            continue
        if CHATTER_RE.search(plain):
            lines.pop(0)
            continue
        break
    return _strip_separators(lines)


def split_marked(text: str) -> dict[str, str]:
    """按 ===正文总结=== 这类分隔标题切分模型输出，容错处理 ### 标题。"""
    matches = list(MARKER_RE.finditer(text))
    if not matches:raise ValueError('模型没有返回规定的分隔标题')
    out: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group('equals') or match.group('markdown')
        if name in out:raise ValueError('模型返回重复分隔标题：'+name)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip()
    return out


def validate_parts(parts, evidence, first):
    """Syntax and literal provenance are necessary, not scientific certification."""
    required=(first,'正文总结','详细解释','结果','一句话结果','原文依据')
    if any(not parts.get(key,'').strip() for key in required):
        raise ValueError('模型输出缺少必需部分或原文依据')
    quote=parts['原文依据'].strip()
    _,valid=verify_quotes(quote,evidence)
    if not valid:
        raise ValueError('原文依据不能在本次提供的证据中逐字核对')
    return quote



def check_parts(parts, evidence, first, provided=None):
    required=(first,'正文总结','详细解释','结果','一句话结果','原文依据')
    if any(not parts.get(key,'').strip() for key in required):
        raise ValueError('模型输出缺少必需部分或原文依据')
    quote=parts['原文依据'].strip()
    try:
        validate_parts(parts,evidence,first)
        if provided is not None:validate_parts(parts,provided,first)
        return quote,True
    except ValueError:
        return quote,False


# ---------------------------------------------------------------- 候选正文判定

CANDIDATE_LABELS = {
    "direct_result": "直接结果",
    "background": "背景",
    "interpretation": "作者解释",
    "irrelevant": "无关",
    "unclassified": "未判定",
}
LABEL_ALIASES = {
    "direct_result": "direct_result",
    "直接结果": "direct_result",
    "观测结果": "direct_result",
    "数据结果": "direct_result",
    "background": "background",
    "背景": "background",
    "背景信息": "background",
    "interpretation": "interpretation",
    "作者解释": "interpretation",
    "解释": "interpretation",
    "推断": "interpretation",
    "irrelevant": "irrelevant",
    "无关": "irrelevant",
    "不相关": "irrelevant",
}
EVIDENCE_ORDER = ["direct_result", "interpretation", "background", "unclassified"]
CLASSIFY_LINE_RE = re.compile(r"^C\s*(\d+)\s*[:：]\s*(direct[ _]result|作者解释|直接结果|观测结果|数据结果|背景信息|背景|background|interpretation|irrelevant|不相关|解释|推断|无关)\s*(?:[-—–:：]\s*)?(.*)$",re.I)


def candidate_text(candidates: list[dict]) -> str:
    """拼给判定步骤看：候选段落 + 页码/章节/来源 + 段内出现的图号表号。"""
    blocks = []
    for i, cand in enumerate(candidates, start=1):
        refs = cand.get("refs") or {}
        mentioned = []
        if refs.get("figures"):
            mentioned.append("Fig. " + ", ".join(str(n) for n in refs["figures"]))
        if refs.get("tables"):
            mentioned.append("Table " + ", ".join(str(n) for n in refs["tables"]))
        meta = f"C{i} [p.{cand['page']} · {cand['section']} · {cand['source']}"
        if mentioned:
            meta += " · 提到 " + "、".join(mentioned)
        meta += "]"
        blocks.append(f"{meta}\n{cand['text']}")
    return "\n\n".join(blocks)


def parse_classification(text: str, total: int) -> dict[int, tuple[str, str]]:
    result: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        match = CLASSIFY_LINE_RE.match(line.strip())
        if not match:
            if re.match(r'^C\s*\d+',line.strip(),re.I):raise ValueError('候选判定标签或格式不合法')
            continue
        index = int(match.group(1))
        if not 1 <= index <= total:
            raise ValueError('相关性判定候选编号越界')
        if index in result:raise ValueError('相关性判定含重复候选编号')
        raw = match.group(2).strip().replace(' ','_')
        label = LABEL_ALIASES.get(raw.lower()) or LABEL_ALIASES.get(raw)
        if not label:
            continue
        result[index] = (label, match.group(3).strip()[:100])
    return result


def apply_classification(candidates: list[dict], labels: dict[int, tuple[str, str]]) -> None:
    for i, cand in enumerate(candidates, start=1):
        label, reason = labels.get(i, ("unclassified", ""))
        cand["label"] = label
        cand["reason"] = reason


def evidence_text(candidates: list[dict]) -> str:
    """按判定结果分组拼证据；无关段落不进入解释步骤。"""
    groups: dict[str, list[dict]] = {}
    for cand in candidates:
        groups.setdefault(cand.get("label") or "unclassified", []).append(cand)
    lines: list[str] = []
    for label in EVIDENCE_ORDER:
        items = groups.get(label) or []
        if not items:
            continue
        lines.append(f"【{CANDIDATE_LABELS[label]}】")
        for cand in items:
            lines.append(f"[p.{cand['page']} · {cand['section']}] {cand['text']}")
        lines.append("")
    return "\n".join(lines).strip()


def classification_summary(candidates: list[dict]) -> str:
    if not candidates:
        return "没有候选正文段落"
    counts: dict[str, int] = {}
    for cand in candidates:
        key = cand.get("label") or "unclassified"
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{CANDIDATE_LABELS.get(key, key)} {value} 段" for key, value in counts.items()]
    text = f"候选 {len(candidates)} 段：" + "、".join(parts)
    if counts.get("irrelevant"):
        text += "；无关段落未进入解释证据"
    return text


def candidate_payload(candidates: list[dict]) -> list[dict]:
    return [
        {
            "index": cand["index"],
            "page": cand["page"],
            "section": cand["section"],
            "source": cand["source"],
            "refs": cand.get("refs") or {},
            "sentences": cand.get("sentences") or [],
            "label": cand.get("label") or "",
            "reason": cand.get("reason") or "",
            "text": cand["text"],
        }
        for cand in candidates
    ]


# ---------------------------------------------------------------- 证据整理


def _trim(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…（内容过长，已截断）"


COMMON_WORDS = {
    "the", "and", "with", "from", "for", "that", "this", "was", "were", "are", "not", "but", "its",
    "their", "which", "study", "figure", "figures", "table", "data", "result",
    "results", "shown", "using", "used", "during", "between", "after", "before", "respectively",
    "however", "these", "those", "such", "also", "can", "may", "has", "have", "been", "more", "than",
    "into", "when", "where", "while", "about", "above", "under", "over", "only", "both", "each", "same",
    "different", "higher", "lower", "value", "values",
}


def name_hints(*texts: str, limit: int = 24) -> str:
    """从 Caption / 正文里挑出可能出现在图例中的名字，供模型校正图例拼写。"""
    counts: dict[str, int] = {}
    for text in texts:
        for token in re.findall(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9\u0370-\u03ff\-]{2,24}", text or ""):
            lowered = token.lower()
            if lowered in COMMON_WORDS:
                continue
            if not (re.search(r"[A-Z]", token) or "-" in token or re.search(r"\d", token)):
                continue
            counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts, key=lambda token: (-counts[token], token))[:limit]
    return "、".join(ordered)


def _figure_card(paper: ParsedPaper, fig) -> FigureCard:
    return FigureCard(
        number=fig.number,
        label=fig.label,
        caption=fig.caption,
        candidates=candidate_payload(fig.candidates),
        sections=fig.sections_of_related,
        image_path=fig.image_path,
        caption_page=fig.caption_page + 1,
        crop_page=fig.crop_page + 1,
        crop_confidence=fig.crop_confidence,
        crop_note=fig.crop_note,
        note=fig.related_note,
    )


def _equation_card(paper: ParsedPaper, eq) -> EquationCard:
    return EquationCard(
        label=eq.group_label or eq.label,
        evidence_id=eq.evidence_id,
        numbers=list(eq.group_numbers or ([eq.number] if eq.number is not None else [])),
        members=[
            {
                "label": member["label"],
                "number": member["number"],
                "page": member["page"],
                "source_note": member["source_note"],
                "confidence": member["confidence"],
                "text": member["text"],
            }
            for member in (eq.members or [])
        ],
        equation_text=eq.text,
        source_geometry=getattr(eq,'source_geometry',{}),
        source_note=eq.source_note,
        image_path=eq.image_path,
        page=eq.page + 1,
        context=list(eq.context),
    )


def _equation_evidence(paper: ParsedPaper, eq_card: EquationCard) -> str:
    """公式上下文正文（只进提示词，不进资料卡展示）。"""
    lines = []
    for item in eq_card.context:
        index = item.get("index")
        if index is None or not 0 <= index < len(paper.paragraphs):
            continue
        lines.append(f"[p.{item['page']} · {item['section']} · {item['source']}] {paper.paragraphs[index].text}")
    from read.api import pdf_geometry__prompt_evidence as prompt_evidence
    geometry=prompt_evidence(eq_card.source_geometry)
    if geometry:lines.append(f'[p.{eq_card.page} · 原PDF几何候选，非正文引句]\n'+geometry)
    return "\n\n".join(lines)


_PIX2TEX_MODEL = None


def latex_from_image(image_path: str | Path | None) -> tuple[str, str]:
    """可选：用 pix2tex / LaTeX-OCR 把公式图转 LaTeX。失败不影响正文包。"""
    global _PIX2TEX_MODEL
    if not image_path or not Path(image_path).exists():
        return "", "没有公式图片，跳过 LaTeX 识别"
    try:
        from PIL import Image
        from pix2tex.cli import LatexOCR
    except Exception:
        return "", "未安装 pix2tex（可选；需要时 pip install pix2tex）"
    try:
        if _PIX2TEX_MODEL is None:
            _PIX2TEX_MODEL = LatexOCR()
        return str(_PIX2TEX_MODEL(Image.open(Path(image_path)))).strip(), "ok"
    except Exception as exc:
        return "", f"LaTeX 识别失败：{exc}"


def _meta(paper: ParsedPaper, client: "OllamaClient") -> dict:
    return {
        "pdf_path": paper.pdf_path,
        "page_count": paper.page_count,
        "model": client.model,
        "ollama_base_url": client.base_url,
        "sections": [s.name for s in paper.sections],
        "paragraph_count": len(paper.paragraphs),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _refresh_evidence(
    card: PaperCard, paper: ParsedPaper, client: "OllamaClient", only_figures: list[int] | None = None
) -> None:
    """重跑时用新的解析结果刷新证据，保留已有的解释文字。

    只刷新这次要重跑的对象，其他 Figure 的候选与判定结果保持不变，
    否则单张重试会把别的图已经判好的候选标签清空。
    """
    by_number = {fig.number: fig for fig in card.figures}
    for parsed_fig in paper.figures:
        target = by_number.get(parsed_fig.number)
        if target is None:
            card.figures.append(_figure_card(paper, parsed_fig))
            continue
        if only_figures is not None and parsed_fig.number not in only_figures:
            continue
        fresh = _figure_card(paper, parsed_fig)
        target.caption = fresh.caption
        same_candidates=[(c.get('index'),c.get('source')) for c in target.candidates]==[(c.get('index'),c.get('source')) for c in fresh.candidates]
        if not same_candidates:
            target.candidates=fresh.candidates
            target.classification_status='pending'
        # Matching source/input identity was checked by the caller.
        target.classify_note = ""
        target.sections = fresh.sections
        target.image_path = fresh.image_path
        target.caption_page = fresh.caption_page
        target.crop_page = fresh.crop_page
        target.crop_confidence = fresh.crop_confidence
        target.crop_note = fresh.crop_note
        target.note = fresh.note
    card.figures.sort(key=lambda fig: fig.number)
    if only_figures is None:
        found_numbers = {fig.number for fig in paper.figures}
        card.figures = [fig for fig in card.figures if fig.number in found_numbers]

    by_identity = {eq.evidence_id:eq for eq in card.equations if eq.evidence_id}
    by_label = {eq.label:eq for eq in card.equations if not eq.evidence_id}
    equations=[]
    for parsed_eq in paper.equations:
        if not parsed_eq.members:continue
        if any(eq.evidence_id==parsed_eq.evidence_id for eq in equations):continue
        fresh = _equation_card(paper, parsed_eq)
        target = by_identity.get(parsed_eq.evidence_id) or by_label.pop(parsed_eq.group_label or parsed_eq.label,None)
        if target is None:
            equations.append(fresh)
            continue
        equations.append(target)
        target.evidence_id=fresh.evidence_id
        target.label=fresh.label
        target.image_path=fresh.image_path
        target.page=fresh.page
        target.numbers=fresh.numbers
        target.members=fresh.members
        if target.status == "ok":
            continue
        target.equation_text = fresh.equation_text
        target.source_geometry = fresh.source_geometry
        target.source_note = fresh.source_note
        target.context = fresh.context
        target.image_path = fresh.image_path
        target.page = fresh.page
        # Preserve completed transcription and provisional generated fields on retry.
    card.equations=equations
    card.meta.update(_meta(paper, client))


def closing_text(paper,max_chars=None):
    """Use the actual closing section, preserving its original section name."""
    for name in ('Conclusion','Discussion and Conclusions','Summary','Discussion','Results and Discussion'):
        text=paper.section_text(name,max_chars)
        if text:return text
    for paragraph in reversed(paper.paragraphs):
        if paragraph.role=='body' and re.match(r'^(?:In conclusion\b|We conclude\b|To summari[sz]e\b|In summary\b)',paragraph.text,re.I):
            return paragraph.text[:max_chars] if max_chars else paragraph.text
    return ''


# ---------------------------------------------------------------- 分析流程


def analyze_paper(
    paper: ParsedPaper,
    config: dict | None = None,
    prompt_dir: Path | str = PROMPT_DIR,
    out_dir: str | Path | None = None,
    progress: ProgressCb | None = None,
    client: OllamaClient | None = None,
    only_figures: list[int] | None = None,
    base_card: PaperCard | None = None,
    checkpoint: Callable[[PaperCard], None] | None = None,
    renderer=None,transcriber=None,prompt_renderer=None,
) -> PaperCard:
    """把 ParsedPaper 变成 PaperCard。单个 Figure 失败不影响整篇。

    传入 base_card 时复用成功阶段，分别重试失败的元数据、Figure / Equation。
    没有阶段状态的旧机器卡片重新生成元数据；人工卡片保护由调用方执行。
    """
    config = config or load_config()
    client = client or OllamaClient(config)
    out_dir = Path(out_dir) if out_dir else PROJECT_ROOT / config["workspace_dir"]
    max_chars = int(config.get("max_context_chars", 12000))
    options=getattr(client,'options',config.get('ollama_options',{}))
    system=getattr(client,'system','')
    input_scopes=list(base_card.meta.get('input_budget_scope',[])) if base_card else []
    input_prompts={}
    renderer=renderer or render_figures
    transcriber=transcriber or latex_from_image
    render_prompt=prompt_renderer or _render_prompt
    from read.api import prompt_input__source_prompt as source_prompt
    def prompt(name,values,prompt_dir=prompt_dir,images=None):
        limit=input_limit(options,system,images)
        from read.api import prompt_input__PromptInput as PromptInput
        def render_fields(fields):
            result=render_prompt(name,fields,prompt_dir)
            return result if isinstance(result,PromptInput) else source_prompt(result,fields)
        rendered,trimmed=fit_fields(values,render_fields,limit)
        input_prompts[name]=rendered
        input_scopes.append({'stage':name,'estimated_tokens':estimate_tokens(rendered),'input_limit':limit,'truncated_fields':trimmed})
        return rendered
    def save():
        card.meta['input_budget_scope']=input_scopes
        card.meta['model_telemetry']=list(getattr(client,'telemetry',[]))
        if checkpoint:checkpoint(card)

    def propagate_schedule(exc):
        from core.api import model_schedule__ModelWindowClosed as ModelWindowClosed
        if isinstance(exc,ModelWindowClosed):
            save()
            raise exc

    def report(message: str) -> None:
        if progress:
            progress(message)

    if paper.figures or paper.equations:
        report("渲染 Figure / Equation 图片…")
        renderer(
            paper,
            out_dir,
            int(config.get("render_dpi", 150)),
            int(config.get("equation_render_dpi", 300)),
        )

    if base_card is not None:
        card = PaperCard.from_dict(base_card.to_dict())
        _refresh_evidence(card, paper, client, only_figures)
        # 重跑前清掉这些 Figure / Equation 的旧失败告警，避免历史噪声留在资料卡里
        targets = [f"{fig.label} 生成失败" for fig in card.figures]
        targets += [f"{eq.label} 生成失败" for eq in card.equations]
        targets += [f"{fig.label} 相关性判定失败" for fig in card.figures]
        card.warnings = [
            warning for warning in card.warnings if not any(warning.startswith(t) for t in targets)
        ]
    else:
        card = PaperCard(
            title=Path(paper.pdf_path).stem,
            figures=[_figure_card(paper, fig) for fig in paper.figures],
            equations=[_equation_card(paper, eq) for eq in paper.equations if eq.members],
            warnings=list(paper.warnings),
            meta=_meta(paper, client),
        )

    from read.api import generation_state__expected_coverage as expected_coverage
    card.meta['evidence_coverage']=expected_coverage(paper)
    first_pages="\n\n".join(f"[p.{i+1}]\n{text}" for i,text in enumerate(paper.page_texts[:2]))
    abstract=paper.section_text("Abstract")
    intro=paper.section_text("Introduction")
    conclusion=closing_text(paper)
    # Heading-free short reports still have real source paragraphs. Preserve
    # their scope explicitly rather than inventing named scientific sections.
    body=[p for p in paper.paragraphs if not p.is_caption and not p.is_heading and paper.section_of(p.index) not in ('References','Acknowledgments','Supplementary') and len(p.text)>80]
    scopes={"abstract":"原文摘要/引言前段落候选" if abstract else "未提取到摘要",
            "conclusion":next((s.name for s in reversed(paper.sections) if s.name in ("Conclusion","Discussion","Results and Discussion")),"原文无标题结尾总结段" if conclusion else "未提取到结尾章节")}
    if not intro and body:
        intro='\n\n'.join(f'[p.{p.page+1}] {p.text}' for p in body[:3])
        scopes['introduction']='正文开头段落（未识别到引言标题）'
    if not conclusion and body:
        conclusion='\n\n'.join(f'[p.{p.page+1}] {p.text}' for p in body[-3:])
        scopes['conclusion']='正文结尾段落（未识别到结论/讨论标题）'
    card.meta['metadata_source_scope']=scopes
    generation=card.meta.setdefault('generation',{})
    generation['schema_version']=GENERATION_SCHEMA_VERSION
    stages=generation.setdefault('stages',{})
    for name in METADATA_STAGES:stages.setdefault(name,{'state':'pending'})
    def completed(name):
        stages[name]={'state':'ok'}
        save()
    def failed(name,exc):
        stages[name]={'state':'failed','error':str(exc)[:1000]}
        save()
    # Remove only display warnings for metadata stages being retried.
    prefixes={'paper_info':'论文信息生成失败','key_findings':'核心结论生成失败',
              'introduction':'前言生成失败','conclusion':'结论生成失败'}
    card.warnings=[w for w in card.warnings if not any(w.startswith(prefixes[n]) for n in METADATA_STAGES if stages[n]['state']!='ok')]

    if stages['paper_info']['state']!='ok':
        # 1) 论文信息
        report("生成论文信息…")
        try:
            raw = client.chat(
                prompt(
                    "paper_info",
                    {"metadata": json.dumps(paper.metadata, ensure_ascii=False, indent=2), "first_pages": first_pages},
                    prompt_dir,
                )
            )
            card.info_raw = raw
            card.info = parse_info(raw)
            if not card.info:raise ValueError('模型未返回可解析的论文信息')
            card.title = card.info.get("标题") or card.title
            completed('paper_info')
        except Exception as exc:
            propagate_schedule(exc)
            card.info = {}
            card.info_raw = ""
            failed('paper_info',exc)
            card.warnings.append(f"论文信息生成失败：{exc}")

    if stages['key_findings']['state']!='ok':
        # 2) 核心结论
        report("生成核心结论…")
        try:
            body, one_line = parse_one_line(
                client.chat(
                    prompt(
                        "key_findings",
                        {
                            "abstract": abstract or "（未识别到 Abstract 章节）",
                            "introduction": intro or "（未识别到 Introduction 章节）",
                            "conclusion": conclusion or "（未识别到 Conclusion / Discussion 章节）",
                        },
                        prompt_dir,
                    )
                )
            )
            card.key_findings = clean_findings(body)
            card.one_line_summary = one_line
            if not card.key_findings.strip():raise ValueError('模型未返回核心结论')
            completed('key_findings')
        except Exception as exc:
            propagate_schedule(exc)
            failed('key_findings',exc)
            card.warnings.append(f"核心结论生成失败：{exc}")

    if stages['introduction']['state']!='ok':
        # 3) 前言与总结
        report("生成前言总结…")
        try:
            card.intro_summary = (
                client.chat(prompt("introduction", {"text": intro}, prompt_dir))
                if intro
                else ""
            )
            if intro and card.intro_summary.strip():completed('introduction')
            else:stages['introduction']={'state':'missing_source' if not intro else 'failed','error':'没有可总结的引言证据或模型响应为空'}
        except Exception as exc:
            propagate_schedule(exc)
            failed('introduction',exc)
            card.intro_summary = ""
            card.warnings.append(f'前言生成失败：{exc}')
    if stages['conclusion']['state']!='ok':
        report("生成结论总结…")
        try:
            card.conclusion_summary = (
                client.chat(prompt("conclusion", {"text": conclusion}, prompt_dir))
                if conclusion
                else ""
            )
            if conclusion and card.conclusion_summary.strip():completed('conclusion')
            else:stages['conclusion']={'state':'missing_source' if not conclusion else 'failed','error':'没有可总结的结论/讨论证据或模型响应为空'}
        except Exception as exc:
            propagate_schedule(exc)
            failed('conclusion',exc)
            card.conclusion_summary = ""
            card.warnings.append(f'结论生成失败：{exc}')
    card.meta['metadata_generation_ok']=metadata_complete(card.meta)
    save()

    # 4) 每张 Figure：先判定候选正文与这张图的关系，再生成解释
    total = len(card.figures)
    for index, fig_card in enumerate(card.figures, start=1):
        if only_figures is not None and fig_card.number not in only_figures:
            continue
        if not fig_card.image_path:
            fig_card.status='failed';fig_card.error='未取得图截图，原文保留等待重试'
            continue
        if fig_card.candidates and fig_card.classification_status!='ok':
            report(f"判定 {fig_card.label} 的候选正文（{index}/{total}）…")
            try:
                raw = client.chat(
                    prompt(
                        "classify",
                        {
                            "title": card.title,
                            "label": fig_card.label,
                            "caption": fig_card.caption,
                            "candidates": candidate_text(fig_card.candidates),
                        },
                        prompt_dir,
                    )
                )
                labels = parse_classification(raw, len(fig_card.candidates))
                apply_classification(fig_card.candidates, labels)
                fig_card.classification_status='ok' if len(labels)==len(fig_card.candidates) else 'failed'
                fig_card.classify_note = (
                    classification_summary(fig_card.candidates)
                    if labels
                    else "相关性判定没有返回可识别结果，已把全部候选段落交给解释步骤"
                )
            except Exception as exc:
                propagate_schedule(exc)
                fig_card.classification_status='failed'
                apply_classification(fig_card.candidates, {})
                fig_card.classify_note = f"相关性判定失败（{exc}），已把全部候选段落交给解释步骤"
        elif not fig_card.candidates:
            fig_card.classification_status='not_applicable'
            fig_card.classify_note = "没有候选正文段落"

        save()
        report(f"生成 {fig_card.label} 的解释（{index}/{total}）…")
        text=''
        try:
            text = client.chat(
                prompt(
                    "figure",
                    {
                        "title": card.title,
                        "label": fig_card.label,
                        "caption_page": fig_card.caption_page,
                        "sections": "、".join(fig_card.sections) or "未确定",
                        "caption": fig_card.caption,
                        "name_hints": name_hints(fig_card.caption, evidence_text(fig_card.candidates)),
                        "related_text": evidence_text(fig_card.candidates)
                        or "（没有找到引用这张图的正文段落）",
                    },
                    prompt_dir,images=[fig_card.image_path],
                ),
                images=[fig_card.image_path] if fig_card.image_path else None,
            )
            parts = split_marked(text)
            fig_card.raw_response=text
            fig_card.evidence_quote,quote_ok=check_parts(parts,'\n'.join(paper.page_texts),'图面信息',provided=getattr(input_prompts.get('figure'),'evidence',str(input_prompts.get('figure') or '')))
            fig_card.evidence_status='verified' if quote_ok else 'needs_review'
            fig_card.figure_info = parts.get("图面信息", "").replace("横称", "横轴")
            fig_card.summary = parts.get("正文总结", "")
            fig_card.detail = parts.get("详细解释", "")
            fig_card.result = parts.get("结果", "")
            fig_card.one_line = (
                plain_text(parts.get("一句话结果", "").splitlines()[0])
                if parts.get("一句话结果")
                else ""
            )
            fig_card.status = "ok" if quote_ok else "needs_review"
            fig_card.error = None if quote_ok else "原文依据不能在本次提供的证据中逐字核对；生成内容保留待核验"
            if not quote_ok:card.warnings.append(f"{fig_card.label} 原文依据待核验，当前解释不能视为已核实")
        except Exception as exc:
            propagate_schedule(exc)
            fig_card.raw_response=locals().get('text','')
            fig_card.status = "failed"
            fig_card.error = str(exc)
            card.warnings.append(f"{fig_card.label} 生成失败：{exc}")

        save()

    # 5) 公式：截图与上下文优先，AI 解释与 LaTeX 识别都是加分项
    if config.get("enable_equations", True):
        for eq_card in card.equations:
            if base_card is not None and eq_card.status == "ok" and eq_card.latex:
                continue
            if not eq_card.image_path:
                eq_card.status='failed';eq_card.error='未取得公式截图，原文与上下文保留等待重试'
                continue
            if not eq_card.latex:
                report(f"尝试识别 {eq_card.label} 的 LaTeX（可选）…")
                eq_card.latex, eq_card.latex_status = transcriber(eq_card.image_path)
                eq_card.latex_raw_response=getattr(transcriber,"last_raw_response","")
                save()
            if base_card is not None and eq_card.status=="ok":
                save()
                continue
            report(f"生成 {eq_card.label} 的解释…")
            members_text = "\n".join(
                f"{m['label']}（p.{m['page']}，{m['source_note']}，置信度 {m['confidence']}）：{m['text']}"
                for m in eq_card.members
            ) or "（没有成员信息）"
            try:
                text=''
                text = client.chat(
                    prompt(
                        "equation",
                        {
                            "title": card.title,
                            "label": eq_card.label,
                            "page": eq_card.page,
                            "count": len(eq_card.members) or 1,
                            "numbers": "、".join(f"({n})" for n in eq_card.numbers) or "无编号",
                            "members": members_text,
                            "source_note": eq_card.source_note or "未说明",
                            "equation_text": eq_card.equation_text or "（文字层没有可用内容）",
                            "latex": eq_card.latex or "（没有可用的 LaTeX）",
                            "related_text": _equation_evidence(paper, eq_card)
                            or "（没有找到公式附近的正文）",
                        },
                        prompt_dir,images=[eq_card.image_path],
                    ),
                    images=[eq_card.image_path] if eq_card.image_path else None,
                )
                parts = split_marked(text)
                eq_card.raw_response=text
                eq_card.evidence_quote,quote_ok=check_parts(parts,'\n'.join(paper.page_texts),'量清单',provided=getattr(input_prompts.get('equation'),'evidence',str(input_prompts.get('equation') or '')))
                eq_card.evidence_status='verified' if quote_ok else 'needs_review'
                eq_card.quantities = parts.get("量清单", "")
                eq_card.summary = parts.get("正文总结", "")
                eq_card.detail = parts.get("详细解释", "")
                eq_card.result = parts.get("结果", "")
                eq_card.one_line = (
                    plain_text(parts.get("一句话结果", "").splitlines()[0])
                    if parts.get("一句话结果")
                    else ""
                )
                eq_card.status = "ok" if quote_ok else "needs_review"
                eq_card.error = None if quote_ok else "原文依据不能在本次提供的证据中逐字核对；生成内容保留待核验"
                if not quote_ok:card.warnings.append(f"{eq_card.label} 原文依据待核验，当前解释不能视为已核实")
            except Exception as exc:
                propagate_schedule(exc)
                eq_card.raw_response=locals().get('text','')
                eq_card.status = "failed"
                eq_card.error = str(exc)
                card.warnings.append(f"{eq_card.label} 生成失败：{exc}")

            save()

    save()
    report("完成")
    return card
