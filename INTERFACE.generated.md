# read：自动接口快照

由全局更新生成；仅记录当前源码结构，不承诺业务语义或运行验收。默认参数值以源码/人工工具卡为准。列出的文件级函数也可能是内部实现，不自动成为公共 API。

权威目录：`read`

## 相对已审查基线的变化

无源码变化。

## Python 声明

- `load_config(path=…)` — [app/analyzer.py:38](read/app/analyzer.py#L38)
- `OllamaClient.__init__(self, config)` — [app/analyzer.py:73](read/app/analyzer.py#L73)
- `OllamaClient.health(self)` — [app/analyzer.py:87](read/app/analyzer.py#L87)
- `OllamaClient.chat(self, user_prompt, images=…, retries=…)` — [app/analyzer.py:98](read/app/analyzer.py#L98)
- `FigureCard.folder_name(self)` — [app/analyzer.py:186](read/app/analyzer.py#L186)
- `FigureCard.heading(self)` — [app/analyzer.py:190](read/app/analyzer.py#L190)
- `EquationCard.folder_name(self)` — [app/analyzer.py:223](read/app/analyzer.py#L223)
- `EquationCard.heading(self)` — [app/analyzer.py:227](read/app/analyzer.py#L227)
- `EquationCard.unnumbered(self)` — [app/analyzer.py:233](read/app/analyzer.py#L233)
- `PaperCard.to_dict(self)` — [app/analyzer.py:251](read/app/analyzer.py#L251)
- `PaperCard.from_dict(cls, data)` — [app/analyzer.py:255](read/app/analyzer.py#L255)
- `parse_info(text)` — [app/analyzer.py:291](read/app/analyzer.py#L291)
- `plain_text(text)` — [app/analyzer.py:321](read/app/analyzer.py#L321)
- `parse_one_line(text)` — [app/analyzer.py:331](read/app/analyzer.py#L331)
- `clean_findings(text)` — [app/analyzer.py:354](read/app/analyzer.py#L354)
- `split_marked(text)` — [app/analyzer.py:369](read/app/analyzer.py#L369)
- `validate_parts(parts, evidence, first)` — [app/analyzer.py:383](read/app/analyzer.py#L383)
- `check_parts(parts, evidence, first, provided=…)` — [app/analyzer.py:396](read/app/analyzer.py#L396)
- `candidate_text(candidates)` — [app/analyzer.py:438](read/app/analyzer.py#L438)
- `parse_classification(text, total)` — [app/analyzer.py:456](read/app/analyzer.py#L456)
- `apply_classification(candidates, labels)` — [app/analyzer.py:475](read/app/analyzer.py#L475)
- `evidence_text(candidates)` — [app/analyzer.py:482](read/app/analyzer.py#L482)
- `classification_summary(candidates)` — [app/analyzer.py:499](read/app/analyzer.py#L499)
- `candidate_payload(candidates)` — [app/analyzer.py:513](read/app/analyzer.py#L513)
- `name_hints(*texts, limit=…)` — [app/analyzer.py:550](read/app/analyzer.py#L550)
- `latex_from_image(image_path)` — [app/analyzer.py:623](read/app/analyzer.py#L623)
- `closing_text(paper, max_chars=…)` — [app/analyzer.py:720](read/app/analyzer.py#L720)
- `analyze_paper(paper, config=…, prompt_dir=…, out_dir=…, progress=…, client=…, only_figures=…, base_card=…, checkpoint=…, renderer=…, transcriber=…, prompt_renderer=…)` — [app/analyzer.py:734](read/app/analyzer.py#L734)
- `atomic_text(path, text, durable=…)` — [app/atomic_io.py:5](read/app/atomic_io.py#L5)
- `atomic_json(path, value, durable=…)` — [app/atomic_io.py:20](read/app/atomic_io.py#L20)
- `estimate_tokens(text)` — [app/context_budget.py:10](read/app/context_budget.py#L10)
- `image_tokens(paths)` — [app/context_budget.py:17](read/app/context_budget.py#L17)
- `input_limit(options, system=…, images=…)` — [app/context_budget.py:31](read/app/context_budget.py#L31)
- `trim_tokens(text, limit, marker=…)` — [app/context_budget.py:35](read/app/context_budget.py#L35)
- `fit_fields(values, render, limit)` — [app/context_budget.py:45](read/app/context_budget.py#L45)
- `equation_identity(page, bbox)` — [app/evidence_identity.py:6](read/app/evidence_identity.py#L6)
- `equation_folder(number, page, identity=…)` — [app/evidence_identity.py:11](read/app/evidence_identity.py#L11)
- `canonical(text)` — [app/evidence_literal.py:5](read/app/evidence_literal.py#L5)
- `literal_match(quote, evidence, *, case_sensitive=…)` — [app/evidence_literal.py:11](read/app/evidence_literal.py#L11)
- `line_text(line)` — [app/evidence_preparation.py:13](read/app/evidence_preparation.py#L13)
- `heading_name(text)` — [app/evidence_preparation.py:17](read/app/evidence_preparation.py#L17)
- `union(boxes)` — [app/evidence_preparation.py:37](read/app/evidence_preparation.py#L37)
- `repair_sections(parsed, reader)` — [app/evidence_preparation.py:42](read/app/evidence_preparation.py#L42)
- `recover_split_figures(parsed, reader)` — [app/evidence_preparation.py:121](read/app/evidence_preparation.py#L121)
- `normalized_number(text)` — [app/evidence_preparation.py:170](read/app/evidence_preparation.py#L170)
- `recover_caption_text(parsed, reader)` — [app/evidence_preparation.py:178](read/app/evidence_preparation.py#L178)
- `recover_numbered_equations(parsed, reader)` — [app/evidence_preparation.py:201](read/app/evidence_preparation.py#L201)
- `definition_tokens(text)` — [app/evidence_preparation.py:318](read/app/evidence_preparation.py#L318)
- `source_definitions(parsed, text, max_chars=…, limit=…)` — [app/evidence_preparation.py:327](read/app/evidence_preparation.py#L327)
- `include_adjacent_definitions(parsed, max_chars=…)` — [app/evidence_preparation.py:369](read/app/evidence_preparation.py#L369)
- `equation_gaps(parsed)` — [app/evidence_preparation.py:407](read/app/evidence_preparation.py#L407)
- `line_text_for_caption(line)` — [app/evidence_preparation.py:424](read/app/evidence_preparation.py#L424)
- `extend_split_caption_lines(parsed, doc)` — [app/evidence_preparation.py:428](read/app/evidence_preparation.py#L428)
- `expand_unnumbered_relation_lines(parsed, reader)` — [app/evidence_preparation.py:471](read/app/evidence_preparation.py#L471)
- `complete_column_captions(parsed)` — [app/evidence_preparation.py:506](read/app/evidence_preparation.py#L506)
- `filter_equation_candidates(parsed)` — [app/evidence_preparation.py:544](read/app/evidence_preparation.py#L544)
- `unwrap(text)` — [app/evidence_quotes.py:9](read/app/evidence_quotes.py#L9)
- `verify_quotes(raw, evidence, provided=…)` — [app/evidence_quotes.py:17](read/app/evidence_quotes.py#L17)
- `slugify(text, fallback=…)` — [app/exporter.py:22](read/app/exporter.py#L22)
- `workspace_root(config)` — [app/exporter.py:28](read/app/exporter.py#L28)
- `file_key(data)` — [app/exporter.py:35](read/app/exporter.py#L35)
- `workspace_path(config, key, name)` — [app/exporter.py:39](read/app/exporter.py#L39)
- `find_workspace(config, key)` — [app/exporter.py:44](read/app/exporter.py#L44)
- `figure_context_markdown(card, fig)` — [app/exporter.py:83](read/app/exporter.py#L83)
- `equation_context_markdown(card, eq)` — [app/exporter.py:133](read/app/exporter.py#L133)
- `export_figure_pack(card, fig, root)` — [app/exporter.py:181](read/app/exporter.py#L181)
- `export_equation_pack(card, eq, root)` — [app/exporter.py:191](read/app/exporter.py#L191)
- `card_markdown(card)` — [app/exporter.py:210](read/app/exporter.py#L210)
- `export_card(card, root)` — [app/exporter.py:325](read/app/exporter.py#L325)
- `load_card(root)` — [app/exporter.py:339](read/app/exporter.py#L339)
- `metadata_complete(meta)` — [app/generation_state.py:6](read/app/generation_state.py#L6)
- `generation_complete(card)` — [app/generation_state.py:11](read/app/generation_state.py#L11)
- `expected_coverage(paper)` — [app/generation_state.py:36](read/app/generation_state.py#L36)
- `chat(base_url, payload, timeout, schedule_config)` — [app/ollama_transport.py:10](read/app/ollama_transport.py#L10)
- `Paragraph.cite(self, paper_title=…)` — [app/parser.py:86](read/app/parser.py#L86)
- `Section.text_span(self)` — [app/parser.py:100](read/app/parser.py#L100)
- `Figure.folder_name(self)` — [app/parser.py:126](read/app/parser.py#L126)
- `Equation.folder_name(self)` — [app/parser.py:149](read/app/parser.py#L149)
- `Equation.evidence_id(self)` — [app/parser.py:155](read/app/parser.py#L155)
- `ParsedPaper.paragraph_text(self, index)` — [app/parser.py:174](read/app/parser.py#L174)
- `ParsedPaper.section_of(self, paragraph_index)` — [app/parser.py:179](read/app/parser.py#L179)
- `ParsedPaper.section_at(self, page, y)` — [app/parser.py:188](read/app/parser.py#L188)
- `ParsedPaper.section_text(self, name, max_chars=…)` — [app/parser.py:198](read/app/parser.py#L198)
- `ParsedPaper.full_text(self, max_chars=…)` — [app/parser.py:221](read/app/parser.py#L221)
- `ParsedPaper.to_dict(self)` — [app/parser.py:228](read/app/parser.py#L228)
- `collect_refs(text)` — [app/parser.py:780](read/app/parser.py#L780)
- `collect_figure_refs(text)` — [app/parser.py:788](read/app/parser.py#L788)
- `equation_number(value)` — [app/parser.py:1003](read/app/parser.py#L1003)
- `equation_sort_key(value)` — [app/parser.py:1008](read/app/parser.py#L1008)
- `render_region(doc, page_no, bbox, out_path, dpi=…)` — [app/parser.py:1160](read/app/parser.py#L1160)
- `render_page_image(doc, page_no, out_path, dpi=…)` — [app/parser.py:1173](read/app/parser.py#L1173)
- `parse_pdf(pdf_path, config=…)` — [app/parser.py:1186](read/app/parser.py#L1186)
- `render_figures(parsed, out_dir, dpi=…, equation_dpi=…)` — [app/parser.py:1283](read/app/parser.py#L1283)
- `prepare_evidence(parsed, config)` — [app/parser.py:1335](read/app/parser.py#L1335)
- `prepare_pdf(source, config=…)` — [app/parser.py:1357](read/app/parser.py#L1357)
- `extract_regions(source, regions)` — [app/pdf_geometry.py:58](read/app/pdf_geometry.py#L58)
- `extract_bounded(source, regions, config=…)` — [app/pdf_geometry.py:115](read/app/pdf_geometry.py#L115)
- `prepare_geometry(paper, config)` — [app/pdf_geometry.py:129](read/app/pdf_geometry.py#L129)
- `prompt_evidence(row)` — [app/pdf_geometry.py:175](read/app/pdf_geometry.py#L175)
- `source_prompt(text, fields)` — [app/prompt_input.py:6](read/app/prompt_input.py#L6)
- `render_figure(card, fig, workspace, retry=…)` — [app/render.py:28](read/app/render.py#L28)
- `render_equation(card, eq, workspace, widget_index=…)` — [app/render.py:108](read/app/render.py#L108)
- `render_card(card, workspace, retry=…, show_source=…)` — [app/render.py:157](read/app/render.py#L157)
- `tags_path(root)` — [app/tags.py:17](read/app/tags.py#L17)
- `clean_tag(raw)` — [app/tags.py:21](read/app/tags.py#L21)
- `split_keywords(raw)` — [app/tags.py:26](read/app/tags.py#L26)
- `load_tags(root)` — [app/tags.py:34](read/app/tags.py#L34)
- `save_tags(root, tags)` — [app/tags.py:50](read/app/tags.py#L50)
- `SourceContract.test_parse_pdf_preserves_source_bytes_page_identity_and_numeric_conditions(self)` — [tests/test_source_contract.py:12](read/tests/test_source_contract.py#L12)
- `SourceContract.test_quote_must_match_original_and_actual_sent_evidence(self)` — [tests/test_source_contract.py:32](read/tests/test_source_contract.py#L32)
- `SourceContract.test_multiple_quotes_do_not_silently_accept_only_matching_subset(self)` — [tests/test_source_contract.py:39](read/tests/test_source_contract.py#L39)
- `SourceContract.test_prompt_evidence_retains_source_fields_and_excludes_notes_and_old_answers(self)` — [tests/test_source_contract.py:46](read/tests/test_source_contract.py#L46)

## 文件 SHA-256

```json
{
  "README.md": "50349bc87bf8442aec8522d4eeee4cab60deace980c17b35707a660013d6e3a7",
  "__init__.py": "67cb511643f45fb414d7313ae65f06fc12131eae1f05974835ac494d639768dc",
  "api.py": "2d63b359c9afb6e87f2e4de7b40f1430cef7df2df6ceb408618a01ea82c5b874",
  "app/analyzer.py": "150600aea4586293aeea42def504b411f4bbac1045ae2b1d834d96a81c839eb4",
  "app/atomic_io.py": "8a8fb260034a0dc53cb5a182c9b370d51a4f8e2bca37be4753a842a98c3fca88",
  "app/config.json": "79dea075ee3efcee03432dcaf1799cfb9934be8b49db2b0c7739f6841065fe3c",
  "app/context_budget.py": "1e725cb3193e2c3eb8846662944e73476a15d4d297a403d8eebef1d74908a725",
  "app/evidence_identity.py": "3d3967e666d07f8d8c373ffab00ec714555090a7d77e7bda6b9310b2e46d6b2a",
  "app/evidence_literal.py": "ffc2638c741be75fbbcd7bbc2e11ce8d30a9b366a90a859ab4499d7cae275d17",
  "app/evidence_preparation.py": "bf208a1164b27f865f5288fa5487082fa6e8fa89f9843b3c9296247a35fd5981",
  "app/evidence_quotes.py": "509f336af6b8b07b1d1266c78723cd4086cb06abdab0288181d77e4d07f318d9",
  "app/exporter.py": "b831340d7f0b2ea14c0937b32537b0cdc01b7599c159a47f5d56f7bf70c5f3e3",
  "app/generation_state.py": "959ab251d42c2a59120224700f929af21161ff8001729c57a6cd8d80a21a7d9a",
  "app/ollama_transport.py": "4b91ac7b8ed9884b694915335800ab38b1331243e8d203811330388f8323160a",
  "app/parser.py": "c0013ef23201787f005c1dacc85d5765b50af379cebf4ab99e33d7de3bf59d79",
  "app/pdf_geometry.py": "8946c27efc533a3dda56e0cf206340e1da7589444ddae8723181ef8f0761b17b",
  "app/prompt_input.py": "099ab59c9fb2d333f9cf21c057ccb2bcf77c4b17403293ae4c8e8fbaa2594ec2",
  "app/prompts/classify.md": "fd84e2a90bed4f76232e6cd347c63fa99b2a85a15f085143a490bb5ec7dcfae7",
  "app/prompts/conclusion.md": "fca768d3d2eadb501d84c0e546ba41867e4a843cd8260f752ba24a2faaea76fe",
  "app/prompts/domain_oled.md": "bde6ad8b649e74d2909dc1417b16a85d42e791a6c6fe09d6476bf0c4164b5566",
  "app/prompts/equation.md": "e692179918dd4df72cafc8ef82e050f1e17b6c19efc356ded105731265d1d689",
  "app/prompts/figure.md": "2dd3df5d7d4cb744ab37972007d8618f3b4136055e7dfbfe21867bce1f291042",
  "app/prompts/introduction.md": "1d75517d23157462482d4ec3f81fa956e0ac616402033a5539123f8434d81e37",
  "app/prompts/key_findings.md": "d89fb813f4935c5a9c4b9247f132d34dd6ab97b519d2ab55aced7c66513e629d",
  "app/prompts/paper_info.md": "e9846401c638c75417e252a220c7dce1ce1d9d13cab58c74f6cc5df6b5d743d1",
  "app/prompts/system.md": "87771c56c383f6da32f290efd67c24c56ac8032b1dd0bca50bf712960f456200",
  "app/render.py": "9a6051fca6d7958db3903508d7fa5f8e9d3508934ca5bf2c97a91fb2b65ede64",
  "app/requirements-mac-studio.lock.txt": "fd718dbfebfa7bb86cd16b0437dc8bcebdf3c53bde869aad7a20f1b93288978f",
  "app/requirements.txt": "e2253cc6b149b00cc0dcc1b9e86c7599d3cd721f3e9875f79a037f7cd97d4681",
  "app/tags.py": "c8e581ed0dfb956031fe69ccde09324b3b9e686cabed70e4818b5d55535b13fa",
  "interface.json": "b0465bac9ce76375dfdd9285b4cb4959ee3bbef91f71315f900942fa9549618c",
  "pyproject.toml": "bd0b3c8f530892896353446ee005c8ace10079e414b6ad695ab2b0cf5b8da032",
  "requirements-pdf-geometry.txt": "7b3e672b0bc3c3a0228284448a1b353d870c984233b5ba1f312e0f40b6f7a09d",
  "scripts/ollama": "4085e5fe98ea9f375261107974798e145d4266763567fc1af81c59a276fd5cb2",
  "scripts/ollama_env.sh": "20b2fb584c5517af14cdedaa60d40334da91475fd5c63f2f817fbcaa0b14db37",
  "tests/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "tests/test_source_contract.py": "a5f8b7a246563b18cd276a53c23a19dc84d728d738f0dd7870653c570f61eab1"
}
```
