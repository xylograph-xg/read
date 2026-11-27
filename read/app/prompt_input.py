"""A rendered prompt retains the exact evidence fields used to render it."""
class PromptInput(str):
 def __new__(cls,text,evidence="",fields=None):
  obj=super().__new__(cls,text);obj.evidence=evidence;obj.fields=dict(fields or {});return obj

def source_prompt(text,fields):
 keys=("caption","related_text","equation_text","members","first_pages","abstract","introduction","conclusion","candidates")
 return PromptInput(text,"\n".join(str(fields[k]) for k in keys if fields.get(k)),fields)
