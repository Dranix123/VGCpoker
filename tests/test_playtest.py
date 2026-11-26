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
from game_ai import alternatives, model_context, model_payload, select_model_move
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
        self.assertEqual(actions[0]['source'], 'fallback')
        self.assertEqual(actions[0]['api']['status'], 429)
        self.assertNotIn('test-secret', log)
        self.assertGreater(len({c['player'] for c in model.contexts}), 1)
        for context in model.contexts:
            self.assertEqual(sum(c['count'] for c in context['players'] if c['actor'] == context['actor']), len(context['hand']))
            self.assertTrue(all('hand' not in p for p in context['players']))

    def test_invalid_api_request_does_not_repeat_for_the_rest_of_the_run(self):
        class InvalidRequest:
            model = 'deepseek-flash'

            def choose(self, context, count):
                raise HTTPError('http://unused', 400, 'Bad Request', {}, None)

        config = run_config({'mode': 'landlord', 'maxModelCalls': 5}, True)
        with TemporaryDirectory() as temp:
            summary = {}
            play_batch('test', Path(temp), config, InvalidRequest(), summary.update)
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual((summary['calls'], summary['fallbacks']), (1, 1))
        self.assertEqual(summary['modelDisabledReason'], 'http_400')

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
