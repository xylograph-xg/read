"""资料卡渲染：浏览页与处理页共用。

只读 card.json / 图片文件，不使用 Ollama、不解析 PDF。
"""

from __future__ import annotations

import json
import sys
from core.api import paths__WorkspacePath as Path
_repo_root=str(Path(__file__).resolve().parents[2])
if _repo_root not in sys.path:sys.path.insert(0,_repo_root)
from typing import Callable

HERE = Path(__file__).resolve().parent
for candidate in (HERE, HERE.parent):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import streamlit as st

from read.api import analyzer as ana
from read.api import exporter as exp

RetryHook = Callable[[list[int] | None], None] | None


def render_figure(
    card: ana.PaperCard,
    fig: ana.FigureCard,
    workspace: Path,
    retry: RetryHook = None,
) -> None:
    image_path = Path(fig.image_path) if fig.image_path else workspace / fig.folder_name / "figure.png"
    if image_path.exists():
        st.image(str(image_path), caption=f"{fig.label}（裁切自 p.{fig.crop_page}）", width="stretch")
    else:
        st.warning("没有可用的图片文件，自动裁切失败。")
    if fig.crop_confidence != "high":
        st.caption(f"裁切置信度 {fig.crop_confidence}：{fig.crop_note}")

    st.markdown("**Caption（原文）**")
    st.write(fig.caption or "（未提取到 caption）")

    st.markdown("**图面信息（面板 / 坐标轴 / 物理量含义 / 图例）**")
    st.write(fig.figure_info or "（未生成）")

    st.markdown("**正文总结**")
    st.write(fig.summary or "（未生成）")
    st.markdown("**详细解释**")
    st.write(fig.detail or "（未生成）")
    st.markdown("**结果**")
    st.write(fig.result or "（未生成）")
    st.markdown("**一句话结果**")
    st.write(fig.one_line or "（未生成）")

    st.markdown("**相关正文判定**")
    if fig.candidates:
        st.caption("正文请看原文；这里只记录哪几段被判成与这张图相关，以及判定理由。")
        if fig.classify_note:
            st.caption(fig.classify_note)
        if fig.note:
            st.caption(fig.note)
        for cand in fig.candidates:
            label = ana.CANDIDATE_LABELS.get(cand.get("label") or "unclassified", "未判定")
            refs = cand.get("refs") or {}
            extra = []
            if refs.get("figures"):
                extra.append("Fig. " + ", ".join(str(n) for n in refs["figures"]))
            if refs.get("tables"):
                extra.append("Table " + ", ".join(str(n) for n in refs["tables"]))
            head = f"**[{label}]** p.{cand['page']} · {cand['section']} · {cand['source']}"
            if extra:
                head += " · 提到 " + "、".join(extra)
            st.markdown(head)
            if cand.get("reason"):
                st.caption(f"判定理由：{cand['reason']}")
    else:
        st.write(fig.note or "没有找到与这张图相关的候选正文段落。")

    if fig.status != "ok":
        st.error(f"处理状态：{fig.status}（{fig.error or '未完成'}）")
        if retry is not None and (workspace / "source.pdf").exists():
            if st.button(f"重新生成 {fig.label}", key=f"retry_{fig.folder_name}"):
                retry([fig.number])

    context = exp.figure_context_markdown(card, fig)
    col1, col2 = st.columns(2)
    with col1:
        if image_path.exists():
            st.download_button(
                f"下载 {fig.folder_name}/figure.png",
                data=image_path.read_bytes(),
                file_name=f"{fig.folder_name}_figure.png",
                mime="image/png",
                key=f"png_{fig.folder_name}",
            )
    with col2:
        st.download_button(
            f"下载 {fig.folder_name}/context.md",
            data=context.encode("utf-8"),
            file_name=f"{fig.folder_name}_context.md",
            mime="text/markdown",
            key=f"md_{fig.folder_name}",
        )


def render_equation(
    card: ana.PaperCard,
    eq: ana.EquationCard,
    workspace: Path,
    widget_index: int = 0,
) -> None:
    with st.expander(eq.heading, expanded=False):
        image_path = Path(eq.image_path) if eq.image_path else workspace / eq.folder_name / "equation.png"
        if image_path.exists():
            st.image(str(image_path), caption=f"{eq.label}（截自 p.{eq.page}，300 dpi）", width="stretch")
        else:
            st.warning("没有公式组截图，自动裁切失败。")
        note = f"{eq.label}｜{len(eq.members)} 条公式｜p.{eq.page}"
        if eq.unnumbered:
            note += "｜含无编号公式（自动识别）"
        st.caption(note)
        st.markdown("**组内公式**")
        for member in eq.members:
            marker = "带编号" if member.get("confidence") == "high" else "无编号（自动识别）"
            st.markdown(f"- {member['label']}｜p.{member['page']}｜{member['source_note']}（{marker}）")
        st.markdown("**组上下文位置**")
        if eq.context:
            for item in eq.context:
                st.markdown(f"- {item['source']}｜p.{item['page']} · {item['section']}")
        else:
            st.write("没有找到公式附近的正文。")
        st.markdown("**量清单（符号 / 含义）**")
        st.write(eq.quantities or "（未生成）")
        st.markdown("**正文总结**")
        st.write(eq.summary or "（未生成）")
        st.markdown("**详细解释（含公式之间关系）**")
        st.write(eq.detail or "（未生成）")
        st.markdown("**结果**")
        st.write(eq.result or "（未生成）")
        if eq.status != "ok":
            st.error(f"解释状态：{eq.status}（{eq.error or '未完成'}）")
        st.markdown("**机器识别的 LaTeX（可选，可能不准）**")
        if eq.latex:
            st.code(eq.latex, language="latex")
        st.caption(eq.latex_status or "没有 LaTeX")
        st.download_button(
            f"下载 {eq.folder_name}/context.md",
            data=exp.equation_context_markdown(card, eq).encode("utf-8"),
            file_name=f"{eq.folder_name}_context.md",
            mime="text/markdown",
            key=f"md_equation_{eq.folder_name}_{widget_index}",
        )


def render_card(
    card: ana.PaperCard,
    workspace: Path,
    retry: RetryHook = None,
    show_source: bool = True,
) -> None:
    st.title(card.title or "（未识别标题）")
    if show_source:
        st.caption(
            f"{card.meta.get('pdf_path', '')} ｜ 模型 {card.meta.get('model', '')} ｜ "
            f"生成于 {card.meta.get('generated_at', '')} ｜ 工作目录 {workspace}"
        )
    for warning in card.warnings:
        st.warning(warning)

    if retry is not None:
        failed_figures = [fig.number for fig in card.figures if fig.status != "ok"]
        failed_equations = [eq.label for eq in card.equations if eq.status != "ok"]
        if (failed_figures or failed_equations) and (workspace / "source.pdf").exists():
            if st.button(f"重试失败项（{len(failed_figures)} 张图、{len(failed_equations)} 个公式）"):
                retry(failed_figures)

    with st.expander("1. 论文信息", expanded=True):
        if card.info:
            st.markdown("\n".join(f"- **{k}**：{v}" for k, v in card.info.items()))
        else:
            st.write(card.info_raw or "（未生成论文信息）")

    with st.expander("2. 核心结论", expanded=True):
        st.write(card.key_findings or "（未生成）")
        if card.one_line_summary:
            st.info(f"一句话总结：{card.one_line_summary}")

    with st.expander("3. 前言与总结", expanded=True):
        st.markdown("**前言**")
        st.write(card.intro_summary or "（未生成）")
        st.markdown("**结论 / 讨论**")
        st.write(card.conclusion_summary or "（未生成）")

    st.header("4. Figure / Equation")
    st.caption("每张 Figure 默认折叠，标题即为一句话结果；展开可查看原图、图面信息、解释与结果。")
    if not card.figures:
        st.write("没有识别到 Figure。")
    for fig in card.figures:
        with st.expander(fig.heading, expanded=False):
            render_figure(card, fig, workspace, retry=retry)

    ok_equations = [eq for eq in card.equations if eq.status == "ok"]
    failed_equations = [eq for eq in card.equations if eq.status != "ok"]
    if ok_equations:
        st.subheader("Equation")
        for widget_index, eq in enumerate(ok_equations):
            render_equation(card, eq, workspace, widget_index=widget_index)
    if failed_equations:
        st.caption(
            "公式解释未完成："
            + "、".join(eq.label for eq in failed_equations)
            + "（截图与上下文仍可用）"
        )

    st.divider()
    card_md = exp.card_markdown(card)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "下载 card.md（全文资料卡）",
            data=card_md.encode("utf-8"),
            file_name="card.md",
            mime="text/markdown",
        )
    with col2:
        st.download_button(
            "下载 card.json（含全部证据）",
            data=json.dumps(card.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="card.json",
            mime="application/json",
        )
