import http.client
import json
import sqlite3
import stat
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from admin import start_admin
from analytics import Analytics


class UsageStatistics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'stats.sqlite3'
        self.now = datetime(2026,10,19,0,0,tzinfo=timezone.utc).timestamp()
        self.clock = patch('analytics.time.time',side_effect=lambda:self.now);self.clock.start()
        with self.connect() as c:
            c.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,created INTEGER);CREATE TABLE results(id TEXT PRIMARY KEY);')
        self.stats = Analytics(self.connect);self.stats.initialize()

    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c

    def tearDown(self):
        self.clock.stop();self.temp.cleanup()

    def room(self,id='one',humans=1,mode='standard',options=None):
        players=[{'id':i+1} for i in range(humans)]+[{'id':'bot'+str(i),'bot':True,'model':i==0} for i in range(4-humans)]
        return {'matchId':id,'mode':mode,'options':options or {},'players':players,'game':SimpleNamespace(phase='play')}

    def test_empty_statistics_have_zeroes_and_all_standard_modes(self):
        report=self.stats.report([])
        self.assertEqual(report['totals']['started'],0);self.assertEqual(report['dau'],0)
        self.assertEqual(len(report['modes']),8);self.assertEqual(len(report['days']),30)
        self.assertIsNone(report['totals']['average_seconds'])

    def test_dau_is_deduplicated_throttled_and_uses_shanghai_midnight(self):
        self.stats.activity(1);self.stats.activity(1);self.stats.activity(2)
        self.assertEqual(self.stats.report([])['dau'],2)
        with self.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM usage_daily').fetchone()[0],2)
        self.now+=30;self.stats.activity(1)
        with self.connect() as c:self.assertNotEqual(c.execute('SELECT last_seen FROM usage_daily WHERE user_id=1').fetchone()[0],self.now)
        self.now+=40;self.stats.activity(1)
        with self.connect() as c:self.assertEqual(c.execute('SELECT last_seen FROM usage_daily WHERE user_id=1').fetchone()[0],self.now)
        self.now=datetime(2026,10,19,16,0,tzinfo=timezone.utc).timestamp()
        self.stats.activity(1);report=self.stats.report([])
        self.assertEqual(report['days'][-1]['day'],'2026-10-20')
        self.assertEqual((report['dau'],report['wau'],report['mau']),(1,2,2))

    def test_matches_channels_variants_duration_and_completion_are_idempotent(self):
        one=self.room();two=self.room('two',2,options={'_alternate':True});three=self.room('three',4,options={'dlc':True})
        for r in (one,two,three):self.stats.start(r)
        self.stats.start(one);self.now+=180
        self.stats.finish(one,'completed','normal');self.stats.finish(two,'interrupted','leave')
        self.now+=60;self.stats.finish(one,'completed','resign')
        report=self.stats.report([])
        self.assertEqual(report['totals']['started'],3);self.assertEqual(report['totals']['completed'],1)
        self.assertEqual(report['totals']['interrupted'],1);self.assertEqual(report['totals']['average_seconds'],180)
        self.assertEqual(report['totals']['player_visits'],7)
        alternate=next(r for r in report['modes'] if r['variant']=='alternate')
        self.assertEqual(alternate['channel'],'multi');self.assertEqual(alternate['started'],1)
        self.assertEqual(report['days'][-1]['single'],1);self.assertEqual(report['days'][-1]['multi'],2)

    def test_realtime_excludes_idle_rooms_and_admin_reads_do_not_add_activity(self):
        room=self.room();self.stats.start(room)
        self.assertEqual(self.stats.report([room])['active_games'],0)
        self.stats.activity(1);report=self.stats.report([room])
        self.assertEqual((report['online'],report['playing'],report['active_games'],report['running_games']),(1,1,1,1))
        self.now+=61;report=self.stats.report([room])
        self.assertEqual((report['online'],report['active_games'],report['running_games']),(0,0,1))
        self.assertEqual(report['dau'],1)

    def test_restart_preserves_history_and_closes_running_matches(self):
        self.stats.activity(1);room=self.room();self.stats.start(room)
        with self.connect() as c:c.execute("INSERT INTO results VALUES('old')")
        self.now+=60;restarted=Analytics(self.connect);restarted.initialize();report=restarted.report([])
        self.assertEqual(report['totals']['interrupted'],1);self.assertEqual(report['dau'],1)
        self.assertEqual(report['historical_completed'],1);self.assertEqual(report['totals']['started'],1)
        with self.connect() as c:self.assertEqual(c.execute('SELECT reason FROM usage_matches').fetchone()[0],'restart')

    def test_model_call_health_and_signup_counts(self):
        self.stats.ai('model',False,1,{'prompt_cache_hit_tokens':31,'prompt_cache_miss_tokens':19})
        self.stats.ai('model',True,3)
        with self.connect() as c:
            c.execute('INSERT INTO users VALUES(1,?)',(self.now,));c.execute('INSERT INTO users VALUES(2,?)',(self.now-86400,))
        report=self.stats.report([])
        self.assertEqual(report['ai'],{'requests':2,'failures':1,'seconds':4,'cache_hits':31,'cache_misses':19})
        self.assertEqual((report['users'],report['new_users']),(2,1))
        self.assertEqual(report['days'][-1]['signups'],1)


class PrivateAdmin(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'admin-token'
        self.http=start_admin(lambda:{'ok':True},self.path,port=0)
        self.token=self.path.read_text();self.port=self.http.server_port

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.temp.cleanup()

    def request(self,path='/',headers=None,method='GET',body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port)
        conn.request(method,path,body=body,headers=headers or {})
        response=conn.getresponse();result=(response.status,dict(response.getheaders()),response.read())
        conn.close();return result

    def test_requires_admin_token_and_keeps_assets_out_of_public_server(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
        self.assertIn('管理口令'.encode(),self.request()[2])
        self.assertEqual(self.request('/api/stats')[0],401)
        self.assertEqual(self.request('/app.js')[0],401)
        self.assertEqual(self.request('/api/stats',{'Cookie':'poker_session=game-user'})[0],401)
        self.assertEqual(self.request('/api/stats',{'Authorization':'Bearer wrong'})[0],401)
        status,headers,body=self.request('/api/stats',{'Authorization':'Bearer '+self.token})
        self.assertEqual(status,200);self.assertEqual(json.loads(body),{'ok':True})
        self.assertEqual(headers['Cache-Control'],'no-store');self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertEqual(self.request('/../../server.py',{'Authorization':'Bearer '+self.token})[0],404)

    def test_login_cookie_csrf_and_proxy_restrictions(self):
        body=urllib.parse.urlencode({'token':self.token})
        self.assertEqual(self.request('/login',{'Origin':'https://evil.example'},'POST',body)[0],403)
        self.assertEqual(self.request('/login',{'Origin':'null'},'POST',body)[0],403)
        self.assertEqual(self.request('/login',method='POST',body='token=wrong')[0],401)
        self.assertEqual(self.request('/login',method='POST',body=urllib.parse.urlencode({'token':'错误'}))[0],401)
        status,headers,_=self.request('/login',{'Origin':'http://127.0.0.1:'+str(self.port)},'POST',body)
        self.assertEqual(status,303);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(headers['Referrer-Policy'],'same-origin')
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/stats',{'Cookie':cookie})[0],200)
        self.assertIn('运行统计'.encode(),self.request('/',{'Cookie':cookie})[2])
        for extra in ({'Host':'poker.vulpolirant.com'},{'X-Forwarded-For':'127.0.0.1'},{'CF-Connecting-IP':'127.0.0.1'}):
            self.assertEqual(self.request('/api/stats',{'Cookie':cookie,**extra})[0],404)
