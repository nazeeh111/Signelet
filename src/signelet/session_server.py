"""Loopback-only HTTP adapter. One SessionOwner remains the state authority."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import resources
import secrets
from . import __version__
from .session import ReviewSession,MAX_SESSION_BYTES,encoded
from .review import parse_decision


def make_server(owner,port=0):
    class Handler(BaseHTTPRequestHandler):
        server_version=f'Signelet/{__version__}'
        def log_message(self,*args):pass
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def send(self,status,raw,kind='application/json'):
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):self.close_connection=True
        def allowed(self):
            if self.headers.get('Host')!=self.server.origin.removeprefix('http://'):
                self.send(403,encoded({'error':'invalid loopback host'}));return False
            return True
        def do_GET(self):
            if not self.allowed():return
            if self.path=='/':
                page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Signelet review session</title><link rel="stylesheet" href="/assets/review.css"></head><body><main id="session"></main><script id="session-bootstrap" type="application/json">'''+json.dumps({'nonce':self.server.nonce})+'''</script><script type="module" src="/assets/session.mjs"></script></body></html>'''
                return self.send(200,page.encode(),'text/html; charset=utf-8')
            if self.path in ('/api/state','/api/journal','/api/bundle'):
                try:
                    current=owner.read_session()
                    raw=encoded(current.view()) if self.path=='/api/state' else current.bytes() if self.path=='/api/journal' else current.bundle()
                    return self.send(200,raw,'application/zip' if self.path=='/api/bundle' else 'application/json')
                except (ValueError,OSError,RuntimeError) as error:return self.send(409,encoded({'error':str(error)}))
            if self.path in ('/assets/review.css','/assets/review.mjs','/assets/session.mjs'):
                name=self.path.rsplit('/',1)[1];raw=resources.files('signelet').joinpath('assets',name).read_bytes()
                return self.send(200,raw,'text/css' if name.endswith('.css') else 'text/javascript')
            self.send(404,encoded({'error':'not found'}))
        def do_POST(self):
            if not self.allowed():return
            if self.headers.get('Origin')!=self.server.origin or self.headers.get('X-Signelet-Session')!=self.server.nonce:
                return self.send(403,encoded({'error':'local session header and origin required'}))
            if self.path not in ('/api/step','/api/undo','/api/import'):return self.send(404,encoded({'error':'not found'}))
            lengths=self.headers.get_all('Content-Length',[])
            if self.headers.get('Transfer-Encoding') or len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit():
                self.close_connection=True;return self.send(411,encoded({'error':'one bounded Content-Length required; chunked bodies unsupported'}))
            if len(lengths[0])>10:
                self.close_connection=True;return self.send(413,encoded({'error':'Content-Length exceeds bounded admission'}))
            length=int(lengths[0])
            if length>2*MAX_SESSION_BYTES+2048:
                self.close_connection=True;return self.send(413,encoded({'error':'request exceeds byte limit'}))
            try:
                raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete body')
                body=parse_decision(raw,max_bytes=2*MAX_SESSION_BYTES+2048)
                expected={'revision','choice'} if self.path=='/api/step' else {'revision','journal_text'} if self.path=='/api/import' else {'revision'}
                if type(body) is not dict or set(body)!=expected:raise ValueError('invalid request fields')
                if self.path=='/api/import':
                    if type(body['journal_text']) is not str:raise ValueError('session text required')
                    current=owner.read_session()
                    candidate=ReviewSession.open(body['journal_text'].encode())
                    # A server is scoped to one original input/context. Open another via CLI resume.
                    a=json.loads(current.bytes());b=json.loads(candidate.bytes())
                    if (a['input_sha256'],encoded(a['context']))!=(b['input_sha256'],encoded(b['context'])):raise ValueError('different original/context; resume in a separate session directory')
                    result=owner.import_session(candidate,body['revision'])
                else:result=owner.apply(self.path.rsplit('/',1)[1],body['revision'],body.get('choice'))
                self.send(200,encoded(result))
            except ValueError as error:self.send(409 if 'stale' in str(error) or 'changed' in str(error) else 400,encoded({'error':str(error)}))
            except Exception as error:self.send(503,encoded({'error':str(error),'reconcile':'Reload saved state before retry; a disconnected response does not imply rollback.'}))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    server.origin=f'http://127.0.0.1:{server.server_address[1]}';server.nonce=secrets.token_urlsafe(24)
    return server
