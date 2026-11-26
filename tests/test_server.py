import http.cookiejar
import json
import re
import tempfile
import threading
import unittest
import urllib.error
from datetime import date, timedelta
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
        server.ROOMS.clear();server.WATCHING.clear()

    def test_checkin_once_daily_doubles_from_day_seven_and_resets_after_gap(self):
        local_day = date(2026,11,26)
        client = self.clients[0]
        uid = self.users[0]['id']
        initial = self.request(client,'state')[1]['user']['points']
        total = 0
        try:
            for offset, expected_streak in enumerate([1,2,3,4,5,6,7,8,0,1]):
                with patch.object(server,'checkin_day',return_value=local_day+timedelta(days=offset)), patch.object(server.secrets,'randbelow',return_value=20):
                    if expected_streak == 0:
                        self.assertEqual(self.request(client,'state')[1]['checkin']['streak'],8)
                        continue
                    points = 60 if expected_streak >= 7 else 30
                    total += points
                    expected = dict(checked=True,streak=expected_streak,reward=points)
                    for _ in range(2):
                        self.assertEqual(self.request(client,'checkin',{}) ,(200,{'checkin':expected}))
                    status = self.request(client,'state')[1]
                    self.assertEqual(status['checkin'],expected)
                    self.assertEqual(status['user']['points'],initial+total)
        finally:
            with server.db() as connection:
                connection.execute('DELETE FROM daily_checkins WHERE user_id=?',(uid,))
                connection.execute('UPDATE users SET points=? WHERE id=?',(initial,uid))

    def test_player_profile_is_visible_to_room_members_and_spectators(self):
        host, peer, viewer, outsider = self.clients
        _, created = self.request(host, 'create', {'mode': 'basic', 'options': {'allowSpectators': True}})
        code = {'code': created['room']['code']}
        self.request(peer, 'join', code)
        self.request(viewer, 'watch', code)
        path = 'leaderboard?roomPlayer=' + str(self.users[1]['id'])
        for client in (host, peer, viewer):
            status, data = self.request(client, path)
            self.assertEqual(status, 200)
            self.assertEqual(data['players'], [self.request(peer, 'state')[1]['user']])
        self.assertEqual(self.request(outsider, path)[0], 404)
        self.assertEqual(self.request(host, 'leaderboard?roomPlayer=' + str(self.users[3]['id']))[0], 404)

    def test_usage_tracks_start_completion_and_abandonment(self):
        client=self.clients[0]
        self.request(client,'create',{'mode':'landlord','single':True})
        for _ in range(2):self.request(client,'bot',{})
        self.assertEqual(self.request(client,'start',{})[0],200)
        room=server.room_of(self.users[0]['id']);match=room['matchId']
        self.assertEqual(self.request(client,'start',{})[0],400)
        self.assertEqual(self.request(client,'resign',{})[0],200)
        server.persist_result(room)
        with server.db() as c:
            row=c.execute('SELECT * FROM usage_matches WHERE id=?',(match,)).fetchone()
            self.assertEqual((row['status'],row['channel'],row['humans'],row['bots'],row['reason']),('completed','single',1,2,'resign'))
        self.request(client,'leave',{})
        self.request(client,'join',{'code':'001255','single':True})
        match=server.room_of(self.users[0]['id'])['matchId']
        self.request(client,'leave',{})
        with server.db() as c:
            row=c.execute('SELECT * FROM usage_matches WHERE id=?',(match,)).fetchone()
            self.assertEqual((row['status'],row['variant'],row['reason']),('interrupted','alternate','leave'))

    def test_stats_are_private_and_background_polling_does_not_record_activity(self):
        client=self.clients[0]
        with patch.object(server.STATS,'activity') as activity:
            self.request(client,'state',headers={'X-Poker-Audio':'0'});activity.assert_not_called()
            self.request(client,'state',headers={'X-Poker-Audio':'1'});activity.assert_called_once_with(self.users[0]['id'])
        self.assertEqual(self.request(client,'stats')[0],404)
        for path in ('/admin','/admin/index.html','/../admin/index.html','/analytics.py'):
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.url+path)
            self.assertEqual(error.exception.code,404)

    def test_web_playtest_is_scoped_to_granted_accounts_and_uses_per_run_model(self):
        from playtest_web import set_access

        alice, bob, ungranted = self.clients[:3]
        names = [user['name'] for user in self.users[:2]]
        for path in ('playtest', 'playtest/runs/0123456789abcdef/log'):
            self.assertEqual(self.request(ungranted,path)[0],403)
        self.assertEqual(self.request(ungranted,'playtest/runs',{'driver':'rules'})[0],403)
        with server.db() as db:
            for name in names:
                set_access(db,name,True)
        try:
            self.assertTrue(self.request(alice,'state')[1]['features']['playtest'])
            self.assertFalse(self.request(ungranted,'state')[1]['features']['playtest'])
            self.assertEqual(self.request(alice,'playtest/credential',{'key':'alice-test-only'}),(200,{'configured':True}))
            self.assertFalse(self.request(bob,'playtest')[1]['configured'])
            self.assertNotIn('alice-test-only',json.dumps(self.request(alice,'playtest')[1]))
            self.assertEqual(self.request(bob,'playtest/runs',{'driver':'deepseek'})[0],400)
            with patch('playtest.DeepSeek.choose', return_value=(0, {'total_tokens':7})):
                status,data=self.request(alice,'playtest/runs',{'mode':'landlord','model':'deepseek-v4-pro','thinking':True,'maxSteps':2})
                self.assertEqual(status,202,data)
                route='playtest/runs/'+data['id']
                for _ in range(120):
                    run=self.request(alice,route)[1]
                    if run['status'] not in ('queued','running'): break
                    __import__('time').sleep(.01)
                self.assertEqual(run['status'],'step_limit')
                self.assertEqual(run['model'],'deepseek-v4-pro')
                self.assertTrue(run['thinking'])
                self.assertGreater(run['calls'],0)
            self.assertEqual(self.request(bob,route)[0],404)
            self.assertEqual(self.request(bob,route+'/log')[0],404)
            replay=route+'/matches/1'
            self.assertEqual(self.request(bob,replay)[0],404)
            self.assertEqual(self.request(bob,replay+'/frames/1')[0],404)
            self.assertEqual(self.request(ungranted,replay+'/frames/1')[0],403)
            status,view=self.request(alice,replay)
            self.assertEqual(status,200)
            self.assertEqual(view['frames'],3)
            self.assertTrue(view['room']['spectator'])
            self.assertEqual(view['first']['game']['hand'],[])
            self.assertEqual([len(h['cards']) for h in view['first']['game']['publicHands']],[17,17,17])
            self.assertEqual(self.request(alice,replay+'/frames/2')[1]['step'],2)
            status, batch = self.request(alice,replay+'/frames/1/16')
            self.assertEqual(status,200)
            self.assertEqual([frame['step'] for frame in batch['frames']],[1,2])
            self.assertEqual(batch['frames'][1],self.request(alice,replay+'/frames/2')[1])
            self.assertEqual(self.request(alice,replay+'/frames/0/33')[0],400)
            self.assertEqual(self.request(alice,replay+'/frames/3/16')[0],404)
            self.assertEqual(self.request(bob,replay+'/frames/1/16')[0],404)
            self.assertEqual(self.request(ungranted,replay+'/frames/1/16')[0],403)
            self.assertEqual(self.request(alice,replay+'/frames/3')[0],404)
            self.assertEqual(self.request(alice,route+'/matches/2')[0],404)
            with alice.open(self.url+'/api/'+route+'/log') as response:
                self.assertIn('attachment;',response.headers['Content-Disposition'])
                log=response.read().decode()
                self.assertIn('run_finished',log)
                self.assertNotIn('alice-test-only',log)
            with server.db() as db:
                set_access(db,names[0],False)
            self.assertEqual(self.request(alice,route)[0],403)
        finally:
            with server.db() as db:
                for name in names:
                    set_access(db,name,False)

    def test_play_preview_uses_the_submitted_rules_without_playing_the_cards(self):
        client = self.clients[0]
        for mode in ('standard', 'conveyor'):
            with self.subTest(mode=mode):
                server.ROOMS.clear()
                self.request(client, 'create', {'mode': mode, 'single': True})
                for _ in range(3):
                    self.request(client, 'bot', {})
                if mode == 'conveyor':
                    self.request(client, 'skill', {'skill': 'balance'})
                self.request(client, 'start', {})
                room = server.room_of(self.users[0]['id'])
                game = room['game']
                core = game.core if mode == 'conveyor' else game
                core.phase, core.turn = 'play', 0
                card = {'id': 'test-5', 'suit': 'H', 'rank': 5}
                core.hands[0] = [card, {'id': 'test-8', 'suit': 'D', 'rank': 8}]
                revision = room['revision']
                sample = {'ids': [card['id']], 'revision': revision}
                if mode == 'conveyor':
                    sample['actor'] = 0
                self.assertEqual(self.request(client, 'play-preview', sample), (200, {'kind': '单张'}))
                self.assertEqual(self.request(client, 'play-preview', {**sample, 'revision': revision - 1}), (200, {'stale': True}))
                self.assertEqual(room['revision'], revision)
                self.assertIsNone(core.last)
                self.assertIn(card, core.hands[0])
                result, data = self.request(client, 'action', {'action': 'auto', **sample})
                self.assertEqual(result, 200, data)
                self.assertEqual(core.seat_plays[0]['kind'], '单张')

    def test_tribute_option_is_saved_and_controls_next_deal(self):
        client=self.clients[0]
        for mode in ('basic','standard'):
            for enabled in (False,True):
                server.ROOMS.clear()
                _,data=self.request(client,'create',{'mode':mode,'options':{'tribute':enabled}})
                self.assertEqual(data['room']['options']['tribute'],enabled)
                for _ in range(3):self.request(client,'bot',{})
                self.request(client,'start',{})
                room=server.room_of(self.users[0]['id']);g=room['game']
                self.assertEqual(g.phase,'setup')
                g.phase='over';g.finished=[0,2,1,3];g.captured=[1,3]
                status,data=self.request(client,'start',{})
                self.assertEqual(status,200)
                if enabled: self.assertEqual(data['room']['game']['phase'],'tribute')
                else: self.assertIn(data['room']['game']['phase'],('setup','play'))

    def test_reserved_room_never_enables_tribute(self):
        client=self.clients[0]
        for single in (False,True):
            server.ROOMS.clear()
            _,data=self.request(client,'join',{'code':'001255','single':single,'options':{'tribute':True}})
            room=server.room_of(self.users[0]['id'])
            self.assertFalse(data['room']['options']['tribute'])
            if not single:
                for _ in range(3):self.request(client,'bot',{})
                self.request(client,'start',{})
            g=room['game'];g.phase='over';g.finished=[0,2,1,3];g.captured=[1,3]
            self.assertEqual(self.request(client,'start',{})[0],200)
            self.assertIn(room['game'].phase,('setup','play'));self.assertIsNone(room['game'].tribute)

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
        self.assertIsNotNone(room['game']);self.assertEqual(room['host'],self.users[1]['id'])
        self.assertTrue(room['players'][0]['autoplay']);self.assertIsNone(server.room_of(self.users[0]['id']))
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status,data=self.request(other,'register',{'name':'临时房主','password':'testpass123'})
        self.assertEqual(status,200)
        self.request(second,'leave',{});self.request(other,'join',{'code':'001255'})
        self.request(first,'join',{'code':'001255'})
        self.assertEqual(self.request(other,'logout',{})[0],200)
        self.assertEqual(server.ROOMS['001255']['host'],self.users[0]['id'])

    def test_multiplayer_exit_preserves_game_and_seat_even_during_audio(self):
        code=self.new_room('basic',4)
        self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];game=room['game']
        for p in room['players']: p.update(audioEnabled=True,seen=__import__('time').time())
        server.queue_audio(room,[{'voice':'deal'}])
        status,data=self.request(self.clients[0],'resign',{})
        self.assertEqual(status,200);self.assertIsNone(data['room'])
        self.assertIs(room['game'],game);self.assertNotEqual(game.phase,'over')
        self.assertEqual(len(room['players']),4);self.assertTrue(room['players'][0]['autoplay'])
        self.assertIsNone(server.room_of(self.users[0]['id']))
        self.assertEqual(room['host'],self.users[1]['id'])

    def test_single_can_end_during_opening_audio(self):
        self.request(self.clients[0],'create',{'mode':'basic','single':True})
        for _ in range(3):self.request(self.clients[0],'bot',{})
        self.request(self.clients[0],'start',{})
        room=server.room_of(self.users[0]['id'])
        room['players'][0].update(audioEnabled=True,seen=__import__('time').time())
        server.queue_audio(room,[{'voice':'deal'}])
        self.assertTrue(server.audio_waiting(room))
        self.assertEqual(self.request(self.clients[0],'resign',{})[0],200)
        self.assertEqual(room['game'].phase,'over')

    def test_audio_ack_from_previous_match_cannot_release_current_event(self):
        code=self.new_room('basic',4);room=server.ROOMS[code];room['matchId']='current'
        server.queue_audio(room,[{'voice':'deal'}]);event=room['audioEvent']
        status,_=self.request(self.clients[0],'audio-ack',{'event':event['id'],'code':code,'matchId':'old'})
        self.assertEqual(status,200);self.assertEqual(event['acknowledged'],[])
        self.request(self.clients[0],'audio-ack',{'event':event['id'],'code':code,'matchId':'current'})
        self.assertEqual(event['acknowledged'],[self.users[0]['id']])

    def test_confirmation_skips_ineligible_players_and_moves_counterclockwise(self):
        code=self.new_room('standard',4);self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.phase='setup'
        g.hands=[[{'rank':rank,'suit':suit} for rank,suit in hand] for hand in (
            [(3,'S')],[(7,'H')]*6,[(5,'H')],[(3,'S')])]
        for seat in [0,3,1]:
            self.assertEqual(server.confirmation_seat(room),seat)
            self.assertEqual(self.request(self.clients[2],'action',{'action':'confirm','revision':room['revision']})[0],400)
            self.assertEqual(self.request(self.clients[seat],'action',{'action':'confirm','revision':room['revision']})[0],200)
        self.assertEqual(g.phase,'play')

    def test_priority_clock_is_public_and_expires_without_solo_takeover(self):
        code=self.new_room('basic',4);self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.phase='play';g.priority={'pending':[1,2],'bots':[]}
        server.update_priority_clock(room)
        self.assertEqual(server.room_view(room,self.users[3]['id'])['game']['priorityClock']['seat'],1)
        room['priorityClock']['expires']=0;server.update_priority_clock(room)
        self.assertNotIn(1,g.priority['pending'])
        room['single']=True;server.update_priority_clock(room)
        self.assertNotIn('priorityClock',room)

    def test_suitmark_selected_suit_reaches_the_game_through_http(self):
        from conveyor import ConveyorGame
        code=self.new_room('basic',4);room=server.ROOMS[code]
        for player,skill in zip(room['players'],['suitmark','balance','anchor','leap']):player['skill']=skill
        g=ConveyorGame('conveyor',room['players'],{'skillDlc':[1]})
        room.update(game=g,mode='conveyor');g.phase='play';g.core.pending=[];g.core.turn=0
        g.core.offer(0,'suitmark','烙印',target=1,suits=['C','H'])
        status,data=self.request(self.clients[0],'action',{'action':'choice','actor':0,'suit':'C','revision':room['revision']})
        self.assertEqual(status,200,data)
        self.assertEqual(data['room']['game']['conveyor']['actors'][1]['resources']['suits'],['C'])

    def test_priority_clock_pauses_during_an_intervening_announcement(self):
        code=self.new_room('basic',4);self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.phase='play';g.priority={'pending':[1],'bots':[]}
        with patch.object(server.time,'time',return_value=100):server.update_priority_clock(room)
        room['players'][0].update(audioEnabled=True,seen=100);server.queue_audio(room,[{'voice':'pass'}])
        with patch.object(server.time,'time',return_value=102):server.update_priority_clock(room)
        with patch.object(server.time,'time',return_value=106):
            self.assertEqual(server.room_view(room,self.users[3]['id'])['game']['priorityClock']['remaining'],3)
        room['audioEvent']['acknowledged']=[self.users[0]['id']]
        with patch.object(server.time,'time',return_value=107):server.update_priority_clock(room)
        self.assertEqual(room['priorityClock']['expires'],110)
        self.assertEqual(g.priority['pending'],[1])

    def test_priority_clock_shows_full_time_while_the_opening_voice_plays(self):
        code=self.new_room('basic',4);self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.phase='play';g.priority={'pending':[1],'bots':[]}
        room['players'][0].update(audioEnabled=True,seen=100)
        with patch.object(server.time,'time',return_value=100):
            server.queue_audio(room,[{'voice':'单张-5'}])
            clock=server.room_view(room,self.users[1]['id'])['game']['priorityClock']
            self.assertTrue(clock['paused'])
            self.assertEqual(clock['remaining'],5)
        with patch.object(server.time,'time',return_value=108):
            server.update_priority_clock(room)
            self.assertEqual(g.priority['pending'],[1])
            room['audioEvent']['acknowledged']=[self.users[0]['id']]
            clock=server.room_view(room,self.users[1]['id'])['game']['priorityClock']
            self.assertFalse(clock['paused'])
            self.assertEqual(clock['remaining'],5)

    def test_autoplay_response_precedes_automatic_pass_for_other_seat(self):
        code=self.new_room('basic',4);self.request(self.clients[0],'start',{})
        room=server.ROOMS[code];g=room['game'];g.phase='play'
        g.priority={'pending':[1],'bots':[]};room['players'][1]['autoplay']=True
        g.forced_pass=lambda:True
        g.bot_action=lambda seat:{'action':'priority-decline'}
        with patch.object(server,'update_autoplay'),patch.object(server,'perform_game_action') as action,patch.object(server.time,'sleep',side_effect=[None,RuntimeError('loop stopped')]):
            with self.assertRaisesRegex(RuntimeError,'loop stopped'):server.bot_loop()
        action.assert_called_once_with(room,1,{'action':'priority-decline'})

    def test_priority_clock_tracks_twins_b_hand(self):
        from conveyor import ConveyorGame
        code=self.new_room('basic',4);room=server.ROOMS[code]
        for player,skill in zip(room['players'],['twins','balance','anchor','leap']):player['skill']=skill
        g=ConveyorGame('conveyor',room['players'],{'skillDlc':[3]})
        room.update(game=g,mode='conveyor')
        g.phase='play';g.core.pending=[];g.core.turn=0
        g.core.priority={'pending':[1],'bots':[]}
        server.update_priority_clock(room)
        self.assertEqual(server.room_view(room,self.users[3]['id'])['game']['priorityClock']['actor'],1)
        with self.assertRaisesRegex(server.RuleError,'等待优先'):
            server.perform_game_action(room,0,{'action':'pass','actor':0})
        room['priorityClock']['expires']=0;server.update_priority_clock(room)
        self.assertFalse(g.core.priority)

    def test_buy_logs_the_card_and_preserves_private_gain_voice(self):
        from conveyor import ConveyorGame
        room=server.ROOMS[self.new_room('basic',4)]
        for player, skill in zip(room['players'], ('money','anchor','anchor','anchor')):
            player['skill']=skill
        g=ConveyorGame('conveyor',room['players'])
        room.update(mode='conveyor',game=g)
        c=g.core
        c.phase='play'; c.pending=[]; c.turn=0
        card=dict(id='public-buy',rank=9,suit='D')
        c.discard.append(card)
        c.resources[0]['money']=4
        c.offer(0,'buy','聚宝',cards=[card])
        server.perform_game_action(room,0,{'action':'choice','ids':[card['id']]})
        for seat, user in enumerate(self.users):
            view=server.room_view(room,user['id'])
            self.assertTrue(any('买入方片9' in line for line in view['game']['log']))
            self.assertFalse(any('获得1张牌' in line for line in view['game']['log']))
            voices = [item.get('voice') for item in view['audioEvent']['items']]
            self.assertIn('cv-choice', voices)
            self.assertIn('cv-suit-D', voices)
            self.assertIn('单张-9', voices)
            self.assertEqual('cv-deal-1' in voices, seat == 0)
        c.offer(0,'deal','选择发牌',maximum=1)
        server.perform_game_action(room,0,{'action':'choice','value':1})
        self.assertTrue(any('获得1张牌' in line for line in c.log))

    def test_draw_voice_is_visible_only_to_recipient(self):
        code=self.new_room('basic',4);room=server.ROOMS[code]
        server.queue_audio(room,[{'voice':'cv-deal-2','recipient':self.users[1]['id']},{'dealTo':1,'count':2}])
        for i,user in enumerate(self.users):
            items=server.room_view(room,user['id'])['audioEvent']['items']
            self.assertEqual(any('voice' in item for item in items),i==1)
            self.assertTrue(any(item.get('dealTo')==1 for item in items))
            self.assertTrue(all('recipient' not in item for item in items))

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

    def test_autoplay_runs_rules_and_cancels_even_during_audio(self):
        client=self.clients[0]
        _,data=self.request(client,'create',{'mode':'landlord'})
        for _ in range(2):self.request(client,'bot',{})
        _,data=self.request(client,'start',{})
        room=server.ROOMS[data['room']['code']];g=room['game'];g.phase='play';g.turn=0;g.landlord=0
        g.hands[0]=[{'id':'a'+str(i),'rank':r,'suit':'H'} for i,r in enumerate([3,4,5,6,7,9])]
        for seat in (1,2):g.hands[seat]=[{'id':str(seat)+str(i),'rank':r,'suit':'H'} for i,r in enumerate([8,10])]
        status,data=self.request(client,'autoplay',{'enabled':True})
        self.assertEqual(status,200);self.assertTrue(data['room']['players'][0]['autoplay'])
        self.assertFalse(room['players'][0].get('bot'))
        self.assertEqual(self.request(client,'action',{'action':'pass','revision':room['revision']})[0],400)
        before=len(g.hands[0])
        with patch('server.time.sleep',side_effect=[None,RuntimeError('stop loop')]),patch('server.model_move',side_effect=AssertionError('must use rules')):
            with self.assertRaisesRegex(RuntimeError,'stop loop'):server.bot_loop()
        self.assertLess(len(g.hands[0]),before)
        room['players'][0]['audioEnabled']=True
        server.queue_audio(room,[{'voice':'pass'}])
        status,data=self.request(client,'autoplay',{'enabled':False},{'X-Poker-Audio':'1'})
        self.assertEqual(status,200);self.assertFalse(data['room']['players'][0]['autoplay'])
        g.turn=0;g.last=None;before=len(g.hands[0])
        room['players'][0]['audioEnabled']=False
        for p in room['players'][1:]:p['bot']=False
        with patch('server.time.sleep',side_effect=[None,RuntimeError('stop loop')]),patch.object(g,'bot_action',side_effect=AssertionError('manual player must not run')):
            with self.assertRaisesRegex(RuntimeError,'stop loop'):server.bot_loop()
        self.assertEqual(len(g.hands[0]),before)
        self.assertEqual(self.request(client,'autoplay',{'enabled':'true'})[0],400)

    def test_autoplay_keeps_multiplayer_room_rated_and_only_changes_self(self):
        first=self.clients[0]
        _,data=self.request(first,'create',{'mode':'standard'})
        for client in self.clients[1:]:self.request(client,'join',{'code':data['room']['code']})
        _,data=self.request(first,'start',{})
        status,data=self.request(self.clients[1],'autoplay',{'enabled':True,'seat':0})
        self.assertEqual(status,200);self.assertTrue(data['room']['rated'])
        self.assertTrue(data['room']['players'][1]['autoplay']);self.assertFalse(data['room']['players'][0]['autoplay'])
        self.assertFalse(data['room']['players'][1]['bot'])
        room=server.ROOMS[data['room']['code']]
        g=room['game'];g.phase='play';g.turn=1
        self.assertIsNotNone(g.bot_action(1))

    def test_wildcard_bomb_passes_back_to_airplane_or_pair_run(self):
        client=self.clients[0]
        for follow in ([11,11,11,12,12,12,8,10],[4,4,5,5,6,6]):
            server.ROOMS.clear()
            _,data=self.request(client,'create',{'mode':'standard'})
            for _ in range(3):self.request(client,'bot',{})
            _,data=self.request(client,'start',{})
            room=server.ROOMS[data['room']['code']];g=room['game'];g.phase='play';g.turn=0
            def hand(ranks,prefix):
                return [{'id':prefix+str(i),'rank':r,'suit':'S' if r==14 else 'H'} for i,r in enumerate(ranks)]
            g.hands[0]=hand([9,9,9,14]+follow+[7],'a')
            for seat in (1,2,3):g.hands[seat]=hand([5,6,8],str(seat))
            status,data=self.request(client,'action',{'action':'auto','ids':['a0','a1','a2','a3'],'wildcard':9,'revision':room['revision']})
            self.assertEqual(status,200);self.assertEqual(g.last['power'],4)
            for seat in (3,2,1):server.perform_game_action(room,seat,{'action':'pass'})
            self.assertEqual(g.turn,0);self.assertIsNone(g.last)
            status,data=self.request(client,'action',{'action':'auto','ids':['a'+str(i) for i in range(4,4+len(follow))],'revision':room['revision']})
            self.assertEqual(status,200)
            self.assertEqual(data['room']['game']['last']['kind'],'飞机带单' if len(follow)==8 else '连对')

    def test_three_jokers_hint_and_play_beat_five_and_six_card_bombs(self):
        client=self.clients[0]
        for size in (5,6):
            for jokers in ([16,16,17],[16,17,17],[17,17,17]):
                server.ROOMS.clear()
                _, data=self.request(client,'create',{'mode':'standard'})
                for _ in range(3):self.request(client,'bot',{})
                _,data=self.request(client,'start',{})
                room=server.ROOMS[data['room']['code']];g=room['game'];g.phase='play';g.turn=1
                def hand(ranks,prefix):
                    return [{'id':prefix+str(i),'rank':rank,'suit':'J' if rank>=16 else 'H'} for i,rank in enumerate(ranks)]
                g.hands[0]=hand(jokers+[8],'a');g.hands[1]=hand([5]*(size-1)+[14,10],'b')
                g.hands[1][size-1]['suit']='S'
                g.hands[2]=hand([6,7],'c');g.hands[3]=hand([6,7],'d')
                _,hint=self.request(client,'hint',{})
                self.assertEqual(hint['reason'],'还没轮到你出牌。')
                g.priority={'pending':[],'bots':[1]}
                _,hint=self.request(client,'hint',{})
                self.assertEqual(hint['reason'],'等待优先管牌处理完成。')
                g.priority=None
                server.perform_game_action(room,1,{'action':'auto','ids':['b'+str(i) for i in range(size)],'wildcard':5})
                self.assertEqual(g.last['power'],size)
                self.assertEqual(g.last['ranks'],[5]*size)
                self.assertEqual(g.turn,0)
                status,data=self.request(client,'hint',{})
                self.assertEqual(status,200)
                self.assertTrue(any(m['label']=='王炸' and m['power']==6.5 and set(m['ids'])=={'a0','a1','a2'} for m in data['moves']))
                status,data=self.request(client,'action',{'action':'auto','ids':['a0','a1','a2'],'revision':room['revision']})
                self.assertEqual(status,200)
                self.assertEqual(data['room']['game']['last']['power'],6.5)

    def test_server_automatically_passes_without_requesting_a_bot_move(self):
        self.request(self.clients[0], 'create', {'mode': 'basic'})
        for _ in range(3): self.request(self.clients[0], 'bot', {})
        _, data = self.request(self.clients[0], 'start', {})
        room = server.ROOMS[data['room']['code']];g=room['game'];g.phase='play';g.turn=1
        def hand(ranks, prefix):
            return [{'id': prefix+str(i), 'rank':r, 'suit':'H'} for i,r in enumerate(ranks)]
        g.hands=[hand([7,8],'a'),hand([5,9],'b'),hand([6,7],'c'),hand([5,5,9],'d')]
        g.action(1,'play',['b0']);g.action(3,'cross',['d0','d1'])
        g.turn=0;g.priority=None
        revision=room['revision']
        room['players'][0]['audioEnabled']=True
        server.queue_audio(room,[{'voice':'pass'}])
        with patch('server.time.sleep', side_effect=[None, RuntimeError('stop loop')]), patch.object(g,'forced_pass', side_effect=AssertionError('wait for narration')):
            with self.assertRaisesRegex(RuntimeError,'stop loop'): server.bot_loop()
        self.assertEqual(room['revision'],revision)
        room['audioEvent']['acknowledged']=[room['players'][0]['id']]
        with patch('server.time.sleep', side_effect=[None, RuntimeError('stop loop')]), patch.object(g,'bot_action', side_effect=AssertionError('must skip first')):
            with self.assertRaisesRegex(RuntimeError,'stop loop'): server.bot_loop()
        self.assertEqual(g.turn,3)
        self.assertEqual(room['revision'],revision+1)
        self.assertTrue(g.seat_plays[0]['passed'])
        self.assertEqual(room['audioEvent']['items'],[{'voice':'pass'}])

    def test_advanced_options_default_on_and_allow_explicit_disable(self):
        for mode in ('standard', 'trio', 'basic', 'landlord'):
            for options in ({}, {'advancedHui': False, 'advancedDead': False}):
                server.ROOMS.clear()
                status, data = self.request(self.clients[0], 'create', {'mode': mode, 'options': options})
                self.assertEqual(status, 200)
                for key in ('advancedHui', 'advancedDead'):
                    self.assertEqual(data['room']['options'][key], mode in ('standard', 'trio') and not options)

    def test_automatic_autoplay_times_only_required_player_and_offline_host(self):
        players=[{'id':i+1,'name':str(i),'seen':100,'connected':True} for i in range(4)]
        g=Game('basic',players,interactive=True);g.phase='play';g.turn=1
        room={'host':1,'players':players,'game':g,'revision':1}
        for now in (100,159):
            players[0]['seen']=now
            with patch('server.time.time',return_value=now):server.update_autoplay(room)
            self.assertFalse(players[1].get('autoplay'))
        players[0]['seen']=160
        with patch('server.time.time',return_value=160):server.update_autoplay(room)
        self.assertTrue(players[1]['autoplay']);self.assertFalse(players[2].get('autoplay'));self.assertFalse(players[3].get('autoplay'))
        self.assertEqual(room['revision'],2);self.assertFalse(players[1].get('bot'))
        g.phase='setup';players[0]['seen']=200
        with patch('server.time.time',return_value=214):server.update_autoplay(room)
        self.assertFalse(players[0].get('autoplay'))
        with patch('server.time.time',return_value=215):server.update_autoplay(room)
        self.assertTrue(players[0]['autoplay'])

    def test_idle_timeout_pauses_during_audio_and_resets_after_action(self):
        players=[{'id':i+1,'name':str(i),'seen':100,'connected':True} for i in range(4)]
        g=Game('basic',players,interactive=True);g.phase='play';g.turn=1
        room={'host':1,'players':players,'game':g,'revision':1}
        players[1]['audioEnabled']=True
        server.queue_audio(room,[{'voice':'pass'}])
        for now in (100,180):
            players[0]['seen']=now;players[1]['seen']=now
            with patch('server.time.time',return_value=now):server.update_autoplay(room)
            self.assertNotIn('idleWait',room)
        room['audioEvent']['acknowledged']=[2]
        for now in (200,259):
            players[0]['seen']=now
            with patch('server.time.time',return_value=now):server.update_autoplay(room)
            self.assertFalse(players[1].get('autoplay'))
        players[0]['seen']=260
        with patch('server.time.time',return_value=260):server.update_autoplay(room)
        self.assertTrue(players[1]['autoplay'])
        room['idleWait']={1:200}
        card=g.hands[1][0]
        server.perform_game_action(room,1,{'action':'play','ids':[card['id']]})
        self.assertNotIn('idleWait',room)

    def test_spectator_has_public_view_and_cannot_control_or_block_game(self):
        host,viewer=self.clients[:2]
        _,data=self.request(host,'create',{'mode':'landlord','options':{'allowSpectators':True}})
        code=data['room']['code']
        for _ in range(2):self.request(host,'bot',{})
        room=server.ROOMS[code]
        status,data=self.request(viewer,'watch',{'code':code})
        self.assertEqual(status,200);self.assertTrue(data['room']['spectator']);self.assertIsNone(data['room']['seat'])
        self.assertEqual(len(room['players']),3)
        self.request(host,'start',{}, {'X-Poker-Audio':'1'})
        status,data=self.request(viewer,'state',headers={'X-Poker-Audio':'1'})
        watch=data['room'];self.assertTrue(watch['spectator']);self.assertEqual(watch['game']['hand'],[])
        g=room['game']
        self.assertEqual(watch['game']['publicHands'],
                         [dict(owner=s,actor=s,cards=g.visible_hand(s)) for s in range(3)])
        self.assertEqual(self.request(host,'state')[1]['room']['game']['publicHands'],[])
        g.hands[1].pop()
        self.assertEqual(self.request(viewer,'state')[1]['room']['game']['publicHands'][1]['cards'],g.visible_hand(1))
        self.assertIsNone(watch['game']['response']);self.assertIsNone(watch['game']['priority'])
        self.assertIsNone(watch['audioEvent']);self.assertFalse(watch['audioWaiting'])
        self.assertNotIn(self.users[1]['id'],room['audioEvent']['listeners'])
        for path,body in (('action',{'action':'pass','revision':room['revision']}),('autoplay',{'enabled':True}),('resign',{}),('start',{}),('bot',{}),('chat',{'text':'悲'})):
            self.assertEqual(self.request(viewer,path,body)[0],400)
        self.assertEqual(self.request(viewer,'join',{'code':code})[0],400)
        before=room['revision'];self.assertEqual(self.request(viewer,'leave',{})[0],200)
        self.assertEqual(room['revision'],before);self.assertIsNotNone(room['game'])
        self.assertIsNone(self.request(viewer,'state')[1]['room'])

    def test_watch_permissions_closed_rooms_and_practice_rooms(self):
        host,viewer=self.clients[:2]
        _,data=self.request(host,'create',{'mode':'standard'})
        code=data['room']['code']
        self.assertFalse(data['room']['options']['allowSpectators'])
        self.assertEqual(self.request(viewer,'watch',{'code':code})[0],400)
        server.ROOMS[code]['options']['allowSpectators']=True
        self.assertEqual(self.request(viewer,'watch',{'code':code})[0],200)
        self.request(host,'leave',{})
        self.assertIsNone(self.request(viewer,'state')[1]['room']);self.assertNotIn(self.users[1]['id'],server.WATCHING)
        _,data=self.request(host,'create',{'mode':'basic','single':True,'options':{'allowMatching':True,'allowSpectators':True}})
        self.assertFalse(data['room']['options']['allowMatching']);self.assertFalse(data['room']['options']['allowSpectators'])
        self.assertEqual(self.request(viewer,'watch',{'code':data['room']['code']})[0],400)

    def test_match_counts_and_join_filter_private_full_active_and_offline_rooms(self):
        host,joiner=self.clients[:2]
        _,data=self.request(host,'create',{'mode':'standard','options':{'allowMatching':True}})
        code=data['room']['code'];room=server.ROOMS[code]
        self.assertEqual(self.request(joiner,'state')[1]['matchCounts']['standard'],1)
        self.assertEqual(self.request(joiner,'match',{'mode':'basic'})[0],400)
        room['options']['allowMatching']=False
        self.assertEqual(self.request(joiner,'state')[1]['matchCounts']['standard'],0)
        self.assertEqual(self.request(joiner,'match',{'mode':'standard'})[0],400)
        room['options']['allowMatching']=True
        room['players'][0]['seen']=0
        self.assertEqual(self.request(joiner,'state')[1]['matchCounts']['standard'],0)
        self.request(host,'state')
        status,data=self.request(joiner,'match',{'mode':'standard'})
        self.assertEqual(status,200);self.assertEqual(data['room']['code'],code)
        room['players'][0]['seen']=0
        self.assertEqual(self.request(self.clients[2],'state')[1]['matchCounts']['standard'],0)
        self.request(host,'state')
        for _ in range(2):self.request(host,'bot',{})
        self.assertEqual(self.request(self.clients[2],'state')[1]['matchCounts']['standard'],0)
        self.request(host,'start',{})
        self.assertEqual(self.request(self.clients[2],'match',{'mode':'standard'})[0],400)

    def test_matching_cannot_overfill_room_or_expose_reserved_room(self):
        from concurrent.futures import ThreadPoolExecutor
        host=self.clients[0]
        _,data=self.request(host,'create',{'mode':'landlord','options':{'allowMatching':True}})
        code=data['room']['code']
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda client:self.request(client,'match',{'mode':'landlord'})[0],self.clients[1:]))
        self.assertEqual(sorted(results),[200,200,400]);self.assertEqual(len(server.ROOMS[code]['players']),3)
        server.ROOMS.clear()
        _,data=self.request(host,'join',{'code':'001255'})
        self.assertEqual(data['room']['code'],'001255')
        server.ROOMS['001255']['options']['allowMatching']=True
        self.assertEqual(self.request(self.clients[1],'state')[1]['matchCounts']['standard'],0)
        self.assertEqual(self.request(self.clients[1],'match',{'mode':'standard'})[0],400)
        self.assertEqual(self.request(self.clients[1],'join',{'code':'001255'})[0],200)

    def test_four_players_can_display_messages_at_the_same_time(self):
        _,data=self.request(self.clients[0],'create',{'mode':'standard'})
        for client in self.clients[1:]:self.request(client,'join',{'code':data['room']['code']})
        self.request(self.clients[0],'start',{})
        expected={}
        for seat,client in enumerate(self.clients):
            text=server.CHAT_PHRASES[seat%len(server.CHAT_PHRASES)]
            status,data=self.request(client,'chat',{'text':text})
            self.assertEqual(status,200)
            expected[str(seat)]=text
        for client in self.clients:self.assertEqual(self.request(client,'state')[1]['room']['bubbles'],expected)

    def test_chat_is_preset_only_shared_temporary_and_does_not_change_game_revision(self):
        first, second = self.clients[:2]
        _, data = self.request(first, 'create', {'mode': 'standard'})
        code = data['room']['code']
        self.request(second, 'join', {'code': code})
        for _ in range(2): self.request(first, 'bot', {})
        _, data = self.request(first, 'start', {})
        revision = data['room']['revision']
        event = data['room']['audioEvent']
        for text in server.CHAT_PHRASES:
            server.ROOMS[code].pop('bubbles', None)
            status, data = self.request(first, 'chat', {'text': text})
            self.assertEqual(status, 200)
            self.assertEqual(data['room']['bubbles'], {'0': text})
            self.assertEqual(data['room']['revision'], revision)
            self.assertEqual(data['room']['audioEvent'], event)
            self.assertEqual(self.request(second, 'state')[1]['room']['bubbles'], {'0': text})
        self.assertEqual(self.request(first, 'chat', {'text': '悲'})[0], 400)
        for text in ('任意文本', '<script>alert(1)</script>', None, ['悲']):
            self.assertEqual(self.request(first, 'chat', {'text': text})[0], 400)
        with patch('server.time.time', return_value=__import__('time').time() + 7):
            self.assertEqual(self.request(second, 'state')[1]['room']['bubbles'], {})
        self.assertEqual(self.request(self.clients[2], 'chat', {'text': '悲'})[0], 400)

    def test_show_hand_is_public_live_and_resets_next_match(self):
        first,second=self.clients[:2]
        _,data=self.request(first,'create',{'mode':'standard'})
        code=data['room']['code'];self.request(second,'join',{'code':code})
        for _ in range(2):self.request(first,'bot',{})
        self.request(first,'start',{});room=server.ROOMS[code];g=room['game']
        self.assertEqual(self.request(first,'show-hand',{})[0],200)
        g.phase='play';g.turn=1
        g.hands[0]=list(reversed(g.visible_hand(0)))
        status,data=self.request(first,'show-hand',{})
        self.assertEqual(status,200)
        public=self.request(second,'state')[1]['room']['game']['publicHands']
        self.assertEqual([h['owner'] for h in public],[0])
        self.assertEqual(public[0]['cards'],g.view(0)['hand'])
        g.hands[0].pop()
        self.assertEqual(len(server.room_view(room,None)['game']['publicHands'][0]['cards']),len(g.hands[0]))
        room['matchId']='next-match'
        self.assertEqual(server.room_view(room,None)['game']['publicHands'],[])

    def test_report_uses_shared_bubble_once_instead_of_log(self):
        first=self.clients[0]
        _,data=self.request(first,'create',{'mode':'standard','single':True})
        for _ in range(3):self.request(first,'bot',{})
        self.request(first,'start',{});room=server.room_of(self.users[0]['id']);g=room['game']
        g.phase='play';g.turn=0;g.last=None;g.priority=None
        g.hands[0]=[dict(id='report-'+str(i),rank=4,suit='H') for i in range(11)]
        server.perform_game_action(room,0,dict(action='auto',ids=['report-0']))
        self.assertEqual(server.room_view(room,None)['bubbles']['0'],'我只剩10张牌了')
        self.assertFalse(any('爆牌' in line for line in g.log))
        g.report(0);self.assertEqual(g.report_counts[0],10)

    def test_extended_airplane_uses_recorded_voice(self):
        players = [{'id': i, 'name': str(i)} for i in range(4)]
        for wings, voice in (([], '飞机'), ([8, 9, 10, 11], '飞机带单'), ([8, 8, 9, 9, 10, 10, 11, 11], '飞机带对')):
            g = Game('standard', players); g.phase = 'play'; g.turn = 0
            ranks = [5]*4 + [6]*4 + wings
            g.hands[0] = [{'id': str(i), 'rank': rank, 'suit': 'H'} for i, rank in enumerate(ranks + [13])]
            room = {'players': players, 'game': g}
            server.perform_game_action(room, 0, {'action': 'auto', 'ids': [str(i) for i in range(len(ranks))]})
            self.assertEqual(room['audioEvent']['items'], [{'effect': 'play'}, {'voice': voice}])

    def test_audio_gate_requires_current_completion_acknowledgement(self):
        client=self.clients[0];headers={'X-Poker-Audio':'1'}
        self.request(client,'create',{'mode':'basic'},headers)
        for _ in range(3):self.request(client,'bot',{})
        status,data=self.request(client,'start',{},headers);self.assertEqual(status,200)
        room=data['room'];self.assertTrue(room['audioWaiting'])
        g=server.ROOMS[room['code']]['game']
        for hand in g.hands:
            for card in hand:
                if card['rank']==3 and card['suit']=='S': card['suit']='H'
        g.hands[0][0].update(rank=3,suit='S')
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
                if g.phase=='setup' and server.confirmation_seat(room)!=seat: continue
                if room.get('priorityClock') and room['priorityClock']['seat'] != seat: continue
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
        server.room_of(self.users[0]['id'])['single']=True
        self.request(self.clients[0],'bot',{});self.request(self.clients[0],'bot',{})
        first=self.request(self.clients[0],'start',{})[1]['room']['matchId']
        self.assertEqual(self.request(self.clients[0],'state')[1]['room']['matchId'],first)
        self.request(self.clients[0],'resign',{})
        second=self.request(self.clients[0],'start',{})[1]['room']['matchId']
        self.assertNotEqual(first,second)

    def test_ai_games_never_change_rating(self):
        code=self.new_room('landlord',1)
        server.ROOMS[code]['single']=True
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

    def test_live_model_auth_failure_pauses_requests_and_reuses_rule_move(self):
        import copy
        code = self.new_room('landlord',1)
        for _ in range(2): self.request(self.clients[0],'bot',{})
        self.request(self.clients[0],'start',{})
        room = server.ROOMS[code]
        game = room['game']
        game.action(0,'bid',value=3)
        config = {'endpoint':'https://api.deepseek.com','model':'deepseek-flash','key':'test-secret'}
        room['modelConfig'] = config.copy()
        fallback = game.bot_action(0)
        with patch.object(server,'model_move',side_effect=urllib.error.HTTPError(config['endpoint'],401,'auth',{},None)):
            server.tick_bot(code,0,room['revision'],copy.deepcopy(game),config,room['matchId'],fallback)
        self.assertEqual(room['modelRetryAt'],float('inf'))
        self.assertTrue(any('HTTP 401' in line for line in game.log))
        self.assertEqual(game.play_number,1)
        with patch.object(server,'validate_endpoint',return_value=config['endpoint']):
            self.request(self.clients[0],'model-settings',config)
        self.assertNotIn('modelRetryAt',room)
        self.request(self.clients[0],'model-settings',{'clear':True})

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

    def test_room_model_can_choose_a_pending_skill_with_full_hand_and_goal(self):
        from test_conveyor import ConveyorRules
        fixture = ConveyorRules()
        game = fixture.game('money','anchor','anchor','anchor')
        core = fixture.table(game,[[4,9],[8],[10],[11,12]])
        card = core.hands[3].pop()
        core.discard.append(card)
        core.resources[0]['money'] = 4
        core.offer(0,'buy','聚宝',cards=[card])
        expected = {'action':'choice','ids':[card['id']]}
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {'choices':[{'message':{'content':json.dumps({'move':expected})}}]}).encode()
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(server,'validate_endpoint',return_value='https://example.com/v1'), patch.object(server.urllib.request,'build_opener',return_value=opener):
            move = server.model_move({'endpoint':'https://example.com/v1','key':'test-key','model':'test'},game,0)
        prompt = json.loads(json.loads(opener.open.call_args[0][0].data)['messages'][1]['content'])
        self.assertEqual(prompt['hand'],core.visible_hand(0))
        self.assertEqual(prompt['choice']['kind'],'buy')
        self.assertIn('各自为战',prompt['goal'])
        self.assertEqual(move,{**expected,'actor':0})
        self.assertEqual(core.resources[0]['money'],4)
        game.action(0,**move)
        self.assertIn(card,core.hands[0])
        self.assertEqual(core.resources[0]['money'],0)

    def test_conveyor_room_selection_start_and_private_view(self):
        client=self.clients[0]
        status,data=self.request(client,'create',{'mode':'conveyor','single':True,'options':{'skillDlc':[1,2,3,4],'tribute':True,'recycle':False}})
        self.assertEqual(status,200,data)
        self.assertFalse(data['room']['options']['tribute'])
        self.assertFalse(data['room']['options']['recycle'])
        self.assertEqual(len(data['room']['skills']),30)
        for _ in range(3):self.assertEqual(self.request(client,'bot',{})[0],200)
        self.assertEqual(self.request(client,'start',{})[0],400)
        self.assertEqual(self.request(client,'skill',{'skill':'twins'})[0],200)
        status,data=self.request(client,'start',{})
        self.assertEqual(status,200,data)
        self.assertEqual(data['room']['game']['phase'],'draft')
        self.assertEqual(len(data['room']['game']['conveyor']['actors']),4 + sum(p['skill']=='twins' for p in data['room']['players']))
        self.assertTrue(all(p['skill'] in server.SKILLS for p in data['room']['players']))
        room=server.room_of(self.users[0]['id'])
        public=server.room_view(room,self.users[1]['id'])
        self.assertEqual(public['game']['hand'],[])
        self.assertIsNone(public['game']['conveyor']['choice'])
        self.assertEqual(self.request(client,'skill',{'skill':'balance'})[0],400)
        with server.db() as c:
            metric=c.execute('SELECT * FROM usage_matches WHERE id=?',(room['matchId'],)).fetchone()
            self.assertEqual((metric['mode'],metric['channel']),('conveyor','single'))

    def test_twins_can_view_other_hand_during_audio(self):
        client=self.clients[0]
        self.request(client,'create',{'mode':'conveyor','single':True,'options':{'skillDlc':[3]}})
        self.request(client,'skill',{'skill':'twins'})
        for _ in range(3):self.request(client,'bot',{})
        for player,skill in zip(server.room_of(self.users[0]['id'])['players'][1:],['balance','anchor','leap']):player['skill']=skill
        self.request(client,'start',{})
        room=server.room_of(self.users[0]['id']);g=room['game']
        status,_=self.request(client,'action',{'action':'keep','actor':0,'ids':[x['id'] for x in g.core.hands[0][:7]],'revision':room['revision']})
        self.assertEqual(status,200)
        room['players'][0].update(audioEnabled=True,seen=__import__('time').time())
        server.queue_audio(room,[{'voice':'cv-keep'}])
        self.assertTrue(server.audio_waiting(room))
        status,data=self.request(client,'action',{'action':'focus','actor':1,'revision':room['revision']})
        self.assertEqual(status,200,data)
        self.assertEqual(data['room']['game']['conveyor']['actor'],1)
        self.assertEqual(len(data['room']['game']['hand']),7)
        self.assertTrue(server.audio_waiting(room))

    def test_conveyor_allows_taken_skills_but_rejects_disabled_skills(self):
        _,data=self.request(self.clients[0],'create',{'mode':'conveyor','options':{'disabledSkills':['balance']}})
        code=data['room']['code']
        self.request(self.clients[1],'join',{'code':code})
        self.assertEqual(self.request(self.clients[0],'skill',{'skill':'balance'})[0],400)
        self.assertEqual(self.request(self.clients[0],'skill',{'skill':'anchor'})[0],200)
        self.assertEqual(self.request(self.clients[1],'skill',{'skill':'anchor'})[0],200)
        self.assertEqual(self.request(self.clients[1],'skill',{'skill':'leap'})[0],200)
        self.assertEqual(self.request(self.clients[1],'skill',{'skill':'twins'})[0],400)

    def test_conveyor_can_start_with_players_and_bots_using_one_enabled_skill(self):
        client=self.clients[0]
        disabled = [key for key in server.SKILLS if key != 'balance']
        status, data = self.request(client, 'create', {'mode':'conveyor', 'single':True, 'options':{'disabledSkills':disabled}})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.request(client,'skill',{'skill':'balance'})[0],200)
        for _ in range(3): self.assertEqual(self.request(client,'bot',{})[0],200)
        status,data=self.request(client,'start',{})
        self.assertEqual(status,200,data)
        self.assertEqual([p['skill'] for p in data['room']['players']],['balance']*4)

    def test_conveyor_ultimate_dlc_is_opt_in_and_distinct_skills_start(self):
        client=self.clients[0]
        _,data=self.request(client,'create',{'mode':'conveyor','options':{'skillDlc':[5]}})
        code=data['room']['code']
        self.assertEqual(len(data['room']['skills']),13)
        for other in self.clients[1:]:self.request(other,'join',{'code':code})
        keys=['encourage','shadow','equilibrium','imprison']
        for other,key in zip(self.clients,keys):self.assertEqual(self.request(other,'skill',{'skill':key})[0],200)
        status,data=self.request(client,'start',{})
        self.assertEqual(status,200,data)
        self.assertEqual([p['skill'] for p in data['room']['players']],keys)
        self.assertEqual([a['count'] for a in data['room']['game']['conveyor']['actors']],[12,8,12,8])

    def test_host_can_assign_or_reset_conveyor_bot_skills_before_start(self):
        host,other=self.clients[:2]
        for single in (False,True):
            server.ROOMS.clear()
            _,data=self.request(host,'create',{'mode':'conveyor','single':single})
            if not single:
                self.request(other,'join',{'code':data['room']['code']})
                self.request(other,'skill',{'skill':'balance'})
            target=1 if single else 2
            self.request(host,'skill',{'skill':'balance'})
            for _ in range(4-target): self.request(host,'bot',{})
            if not single: self.assertEqual(self.request(other,'skill',{'skill':'money','botSeat':target})[0],400)
            self.assertEqual(self.request(host,'skill',{'skill':'twins','botSeat':target})[0],400)
            self.assertEqual(self.request(host,'skill',{'skill':'money','botSeat':target})[0],200)
            self.assertEqual(self.request(host,'skill',{'skill':'money','botSeat':target+1})[0],200)
            self.assertEqual(self.request(host,'skill',{'skill':None,'botSeat':target+1})[0],200)
            with patch('server.secrets.choice',return_value='anchor') as random_skill:
                status,data=self.request(host,'start',{})
            self.assertEqual(status,200,data)
            players=data['room']['players']
            self.assertEqual([p['skill'] for p in players[target:]],['money']+['anchor']*(3-target))
            self.assertEqual(random_skill.call_count,3-target)
            self.assertEqual(self.request(host,'skill',{'skill':None,'botSeat':target})[0],400)

    def test_conveyor_new_round_resets_all_four_personal_grades(self):
        client=self.clients[0]
        self.request(client,'create',{'mode':'conveyor','single':True})
        for _ in range(3):self.request(client,'bot',{})
        self.request(client,'skill',{'skill':'balance'});self.request(client,'start',{})
        room=server.room_of(self.users[0]['id']);g=room['game'];c=g.core
        c.phase='play';c.pending=[];c.main=14;c.scores=[11,7,4,3]
        for r in c.resources:r.update(turns=2,turnStart=2)
        for owner in (0,1,2):
            actor=next(s for s,o in enumerate(c.owners) if o==owner)
            c.hands[actor]=[];c.finish(actor)
        self.assertTrue(c.round_complete)
        status,data=self.request(client,'start',{})
        self.assertEqual(status,200,data)
        self.assertEqual(room['game'].scores,[0,0,0,0]);self.assertEqual(room['game'].main,3)
        self.assertIsNone(room['game'].first)

    def test_conveyor_first_out_room_can_start_a_new_round_immediately(self):
        client=self.clients[0]
        _,data=self.request(client,'create',{'mode':'conveyor','single':True,'options':{'firstOutEndsRound':True}})
        self.assertTrue(data['room']['options']['firstOutEndsRound'])
        for _ in range(3):self.request(client,'bot',{})
        self.request(client,'skill',{'skill':'balance'});self.request(client,'start',{})
        room=server.room_of(self.users[0]['id']);core=room['game'].core
        core.phase='play';core.pending=[];core.turn=0;core.resources[0].update(turns=2,turnStart=2)
        core.hands[0]=[{'id':'closing-play','rank':7,'suit':'C'}]
        status,data=self.request(client,'action',{'action':'auto','ids':['closing-play'],'revision':room['revision']})
        self.assertEqual(status,200,data)
        game=data['room']['game']
        self.assertTrue(game['roundComplete'])
        self.assertEqual(game['conveyor']['gradeChanges'],[2,0,0,0])
        self.assertEqual(game['winner'],[0])
        status,data=self.request(client,'start',{})
        self.assertEqual(status,200,data)
        self.assertTrue(data['room']['options']['firstOutEndsRound'])
        self.assertIsNone(room['game'].first)
        self.assertEqual(room['game'].scores,[0,0,0,0])
        self.assertEqual(room['game'].main,3)

    def test_conveyor_ending_practice_keeps_all_grades_and_no_winner(self):
        client=self.clients[0]
        self.request(client,'create',{'mode':'conveyor','single':True})
        for _ in range(3):self.request(client,'bot',{})
        self.request(client,'skill',{'skill':'balance'});self.request(client,'start',{})
        room=server.room_of(self.users[0]['id']);room['game'].core.scores=[1,3,5,7]
        status,data=self.request(client,'resign',{})
        self.assertEqual(status,200,data)
        self.assertEqual(data['room']['game']['winner'],[])
        self.assertEqual(data['room']['game']['scores'],[1,3,5,7])

    def test_conveyor_waiting_skill_choice_auto_takeover(self):
        from conveyor import ConveyorGame
        players=[{'id':self.users[i]['id'],'name':str(i),'skill':skill,'seen':100,'connected':True} for i,skill in enumerate(['balance','anchor','leap','stars'])]
        game=ConveyorGame('conveyor',players,{})
        game.core.phase='play';game.core.turn=0;game.core.pending=[]
        game.core.offer(1,'discard','选择',count=1)
        room={'code':'123456','mode':'conveyor','host':-1,'players':players,'game':game,'revision':1}
        with patch('server.time.time',return_value=100):server.update_autoplay(room)
        self.assertIn(1,room['idleWait'])
        with patch('server.time.time',return_value=161):server.update_autoplay(room)
        self.assertTrue(players[1]['autoplay'])
        self.assertFalse(game.priority_paused())

if __name__=='__main__':unittest.main()
