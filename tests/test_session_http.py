"""Real local HTTP for the same native session owner, no browser simulation."""
import http.client,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from test_session import start,C1,C2
from signelet.session import SessionOwner,replay_bundle
from signelet.session_server import make_server

class SessionHTTPTests(unittest.TestCase):
    def test_real_http_recompute_import_replay_stale_failure_and_admission(self):
        _,s=start()
        with tempfile.TemporaryDirectory() as tmp,SessionOwner(Path(tmp)/'session',create=s) as owner:
            server=make_server(owner);thread=threading.Thread(target=server.serve_forever);thread.start()
            def call(path,body=None,extra=None,raw=None):
                c=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
                headers={'Host':server.origin.removeprefix('http://'),'Origin':server.origin,'X-Signelet-Session':server.nonce}
                headers.update(extra or {})
                c.request('POST' if body is not None or raw is not None else 'GET',path,json.dumps(body) if raw is None and body is not None else raw,headers)
                r=c.getresponse();result=r.status,r.read(),dict(r.getheaders());c.close();return result
            try:
                status,page,headers=call('/');self.assertEqual(status,200);self.assertIn(b'/assets/session.mjs',page);self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
                self.assertEqual(call('/assets/review.css')[0],200)
                self.assertEqual(call('/api/step',{'revision':s.revision,'choice':C1},{'Origin':'https://other.invalid'})[0],403)
                with patch('signelet.session_server.parse_decision') as parser:
                    self.assertEqual(call('/api/step',{},raw=b'x',extra={'Content-Length':str(2*8*1024*1024+2049)})[0],413)
                    parser.assert_not_called()
                import socket
                for framing,expected in [('Transfer-Encoding: chunked',411),('',411),('Content-Length: '+'9'*5000,413)]:
                    wire=(f'POST /api/undo HTTP/1.1\r\nHost: {server.origin.removeprefix("http://")}\r\nOrigin: {server.origin}\r\nX-Signelet-Session: {server.nonce}\r\n'+framing+'\r\nConnection: close\r\n\r\n').encode()
                    with socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=3) as peer:
                        peer.sendall(wire);reply=peer.recv(4096);self.assertIn(str(expected).encode(),reply.split(b'\r\n',1)[0])
                self.assertEqual(owner.session.revision,s.revision)
                self.assertEqual(call('/api/step',{'revision':s.revision,'choice':C1})[0],200)
                self.assertEqual(call('/api/step',{'revision':s.revision,'choice':C2})[0],409)
                state=json.loads(call('/api/state')[1]);self.assertEqual(state['assumptions'],1)
                with patch('signelet.session.os.replace',side_effect=OSError('late failure')):
                    self.assertEqual(call('/api/step',{'revision':state['revision'],'choice':C2})[0],503)
                self.assertEqual(json.loads(call('/api/state')[1])['revision'],state['revision'])
                self.assertEqual(call('/api/step',{'revision':state['revision'],'choice':C2})[0],200)
                current=json.loads(call('/api/state')[1]);self.assertEqual(current['status'],'complete')
                self.assertEqual(replay_bundle(call('/api/bundle')[1]).view()['status'],'complete')
                # Imported text is parsed by native owner, with exact current revision and original context.
                self.assertEqual(call('/api/import',{'revision':current['revision'],'journal_text':s.bytes().decode()})[0],200)
                self.assertEqual(json.loads(call('/api/state')[1])['assumptions'],0)
                self.assertEqual(call('/api/import',{'revision':owner.session.revision,'journal_text':'{broken'})[0],400)
                self.assertEqual(owner.session.view()['assumptions'],0)
            finally:server.shutdown();server.server_close();thread.join(3)
            self.assertFalse(thread.is_alive())
