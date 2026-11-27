"""导出：单张 Figure / Equation 的 figure.png + context.md，以及整篇 card.md。

导出的材料是给我之后手动上传网页版 ChatGPT 用的，所以保持纯文本 + 图片。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from core.api import paths__WorkspacePath as Path

from read.api import analyzer__CANDIDATE_LABELS as CANDIDATE_LABELS, analyzer__EquationCard as EquationCard, analyzer__FigureCard as FigureCard, analyzer__PaperCard as PaperCard

PROJECT_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 路径


def slugify(text: str, fallback: str = "paper") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_.")
    return (cleaned[:60] or fallback)


def workspace_root(config: dict) -> Path:
    root = Path(config.get("workspace_dir", "workspace"))
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root


def file_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def workspace_path(config: dict, key: str, name: str) -> Path:
    """同一篇 PDF 固定映射到同一个工作目录，方便重复查看。"""
    return workspace_root(config) / f"{slugify(name)}_{key}"


def find_workspace(config: dict, key: str) -> Path | None:
    root = workspace_root(config)
    if not root.exists():
        return None
    for path in sorted(root.iterdir(), reverse=True):
        if path.is_dir() and path.name.endswith(f"_{key}") and (path / "card.json").exists():
            return path
    return None


# ---------------------------------------------------------------- 单张图 / 公式


def _candidate_block(card: PaperCard, fig: FigureCard) -> str:
    """只记录判定结果（页码、标签、理由），不复制原文正文。"""
    if not fig.candidates:
        return fig.note or "（没有找到与这张图相关的候选正文段落）"
    lines = ["> 正文请看原文，这里只记录哪几段被判成与这张图相关。" if fig.candidates else ""]
    for cand in fig.candidates:
        label = CANDIDATE_LABELS.get(cand.get("label") or "unclassified", "未判定")
        refs = cand.get("refs") or {}
        extra = []
        if refs.get("figures"):
            extra.append("Fig. " + ", ".join(str(n) for n in refs["figures"]))
        if refs.get("tables"):
            extra.append("Table " + ", ".join(str(n) for n in refs["tables"]))
        head = f"- **[{label}]** p.{cand['page']} · {cand['section']} · {cand['source']}"
        if extra:
            head += " · 提到 " + "、".join(extra)
        lines.append(head)
        if cand.get("reason"):
            lines.append(f"  - 判定理由：{cand['reason']}")
    if fig.classify_note:
        lines.append(f"> {fig.classify_note}")
    if fig.note:
        lines.append(f"> {fig.note}")
    return "\n".join(lines).strip()


def figure_context_markdown(card: PaperCard, fig: FigureCard) -> str:
    lines = [
        f"# Paper",
        card.title,
        "",
        f"# Figure {fig.number}",
        "",
    ]
    lines += [
        "## Original Caption",
        "",
        fig.caption or "（未提取到 caption）",
        "",
        "## 图面信息（面板 / 坐标轴 / 物理量含义 / 图例）",
        "",
        fig.figure_info or "（未生成）",
        "",

        "## 正文总结",
        "",
        fig.summary or "（未生成）",
        "",
        "## 详细解释",
        "",
        fig.detail or "（未生成）",
        "",
        "## 结果",
        "",
        fig.result or "（未生成）",
        "",
        "## 一句话结果",
        "",
        fig.one_line or "（未生成）",
        "",
    ]
    if fig.status != "ok":
        lines += ["## 处理状态", "", f"{fig.status}：{fig.error or fig.crop_note or '未完成'}", ""]
    return "\n".join(lines)


def _equation_pointer_block(eq: EquationCard) -> str:
    """公式上下文只给位置指针，不复制原文。"""
    if not eq.context:
        return "（没有找到公式附近的正文）"
    lines = ["> 正文请看原文，这里只记录位置。"]
    for item in eq.context:
        lines.append(f"- {item['source']}｜p.{item['page']} · {item['section']}")
    return "\n".join(lines)


def equation_context_markdown(card: PaperCard, eq: EquationCard) -> str:
    lines = [
        "# Paper",
        card.title,
        "",
        f"# Equation {eq.label}",
        "",
        "## 编号与位置",
        "",
        f"- 组标签：{eq.label}（共 {len(eq.members) or 1} 条公式，第 p.{eq.page} 页）",
        f"- 编号：{'、'.join(f'({n})' for n in eq.numbers) or '无编号（自动识别）'}",
        f"- 图片：{eq.folder_name}/equation.png（从 PDF 页面裁切，公式以此为准）",
        "- 组内公式：" + "；".join(
            f"{m['label']} p.{m['page']}（{m['source_note']}，{'带编号' if m.get('confidence') == 'high' else '无编号自动识别'}）"
            for m in eq.members
        ),
        "",
        "## 机器识别的 LaTeX（可选，可能不准）",
        "",
        eq.latex or f"（{eq.latex_status or '没有 LaTeX'}）",
        "",

        "## 量清单（符号 / 含义）",
        "",
        eq.quantities or "（未生成）",
        "",
        "## 正文总结",
        "",
        eq.summary or "（未生成）",
        "",
        "## 详细解释",
        "",
        eq.detail or "（未生成）",
        "",
        "## 结果",
        "",
        eq.result or "（未生成）",
        "",
        "## 一句话结果",
        "",
        eq.one_line or "（未生成）",
        "",
    ]
    if eq.status != "ok":
        lines += ["## 解释状态", "", f"{eq.status}：{eq.error or '未完成'}（截图与上下文仍有效）", ""]
    return "\n".join(lines)


def export_figure_pack(card: PaperCard, fig: FigureCard, root: str | Path) -> Path:
    folder = Path(root) / fig.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "figure.png"
    if fig.image_path and Path(fig.image_path).exists() and Path(fig.image_path).resolve() != target.resolve():
        shutil.copyfile(Path(fig.image_path), target)
    (folder / "context.md").write_text(figure_context_markdown(card, fig), encoding="utf-8")
    return folder


def export_equation_pack(card: PaperCard, eq: EquationCard, root: str | Path) -> Path:
    folder = Path(root) / eq.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "equation.png"
    if eq.image_path and Path(eq.image_path).exists() and Path(eq.image_path).resolve() != target.resolve():
        shutil.copyfile(Path(eq.image_path), target)
    (folder / "context.md").write_text(equation_context_markdown(card, eq), encoding="utf-8")
    return folder


# ---------------------------------------------------------------- 整篇 card.md


def _info_block(card: PaperCard) -> str:
    if card.info:
        return "\n".join(f"- **{key}**：{value}" for key, value in card.info.items())
    return card.info_raw.strip() or "（未生成论文信息）"


def card_markdown(card: PaperCard) -> str:
    blocks: list[str] = [f"# {card.title}", ""]
    if card.meta:
        blocks += [
            f"> 来源：{card.meta.get('pdf_path', '')}｜模型：{card.meta.get('model', '')}｜生成时间：{card.meta.get('generated_at', '')}",
            "",
        ]

    blocks += ["## 1. 论文信息", "", _info_block(card), ""]
    if card.info_raw and not card.info:
        blocks += ["原始输出：", "", card.info_raw, ""]

    blocks += ["## 2. 核心结论", "", card.key_findings or "（未生成）", ""]
    if card.one_line_summary:
        blocks += ["**一句话总结**：" + card.one_line_summary, ""]

    blocks += [
        "## 3. 前言与总结",
        "",
        "### 前言",
        "",
        card.intro_summary or "（未生成）",
        "",
        "### 结论 / 讨论",
        "",
        card.conclusion_summary or "（未生成）",
        "",
    ]

    blocks += ["## 4. Figure / Equation 正文包", ""]
    items=[('figure',i,f) for i,f in enumerate(card.figures)]+[('equation',i,e) for i,e in enumerate(card.equations)]
    order={(r['kind'],r['index']):i for i,r in enumerate(card.meta.get('reading_order',[]))}
    items.sort(key=lambda item: (order.get((item[0],item[1]),10**6) if order else
        (item[2].crop_page if item[0]=='figure' else item[2].page)*1000+item[1]))
    for kind,index,item in items:
        if kind=='figure':
            fig=item
            blocks += [f"### {fig.heading}", ""]
            if fig.image_path:
                image_rel = Path(fig.image_path).name
                blocks += [f"![{fig.label}]({fig.folder_name}/{image_rel})", ""]
            blocks += [
                f"**Caption（原文）**",
                "",
                fig.caption or "（未提取到 caption）",
                "",
                f"**图面信息（面板 / 坐标轴 / 物理量含义 / 图例）**",
                "",
                fig.figure_info or "（未生成）",
                "",

                f"**正文总结**",
                "",
                fig.summary or "（未生成）",
                "",
                f"**详细解释**",
                "",
                fig.detail or "（未生成）",
                "",
                f"**结果**",
                "",
                fig.result or "（未生成）",
                "",
                f"**一句话结果**",
                "",
                fig.one_line or "（未生成）",
                "",
            ]
            if fig.crop_confidence != "high" and fig.crop_note:
                blocks += [f"> 裁切提示（{fig.crop_confidence}）：{fig.crop_note}", ""]
            if fig.status != "ok":
                blocks += [f"> 处理状态：{fig.status}（{fig.error or '未完成'}）", ""]
        else:
            eq=item
            blocks += [
                f"### {eq.heading}",
                "",
                f"- 组标签 {eq.label}｜{len(eq.members) or 1} 条公式｜p.{eq.page}",
                f"- 编号：{'、'.join(f'({n})' for n in eq.numbers) or '无编号（自动识别）'}",
                f"- 图片：{eq.folder_name}/equation.png（公式以此为准）",
                "- 组内公式：" + "；".join(
                    f"{m['label']} p.{m['page']}（{m['source_note']}）" for m in eq.members
                ),
                "",
                "**正文总结**",
                "",
                eq.summary or "（未生成）",
                "",
                "**详细解释（含公式之间关系）**",
                "",
                eq.detail or "（未生成）",
                "",
                "**结果**",
                "",
                eq.result or "（未生成）",
                "",
                "**量清单（符号 / 含义）**",
                "",
                eq.quantities or "（未生成）",
                "",

                "**机器识别的 LaTeX（可选，可能不准）**",
                "",
                eq.latex or f"（{eq.latex_status or '没有 LaTeX'}）",
                "",
            ]
            if eq.status != "ok":
                blocks += [f"> 解释状态：{eq.status}（{eq.error or '未完成'}），截图与上下文仍有效", ""]

    if card.warnings:
        blocks += ["## 处理过程中的提示", ""] + [f"- {item}" for item in card.warnings] + [""]

    return "\n".join(blocks).rstrip() + "\n"


def export_card(card: PaperCard, root: str | Path) -> dict[str, str]:
    """写出 card.md 与 card.json，并把每张 Figure / Equation 导出成小包。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    from read.api import atomic_io__atomic_json as atomic_json, atomic_io__atomic_text as atomic_text
    atomic_text(root/"card.md",card_markdown(card))
    atomic_json(root/"card.json",card.to_dict())
    for fig in card.figures:
        export_figure_pack(card, fig, root)
    for eq in card.equations:
        export_equation_pack(card, eq, root)
    return {"card_md": str(root / "card.md"), "card_json": str(root / "card.json")}


def load_card(root: str | Path) -> PaperCard | None:
    path = Path(root) / "card.json"
    if not path.exists():
        return None
    card = PaperCard.from_dict(json.loads(path.read_text(encoding="utf-8")))
    # 图片以工作目录内的文件为准：项目或工作目录被搬动过时，card.json 里的旧绝对路径会失效
    for fig in card.figures:
        candidate = Path(root) / fig.folder_name / "figure.png"
        if candidate.exists():
            fig.image_path = str(candidate)
    for eq in card.equations:
        candidate = Path(root) / eq.folder_name / "equation.png"
        if candidate.exists():
            eq.image_path = str(candidate)
    return card
