import copy, sqlite3, unittest
import db
from dbc_ingest import ingest, ValidationError
import dbc_queries

Q='XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W'; C='11111111111111111111111111111111'; P='SysvarRent111111111111111111111111111111111'; B='Vote111111111111111111111111111111111111111'; A='Config1111111111111111111111111111111111111'
def payload():
 return {'version':1,'complete':True,'programId':'dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN','idlVersion':'0.2.1','sdkVersion':'1.5.12','startedAt':'2026-09-14T00:00:00Z','finishedAt':'2026-09-14T00:00:01Z','slot':'123','stats':{'quotes':1,'configs':1,'pools':1,'rpcRequests':5},'quotes':[{'mint':Q,'symbol':'SPYx'}],'configs':[{'address':C,'variant':'PoolConfig','quoteMint':Q,'version':1,'collectFeeMode':0,'migrationOption':1,'activationType':0,'tokenType':1,'creatorTradingFeePercentage':0,'partnerPermanentLockedLiquidityPercentage':50,'creatorPermanentLockedLiquidityPercentage':50,'migrationQuoteThreshold':'4','migrationBaseThreshold':'5','migratedPoolFeeBps':100,'raw':{}}],'pools':[{'address':P,'variant':'VirtualPool','config':C,'baseMint':B,'creator':A,'baseReserve':'18446744073709551615','quoteReserve':'2','sqrtPrice':'340282366920938463463374607431768211455','activationPoint':'3','isMigrated':0,'migrationProgress':0,'slot':'123','raw':{}}]}
class DbcTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;db.init_db(self.c)
 def tearDown(self):self.c.close()
 def test_schema_ingest_idempotency_and_queries(self):
  self.assertEqual(ingest(self.c,payload()),1);self.assertEqual(ingest(self.c,payload()),1);self.assertEqual(self.c.execute('select count(*) from dbc_collection_runs').fetchone()[0],1)
  s=dbc_queries.summary(self.c);self.assertTrue(s['available']);self.assertEqual(s['stats']['pools'],1)
  x=dbc_queries.pools(self.c,{'quote':[Q],'status':['active']});self.assertEqual(x['total'],1);self.assertEqual(x['pools'][0]['baseReserve'],'18446744073709551615')
  self.assertEqual(x['pools'][0]['curveProgress'],'0.5000');self.assertEqual(x['pools'][0]['migratedPoolFeeBps'],100)
  self.assertEqual(dbc_queries.pool_detail(self.c,P)['pool']['address'],P)
  with self.assertRaises(dbc_queries.QueryError):dbc_queries.pools(self.c,{'limit':['101']})
 def test_validation_rolls_back(self):
  bad=copy.deepcopy(payload());bad['pools'][0]['sqrtPrice']=str(2**128)
  with self.assertRaises(ValidationError):ingest(self.c,bad)
  self.assertEqual(self.c.execute('select count(*) from dbc_collection_runs').fetchone()[0],0)
 def test_transaction_rolls_back_on_sql_failure(self):
  p=payload();self.c.execute('CREATE TRIGGER fail_pool BEFORE INSERT ON dbc_pools BEGIN SELECT RAISE(FAIL,"boom"); END;')
  with self.assertRaises(sqlite3.IntegrityError):ingest(self.c,p)
  self.assertEqual(self.c.execute('select count(*) from dbc_collection_runs').fetchone()[0],0)
 def test_bounded_synthetic_fixture_round_trip(self):
  import json, pathlib
  fixture=pathlib.Path(__file__).with_name('fixtures')/'dbc-sample.json'
  p=json.loads(fixture.read_text(encoding='utf-8'));rid=ingest(self.c,p)
  self.assertGreater(rid,0);self.assertEqual(ingest(self.c,p),rid)
  s=dbc_queries.summary(self.c)
  self.assertEqual(s['stats']['configs'],1);self.assertEqual(s['stats']['pools'],1)
  rows=dbc_queries.pools(self.c,{'limit':['10']})['pools']
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['quoteReserve'],'50')
