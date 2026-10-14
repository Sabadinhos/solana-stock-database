import json, os, sqlite3, sys, tempfile, threading, types, unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch
for name in ('m1','m3','m4','cards','insights','og','onchain','prices'):
 sys.modules.setdefault(name, types.ModuleType(name))
import db, server
from dbc_ingest import ingest
from test_dbc import payload, P
class ApiTests(unittest.TestCase):
 def setUp(self):
  self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row;db.init_db(self.conn)
  self.old_enabled=server.DBC_ENABLED;server.DBC_ENABLED=True
  self.patcher=patch.object(server.db,'connect',lambda:self._connection());self.patcher.start()
  self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
 def _connection(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;db.init_db(c);return c
 def tearDown(self):self.http.shutdown();self.http.server_close();self.patcher.stop();self.conn.close();server.DBC_ENABLED=self.old_enabled
 def get(self,path):
  h=HTTPConnection('127.0.0.1',self.http.server_port);h.request('GET',path);r=h.getresponse();return r.status,json.loads(r.read())
 def test_empty_summary_and_structured_errors(self):
  status,body=self.get('/api/dbc/summary');self.assertEqual(status,200);self.assertFalse(body['available'])
  status,body=self.get('/api/dbc/pools?limit=999');self.assertEqual(status,400);self.assertEqual(body['error'],'invalid_request')
  status,body=self.get('/api/dbc/pool/not_base58!');self.assertEqual(status,400);self.assertEqual(body['error'],'invalid_pool_address')
 def test_routes_with_imported_data(self):
  fd,path=tempfile.mkstemp(suffix='.db');os.close(fd)
  setup=sqlite3.connect(path);setup.row_factory=sqlite3.Row;db.init_db(setup);ingest(setup,payload());setup.close()
  old=server.db.connect
  def connect():
   c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
  server.db.connect=connect
  try:
   status,body=self.get('/api/dbc/pools?limit=1');self.assertEqual(status,200);self.assertEqual(body['pools'][0]['curveProgress'],'0.5000')
   status,body=self.get('/api/dbc/pool/'+P);self.assertEqual(status,200);self.assertEqual(body['pool']['address'],P)
  finally:
   server.db.connect=old;os.unlink(path)
if __name__=='__main__':unittest.main()
