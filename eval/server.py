"""Local website and OpenAI evaluation runner. Credentials never reach the browser."""
import argparse
import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
JOB={'status':'idle','error':None}
LOCK=threading.Lock()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--env-file',type=Path)
    args=parser.parse_args()
    if args.env_file and not args.env_file.is_file():
        parser.error('The specified .env file does not exist.')
    def worker():
        command=[sys.executable,str(ROOT/'eval'/'runner.py'),'--run']
        if args.env_file:command+=['--env-file',str(args.env_file.resolve())]
        try:
            done=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=300)
            if done.returncode:
                error='OpenAI has no credits remaining. Add credits or configure a funded key.' if 'credit_balance_exhausted' in done.stderr else 'The evaluation failed. Check the local terminal and API access.'
                print(done.stderr[-3000:],flush=True)
                with LOCK:JOB.update(status='failed',error=error)
            else:
                print(done.stdout,flush=True)
                with LOCK:JOB.update(status='completed',error=None)
        except subprocess.TimeoutExpired:
            with LOCK:JOB.update(status='failed',error='Evaluation timed out after five minutes. The previous report is retained.')
        except Exception as error:
            print(type(error).__name__,flush=True)
            with LOCK:JOB.update(status='failed',error='Could not start the local evaluation runner.')
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'dist'),**kw)
        def send_json(self,data,status=200):
            payload=json.dumps(data).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            if self.path=='/api/health':return self.send_json({'runner':True})
            if self.path=='/api/status':
                with LOCK:data=JOB.copy()
                return self.send_json(data)
            super().do_GET()
        def do_POST(self):
            if self.path!='/api/evaluate':return self.send_json({'error':'Not found'},404)
            allowed={f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}'}
            if self.headers.get('Origin') not in allowed or self.headers.get('Content-Type')!='application/json':
                return self.send_json({'error':'Use the local website to start an evaluation.'},403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1024:raise ValueError()
                if json.loads(self.rfile.read(size))!={}:raise ValueError()
            except (ValueError,TypeError):return self.send_json({'error':'Expected an empty JSON object.'},400)
            with LOCK:
                if JOB['status']=='running':return self.send_json({'error':'An evaluation is already running.'},409)
                JOB.update(status='running',error=None)
            threading.Thread(target=worker,daemon=True).start()
            self.send_json({'status':'running'},202)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Local: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()

if __name__=='__main__':main()
