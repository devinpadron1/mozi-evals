"""Local Classify website and Jev runner. Credentials never reach the browser."""
import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
JOBS = {
    'jev': {'status': 'idle', 'error': None},
}
PROGRESS = ROOT / '.eval-runs' / 'jev-progress.json'
REPORT = ROOT / 'dist' / 'jev_report.json'
BASELINE_PROGRESS = ROOT / '.eval-runs' / 'baseline-progress.json'
LOCK = threading.Lock()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    if args.env_file and not args.env_file.is_file():
        parser.error('The specified .env file does not exist.')

    def configured():
        env_file = args.env_file or ROOT / '.env'
        values = dotenv_values(env_file) if env_file.is_file() else {}
        return bool(os.getenv('OPENROUTER_API_KEY') or values.get('OPENROUTER_API_KEY'))

    def configured_workers():
        env_file = args.env_file or ROOT / '.env'
        values = dotenv_values(env_file) if env_file.is_file() else {}
        raw = os.getenv('JEV_WORKERS') or values.get('JEV_WORKERS') or '32'
        try:
            return max(1, min(32, int(raw)))
        except (TypeError, ValueError):
            return 32

    def worker(model):
        job = JOBS[model]
        command = [sys.executable, str(ROOT / 'eval' / f'{model}_runner.py'), '--run']
        if args.env_file:
            command += ['--env-file', str(args.env_file.resolve())]
        try:
            done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=1200)
            if done.returncode:
                print(done.stderr[-3000:], flush=True)
                if 'OPENROUTER_API_KEY' in done.stderr:
                    error = 'Set OPENROUTER_API_KEY in the local environment or .env, then restart the server.'
                elif 'HTTP 402' in done.stderr:
                    error = 'OpenRouter has insufficient credits for this run.'
                elif 'HTTP 401' in done.stderr or 'HTTP 403' in done.stderr:
                    error = 'OpenRouter rejected the API key or model access.'
                else:
                    error = f'{model.title()} classification failed. Check the local terminal for details.'
                with LOCK:
                    job.update(status='failed', error=error)
            else:
                print(done.stdout, flush=True)
                with LOCK:
                    job.update(status='completed', error=None)
        except subprocess.TimeoutExpired:
            with LOCK:
                job.update(status='failed', error=f'{model.title()} classification timed out. The previous report is retained.')
        except Exception as error:
            print(type(error).__name__, flush=True)
            with LOCK:
                job.update(status='failed', error=f'Could not start the {model.title()} runner.')

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def send_json(self, data, status=200):
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == '/api/health':
                return self.send_json({'runner': True, 'jev_configured': configured(), 'jev_workers': configured_workers()})
            if self.path == '/api/jev/status':
                with LOCK:
                    data = JOBS['jev'].copy()
                if PROGRESS.is_file():
                    try:
                        data['progress'] = json.loads(PROGRESS.read_text())
                    except (OSError, json.JSONDecodeError):
                        data['progress'] = None
                return self.send_json(data)
            if self.path == '/api/baseline/status':
                data = {'status': 'idle', 'error': None}
                if BASELINE_PROGRESS.is_file():
                    try:
                        data['progress'] = json.loads(BASELINE_PROGRESS.read_text())
                    except (OSError, json.JSONDecodeError):
                        data['progress'] = None
                return self.send_json(data)
            super().do_GET()

        def do_POST(self):
            if self.path not in ('/api/jev/evaluate', '/api/jev/clear'):
                return self.send_json({'error': 'Not found'}, 404)
            action = self.path.rsplit('/', 1)[-1]
            model = 'jev'
            allowed = {f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}'}
            if self.headers.get('Origin') not in allowed or self.headers.get('Content-Type') != 'application/json':
                return self.send_json({'error': 'Use the local website to start classification.'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError()
                if json.loads(self.rfile.read(size)) != {}:
                    raise ValueError()
            except (ValueError, TypeError):
                return self.send_json({'error': 'Expected an empty JSON object.'}, 400)
            if action == 'clear':
                with LOCK:
                    if any(job['status'] == 'running' for job in JOBS.values()):
                        return self.send_json({'error': 'A run is in progress and cannot be cleared yet.'}, 409)
                    try:
                        REPORT.unlink(missing_ok=True)
                        PROGRESS.unlink(missing_ok=True)
                    except OSError:
                        return self.send_json({'error': 'Could not clear the saved run files.'}, 500)
                    for job in JOBS.values():
                        job.update(status='idle', error=None)
                return self.send_json({'status': 'cleared'})
            if not configured():
                    return self.send_json({'error': 'Set OPENROUTER_API_KEY in the local environment or .env, then restart the server.'}, 400)
            with LOCK:
                if any(job['status'] == 'running' for job in JOBS.values()):
                    return self.send_json({'error': 'A run is already in progress.'}, 409)
                JOBS[model].update(status='running', error=None)
            threading.Thread(target=worker, args=(model,), daemon=True).start()
            self.send_json({'status': 'running'}, 202)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Local: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
