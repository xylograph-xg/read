"""Conservative token estimates, not byte counts or an exact model tokenizer."""
import math
import re
import struct
from core.api import paths__WorkspacePath as Path

SCHEMA_VERSION=1
TRUNCATION='\n…（输入预算所限，仅提供原文片段，未提供部分不得推断）'

def estimate_tokens(text):
    text=str(text or '')
    cjk=len(re.findall(r'[\u3000-\u9fff\uac00-\ud7af]',text))
    ascii_letters=len(re.findall(r'[a-zA-Z0-9\s]',text))
    other=len(text)-cjk-ascii_letters
    return math.ceil((cjk*1.5+ascii_letters/3+other)*1.1)

def image_tokens(paths):
    total=0
    for path in paths or []:
        if not Path(path).is_file():continue
        # Reserve for tiled vision inputs; model-specific tokenization may differ.
        tiles=16
        try:
            from PIL import Image
            with Image.open(path) as im:width,height=im.size
            tiles=max(1,math.ceil(width/768)*math.ceil(height/768))
        except (OSError,ValueError):pass
        total+=1024*tiles
    return total

def input_limit(options,system='',images=None):
    context=int(options.get('num_ctx',8192));output=int(options.get('num_predict',2048))
    return context-output-max(512,context//16)-estimate_tokens(system)-image_tokens(images)

def trim_tokens(text,limit,marker=TRUNCATION):
    if estimate_tokens(text)<=limit:return text
    left,right=0,len(text);room=limit-estimate_tokens(marker)
    if room<=0:raise ValueError('固定提示超过输入预算')
    while left<right:
        middle=(left+right+1)//2
        if estimate_tokens(text[:middle])<=room:left=middle
        else:right=middle-1
    return text[:left]+marker

def fit_fields(values,render,limit):
    values=dict(values);prompt=render(values);truncated=[]
    iterations=0
    while estimate_tokens(prompt)>limit:
        iterations+=1
        if iterations>max(32,len(values)*128):raise ValueError("输入预算截断未收敛")
        fields=[(estimate_tokens(v),k) for k,v in values.items() if isinstance(v,str) and estimate_tokens(v)>estimate_tokens(TRUNCATION)+40]
        if not fields:raise ValueError('固定提示超过输入预算，请增加上下文或减少模板')
        size,key=max(fields);excess=estimate_tokens(prompt)-limit
        values[key]=trim_tokens(values[key],max(estimate_tokens(TRUNCATION)+20,size-max(excess,128)))
        if key not in truncated:truncated.append(key)
        prompt=render(values)
    return prompt,truncated
