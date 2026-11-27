"""Original PDF glyph evidence through pdfplumber; no OCR/model inference.

All text is from the exact existing crop. Geometry candidates are not LaTeX
truth; incomplete fonts, unsupported page transforms and errors stay visible.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from core.api import paths__WorkspacePath as Path
import re
import subprocess
import sys

VERSION=1
VERSIONS={'pdfplumber':'0.11.9','pdfminer.six':'20251230'}
BUNDLED_PYTHON=Path(sys.executable) # Explicit environment/config overrides take precedence.


def _fraction_candidates(chars, lines):
    results=[]
    for line in lines:
        x0,x1,top=line['x0'],line['x1'],line['top']
        if abs(line['bottom']-top)>.5 or not 3<=x1-x0<=100:
            continue
        above=[i for i,c in enumerate(chars) if x0-1<=c['x0'] and c['x1']<=x1+1
               and 0<=top-c['bottom']<=14]
        below=[i for i,c in enumerate(chars) if x0-1<=c['x0'] and c['x1']<=x1+1
               and 0<=c['top']-top<=14]
        if above and below:
            def text(indices):return ''.join(chars[i]['text'] for i in sorted(indices,key=lambda j:chars[j]['x0']))
            results.append({'state':'geometry_candidate','bar_bbox':[x0,top,x1,line['bottom']],
                            'above_glyphs':above,'below_glyphs':below,
                            'above_text':text(above),'below_text':text(below)})
    return results


def _script_candidates(chars):
    result=[]
    for index,c in enumerate(chars):
        if not c['text'].strip():continue
        candidates=[]
        for base_index,base in enumerate(chars):
            dx=c['x0']-base['x1']
            if (-2.5<=dx<=2.5 and c['x0']>=base['x0']+.5*(base['x1']-base['x0'])
                and .4<c['size']/max(base['size'],.01)<.85 and base['text'].strip()):
                offset=c['bottom']-base['bottom']
                if .6<abs(offset)<base['size']*1.3:
                    candidates.append((dx,base_index,offset))
        if candidates:
            _,base_index,offset=min(candidates)
            result.append({'state':'geometry_candidate','base_glyph':base_index,'script_glyph':index,
                           'position':'superscript' if offset<0 else 'subscript'})
    return result


def extract_regions(source, regions):
    """Worker API: regions have id, zero-based page, bbox and page_size."""
    from importlib.metadata import version
    runtime={name:version(name) for name in VERSIONS}
    if runtime!=VERSIONS:raise RuntimeError('pdfplumber依赖版本与锁不一致')
    import pdfplumber
    if len(regions)>200:raise ValueError('公式区域超过200个预算')
    source=Path(source)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    rows=[]
    from collections import Counter
    remaining=Counter(r['page'] for r in regions)
    with pdfplumber.open(source) as pdf:
        for region in regions:
            page=None
            base={'id':region['id'],'page':region['page'],'bbox':region['bbox']}
            try:
                if not isinstance(region['page'],int) or not 0<=region['page']<len(pdf.pages):
                    raise ValueError('页索引不合法')
                page=pdf.pages[region['page']]
                box=region['bbox']
                if len(box)!=4 or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in box):
                    raise ValueError('区域坐标不合法')
                if box[0]>=box[2] or box[1]>=box[3]:raise ValueError('区域为空')
                size=region.get('page_size')
                if size and any(abs(a-b)>1 for a,b in zip(size,[page.width,page.height])):
                    raise ValueError('两种解析器的页面坐标系不同，禁止套用区域')
                # Filtering before cropping prevents a barely intersecting
                # prose line from appearing as a complete equation sentence.
                def inside(c):
                    return (box[0]<=(c['x0']+c['x1'])/2<=box[2]
                            and box[1]<=(c['top']+c['bottom'])/2<=box[3])
                filtered=page.filter(lambda obj:obj['object_type']!='char' or inside(obj))
                crop=filtered.crop(tuple(box),strict=True)
                # Retain original coordinates; do not let crop clip glyphs into
                # apparently complete tokens. Partially intersecting chars are
                # included whole only if their centre is inside the same crop.
                original=[c for c in page.chars if inside(c)]
                if len(original)>1500:raise ValueError('字符数超过单式1500预算')
                keys=('text','x0','x1','top','bottom','size')
                chars=[{k:c[k] for k in keys} for c in original]
                text=crop.extract_text(x_tolerance=1,y_tolerance=2) or ''
                unknown=any(re.search(r'\(cid:\d+\)|[\x00-\x08\ue000-\uf8ff]',c['text']) for c in chars)
                rows.append({**base,'state':'extracted' if chars else 'no_text_layer','text':text,
                             'glyphs':chars,'fraction_candidates':_fraction_candidates(chars,crop.lines),
                             'script_candidates':_script_candidates(chars),
                             'unknown_glyphs':unknown,'source_verified':False})
            except (ValueError,KeyError,TypeError) as exc:
                rows.append({**base,'state':'unsupported','error':str(exc),'source_verified':False})
            finally:
                # Release page caches between distinct pages after extraction.
                remaining[region['page']]-=1
                if page is not None and remaining[region['page']]==0:page.close()
    return {'schema_version':VERSION,'state':'extracted','runtime':runtime,
            'source_sha256':source_hash,'regions':rows,'model_calls':0}


def extract_bounded(source,regions,config=None):
    config=config or {}
    executable=os.environ.get('PAPER_PDF_GEOMETRY_PYTHON') or config.get('python') or str(BUNDLED_PYTHON)
    executable = str((Path(__file__).parent / Path(executable).expanduser()).absolute()) if '/' in executable else executable
    try:
        request=json.dumps({'source':str(Path(source).resolve()),'regions':regions},ensure_ascii=False)
        completed=subprocess.run([executable,str(Path(__file__).resolve()),'--worker'],input=request,
                                 capture_output=True,text=True,timeout=config.get('timeout_seconds',15))
        if completed.returncode:raise RuntimeError(completed.stderr[-500:])
        return json.loads(completed.stdout)
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
        return {'schema_version':VERSION,'state':'unavailable','error':str(exc)[:600],'regions':[],'model_calls':0}


def prepare_geometry(paper,config):
    """Add source evidence; repair only missing assignments with a printed ID.

    Crop/labels/counts never change. Existing complete text is left intact;
    original incomplete extraction remains in the ledger for review.
    """
    policy=config.get('pdf_geometry',{})
    if not policy.get('enabled'):return None
    equations=[eq for eq in paper.equations if eq.members and eq.group_numbers]
    if not equations:return {'state':'not_needed','regions':[],'model_calls':0}
    regions=[{'id':eq.evidence_id,'page':eq.page,'bbox':eq.group_bbox or eq.bbox,
              'page_size':paper.page_sizes[eq.page]} for eq in equations]
    report=extract_bounded(paper.pdf_path,regions,policy)
    results={r['id']:r for r in report['regions']}
    recovered=[]
    for eq in equations:
        row=results.get(eq.evidence_id)
        if not row:continue
        row=dict(row,source_sha256=report.get('source_sha256'),original_extraction=eq.text)
        eq.source_geometry=row
        text=row.get('text','')
        glyphs=row.get('glyphs',[])
        # A single numbered display and an original relation are mandatory.
        # Multiple assignments/prose bands are never substituted automatically.
        numbers=re.findall(r'\((\d{1,3})\)',text)
        equals=[c for c in glyphs if c['text']=='=']
        before=bool(equals and any(c['x1']<=equals[0]['x0'] and c['text'].strip() for c in glyphs))
        if ('=' not in eq.text and row['state']=='extracted' and not row.get('unknown_glyphs')
            and len(eq.group_numbers)==1 and numbers==[str(eq.group_numbers[0])]
            and len(equals)==1 and before):
            eq.text=text
            row['original_members']=[dict(member) for member in eq.members]
            eq.members[0]['text']=text
            eq.source_note+='；缺失关系由同区域PDF原始字符补回，多行文本不可当LaTeX'
            row['relation_recovered']=True
            recovered.append(eq.evidence_id)
        else:row['relation_recovered']=False
    paper.extraction_audit['pdf_geometry']={'schema_version':VERSION,'state':report['state'],
        'runtime':report.get('runtime',{}),'source_sha256':report.get('source_sha256'),
        'regions':len(results),'recovered_ids':recovered,'error':report.get('error'),
        'unsupported_ids':[r['id'] for r in report['regions'] if r['state']!='extracted'],'model_calls':0}
    if report['state']=='unavailable':
        paper.warnings.append('PDF字符几何组件不可用；保留原提取，未增加任何公式核验声明。')
    return report


def prompt_evidence(row):
    if not row or row.get('state')!='extracted':return ''
    lines=['同区域PDF原始字符（保持换行，不能当作线性LaTeX）：',row.get('text','')[:1600]]
    for fraction in row.get('fraction_candidates',[])[:8]:
        lines.append('分数线几何候选：线上 '+fraction['above_text']+'；线下 '+fraction['below_text'])
    chars=row.get('glyphs',[])
    for relation in row.get('script_candidates',[])[:12]:
        lines.append('字符位置候选：'+chars[relation['base_glyph']]['text']+' 的 '
                     +relation['position']+' 字符 '+chars[relation['script_glyph']]['text'])
    if row.get('unknown_glyphs'):lines.append('存在未解码字形，必须对照截图，不能自行补字。')
    lines.append('以上是几何候选，截图优先；不能把上下标或分数两行拼成乘积，不是可引用的原文正文句。')
    return '\n'.join(lines)


if __name__=='__main__':
    if sys.argv[1:]!=['--worker']:raise SystemExit('仅支持 --worker JSON标准输入')
    request=json.load(sys.stdin)
    print(json.dumps(extract_regions(request['source'],request['regions']),ensure_ascii=False))
