"""Guard every local request, including the standalone reader, across midnight."""
import json
import os
import subprocess
import sys
import time
from core.api import paths__WorkspacePath as Path


def chat(base_url,payload,timeout,schedule_config):
    from core.api import model_schedule__require_allowed as require_allowed
    require_allowed(schedule_config)
    lease_read,lease_write=os.pipe();process=None
    try:
        process=subprocess.Popen([sys.executable,'-m','read.app.ollama_transport',str(lease_read)],
            cwd=Path(__file__).resolve().parents[2],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,pass_fds=(lease_read,))
        os.close(lease_read);lease_read=None
        pending=json.dumps({'base_url':base_url,'payload':payload,'timeout':timeout})
        started=time.monotonic()
        while True:
            require_allowed(schedule_config)
            try:
                stdout,stderr=process.communicate(input=pending,timeout=min(1,max(.01,timeout-(time.monotonic()-started))))
                if process.returncode:raise RuntimeError(stderr[-1500:] or '本地模型请求失败')
                require_allowed(schedule_config)
                return json.loads(stdout)
            except subprocess.TimeoutExpired:
                pending=None
                if time.monotonic()-started>=timeout:raise TimeoutError('本地模型请求超时')
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(3)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if process:
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream is not None:stream.close()
        if lease_read is not None:os.close(lease_read)
        os.close(lease_write)


if __name__=='__main__':
    from core.api import runtime__watch_supervisor as watch_supervisor
    watch_supervisor(int(sys.argv[1]))
    import urllib.request
    data=json.load(sys.stdin)
    request=urllib.request.Request(data['base_url'].rstrip('/')+'/api/chat',data=json.dumps(data['payload']).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=data['timeout']) as response:result=json.load(response)
    print(json.dumps(result))
