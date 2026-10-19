import http.cookiejar
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import server
from engine import Game


class ServerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.old_db=server.DB_PATH
        server.DB_PATH=Path(cls.temp.name)/'test.sqlite3'
        server.ROOMS.clear();server.ATTEMPTS.clear();server.MODEL_CONFIG.clear()
        server.initialize()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)
        cls.clients=[]
        cls.users=[]
        for i in range(4):
            client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            cls.clients.append(client)
            status,data=cls.request(client,'register',{'name':'测试玩家'+str(i),'password':'testpass123'})
            assert status==200,data
            cls.users.append(data['user'])

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()
        server.DB_PATH=cls.old_db;server.ROOMS.clear();server.ATTEMPTS.clear();server.MODEL_CONFIG.clear();cls.temp.cleanup()

    @classmethod
    def request(cls,client,path,body=None,headers=None):
        req=urllib.request.Request(cls.url+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with client.open(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)

    def setUp(self):
        server.ROOMS.clear()

    def test_reserved_room_handoff_and_recreation(self):
        first,second,third=self.clients[:3]
        status,data=self.request(first,'join',{'code':'001255'})
        self.assertEqual(status,200);room=server.ROOMS['001255']
        self.assertEqual(data['room']['mode'],'standard');self.assertTrue(data['room']['options']['advancedHui'])
        self.assertNotIn('_alternate',data['room']['options'])
        self.assertEqual(self.request(second,'join',{'code':'001255'})[0],200)
        self.assertEqual(self.request(third,'join',{'code':'001255'})[0],200)
        self.assertEqual(self.request(first,'leave',{})[0],200)
        self.assertEqual(room['host'],self.users[1]['id'])
        self.assertEqual(self.request(second,'leave',{})[0],200)
        self.assertEqual(room['host'],self.users[2]['id'])
        self.assertEqual(self.request(third,'leave',{})[0],200)
        self.assertNotIn('001255',server.ROOMS)
        self.assertEqual(self.request(second,'join',{'code':'001255'})[0],200)
        self.assertEqual(server.ROOMS['001255']['host'],self.users[1]['id'])

    def test_reserved_single_is_private_and_only_accepts_reserved_number(self):
        first,second,third=self.clients[:3]
        self.request(third,'create',{'mode':'basic'})
        normal_code=server.room_of(self.users[2]['id'])['code']
        self.assertEqual(self.request(first,'join',{'code':normal_code,'single':True})[0],400)
        _,one=self.request(first,'join',{'code':'001255','single':True})
        _,two=self.request(second,'join',{'code':'001255','single':True})
        self.assertNotEqual(one['room']['code'],two['room']['code']);self.assertNotIn('001255',server.ROOMS)
        for data in (one,two):
            r=data['room'];self.assertEqual(r['mode'],'standard');self.assertEqual(len(r['players']),4)
            self.assertEqual(sum(bool(p['bot']) for p in r['players']),3)
            self.assertTrue(r['game']['options']['advancedHui']);self.assertNotIn('_alternate',r['game']['options'])
            self.assertEqual(server.ROOMS[r['code']]['game'].pattern,(6,8))
        self.request(third,'leave',{})
        self.assertEqual(self.request(third,'join',{'code':one['room']['code']})[0],400)
        self.assertEqual(self.request(third,'join',{'code':'001255'})[0],200)
        self.assertEqual(self.request(first,'leave',{})[0],200)
        self.assertNotIn(one['room']['code'],server.ROOMS)

    def test_reserved_host_leaves_during_game_and_logs_out(self):
        first,second=self.clients[:2]
        self.request(first,'join',{'code':'001255'})
        self.request(second,'join',{'code':'001255'})
        for _ in range(2):self.request(first,'bot',{})
        self.assertEqual(self.request(first,'start',{})[0],200)
        room=server.ROOMS['001255'];self.assertEqual(room['game'].pattern,(6,8))
        self.assertEqual(self.request(first,'leave',{})[0],200)
        self.assertIsNone(room['game']);self.assertEqual(room['host'],self.users[1]['id'])
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status,data=self.request(other,'register',{'name':'临时房主','password':'testpass123'})
        self.assertEqual(status,200)
        self.request(second,'leave',{});self.request(other,'join',{'code':'001255'})
        self.request(first,'join',{'code':'001255'})
        self.assertEqual(self.request(other,'logout',{})[0],200)
        self.assertEqual(server.ROOMS['001255']['host'],self.users[0]['id'])

    def test_static_assets_are_versioned_and_never_cached(self):
        with urllib.request.urlopen(self.url+'/') as response:
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['CDN-Cache-Control'],'no-store')
            html=response.read().decode()
        for asset in ('app.js','audio.js','style.css'):
            url=re.search(r'/'+re.escape(asset)+r'\?v=[0-9a-f]{12}',html).group(0)
            with urllib.request.urlopen(self.url+url) as response:
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertEqual(response.headers['CDN-Cache-Control'],'no-store')
                self.assertEqual(response.read(),(server.ROOT/'public'/asset).read_bytes())

    def test_recorded_voice_assets_are_served_as_audio(self):
        with urllib.request.urlopen(self.url+'/audio/manifest.json') as response:
            voices=json.load(response)['voices']
        for key in ('pass','单张-8','对子-8','三带一对','连对'):
            self.assertTrue((server.ROOT/'public'/voices[key].split('?',1)[0].lstrip('/')).is_file())
        with urllib.request.urlopen(self.url+voices['pass']) as response:
            self.assertEqual(response.headers['Content-Type'],'audio/mpeg')
            self.assertGreater(len(response.read()),500)

    def test_audio_gate_requires_current_completion_acknowledgement(self):
        client=self.clients[0];headers={'X-Poker-Audio':'1'}
        self.request(client,'create',{'mode':'basic'},headers)
        for _ in range(3):self.request(client,'bot',{})
        status,data=self.request(client,'start',{},headers);self.assertEqual(status,200)
        room=data['room'];self.assertTrue(room['audioWaiting'])
        self.assertEqual(self.request(client,'action',{'action':'confirm','revision':room['revision']},headers)[0],400)
        self.request(client,'audio-ack',{'event':-1},headers)
        self.assertTrue(server.audio_waiting(server.ROOMS[room['code']]))
        self.request(client,'audio-ack',{'event':room['audioEvent']['id']},headers)
        self.assertFalse(server.audio_waiting(server.ROOMS[room['code']]))
        status,data=self.request(client,'action',{'action':'confirm','revision':room['revision']},headers)
        self.assertEqual(status,200);self.assertEqual(data['room']['audioEvent']['items'],[{'voice':'confirm'}])
        server.ROOMS[room['code']]['players'][0]['seen']=0
        self.assertFalse(server.audio_waiting(server.ROOMS[room['code']]))

    def test_audio_gate_waits_for_all_foreground_players(self):
        headers={'X-Poker-Audio':'1'}
        _,data=self.request(self.clients[0],'create',{'mode':'basic'},headers)
        code=data['room']['code']
        for client in self.clients[1:]:self.request(client,'join',{'code':code},headers)
        _,data=self.request(self.clients[0],'start',{},headers)
        room=server.ROOMS[code];event=data['room']['audioEvent']['id']
        for client in self.clients[:3]:
            self.request(client,'audio-ack',{'event':event},headers)
            self.assertTrue(server.audio_waiting(room))
        self.request(self.clients[3],'audio-ack',{'event':event},headers)
        self.assertFalse(server.audio_waiting(room))
        server.queue_audio(room,[{'voice':'pass'}])
        for client in self.clients[:3]:self.request(client,'audio-ack',{'event':room['audioEvent']['id']},headers)
        self.request(self.clients[3],'state',headers={'X-Poker-Audio':'0'})
        self.assertFalse(server.audio_waiting(room))

    def test_ace_round_start_resets_grades_and_reveals(self):
        client=self.clients[0];self.request(client,'create',{'mode':'standard'})
        for _ in range(3):self.request(client,'bot',{})
        self.request(client,'start',{})
        room=server.room_of(self.users[0]['id']);g=room['game'];g.phase='over';g.round_complete=True;g.finished=[0,2,1,3];g.scores=[11,5];g.captured=[1,3]
        self.assertEqual(self.request(client,'start',{})[0],200)
        self.assertEqual(room['game'].main,3);self.assertEqual(room['game'].scores,[0,0]);self.assertIsNone(room['game'].first);self.assertIsNone(room['game'].tribute)

    def test_account_settings_and_session_revocation(self):
        client=self.clients[3]
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.request(other,'login',{'name':'测试玩家3','password':'testpass123'})[0],200)
        self.assertEqual(self.request(client,'account',{'name':'新的名字','currentPassword':'wrongpass'})[0],400)
        self.assertEqual(self.request(client,'create',{'mode':'landlord'})[0],200)
        self.assertEqual(self.request(client,'account',{'name':'新的名字','currentPassword':'testpass123','newPassword':'newpass123'})[0],200)
        data=self.request(client,'state')[1]
        self.assertEqual(data['user']['name'],'新的名字')
        self.assertEqual(data['room']['players'][0]['name'],'新的名字')
        self.assertIsNone(self.request(other,'state')[1]['user'])
        self.assertEqual(self.request(other,'login',{'name':'新的名字','password':'testpass123'})[0],400)
        self.assertEqual(self.request(other,'login',{'name':'新的名字','password':'newpass123'})[0],200)
        self.assertEqual(self.request(client,'account',{'name':'测试玩家3','currentPassword':'newpass123','newPassword':'testpass123'})[0],200)

    def test_model_settings_apply_to_new_rooms_and_hide_key(self):
        client=self.clients[0]
        with patch.object(server,'validate_endpoint',return_value='https://example.com/v1'):
            self.assertEqual(self.request(client,'model-settings',{'endpoint':'https://example.com/v1','key':'private-test-key','model':'demo'})[0],200)
        state=self.request(client,'state')[1]
        self.assertEqual(state['preferences'],{'configured':True,'endpoint':'https://example.com/v1','model':'demo'})
        self.assertNotIn('private-test-key',json.dumps(state))
        self.assertTrue(state['features']['wildUrgent'])
        code=self.new_room(humans=1)
        self.assertEqual(self.request(client,'bot',{'model':True})[0],200)
        self.assertEqual(server.ROOMS[code]['modelConfig']['key'],'private-test-key')
        self.assertEqual(self.request(client,'model-settings',{'clear':True})[0],200)
        self.assertFalse(self.request(client,'state')[1]['preferences']['configured'])
        self.assertEqual(self.request(client,'bot',{'model':True})[0],400)

    def test_authentication_and_origin(self):
        anonymous=urllib.request.build_opener()
        self.assertEqual(self.request(anonymous,'create',{'mode':'landlord'})[0],401)
        self.assertEqual(self.request(anonymous,'state')[1]['user'],None)
        self.assertEqual(self.request(anonymous,'login',{'name':'测试玩家0','password':'wrongpass'})[0],400)
        self.assertEqual(self.request(anonymous,'register',{'name':'测试玩家0','password':'testpass123'})[0],400)
        self.assertEqual(self.request(self.clients[0],'create',{'mode':'landlord'},{'Origin':'https://evil.example'})[0],403)
        with server.db() as c:
            row=c.execute('SELECT password,salt FROM users LIMIT 1').fetchone()
            self.assertNotEqual(row['password'],'testpass123');self.assertEqual(len(row['salt']),32)

    def new_room(self,mode='landlord',humans=3):
        status,data=self.request(self.clients[0],'create',{'mode':mode})
        self.assertEqual(status,200,data)
        code=data['room']['code']
        for i in range(1,humans):self.assertEqual(self.request(self.clients[i],'join',{'code':code})[0],200)
        return code

    def test_solo_priority_waits_before_any_bot_or_model_dispatch(self):
        for mode in ('basic','standard'):
            server.ROOMS.clear()
            code=self.new_room(mode,1)
            for _ in range(3):self.request(self.clients[0],'bot',{})
            room=server.ROOMS[code]
            self.assertEqual([p['name'] for p in room['players'][1:]],['1号','2号','3号'])
            self.request(self.clients[0],'start',{})
            g=room['game'];g.phase='play';g.turn=0
            g.hands=[[{'id':str(s)+'-'+str(i),'rank':r,'suit':'H'} for i,r in enumerate(ranks)] for s,ranks in enumerate(([5,5,8],[7,9],[8,10],[5,5,9]))]
            g.action(0,'play',['0-0'])
            g.action(3,'priority-play',['3-0','3-1'],special='cross')
            self.assertEqual(g.priority['pending'],[0])
            state=self.request(self.clients[0],'state')[1]['room']['game']
            self.assertTrue(any(m['action']=='hook' for m in state['priority']['moves']))
            with patch.object(server.time,'sleep',side_effect=[None,StopIteration]),patch.object(server.threading.Thread,'start') as dispatch,patch.object(g,'bot_action') as bot:
                with self.assertRaises(StopIteration):server.bot_loop()
                dispatch.assert_not_called();bot.assert_not_called()
            status,_=self.request(self.clients[0],'action',{'action':'auto','ids':['0-1'],'revision':room['revision']})
            self.assertEqual(status,200);self.assertEqual(g.last['special'],'hook')

    def test_rooms_authority_and_privacy(self):
        code=self.new_room()
        self.assertEqual(self.request(self.clients[3],'join',{'code':code})[0],400)
        self.assertEqual(self.request(self.clients[1],'start',{})[0],400)
        self.assertEqual(self.request(self.clients[0],'start',{})[0],200)
        data=self.request(self.clients[0],'state')[1]['room']
        self.assertEqual(len(data['game']['hand']),17)
        self.assertNotIn('hands',data['game'])
        self.assertEqual(self.request(self.clients[0],'action',{'action':'bid','value':3,'revision':0})[0],400)
        status,_=self.request(self.clients[0],'action',{'action':'bid','value':3,'revision':data['revision']})
        self.assertEqual(status,200)
        data=self.request(self.clients[1],'state')[1]['room']
        self.assertEqual(self.request(self.clients[1],'action',{'action':'play','ids':[data['game']['hand'][0]['id']],'revision':data['revision']})[0],400)
        # Unknown/unowned cards cannot be injected into a hand.
        data=self.request(self.clients[0],'state')[1]['room']
        self.assertEqual(self.request(self.clients[0],'action',{'action':'play','ids':['forged'],'revision':data['revision']})[0],400)
        # A fresh client with the same session returns to exactly the same room.
        self.assertEqual(self.request(self.clients[0],'state')[1]['room']['code'],code)

    def test_all_human_result_and_idempotency(self):
        code=self.new_room('standard',4)
        self.request(self.clients[0],'start',{})
        room=server.ROOMS[code]
        for step in range(1000):
            g=room['game']
            if g.phase=='over':break
            for seat in range(4):
                move={'action':'priority-decline'} if g.priority and seat in g.priority['pending'] else g.bot_action(seat)
                if move:
                    move={k:v for k,v in move.items() if k in ('action','ids','target','rank','value','wildcard')}
                    move['revision']=room['revision']
                    status,result=self.request(self.clients[seat],'action',move)
                    self.assertEqual(status,200,result)
                    break
        self.assertEqual(room['game'].phase,'over')
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rating_events WHERE result_id=?',(room['matchId'],)).fetchone()[0],4)
            points=[c.execute('SELECT points FROM users WHERE id=?',(u['id'],)).fetchone()[0] for u in self.users]
        for seat,pts in enumerate(points):self.assertEqual(pts,1020 if seat in room['game'].winner else 980)
        server.persist_result(room)
        with server.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM rating_events WHERE result_id=?',(room['matchId'],)).fetchone()[0],4)
        self.assertEqual(len(self.request(self.clients[0],'history')[1]['history']),1)

    def test_new_round_has_a_new_match_identity(self):
        self.new_room('landlord',1)
        self.request(self.clients[0],'bot',{});self.request(self.clients[0],'bot',{})
        first=self.request(self.clients[0],'start',{})[1]['room']['matchId']
        self.assertEqual(self.request(self.clients[0],'state')[1]['room']['matchId'],first)
        self.request(self.clients[0],'resign',{})
        second=self.request(self.clients[0],'start',{})[1]['room']['matchId']
        self.assertNotEqual(first,second)

    def test_ai_games_never_change_rating(self):
        code=self.new_room('landlord',1)
        self.request(self.clients[0],'bot',{});self.request(self.clients[0],'bot',{})
        self.request(self.clients[0],'start',{})
        with server.db() as c:before=c.execute('SELECT points FROM users WHERE id=?',(self.users[0]['id'],)).fetchone()[0]
        self.request(self.clients[0],'resign',{})
        with server.db() as c:
            self.assertEqual(c.execute('SELECT points FROM users WHERE id=?',(self.users[0]['id'],)).fetchone()[0],before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rating_events WHERE result_id=?',(server.ROOMS[code]['matchId'],)).fetchone()[0],0)
        self.assertEqual(self.request(self.clients[0],'leave',{})[0],200)
        self.assertNotIn(code,server.ROOMS)

    def test_model_failure_falls_back_and_stale_response_is_ignored(self):
        code=self.new_room('landlord',1)
        self.request(self.clients[0],'bot',{});self.request(self.clients[0],'bot',{})
        self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.action(0,'bid',value=3)
        import copy
        old_count=len(g.hands[0]);version=room['revision']
        with patch.object(server,'model_move',side_effect=TimeoutError()):
            server.BOT_BUSY.add(code)
            server.tick_bot(code,0,version,copy.deepcopy(g),{})
        self.assertLess(len(g.hands[0]),old_count)
        self.assertNotIn(code,server.BOT_BUSY)
        version=room['revision'];old_hands=copy.deepcopy(g.hands)
        with patch.object(server,'model_move',return_value={'action':'pass'}):
            server.tick_bot(code,1,version-1,copy.deepcopy(g),{})
        self.assertEqual(room['revision'],version);self.assertEqual(g.hands,old_hands)

    def test_model_output_validation(self):
        g=Game('landlord',[{'name':str(i)} for i in range(3)]);g.action(0,'bid',value=3)
        response=unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':'{"index":0}'}}]}).encode()
        opener=unittest.mock.MagicMock();opener.open.return_value=response
        with patch.object(server,'validate_endpoint',return_value='https://example.com/v1'),patch.object(server.urllib.request,'build_opener',return_value=opener):
            move=server.model_move({'endpoint':'https://example.com/v1','key':'test-key','model':'test'},g,0)
            g.validate_play(0,g.select(0,move['ids']),move['action'])
            request=opener.open.call_args[0][0]
            payload=json.loads(request.data)
            self.assertNotIn('hands',payload['messages'][1]['content'])
            response.__enter__.return_value.read.return_value=b'{"choices":[{"message":{"content":"{\\"index\\":9999}"}}]}'
            with self.assertRaises(ValueError):server.model_move({'endpoint':'https://example.com/v1','key':'test','model':'test'},g,0)
        for url in ('http://example.com/v1','https://127.0.0.1/v1','https://user:pass@example.com/v1'):
            with self.assertRaises(ValueError):server.validate_endpoint(url)

if __name__=='__main__':unittest.main()
