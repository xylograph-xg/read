"""Shared literal evidence normalization and matching for screening and reading."""
import re
import unicodedata

def canonical(text):
    text=unicodedata.normalize('NFKC',str(text or ''))
    text=re.sub(r'[‐‑‒–—−]','-',text)
    text=re.sub(r'(?<=\w)-[^\S\n]*\n\s*(?=\w)','\x00',text)
    return re.sub(r'\s+',' ',text).strip()

def literal_match(quote,evidence,*,case_sensitive=False):
    quote=canonical(quote);source=canonical(evidence);pattern=[]
    for i,ch in enumerate(quote):
        if ch=='\x00':pattern.append('[-\x00]?')
        elif ch=='-' and i and i+1<len(quote) and quote[i-1].isalnum() and quote[i+1].isalnum():pattern.append('[-\x00]')
        else:pattern.append(re.escape(ch))
        if i+1<len(quote) and ch.isalnum() and quote[i+1].isalnum():pattern.append('\x00?')
    return bool(quote) and re.search(''.join(pattern),source,0 if case_sensitive else re.I) is not None
