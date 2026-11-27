"""Literal source checks with presentation wrappers only, no fuzzy science repair."""
import re
import unicodedata


from .evidence_literal import canonical,literal_match


def unwrap(text):
    text=text.strip()
    text=re.sub(r'^(?:[-*•]\s+|\d+[.)、]\s+)', '', text)
    if len(text)>=2 and (text[0],text[-1]) in [('"','"'),('“','”'),("'","'"),('‘','’')]:
        text=text[1:-1].strip()
    return text


def verify_quotes(raw,evidence,provided=None):
    """Every submitted quote must match both source and actual sent evidence.

    A continuous wrapped quote is preferred. If it does not match, support
    newline-separated quotations, never accepting only the valid subset.
    """
    documents=[evidence]
    if provided is not None:documents.append(provided)
    def verified(quote):
        value=canonical(quote)
        return len(re.sub(r"\s+","",value))>=15 and all(literal_match(quote,doc) for doc in documents)
    whole=unwrap(raw)
    if verified(whole):return [whole],True
    entries=[unwrap(line) for line in str(raw or '').splitlines() if line.strip()]
    if not entries:return [],False
    return entries,all(verified(entry) for entry in entries)
