# PDF解析与证据引擎

PDF文本、图/式/表候选、整页渲染、逐字引文、条件/符号证据、上下文预算、原子保存与已守卫的旧卡片合同支持。

这是独立源码与接口文件夹，正式包名为 `read`。跨项目只调用 `read.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

删除Streamlit旧UI及其启动/配置入口，保留当前read.app解析与证据模块，因为cards/reading/review仍调用。旧模型运输必须经core的禁用/暂停和租约守卫；不因库被导入启动模型。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from read.api import parser__parse_pdf
```

运行依赖：[core](https://github.com/xylograph-xg/paper/blob/main/infrastructure/core/README.md)。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project read
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [tool-dependencies.json](https://github.com/xylograph-xg/paper/blob/main/workbench/read/tool-dependencies.json) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [AGENTS.md](https://github.com/xylograph-xg/paper/blob/main/workbench/read/AGENTS.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/tags.py](app/tags.py) | 文献库的 tag：论文关键词（只读，来自卡片）+ 自己打的 tag（可编辑，存小 JSON）。 | `tags_path`、`clean_tag`、`split_keywords`、`load_tags`、`save_tags` | 旧 Streamlit 入口遗留；当前无生产调用方，保留待退役/人工脚本核对。 |
| [app/requirements.txt](app/requirements.txt) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/render.py](app/render.py) | 资料卡渲染：浏览页与处理页共用。 | `render_figure`、`render_equation`、`render_card` | 旧 Streamlit 入口遗留；当前无生产调用方，保留待退役/人工脚本核对。 |
| [app/pdf_geometry.py](app/pdf_geometry.py) | Original PDF glyph evidence through pdfplumber; no OCR/model inference. | `_fraction_candidates`、`_script_candidates`、`extract_regions`、`extract_bounded`、`prepare_geometry`、`prompt_evidence` | 当前公开接口或生产链使用；避免复制实现 |
| [app/config.json](app/config.json) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/exporter.py](app/exporter.py) | 导出：单张 Figure / Equation 的 figure.png + context.md，以及整篇 card.md。 | `slugify`、`workspace_root`、`file_key`、`workspace_path`、`find_workspace`、`_candidate_block`、`figure_context_markdown`、`_equation_pointer_block`、`equation_context_markdown`、`export_figure_pack`、`export_equation_pack`、`_info_block`、`card_markdown`、`export_card`、`load_card` | 当前公开接口或生产链使用；避免复制实现 |
| [app/requirements-mac-studio.lock.txt](app/requirements-mac-studio.lock.txt) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/analyzer.py](app/analyzer.py) | 资料卡生成：调用 Ollama 本地模型解释 parser.py 定位到的证据。 | `load_config`、`_load_prompt`、`_render_prompt`、`OllamaError[]`、`OllamaClient[__init__, health, chat]`、`FigureCard[folder_name, heading]`、`EquationCard[folder_name, heading, unnumbered]`、`PaperCard[to_dict, from_dict]`、`_canonical_info_key`、`parse_info`、`plain_text`、`_strip_separators`、`parse_one_line`、`clean_findings`、`split_marked`、`validate_parts`、`check_parts`、`candidate_text`、`parse_classification`、`apply_classification`、`evidence_text`、`classification_summary`、`candidate_payload`、`_trim`、`name_hints`、`_figure_card`、`_equation_card`、`_equation_evidence`、`latex_from_image`、`_meta`、`_refresh_evidence`、`closing_text`、`analyze_paper` | 当前公开接口或生产链使用；避免复制实现 |
| [app/context_budget.py](app/context_budget.py) | Conservative token estimates, not byte counts or an exact model tokenizer. | `estimate_tokens`、`image_tokens`、`input_limit`、`trim_tokens`、`fit_fields` | 当前公开接口或生产链使用；避免复制实现 |
| [app/evidence_identity.py](app/evidence_identity.py) | Shared paths for parsed evidence and generated cards (pages are one-based). | `equation_identity`、`equation_folder` | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompt_input.py](app/prompt_input.py) | A rendered prompt retains the exact evidence fields used to render it. | `PromptInput[__new__]`、`source_prompt` | 当前公开接口或生产链使用；避免复制实现 |
| [app/parser.py](app/parser.py) | PDF 解析：正文段落、章节、Figure caption 与引用段落、裁切区域、公式候选。 | `Paragraph[cite]`、`Section[text_span]`、`Figure[folder_name]`、`Equation[folder_name, evidence_id]`、`ParsedPaper[paragraph_text, section_of, section_at, section_text, full_text, to_dict]`、`_line_text`、`_join_lines`、`_iter_blocks`、`_normalise`、`_drop_headers_footers`、`_columns`、`_column_index`、`_looks_like_table_row`、`_reading_order`、`_body_font_size`、`_detect_sections`、`_looks_like_caption`、`_extract_caption`、`_graphics_boxes`、`_intersects`、`_overlap_ratio`、`_cluster_boxes`、`_figure_region_from_graphics`、`_clip`、`_region_has_graphics`、`_choose_crop`、`_find_figures`、`_numbers_after`、`collect_refs`、`collect_figure_refs`、`_ref_sentences`、`_collect_candidates`、`_is_display_equation_text`、`_blocks_left_of`、`_union_bbox`、`_find_display_equations`、`equation_number`、`equation_sort_key`、`_equation_refs`、`_group_label`、`_paragraphs_between`、`_group_equations`、`_attach_equation_context`、`render_region`、`render_page_image`、`parse_pdf`、`render_figures`、`prepare_evidence`、`prepare_pdf` | 当前公开接口或生产链使用；避免复制实现 |
| [app/ollama_transport.py](app/ollama_transport.py) | Guard every local request, including the standalone reader, across midnight. | `chat` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [app/evidence_preparation.py](app/evidence_preparation.py) | Generic PDF section, caption, and equation evidence recovery. | `line_text`、`heading_name`、`union`、`repair_sections`、`recover_split_figures`、`normalized_number`、`recover_caption_text`、`recover_numbered_equations`、`definition_tokens`、`source_definitions`、`include_adjacent_definitions`、`equation_gaps`、`line_text_for_caption`、`extend_split_caption_lines`、`expand_unnumbered_relation_lines`、`complete_column_captions`、`filter_equation_candidates` | 当前公开接口或生产链使用；避免复制实现 |
| [app/evidence_literal.py](app/evidence_literal.py) | Shared literal evidence normalization and matching for screening and reading. | `canonical`、`literal_match` | 当前公开接口或生产链使用；避免复制实现 |
| [app/evidence_quotes.py](app/evidence_quotes.py) | Literal source checks with presentation wrappers only, no fuzzy science repair. | `unwrap`、`verify_quotes` | 当前公开接口或生产链使用；避免复制实现 |
| [app/atomic_io.py](app/atomic_io.py) | Durable local artifact writes; replace never exposes partial JSON. | `atomic_text`、`atomic_json` | 当前公开接口或生产链使用；避免复制实现 |
| [app/generation_state.py](app/generation_state.py) | Machine-readable completion of reader stages, independent of warning prose. | `metadata_complete`、`generation_complete`、`expected_coverage` | 当前公开接口或生产链使用；避免复制实现 |
| [scripts/ollama_env.sh](scripts/ollama_env.sh) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/conclusion.md](app/prompts/conclusion.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/paper_info.md](app/prompts/paper_info.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/key_findings.md](app/prompts/key_findings.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/introduction.md](app/prompts/introduction.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/system.md](app/prompts/system.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/figure.md](app/prompts/figure.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/classify.md](app/prompts/classify.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/domain_oled.md](app/prompts/domain_oled.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [app/prompts/equation.md](app/prompts/equation.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [tests/test_source_contract.py](tests/test_source_contract.py)：独立合成PDF页码/数值条件、原文与发送证据双重引文匹配、禁止部分引文通过、提示证据隔离测试；无模型调用。
- [tests/__init__.py](tests/__init__.py)：独立测试发现入口。

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

PDF/图片/本地输出；旧模型路径只在显式调用且守卫允许时运行，当前不允许。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](https://github.com/xylograph-xg/paper/blob/main/infrastructure/config/README.md)，共享状态合同见 [data](https://github.com/xylograph-xg/paper/blob/main/infrastructure/data-contract/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](https://github.com/xylograph-xg/paper/blob/main/reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 几何worker部署合同（2026-10-14）

`app/pdf_geometry.py`默认使用当前Python；`PAPER_PDF_GEOMETRY_PYTHON`优先于传入`pdf_geometry.python`。宿主需按`requirements-pdf-geometry.txt`安装锁定依赖；本机`app/config.json`显式绑定已核对的现存解析环境，不在源码中拼接个人缓存目录。缺失/版本不符仍返回unavailable、保留原文本与警告。测试fixture显式读取本机解析配置，缺失worker用例独立覆盖错误回退。打包包含几何依赖清单；reading同样包含科学依赖清单。
