"""Generic PDF section, caption, and equation evidence recovery.

This is the authoritative reader evidence preparation shared by every entrypoint.
No caption or equation number is assigned by document order alone.
"""
from __future__ import annotations
import re
from collections import Counter
from dataclasses import replace
import pymupdf


def line_text(line):
    return ''.join(span['text'] for span in line['spans']).strip()


def heading_name(text):
    core = re.sub(r'^\s*(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+\.)\s*', '', text).strip().rstrip(':')
    names = {
        'abstract': 'Abstract', 'introduction': 'Introduction',
        'results': 'Results', 'results and discussion': 'Results and Discussion',
        'discussion': 'Discussion', 'discussion and conclusions': 'Conclusion',
        'conclusions': 'Conclusion', 'conclusion': 'Conclusion', 'summary': 'Conclusion',
        'summary, conclusions, and outlook': 'Conclusion',
        'summary and conclusions': 'Conclusion',
        'methods': 'Methods', 'materials and methods': 'Methods',
        'references': 'References', 'literature cited': 'References',
        'acknowledgments': 'Acknowledgments', 'acknowledgements': 'Acknowledgments',
    }
    if core.lower() in names:
        return names[core.lower()]
    if re.fullmatch(r'(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+\.)\s+[A-Z][A-Z /,&:()\-]{4,}', text):
        return core  # preserve numbered section boundaries, not just known names
    return None


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def repair_sections(parsed, reader):
    """Recover exact headings lost to footer removal or merged into body blocks."""
    rebuilt = []
    with pymupdf.open(parsed.pdf_path) as doc:
        blocks = [[b for b in page.get_text('dict')['blocks'] if b.get('type') == 0]
                  for page in doc]
        for para in parsed.paragraphs:
            block = next((b for b in blocks[para.page]
                          if all(abs(a-c) < 2 for a,c in zip(b['bbox'], para.bbox))), None)
            lines = block['lines'] if block else []
            if not any(heading_name(line_text(line)) for line in lines):
                rebuilt.append(replace(para))
                continue
            buffer = []
            def flush():
                if buffer:
                    rebuilt.append(replace(para, text=reader._join_lines([line_text(l) for l in buffer]),
                                           bbox=union([l['bbox'] for l in buffer]),
                                           role='body', is_heading=False))
                    buffer.clear()
            for line in lines:
                text = line_text(line)
                if heading_name(text):
                    flush()
                    rebuilt.append(replace(para, text=text, bbox=list(line['bbox']),
                                           role='heading', is_heading=True))
                else:
                    buffer.append(line)
            flush()
        # The owner parser can remove short headings at page tops as footers.
        for page_no, page_blocks in enumerate(blocks):
            for block in page_blocks:
                for line in block['lines']:
                    text = line_text(line)
                    if not heading_name(text):
                        continue
                    if any(p.page == page_no and p.is_heading and p.text == text for p in rebuilt):
                        continue
                    rebuilt.append(reader.Paragraph(-1, page_no, list(line['bbox']), text,
                                                    role='heading', is_heading=True))
    # Preserve original column order, inserting recovered headings into that column.
    for p in rebuilt:
        if p.index >= 0:
            p._order = (p.index, p.bbox[1])
        else:
            below = [x for x in rebuilt if x.index >= 0 and x.page == p.page
                     and x.bbox[1] >= p.bbox[1]
                     and min(x.bbox[2],p.bbox[2]) > max(x.bbox[0],p.bbox[0])]
            anchor = min(below, key=lambda x:x.bbox[1]) if below else None
            p._order = ((anchor.index-.5) if anchor else len(parsed.paragraphs)+p.page, p.bbox[1])
    rebuilt.sort(key=lambda p:p._order)
    for i,p in enumerate(rebuilt):
        p.index=i
        del p._order
    parsed.paragraphs = rebuilt
    for figure in parsed.figures:
        anchor = next((p.index for p in rebuilt if p.page == figure.caption_page
                       and abs(p.bbox[1]-figure.caption_bbox[1]) < 3
                       and abs(p.bbox[0]-figure.caption_bbox[0]) < 3), None)
        if anchor is not None:
            figure.caption_start = anchor
    sections = [reader.Section(heading_name(p.text), p.text, p.page, p.index+1)
                for p in rebuilt if p.is_heading and heading_name(p.text)]
    for i,s in enumerate(sections):
        s.end = sections[i+1].start-1 if i+1 < len(sections) else len(rebuilt)
    if not any(s.name == 'Introduction' for s in sections):
        boundary = next((s.start-1 for s in sections
                         if s.name not in {'Abstract'}), len(rebuilt))
        start = next((s.end for s in sections if s.name == 'Abstract'), 0)
        body = [p for p in rebuilt[start:boundary] if p.role=='body' and len(p.text)>100]
        if body:
            sections.append(reader.Section('Introduction', '无标题开篇正文候选', body[0].page,
                                            body[0].index, boundary, detected=False))
            parsed.warnings.append('引言使用首次正文章节前的开篇段落候选，可能含前置摘要；不是人工确认的章节边界。')
    parsed.sections = sorted(sections, key=lambda s:s.start)
    if sections:
        parsed.warnings = [w for w in parsed.warnings if '没有识别到标准章节标题' not in w]


def recover_split_figures(parsed, reader):
    """Standalone Figure N labels followed by smaller caption text are captions."""
    with pymupdf.open(parsed.pdf_path) as doc:
        raw = [list(reader._iter_blocks(page)) for page in doc]
        clean, bands = reader._drop_headers_footers(raw, len(doc), parsed.page_sizes)
        for page_no, page in enumerate(doc):
            blocks = [b for b in page.get_text('dict')['blocks'] if b.get('type') == 0]
            for label in blocks:
                text = ' '.join(line_text(l) for l in label['lines']).strip()
                match = re.fullmatch(r'Fig(?:ure)?\.?\s*(\d+)', text, re.I)
                if not match:
                    continue
                number=int(match.group(1))
                if number <= 0:
                    continue
                if any(f.number==number for f in parsed.figures):
                    continue
                size=max(s['size'] for l in label['lines'] for s in l['spans'])
                cursor=label['bbox'][3];captions=[];boxes=[label['bbox']]
                for b in sorted(blocks, key=lambda x:x['bbox'][1]):
                    if b is label or b['bbox'][1] < label['bbox'][1]:
                        continue
                    if abs(b['bbox'][0]-label['bbox'][0])>8:
                        continue
                    if b['bbox'][1]-cursor>16:
                        break
                    line_sizes=[s['size'] for l in b['lines'] for s in l['spans']]
                    content=' '.join(line_text(l) for l in b['lines'])
                    if max(line_sizes, default=0)>size+.5 or heading_name(content) or re.match(r'^Figure\s+\d+',content):
                        break
                    captions.append(content);boxes.append(b['bbox']);cursor=max(cursor,b['bbox'][3])
                if not captions or len(' '.join(captions))<50:
                    continue
                anchor=next((p.index for p in parsed.paragraphs if p.page==page_no
                             and abs(p.bbox[1]-label['bbox'][1])<2), -1)
                f=reader.Figure(number, f'Fig. {number}', None, text+' '+' '.join(captions),
                                page_no, union(boxes), caption_start=anchor,
                                caption_strict=False, caption_confidence='medium')
                f.crop_page,f.crop_bbox,f.crop_confidence,f.crop_note,f.graphics_found=reader._choose_crop(
                    doc,f,parsed.paragraphs,clean,bands)
                for p in parsed.paragraphs:
                    if p.page==page_no and any(all(abs(a-c)<2 for a,c in zip(p.bbox,b)) for b in boxes):
                        p.role='caption';p.is_caption=True
                parsed.figures.append(f)
    parsed.figures.sort(key=lambda f:(f.caption_page,f.caption_bbox[1]))
    if parsed.figures:
        parsed.warnings=[w for w in parsed.warnings if '没有识别到 Figure caption' not in w]


def normalized_number(text):
    text=text.replace('ð','(').replace('Þ',')')
    m=re.fullmatch(r'(?:\(\s*([A-Z]?\d{1,3})\s*\)|([A-Z]?\d{1,3})\.)',text.strip())
    if not m:return None
    value=m.group(1) or m.group(2)
    return int(value) if value.isdigit() else value


def recover_caption_text(parsed,reader):
    """Do not inherit prose appended outside the owner's caption rectangle."""
    with pymupdf.open(parsed.pdf_path) as doc:
        for fig in parsed.figures:
            region=pymupdf.Rect(fig.caption_bbox)
            lines=[]
            for b in doc[fig.caption_page].get_text('dict')['blocks']:
                if b.get('type')!=0:continue
                for line in b['lines']:
                    rect=pymupdf.Rect(line['bbox'])
                    if region.contains(rect) or (region & rect).get_area()>.9*rect.get_area():
                        lines.append(line)
            if not lines:continue
            text=reader._join_lines([line_text(l) for l in sorted(lines,key=lambda l:l['bbox'][1])])
            if not re.match(r'^Fig(?:ure)?\.?\s*'+str(fig.number)+r'\b',text,re.I):continue
            previous=fig.caption;fig.caption=text
            for p in parsed.paragraphs:
                if p.page==fig.caption_page and p.role=='caption' and p.text in previous and p.text not in text:
                    rect=pymupdf.Rect(p.bbox)
                    if not rect.intersects(region):
                        p.role='body';p.is_caption=False


def recover_numbered_equations(parsed, reader):
    """Use printed, isolated numbers and whole display bands, including vector glyphs."""
    recovered=[]
    with pymupdf.open(parsed.pdf_path) as doc:
        for page_no,page in enumerate(doc):
            blocks=[b for b in page.get_text('dict')['blocks'] if b.get('type')==0]
            raw=list(reader._iter_blocks(page));columns=reader._columns(raw,page.rect.width)
            body=[b for b in raw if len(re.findall(r'\b[A-Za-z]{3,}\b',b['text']))>=12
                  and b['bbox'][2]-b['bbox'][0]<page.rect.width*.48]
            left=[b for b in body if b['bbox'][0]<page.rect.width*.3]
            right=[b for b in body if b['bbox'][0]>page.rect.width*.45]
            if left and right:
                columns=[(min(b['bbox'][0] for b in left),max(b['bbox'][2] for b in left)),
                         (min(b['bbox'][0] for b in right),max(b['bbox'][2] for b in right))]
            for block in blocks:
                for line in block['lines']:
                    text=line_text(line);number=normalized_number(text)
                    # Accept a publisher's terminal label on the relation line.
                    if number is None and '=' in text:
                        terminal=re.search(r'\(([A-Z]?\d{1,3})\)\s*$',text)
                        if terminal:
                            number=reader.equation_number(terminal.group(1))
                    if number is None or (isinstance(number,int) and not 0<number<=999):
                        continue
                    lb=line['bbox']
                    if text.strip().endswith('.') and lb[0]<page.rect.width*.65:
                        continue
                    column=columns[reader._column_index(columns,(lb[0]+lb[2])/2)]
                    nearby=[e for e in parsed.equations
                            if e.page==page_no and e.bbox[0]>=column[0]-8 and e.bbox[0]<lb[0]
                            and abs((e.bbox[1]+e.bbox[3]-lb[1]-lb[3])/2)<110
                            and ('=' in e.text or re.search(r'[≈∑⟨⟩|]',e.text))]
                    raw_relation=any(re.search(r'[=≈∑∫α-ωΑ-Ω]',line_text(l))
                                     and l['bbox'][0]>=column[0]-8 and l['bbox'][2]<=column[1]+8
                                     and len(re.findall(r'\b[A-Za-z]{3,}\b',line_text(l)))<5
                                     and abs((l['bbox'][1]+l['bbox'][3]-lb[1]-lb[3])/2)<170
                                     for b in blocks for l in b['lines'])
                    if not nearby and not raw_relation:
                        continue
                    prose=[]
                    for b in raw:
                        box=b['bbox'];t=b['text']
                        if min(box[2],column[1])-max(box[0],column[0])<min(box[2]-box[0],column[1]-column[0])*.5:
                            continue
                        if len(re.findall(r'\b[A-Za-z]{3,}\b',t))>=12 or re.match(r'^Fig(?:ure)?\.?\s*\d+',t,re.I):
                            prose.append(b)
                    # A PDF text block may span prose, a display, and more prose.
                    # Use individual prose lines as barriers too; block-level
                    # bounds alone otherwise swallow the next numbered display.
                    for text_block in blocks:
                        for prose_line in text_block['lines']:
                            pb=prose_line['bbox'];pt=line_text(prose_line)
                            if (pb[0]>=column[0]-8 and pb[2]<=column[1]+8
                                and len(re.findall(r'\b[A-Za-z]{3,}\b',pt))>=5
                                and not re.search(r'[=≈∑⟨⟩]',pt)):
                                prose.append({'bbox':pb,'text':pt})
                    floor=max([b['bbox'][3]+2 for b in prose if b['bbox'][3]<lb[1]-1]
                              +[40.0])
                    ceiling=min([b['bbox'][1]-2 for b in prose if b['bbox'][1]>lb[3]+1]
                                +[page.rect.height-30])
                    math=[]
                    for b in blocks:
                        for ml in b['lines']:
                            mb=ml['bbox'];mt=line_text(ml)
                            if (mb[1]>=max(floor,40) and mb[3]<=ceiling
                                and mb[0]>=column[0]-8 and mb[2]<=column[1]+8
                                and len(re.findall(r'\b[A-Za-z]{3,}\b',mt))<7
                                and not heading_name(mt) and mt.lower()!='article'
                                and mt and not re.match(r'^(?:where|here|we|these|this|therefore|thus|hence)\b',mt,re.I)):
                                math.append({'bbox':mb,'text':mt})
                    if not math:
                        continue
                    box=union([b['bbox'] for b in math]+[lb])
                    # Underbrace annotations belong to the displayed equation.
                    annotations=[l['bbox'] for b in blocks for l in b['lines']
                        if l['bbox'][0]>=column[0]-8 and l['bbox'][2]<=column[1]+8
                        and box[1]-12<=l['bbox'][1] and l['bbox'][3]<=min(ceiling,box[3]+14)
                        and len(re.findall(r'\b[A-Za-z]{3,}\b',line_text(l)))<7
                        and not heading_name(line_text(l))]
                    box=union([box]+annotations)
                    # Entire display band preserves non-text brackets and multi-line matrices.
                    box=[max(0,column[0]-5),max(floor,box[1]-5),
                         min(page.rect.width,max(column[1],lb[2])+7),min(ceiling,box[3]+5)]
                    if any(f.crop_page==page_no and pymupdf.Rect(f.crop_bbox).contains(pymupdf.Point((lb[0]+lb[2])/2,(lb[1]+lb[3])/2)) for f in parsed.figures):
                        continue
                    combined=' '.join(b['text'] for b in math)
                    recovered.append(reader.Equation(f'Eq. ({number})',number,page_no,box,
                                                     combined,source_note='PDF 行级独立式号与完整显示区域',confidence='high'))
    # Adjacent numbers sharing one display band remain one whole group.
    unique=[]
    for eq in recovered:
        if not any(e.page==eq.page and e.number==eq.number for e in unique):
            unique.append(eq)
    old=[e for e in parsed.equations if e.members and not any(
        e.page==r.page and any(pymupdf.Rect(m['bbox']).intersects(pymupdf.Rect(r.bbox))
                             for m in e.members) for r in unique)]
    # The owner groups by paragraph anchors; unrelated columns can share an
    # anchor and turn an equation crop into a whole-page bounding box. Only
    # equations in the exact same recovered display band may be grouped.
    bands={}
    for eq in unique:
        bands.setdefault((eq.page,tuple(round(x,1) for x in eq.bbox)),[]).append(eq)
    for band in bands.values():
        reader._group_equations(parsed,band,max_gap_paragraphs=0)
    parsed.equations=sorted(old+[e for e in unique if e.members],key=lambda e:(e.page,e.bbox[1]))
    # Two-column layouts interleave when sorted only by vertical position.
    # Reliable display numbers determine numbered groups' order on each page;
    # unnumbered evidence keeps its original position and is never renumbered.
    for page_no in sorted({e.page for e in parsed.equations}):
        slots=[i for i,e in enumerate(parsed.equations)
               if e.page==page_no and e.group_numbers]
        ordered=sorted((parsed.equations[i] for i in slots),
                       key=lambda e:min(reader.equation_sort_key(n) for n in e.group_numbers))
        for i,eq in zip(slots,ordered):
            parsed.equations[i]=eq


def definition_tokens(text):
    tokens=set(re.findall(r'(?<![A-Za-z])[A-Za-z](?:_[A-Za-z0-9]+)?(?![A-Za-z])',text))
    tokens.update(re.findall(r'\b[A-Z]{2,6}\b',text))
    # PDF extraction flattens subscripts into the same run (Dij, Wkl).
    # Retrieve the original definition sentences without assigning a meaning.
    tokens.update(re.findall(r'\b([A-Z])[a-z]{1,3}\b',text))
    return tokens


def source_definitions(parsed,text,max_chars=3200,limit=6):
    """Return original paper definitions; retain conflicting or local redefinitions."""
    tokens=definition_tokens(text);matches=[]
    for paragraph in parsed.paragraphs:
        fragment=len(paragraph.text)<120 and '=' in paragraph.text
        if paragraph.role!='body' or not (fragment or re.search(r'\b(?:defined?|denotes?|represents?|density|rate|where|with|here|approximation|introduced?|called)\b',paragraph.text,re.I)):continue
        hits=0
        for token in tokens:
            suffix=(r'(?:[a-z]{0,3}|[A-Z]{1,6})' if token.isupper() else r'[A-Z]{0,6}') if len(token)==1 else ''
            if re.search(r'(?<![A-Za-z])'+re.escape(token)+suffix+r'(?![A-Za-z])',paragraph.text):hits+=1
        if hits:
            priority=hits+100 if len(paragraph.text)<80 and re.match(r'^(?:with|where)\b',paragraph.text,re.I) and re.search(r'[=≈]',paragraph.text) else hits+50 if fragment else hits
            matches.append((priority,paragraph.index,paragraph))
    selected=[];used=0
    for _,_,paragraph in sorted(matches,key=lambda item:(-item[0],item[1])):
        text=paragraph.text
        if len(text)<120 and '=' in text:
            # Inline definitions split into separate glyph blocks often lose
            # their explanatory verb. Keep the neighboring original fragments
            # together without inferring or rewriting symbols and meanings.
            neighbors=parsed.paragraphs[max(0,paragraph.index-2):paragraph.index+7]
            fragments=[p.text for p in neighbors if p.page==paragraph.page
                       and p.role not in ('caption','heading')
                       and not re.match(r'^\s*\[\d+\]',p.text)]
            joined='\n'.join(fragments)
            if len(joined)+used+50<=max_chars:text=joined
        # PDF math may split a short 'with/where' definition across body/table
        # fragments. Supply the original page as evidence, without joining or
        # repairing mathematical values, only when it fits the same budget.
        if re.match(r'^(?:with|where)\b',text,re.I) and len(text)<80:
            page_text=parsed.page_texts[paragraph.page]
            start=page_text.find(text)
            if start>=0:
                excerpt=page_text[start:start+1200]
                if len(excerpt)+used+50<=max_chars:text=excerpt
        quote=f'[PDF p.{paragraph.page+1}, 原文定义证据] '+text
        if used+len(quote)>max_chars:continue
        selected.append((paragraph.index,quote));used+=len(quote)
        if len(selected)>=limit:break
    return '\n\n'.join(quote for _,quote in sorted(selected))


def include_adjacent_definitions(parsed,max_chars=12000):
    """The owner context routine skips the anchor itself; keep immediate definitions."""
    for eq in parsed.equations:
        if not eq.members:
            continue
        bbox=eq.group_bbox or eq.bbox
        same=[p for p in parsed.paragraphs if p.page==eq.page and p.role=='body'
              and min(p.bbox[2],bbox[2])-max(p.bbox[0],bbox[0])>min(p.bbox[2]-p.bbox[0],bbox[2]-bbox[0])*.35]
        before=sorted([p for p in same if p.bbox[3]<=bbox[1]+2],key=lambda p:p.bbox[3],reverse=True)[:2]
        after=sorted([p for p in same if p.bbox[1]>=bbox[3]-2],key=lambda p:p.bbox[1])[:2]
        kept={c['index']:c for c in eq.context}
        # Retrieve author definitions across the paper before semantic generation.
        # Exact token boundaries prevent T from matching arbitrary words.
        tokens=definition_tokens(eq.text)
        definitions=[]
        for p in parsed.paragraphs:
            if p.role!='body' or not re.search(r'\b(?:defined?|denotes?|represents?|density|rate|where|with|here|approximation|introduced?|called)\b',p.text,re.I):
                continue
            hits=sum(bool(re.search(r'(?<![A-Za-z])'+re.escape(t)+(r'[a-z]{0,3}' if len(t)==1 and t.isupper() else '')+r'(?![A-Za-z])',p.text)) for t in tokens)
            if hits:definitions.append((hits,p))
        definitions=sorted(definitions,key=lambda item:(-item[0],item[1].index))[:8]
        for p in before+after+[p for _,p in definitions]:
            kept[p.index]={'index':p.index,'page':p.page+1,'section':parsed.section_of(p.index),
                           'source':'公式紧邻定义/论述'}
        # Keep nearby definitions first; never exceed the model evidence budget.
        priority=[p.index for p in before+after]+[c['index'] for c in eq.context]+[p.index for _,p in definitions]
        chosen=[];used=0
        for index in dict.fromkeys(priority):
            context=kept[index];paragraph=parsed.paragraphs[index]
            cost=len(paragraph.text)+len(f"[p.{context['page']} · {context['section']} · {context['source']}] ")+2
            if used+cost>max_chars:continue
            chosen.append(context);used+=cost
        if len(chosen)<len(kept):
            parsed.extraction_audit.setdefault("context_omissions",[]).append({"item":eq.group_label or eq.label,"stage":"adjacent_definitions","paragraphs":sorted(set(kept)-{c["index"] for c in chosen})})
            parsed.warnings.append(f'{eq.group_label or eq.label} 上下文按 {max_chars} 字符预算保留，部分定义候选未发送模型。')
        eq.context=sorted(chosen,key=lambda c:c['index'])


def equation_gaps(parsed):
    """Expose holes in printed number series; never synthesize missing science."""
    series={}
    for eq in parsed.equations:
        for number in eq.group_numbers:
            match=re.fullmatch(r'([A-Z]?)(\d+)',str(number))
            if match:series.setdefault(match.group(1),set()).add(int(match.group(2)))
    gaps={}
    for prefix,numbers in series.items():
        if len(numbers)<2:continue
        absent=set(range(min(numbers),max(numbers)+1))-numbers
        if absent:gaps[prefix]=[f'{prefix}{n}' for n in sorted(absent)]
    if gaps:
        parsed.warnings.append('公式编号缺口待核查：'+', '.join(n for values in gaps.values() for n in values))
    return gaps


def line_text_for_caption(line):
    return ' '.join(''.join(s['text'] for s in line['spans']).split())


def extend_split_caption_lines(parsed,doc):
    """Continue small-font captions within their column across PDF math blocks."""
    for figure in parsed.figures:
        if len(figure.caption_bbox)!=4:continue
        box=figure.caption_bbox
        lines=[line for block in doc[figure.caption_page].get_text('dict')['blocks']
               if block.get('type')==0 for line in block['lines']]
        match=re.match(r'^Fig(?:ure)?\.?\s*(\d+)',figure.caption,re.I)
        if not match:continue
        anchor=[line for line in lines if re.match(r'^Fig(?:ure)?\.?\s*'+match.group(1)+r'\s*[.:|]',line_text_for_caption(line),re.I)
                and abs(line['bbox'][1]-box[1])<5]
        if len(anchor)!=1:continue
        spans=anchor[0]['spans']
        weights=Counter()
        for span in spans:weights[round(span['size'],1)]+=len(span['text'])
        if not weights:continue
        font=weights.most_common(1)[0][0]
        # Superscripts overlap previous lines. Use both endpoints and a small
        # font-relative gap; larger body type and new captions are barriers.
        tail=box[3];additions=[];bounds=[]
        candidates=sorted((line for line in lines if line['bbox'][0]>=box[0]-3
                           and line['bbox'][2]<=box[2]+3 and line['bbox'][1]>=tail-3),
                          key=lambda line:(line['bbox'][1],line['bbox'][0]))
        for line in candidates:
            lb=line['bbox'];text=line_text_for_caption(line)
            if lb[3]<=tail+.2:continue
            if lb[1]>tail+font*1.25:break
            if re.match(r'^Fig(?:ure)?\.?\s*\d+\s*[.:|]',text,re.I):break
            if not line['spans'] or max(span['size'] for span in line['spans'])>font+.35:break
            if not text.strip() or re.fullmatch(r'\d+(?:[-–]\d+)?',text.strip()):break
            additions.append(text);bounds.append(lb);tail=max(tail,lb[3])
        if additions:
            figure.caption+=' '+' '.join(additions)
            figure.caption_bbox=union([box,*bounds])
            for paragraph in getattr(parsed,"paragraphs",[]):
                if paragraph.page!=figure.caption_page:continue
                pb=paragraph.bbox
                if pb[0]>=box[0]-3 and pb[2]<=box[2]+3 and pb[1]>=box[1]-1 and pb[3]<=tail+1:
                    paragraph.role='caption';paragraph.is_caption=True
            if not hasattr(parsed,'extraction_audit'):parsed.extraction_audit={}
            parsed.extraction_audit.setdefault('caption_continuations',[]).append({'figure':getattr(figure,'label','Fig. '+match.group(1)),'page':figure.caption_page+1,'lines':len(additions)})


def expand_unnumbered_relation_lines(parsed,reader):
    """Keep all glyph runs of a relation line, including detached right factors."""
    with pymupdf.open(parsed.pdf_path) as doc:
        for equation in parsed.equations:
            if equation.group_numbers or not equation.members:continue
            box=equation.group_bbox or equation.bbox
            page=doc[equation.page]
            raw=[line for block in page.get_text('dict')['blocks'] if block.get('type')==0 for line in block['lines']]
            # Column-local baseline overlap recovers math runs that the PDF
            # split into separate blocks. Never reach the opposite column.
            cy=(box[1]+box[3])/2
            columns=reader.columns(list(reader.iter_blocks(page)),page.rect.width)
            prose=[line for line in raw if len(re.findall(r'[A-Za-z]{3,}',line_text(line)))>=5
                   and line['bbox'][2]-line['bbox'][0]<page.rect.width*.48]
            left=[line for line in prose if line['bbox'][0]<page.rect.width*.3]
            right=[line for line in prose if line['bbox'][0]>page.rect.width*.45]
            if left and right:
                columns=[(min(line['bbox'][0] for line in group),max(line['bbox'][2] for line in group))
                         for group in (left,right)]
            column=columns[reader.column_index(columns,(box[0]+box[2])/2)] if columns else (0,page.rect.width)
            full_lines=[line for line in raw if line['bbox'][1]<=cy<=line['bbox'][3]
                        and line['bbox'][0]>=column[0]-3 and line['bbox'][2]<=column[1]+3
                        and not (line['bbox'][2]<box[0]-page.rect.width*.08
                                 and len(re.findall(r'[A-Za-z]{3,}',line_text(line)))>=3)]
            if not full_lines:continue
            expanded=union([box,*[line['bbox'] for line in full_lines]])
            if expanded[2]-expanded[0]<=box[2]-box[0]+2:continue
            text=' '.join(line_text(line) for line in sorted(full_lines,key=lambda line:line['bbox'][0]))
            equation.bbox=expanded;equation.group_bbox=expanded;equation.text=text
            for member in equation.members:
                member['bbox']=expanded;member['text']=text
            equation.source_note+='；已合并同列同行全部字形，保留完整关系式及行内上下文'
            parsed.extraction_audit.setdefault('relation_crop_expansions',[]).append({'item':equation.group_label or equation.label,'page':equation.page+1,'old_bbox':box,'bbox':expanded})


def complete_column_captions(parsed):
    """Join same-sized caption continuations across columns, never nearby prose."""
    import pymupdf
    with pymupdf.open(parsed.pdf_path) as doc:
        extend_split_caption_lines(parsed,doc)
        for f in parsed.figures:
            if len(f.caption_bbox)!=4:continue
            blocks=doc[f.caption_page].get_text('dict')['blocks']
            text_blocks=[b for b in blocks if b.get('type')==0]
            start=next((b for b in text_blocks if abs(b['bbox'][0]-f.caption_bbox[0])<2 and abs(b['bbox'][1]-f.caption_bbox[1])<2),None)
            if start is None:continue
            sizes=[s['size'] for line in start['lines'] for s in line['spans']
                   if s['bbox'][2]<=f.caption_bbox[2]+2]
            size=sum(sizes)/len(sizes) if sizes else 0
            additions=[]
            # A later caption in the continuation column is a geometric barrier;
            # inline cross-references in the actual caption are preserved.
            barriers=[line['bbox'][1] for block in text_blocks for line in block['lines']
                      if line['bbox'][0]>f.caption_bbox[2]+5
                      and f.caption_bbox[1]-4<=line['bbox'][1]<f.caption_bbox[3]
                      and (re.match(r'^Fig(?:ure)?\.?\s*\d+\s*[.:]',line_text_for_caption(line),re.I) or heading_name(line_text_for_caption(line)))]
            ceiling=min([f.caption_bbox[3]]+barriers)
            for block in text_blocks:
                whole=' '.join(s['text'] for line in block['lines'] for s in line['spans'])
                if block is not start and (re.match(r'^Fig(?:ure)?\.?\s*\d+',whole,re.I) or heading_name(whole)):continue
                for line in block['lines']:
                    x0,y0,x1,y1=line['bbox']
                    if x0<=f.caption_bbox[2]+5 or not f.caption_bbox[1]-4<=y0<ceiling or y1>f.caption_bbox[3]+4:continue
                    spans=line['spans'];text=' '.join(''.join(s['text'] for s in spans).split())
                    if re.match(r'^Fig(?:ure)?\.?\s*\d+\s*[.:]',text,re.I):break
                    if not spans or any(s['size']>size+.5 for s in spans):continue
                    if text.strip() not in f.caption:additions.append((y0,text))
            if additions:
                f.caption+=' '+' '.join(text for _,text in sorted(additions))




def filter_equation_candidates(parsed):
    """The pipeline accepts numbered equations or explicit relations, not plot labels.

    Keep whole groups only when every member passes; partial group crops would
    still show discarded axes. Numbered equations retain the parser's contract.
    """
    kept_heads=[]
    rejected=0
    for head in parsed.equations:
        if not head.members:
            continue
        valid=True
        for member in head.members:
            text=member.get('text','')
            if member.get('number') is not None:
                continue
            if re.match(r'^\s*Table\s+(?:\d+|[IVX]+)\b',text,re.I):
                valid=False
                break
            if not re.search(r'[=≡≈≤≥<>]',text):
                valid=False
                break
            if len(re.findall(r'\b[A-Za-z]{3,}\b',text))>=7:
                valid=False
                break
            box=member.get('bbox',[])
            page=member.get('page',head.page+1)-1
            if len(box)==4:
                cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
                if any(f.crop_page==page and len(f.crop_bbox)==4
                       and f.crop_bbox[0]<=cx<=f.crop_bbox[2]
                       and f.crop_bbox[1]<=cy<=f.crop_bbox[3] for f in parsed.figures):
                    valid=False
                    break
        if valid:
            kept_heads.append(head)
        else:
            rejected+=1
            if not hasattr(parsed,'extraction_audit'):parsed.extraction_audit={}
            parsed.extraction_audit.setdefault('rejected_equation_candidates',[]).append({
                'label':getattr(head,'group_label',None) or getattr(head,'label','unnumbered'),
                'page':head.page+1,
                'bbox':getattr(head,'group_bbox',None) or getattr(head,'bbox',[]),
                'text':getattr(head,'text','') or ' '.join(m.get('text','') for m in head.members),
                'reason':'unnumbered nonrelation, prose, or in-figure candidate',
                'requires_table_review':any(re.search(r'\bTable\s+[IVX\d]+\b',m.get('text',''),re.I) for m in head.members)})
    # The analyzer consumes one card per item: members must not become duplicate
    # cards with the same group label and screenshot filename.
    parsed.equations=kept_heads
    labels=[getattr(eq,'group_label',None) or getattr(eq,'label','公式组') for eq in kept_heads]
    counts=Counter(labels)
    for i,(eq,label) in enumerate(zip(kept_heads,labels),1):
        if counts[label]>1:
            eq.group_label=f'{label} · 候选 {i}'
    if rejected:
        parsed.warnings=[w for w in parsed.warnings if 'display equation' not in w]
        parsed.warnings.append(f'过滤 {rejected} 组无关系式或位于图内的公式候选；行内关系式仍需结合正文阅读。')
    return rejected
