import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playtest import DeepSeek, PlaytestService, play_batch, run_config, serve
from playtest_replay import load_replay, read, record, replay_path, restore_legacy
from game_ai import alternatives, decision_packet, model_context, model_payload, request_decision, select_model_move, model_shortlist
from engine import RuleError


class Playtest(unittest.TestCase):
    def test_model_context_keeps_three_complete_tricks_and_all_owned_cards(self):
        from test_conveyor import ConveyorRules
        from test_engine import cards, table

        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4, 5, 6, 7, 8, 9], prefix='leader')
        for _ in range(4):
            game.action(0, 'play', [game.hands[0][0]['id']])
            game.action(2, 'pass')
            game.action(1, 'pass')
        context = model_context(game, game, 0, [])
        rounds = context['recentRounds']
        self.assertEqual(len(rounds), 3)
        self.assertEqual([next(item['cards'][0]['rank'] for item in group if isinstance(item, dict) and item['cards'])
                          for group in rounds], [5, 6, 7])
        self.assertTrue(all(sum('不出' in item for item in group if isinstance(item, str)) == 2 for group in rounds))
        self.assertIn('地主', context['goal'])
        self.assertEqual(context['hand'], game.visible_hand(0))

        fixture = ConveyorRules()
        game = fixture.game('twins', 'anchor', 'anchor', 'anchor')
        core = fixture.table(game, [[4, 5], [6, 7], [8], [9], [10]])
        context = model_context(game, core, 0, [])
        self.assertEqual(context['hand'], core.visible_hand(0))
        self.assertEqual(context['otherOwnHands'][0]['hand'], core.visible_hand(1))
        self.assertEqual(len(context['otherOwnHands']), 1)
        self.assertTrue(all('hand' not in seat for seat in context['players']))

    def test_model_sees_a_viable_two_play_exit_in_each_mode(self):
        from test_conveyor import ConveyorRules
        from test_engine import cards, table

        for mode, teammates in (('landlord', [1]), ('basic', [2]), ('standard', [2]), ('trio', []), ('conveyor', [])):
            with self.subTest(mode=mode):
                if mode == 'conveyor':
                    fixture = ConveyorRules()
                    game = fixture.game(*['anchor'] * 4)
                    core = fixture.table(game, [[4,4,5,6,7,8,9],[10],[11],[12]])
                else:
                    game = core = table(mode)
                    core.hands[0] = cards([4,4,5,6,7,8,9], prefix='own')
                    core.landlord = 2 if mode == 'landlord' else None
                    core.turn = 0
                fallback = game.bot_action(0)
                moves = alternatives(game, core, 0, fallback)
                context = model_context(game, core, 0, moves)
                self.assertEqual(context['teammates'], teammates)
                self.assertTrue(context['decision']['freeLead'])
                self.assertEqual(context['turnOrder'][1], len(core.players)-1)
                self.assertEqual(context['hand'], core.visible_hand(0))
                self.assertTrue(context['tactics'])
                pair = next(m for m in context['moves'] if m['label'] == '对子')
                self.assertEqual(pair['afterPlay']['onePlayShape'], '顺子')
                selected = select_model_move(game, 0, 0, moves, pair['index'])
                self.assertEqual(selected['ids'], pair['ids'])

    def test_candidate_limit_leaves_room_for_combos_and_the_model_backup(self):
        from test_engine import cards, table

        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4,5,6,7,8,9], prefix='own')
        fallback = dict(action='play', ids=['own0'], label='单张')
        run = dict(action='play', ids=['own1','own2','own3','own4','own5'], label='顺子')
        repeated = [dict(action='play', ids=[str(i)], label='单张') for i in range(50)]
        with patch.object(game, 'candidates', return_value=[*repeated, run]):
            moves = alternatives(game, game, 0, fallback)
        self.assertEqual(len(moves), 40)
        self.assertEqual(moves[0], fallback)
        self.assertEqual(moves[1], run)
        repair = {'move': {'action':'play','ids':['opponent']}, 'index':1}
        self.assertEqual(select_model_move(game, 0, 0, moves, repair), run)
        self.assertEqual(len(game.hands[0]), 6)

    def test_one_play_remainders_use_physical_wildcards_and_conveyor_skills(self):
        from test_engine import cards, table
        from test_conveyor import ConveyorRules
        for mode in ('basic','standard','trio'):
            game = table(mode)
            game.hands[0] = cards([12,6,7,9,10]) + cards([14],'S','ace')
            single = dict(action='play',ids=['c0'],label='单张')
            after = model_context(game,game,0,[single])['moves'][0]['afterPlay']
            self.assertEqual(after.get('onePlayShape'), None if mode=='basic' else '顺子')
            self.assertEqual(game.lead_shape(0, cards([14,14],'S')), '对子')
        fixture = ConveyorRules()
        for skill, ranks, shape in (
                ('wild',[12,6,7,9,10,(14,'D')],'顺子'),
                ('leap',[12,4,4,4,14,14],'4A4'),
                ('formation',[12,4,4,14],'4A4'),
                ('ascend',[12,7,8,10,11,(13,'S')],None)):
            with self.subTest(skill=skill):
                game = fixture.game(skill,'anchor','anchor','anchor')
                core = fixture.table(game,[ranks,[8,9],[7,9],[9]])
                core.turn = 3
                first = core.hands[0][0]['id']
                move = dict(action='play',ids=[first],label='单张')
                after = model_context(game,core,0,[move])['moves'][0]['afterPlay']
                self.assertEqual(after.get('onePlayShape'),shape)
                self.assertEqual(core.turn,3)
                self.assertEqual(len(core.hands[0]),len(ranks))

    def test_actor_memory_updates_hand_and_no_events_lost_across_compaction(self):
        from test_engine import table, cards
        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4,5,6,7,8,9,10,11], prefix='own')
        packet, memory = decision_packet(game, game, 0, [], None, ())
        memory['plan'] = '留住顺子'
        for i in range(5):
            game.action(0, 'play', ['own'+str(i)])
            game.action(2, 'pass')
            game.action(1, 'pass')
        packet, updated = decision_packet(game, game, 0, [], memory, ())
        self.assertEqual(packet['plan'], '留住顺子')
        self.assertEqual(packet['updates'][-1]['hand'], {'own'+str(i): None for i in range(5)})
        self.assertEqual(sum(e[1]=='不出' for r in packet['news'].values() for e in r if isinstance(e,list)),10)
        same, _ = decision_packet(game, game, 0, [], updated, ())
        self.assertFalse(same['news'])
        self.assertEqual(len(same['rounds']), 4)  # Three complete tricks and the current lead
        other, _ = decision_packet(game, game, 1, [], None, ())
        self.assertNotIn('plan',other)
        self.assertNotIn('own7',json.dumps(other))

    def test_reprompt_invalid_move_without_committing_private_plan_or_spending_extra(self):
        from test_engine import cards, table
        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4,5,6,7,8,12], prefix='hold')
        options = alternatives(game, game, 0, game.bot_action(0))
        packets = []
        def choose(packet, count):
            packets.append(packet)
            if len(packets) == 1:
                return {'selection':{'action':'play','ids':['unowned']},'plan':'错误计划'}, {'prompt_tokens':8}
            return {'selection':0,'plan':'保留牌权'}, {'prompt_tokens':9,'prompt_cache_hit_tokens':3}
        move, report, memory = request_decision(game,game,0,0,options,None,choose)
        self.assertEqual(move,options[0])
        self.assertEqual(len(packets),2)
        self.assertEqual(packets[0]['news'],packets[1]['news'])
        self.assertIn('retry',packets[1])
        self.assertNotIn('错误计划',json.dumps(packets[1],ensure_ascii=False))
        self.assertEqual(report['usage'],{'prompt_tokens':17,'prompt_cache_hit_tokens':3})
        self.assertEqual(memory['plan'],'保留牌权')
        self.assertEqual(len(game.hands[0]),6)

    def test_deepseek_reuses_exact_message_prefix_then_compacts(self):
        from test_engine import cards, table

        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4,5,6,10,12,14],prefix='private')
        sent = []
        def choose(packet,count):
            sent.append(model_payload('deepseek-flash',packet,False)['messages'])
            return 0, {'prompt_cache_hit_tokens':31,'prompt_cache_miss_tokens':19}
        memory = None
        options = alternatives(game,game,0,game.bot_action(0))
        for i in range(5):
            _,report,memory = request_decision(
                game,game,0,0,options,memory,choose,reuse_history=True)
            self.assertEqual(report['usage']['prompt_cache_hit_tokens'],31)
            self.assertEqual(len(sent[-1]),(2,4,6,8,2)[i])
            current = json.loads(sent[i][-1]['content'])
            if i in (1,2,3):
                self.assertEqual(sent[i][:len(sent[i-1])],sent[i-1])
                self.assertNotIn('base',current)
                self.assertEqual(current['moves'], '同上')
            else:
                self.assertIn('base',current)
                self.assertIsInstance(current['moves'],list)
                self.assertFalse(current['updates'])
        changed, _ = decision_packet(game,game,0,list(reversed(options)),memory,(),True)
        self.assertIsInstance(changed['moves'],list)
        other,_ = decision_packet(game,game,1,[],memory,(),True)
        self.assertNotIn('_history',other)
        self.assertNotIn('private',json.dumps(other))

    def test_landlord_cash_unanswered_lead_before_last_single(self):
        from test_engine import table, cards
        for ranks, label in (([3,16,17],'王炸'), ([3,17],'单张'), ([3,7,7],'对子')):
            with self.subTest(ranks=ranks):
                g = table('landlord')
                g.landlord = g.turn = 0
                g.hands = [cards(ranks,prefix='own'), cards([4],prefix='b'), cards([5],prefix='c')]
                bot = g.bot_action(0)
                self.assertEqual(bot['label'],label)
                self.assertNotIn('own0',bot['ids'])
                moves = alternatives(g,g,0,bot)
                move, report, _ = request_decision(g,g,0,0,moves,None,
                    lambda *_: self.fail('可证明走完时无需请求模型'))
                self.assertEqual(move['ids'],bot['ids'])
                self.assertFalse(report['attempts'])
                g.action(0,**move)
                for s in (2,1):
                    g.action(s,**g.bot_action(s))
                g.action(0,**g.bot_action(0))
                self.assertEqual(g.winner,[0])

    def test_landlord_unseen_rocket_prevents_a_certain_exit(self):
        from test_engine import table, cards
        g = table('landlord')
        g.landlord = g.turn = 0
        g.hands = [cards([4]*4+[3],prefix='own'),cards([5,6],prefix='b'),cards([7,8],prefix='c')]
        bomb = next(m for m in g.candidates(0) if m['label']=='炸弹')
        self.assertIsNone(g.landlord_two_play_exit(0,[bomb]))
        g.ai_older_rounds.append(json.dumps([{'cards':cards([16],prefix='played')}]))
        self.assertEqual(g.landlord_two_play_exit(0,[bomb]),bomb)

    def test_conveyor_finishing_skill_respects_refill_and_zone(self):
        from test_conveyor import ConveyorRules
        from game_ai import model_immediate_finish
        fixture = ConveyorRules()
        game = fixture.game('ascend','anchor','anchor','anchor')
        core = fixture.table(game,[[15],[7,8],[9,10],[11,12]])
        move = dict(action='skill',ids=[core.hands[0][0]['id']])
        core.resources[0]['turnStart'] = 1
        self.assertIsNone(model_immediate_finish(core,0,[move]))
        core.resources[0]['turnStart'] = 2
        core.zones[0] = [core.pile.pop()]
        self.assertIsNone(model_immediate_finish(core,0,[move]))
        core.zones[0].clear()
        self.assertEqual(model_immediate_finish(core,0,[move]),move)
        game.action(0,actor=0,**move)
        self.assertIn(0,core.finished)

    def test_model_compares_the_cost_of_dismantling_a_formation(self):
        from test_engine import cards, table

        game = table('basic')
        game.interactive = True
        game.players[1]['bot'] = True
        game.turn = 2
        game.hands[1] = cards([4,4,7,9,14],prefix='bot')
        game.hands[2] = cards([4,8,9,11],prefix='leader')
        game.action(2,'play',['leader0'])
        fallback = game.bot_action(1)
        moves = alternatives(game,game,1,fallback)
        self.assertEqual(moves[0]['action'],'priority-decline')
        packet,_ = decision_packet(game,game,1,moves,None,())
        cross = next(i for i,m in enumerate(moves) if m.get('special')=='cross')
        self.assertIn('拆顶级组合',packet['moves'][cross][-1])
        self.assertEqual(select_model_move(game,1,1,moves,cross)['special'],'cross')

    def test_api_shortlist_limits_repetition_and_can_finish_locally(self):
        from test_engine import cards, table
        game = table('landlord')
        game.turn = 0
        game.hands[0] = cards([4,4,5,5,6,6,7,7,8,9,10,11,12,13,14,15],prefix='own')
        fallback = game.bot_action(0)
        moves = alternatives(game, game, 0, fallback)
        short = model_shortlist(game, 0, moves)
        self.assertGreater(len(moves),14)
        self.assertLessEqual(len(short),14)
        self.assertEqual(short[0],fallback)
        self.assertEqual({m['action'] for m in short},{m['action'] for m in moves})
        game.hands[0] = cards([4,5,6,7,8],prefix='own')
        moves = alternatives(game, game, 0, game.bot_action(0))
        with patch('urllib.request.urlopen', side_effect=AssertionError('无需请求模型')):
            move, api, memory = request_decision(game, game, 0, 0, moves, None, DeepSeek('test','test').choose)
        self.assertEqual(move['label'],'顺子')
        self.assertEqual(api['attempts'],[])
        self.assertIsNone(memory)

    def test_opening_control_and_immediate_exit(self):
        from test_engine import cards, table
        from test_conveyor import ConveyorRules
        for mode, control in [('basic',[4,4,14]), ('standard',[4,4,4,14,14]),
                              ('trio',[4,4,4,14,14]), ('conveyor',[4,4,4,14,14])]:
            with self.subTest(mode=mode):
                if mode == 'conveyor':
                    fixture = ConveyorRules()
                    game = fixture.game(*['anchor']*4)
                    core = fixture.table(game,[control+[6,8,11,13], [7],[8]*4,[9]*4])
                    core.resources[1]['turns'] = 0
                else:
                    game = core = table(mode)
                    core.turn = 0
                    core.hands[0] = cards(control+[6,8,11,13],prefix='own')
                fallback = game.bot_action(0)
                original = {c['id'] for c in core.hands[0] if c['rank'] in (4,14)}
                self.assertTrue(original.isdisjoint(fallback['ids']))
                options = alternatives(game,core,0,fallback)
                packet, _ = decision_packet(game,core,0,options,None,())
                self.assertTrue(packet['opening'])
                self.assertTrue(any(m.get('label')=='4A4' for m in options))
                core.hands[0] = [c for c in core.hands[0] if c['id'] in original]
                self.assertEqual(set(game.bot_action(0)['ids']),original)

    def test_model_can_take_active_and_optional_conveyor_actions(self):
        from test_conveyor import ConveyorRules

        fixture = ConveyorRules()
        game = fixture.game('balance', 'money', 'reflux', 'anchor')
        core = fixture.table(game, [[4, 5, 6], [9], [7, 8, 9, 10, 11, 12], [13]])
        fallback = game.bot_action(0)
        moves = alternatives(game, core, 0, fallback)
        self.assertTrue(any(move['action'] == 'skill' for move in moves))
        reserve = core.hands[0][1]['id']
        selected = {'action': 'skill', 'ids': [core.hands[0][0]['id'], core.hands[0][2]['id']]}
        before = core.hands[0][:]
        self.assertNotIn(selected, moves)
        self.assertEqual(select_model_move(game, 0, 0, moves, selected), selected)
        self.assertEqual(core.hands[0], before)
        with self.assertRaises(RuleError):
            select_model_move(game, 0, 0, moves, {'action': 'skill', 'ids': [core.hands[1][0]['id']]})
        game.action(0, **selected)
        self.assertIn(reserve, [card['id'] for card in core.hands[0]])

        card = core.hands[2].pop()
        core.discard.append(card)
        core.offer(2, 'reflux', '回收', cards=[card])
        fallback = game.bot_action(2)
        self.assertEqual(fallback['ids'], [card['id']])
        moves = alternatives(game, core, 2, fallback)
        self.assertTrue(any(move.get('ids') == [] for move in moves))
        skip = select_model_move(game, 2, 2, moves, {'action': 'choice', 'ids': []})
        game.action(2, **skip)
        core.resources[1]['money'] = 4
        core.offer(1, 'buy', '聚宝', cards=[card])
        moves = alternatives(game, core, 1, game.bot_action(1))
        buy = select_model_move(game, 1, 1, moves, {'action': 'choice', 'ids': [card['id']]})
        game.action(1, **buy)
        self.assertIn(card, core.hands[1])
        self.assertEqual(core.resources[1]['money'], 0)

    def test_model_can_keep_urgent_card_or_use_it_outside_its_turn(self):
        from test_conveyor import ConveyorRules
        fixture = ConveyorRules()
        game = fixture.game('anchor','anchor','anchor','anchor')
        core = fixture.table(game,[[4,5,6],[18,9],[10,11],[12,13]])
        core.ai_model_reactions = True
        fallback = game.bot_action(1)
        self.assertEqual(fallback['action'],'reaction-decline')
        moves = alternatives(game,core,1,fallback)
        self.assertTrue(any(move.get('effect') == 'ban' for move in moves))
        decline = select_model_move(game,1,1,moves,0)
        game.action(1,**decline)
        self.assertTrue(any(card['rank'] == 18 for card in core.hands[1]))
        self.assertIsNone(game.bot_action(1))
        game.action(0,'play',[core.hands[0][0]['id']])
        fallback = game.bot_action(1)
        moves = alternatives(game,core,1,fallback)
        ban = next(move for move in moves if move.get('effect') == 'ban' and move.get('target') == core.turn)
        game.action(1,**select_model_move(game,1,1,moves,ban))
        self.assertTrue(core.resources[core.turn]['ban'])

    def test_separate_replays_and_legacy_recovery(self):
        config = run_config({'driver': 'rules', 'mode': 'landlord', 'games': 2}, False)
        with TemporaryDirectory() as temp:
            output = Path(temp)
            summary = {}
            play_batch('test', output, config, None, summary.update)
            self.assertEqual(summary['status'], 'completed')
            self.assertEqual(len(summary['matches']), 2)
            with (output / 'events.jsonl').open() as log:
                actions = [event for event in map(json.loads, log) if event['event'] == 'action']
            for match in summary['matches']:
                number, steps = match['match'], match['steps']
                path = replay_path(output, number)
                frames, first = read(path, 0)
                self.assertEqual((frames, first['step'], first['game']['phase']), (steps + 1, 0, 'bid'))
                self.assertEqual(first['game']['hand'], [])
                self.assertIsNone(first['game']['remainingHands'])
                self.assertEqual([(h['owner'], len(h['cards'])) for h in first['game']['publicHands']],
                                 [(0, 17), (1, 17), (2, 17)])
                self.assertIsNone(read(path, frames))
                self.assertEqual(read(path, frames - 1)[1]['game']['winner'], match['winner'])
                play = next(e for e in actions if e['match'] == number and e['move']['action'] == 'play')
                _, frame = read(path, play['step'])
                self.assertEqual(frame['game']['seatPlays'][play['seat']]['cards'], play['after']['last']['cards'])
                self.assertEqual({c['id'] for c in frame['game']['publicHands'][play['seat']]['cards']},
                                 {c['id'] for c in play['after']['hands'][play['seat']]})
                cached = [read(path, step)[1] for step in range(frames)]
                with record(path) as append:
                    for state in cached:
                        state['game'].pop('publicHands')
                        append(**state)
                _, [upgraded] = load_replay(output, number, config, match, play['step'])
                self.assertEqual(upgraded['game']['seatPlays'], frame['game']['seatPlays'])
                self.assertEqual(upgraded['game']['publicHands'], frame['game']['publicHands'])
                path.unlink()
                path.with_suffix('.idx').unlink()
                self.assertTrue(restore_legacy(output, path, number, config, match))
                self.assertTrue(read(path, 0)[1]['legacy'])
                self.assertEqual(read(path, frames - 1)[1]['game']['winner'], match['winner'])
                self.assertEqual(read(path, play['step'])[1]['game']['publicHands'], frame['game']['publicHands'])

    def test_conveyor_replay_records_public_state_for_both_identities(self):
        config = run_config({'driver': 'rules', 'mode': 'conveyor', 'maxSteps': 4,
                             'skills': ['twins', 'anchor', 'anchor', 'anchor']}, False)
        with TemporaryDirectory() as temp:
            output = Path(temp)
            summary = {}
            play_batch('test', output, config, None, summary.update)
            self.assertEqual(summary['status'], 'step_limit')
            _, frame = read(replay_path(output, 1), 4)
            view = frame['game']['conveyor']
            twins = [a for a in view['actors'] if a['owner'] == 0]
            self.assertEqual([a['count'] for a in twins], [7, 7])
            hands = frame['game']['publicHands']
            self.assertEqual([(h['owner'], h['actor'], len(h['cards'])) for h in hands],
                             [(0, 0, 7), (0, 1, 7), (1, 2, 6), (2, 3, 6), (3, 4, 6)])
            self.assertTrue(all('effective' in c for h in hands for c in h['cards']))
            self.assertIsNone(view['choice'])
            self.assertEqual(view['boundHands'], [])
            self.assertFalse(any('hand' in a for a in view['actors']))

    def test_configuration_validates_skills_and_infers_dlc(self):
        config = run_config({'driver': 'rules', 'skills': ['转换', 'twins', 'twins', None]}, False)
        self.assertEqual(config['skills'], ['balance', 'twins', 'twins', None])
        self.assertEqual(config['options']['skillDlc'], [3])
        for config in (
            {'driver': 'deepseek'},
            {'driver': 'rules', 'mode': 'landlord', 'skills': ['twins']},
            {'driver': 'rules', 'skills': ['twins', None, None, None], 'options': {'skillDlc': []}},
            {'driver': 'rules', 'skills': ['scavenge'] * 4},
            {'driver': 'rules', 'skills': ['scavenge', 'redirect', 'scavenge', 'redirect']},
            {'driver': 'rules', 'options': {'firstOutEndsRound': 'yes'}},
            {'driver': 'rules', 'maxSteps': True},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                run_config(config, False)

    def test_deepseek_payload_and_response_contract(self):
        adapter = DeepSeek('test-secret', 'deepseek-flash')
        reply = {'choices': [{'message': {'content': '{"index":1}'}}], 'usage': {'total_tokens': 11}}
        with patch('urllib.request.urlopen') as opener:
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
            self.assertEqual(adapter.choose({'player': 1, 'moves': ['a', 'b']}, 2), (1, {'total_tokens': 11}))
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.deepseek.com/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
            body = json.loads(request.data)
            self.assertEqual(body['thinking']['type'], 'disabled')
            self.assertEqual(body['response_format']['type'], 'json_object')
            self.assertIn('json', body['messages'][0]['content'].lower())
            DeepSeek('test-secret', 'deepseek-v4-pro', thinking=True).choose({'moves': ['a','b']}, 2)
            thinking=json.loads(opener.call_args.args[0].data)
            self.assertEqual(thinking['model'],'deepseek-v4-pro')
            self.assertEqual(thinking['thinking']['type'],'enabled')
            self.assertGreater(thinking['max_tokens'],body['max_tokens'])
            reply['choices'][0]['message']['content'] = '{"index":true}'
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
            with self.assertRaisesRegex(ValueError, 'invalid_move_index'):
                adapter.choose({}, 2)

    def test_model_accepts_fenced_compatible_json_and_detects_incomplete_answers(self):
        from io import BytesIO
        from game_ai import read_model_reply

        self.assertNotIn('thinking', model_payload('compatible-model', {}))
        self.assertNotIn('response_format', model_payload('compatible-model', {}))
        fence = chr(96) * 3
        def response(content, reason='stop'):
            return BytesIO(json.dumps({'choices':[{'finish_reason':reason,'message':{'content':content}}]}).encode())
        self.assertEqual(read_model_reply(response(fence + 'json\n{"index":0}\n' + fence),1), (0,{}))
        with self.assertRaisesRegex(ValueError, 'empty_model_reply'):
            read_model_reply(response('    '),1)
        with self.assertRaisesRegex(ValueError, 'truncated_model_reply'):
            read_model_reply(response('', 'length'),1)

    def test_batch_records_model_decisions_and_fallback_without_leaking_other_hands(self):
        class FakeDeepSeek:
            model = 'deepseek-flash'

            def __init__(self):
                self.contexts = []

            def choose(self, context, count):
                self.contexts.append(context)
                if len(self.contexts) == 1:
                    raise HTTPError('http://unused', 429, 'test-secret', {}, None)
                return 0, {'total_tokens': 11}

        cfg = run_config({'mode': 'landlord', 'maxModelCalls': 5}, True)
        model = FakeDeepSeek()
        with TemporaryDirectory() as temp:
            output = Path(temp)
            summary = {}
            play_batch('test', output, cfg, model, summary.update)
            log = (output / 'events.jsonl').read_text()
            actions = [r for r in map(json.loads, log.splitlines()) if r['event'] == 'action']
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(summary['calls'], 5)
        self.assertTrue(summary['modelBudgetReached'])
        self.assertEqual(summary['tokens']['total_tokens'], 44)
        self.assertEqual(actions[0]['source'], 'deepseek')
        self.assertEqual(summary['fallbacks'], 0)
        self.assertEqual(actions[0]['api']['attempts'][0]['status'], 429)
        self.assertIn('retry', model.contexts[1])
        self.assertNotIn('test-secret', log)
        self.assertGreater(len({c['table']['player'] for c in model.contexts}), 1)
        for context in model.contexts:
            base = context['base']
            self.assertEqual(base['counts'][context['table']['actor']], len(base['hand']))
            self.assertNotIn('shownHands',base)

    def test_three_failed_requests_only_replace_one_decision_and_respect_budget(self):
        class InvalidRequest:
            model = 'deepseek-flash'

            def choose(self, context, count):
                raise HTTPError('http://unused', 400, 'Bad Request', {}, None)

        config = run_config({'mode': 'landlord', 'maxModelCalls': 5}, True)
        with TemporaryDirectory() as temp:
            summary = {}
            play_batch('test', Path(temp), config, InvalidRequest(), summary.update)
            actions = [e for e in map(json.loads, (Path(temp)/'events.jsonl').read_text().splitlines()) if e.get('api')]
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual((summary['calls'], summary['fallbacks']), (5, 2))
        self.assertEqual([len(e['api']['attempts']) for e in actions], [3,2])
        self.assertTrue(all(a['status'] == 400 for e in actions for a in e['api']['attempts']))

    def test_cancellation_stops_after_current_model_request(self):
        cancelled = threading.Event()

        class CancellableModel:
            model = 'deepseek-flash'

            def choose(self, context, count):
                cancelled.set()
                return 0, {}

        cfg = run_config({'mode': 'landlord', 'games': 2}, True)
        with TemporaryDirectory() as temp:
            summary = {}
            play_batch('test', Path(temp), cfg, CancellableModel(), summary.update, cancelled)
        self.assertEqual(summary['status'], 'cancelled')
        self.assertEqual(summary['calls'], 1)
        self.assertEqual([match['status'] for match in summary['matches']], ['cancelled'])

    def test_local_http_api_runs_a_rule_game_and_serves_logs(self):
        with TemporaryDirectory() as temp, serve(0, PlaytestService(Path(temp))) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                req = Request(base + '/runs', json.dumps({'mode': 'landlord', 'driver': 'rules'}).encode(),
                              {'Content-Type': 'application/json'})
                with urlopen(req, timeout=2) as response:
                    self.assertEqual(response.status, 202)
                    run = json.load(response)
                for _ in range(75):
                    with urlopen(base + run['status'], timeout=2) as response:
                        summary = json.load(response)
                    if summary['status'] not in ('queued', 'running'):
                        break
                    time.sleep(.02)
                self.assertEqual(summary['status'], 'completed')
                with urlopen(base + run['log'], timeout=2) as response:
                    events = [json.loads(line) for line in response]
                self.assertEqual(events[0]['event'], 'run_started')
                self.assertTrue(any(event['event'] == 'action' for event in events))
                self.assertEqual(events[-1]['event'], 'run_finished')
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base+'/options', headers={'Origin': 'https://elsewhere.example'}),timeout=2)
                self.assertEqual(denied.exception.code, 403)
            finally:
                server.shutdown()
                worker.join(timeout=2)
