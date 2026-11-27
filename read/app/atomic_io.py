"""Durable local artifact writes; replace never exposes partial JSON."""
import json,os,tempfile
from core.api import paths__WorkspacePath as Path

def atomic_text(path,text,durable=True):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:
   f.write(text);f.flush()
   if durable:os.fsync(f.fileno())
  os.replace(name,path)
  if durable:
   fd=os.open(path.parent,os.O_RDONLY)
   try:os.fsync(fd)
   finally:os.close(fd)
 finally:
  Path(name).unlink(missing_ok=True)

def atomic_json(path,value,durable=True):
 atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",durable)
