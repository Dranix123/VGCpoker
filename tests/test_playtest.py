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
from playtest_replay import read, replay_path, restore_legacy


class Playtest(unittest.TestCase):
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
                self.assertIsNone(read(path, frames))
                self.assertEqual(read(path, frames - 1)[1]['game']['winner'], match['winner'])
                play = next(e for e in actions if e['match'] == number and e['move']['action'] == 'play')
                _, frame = read(path, play['step'])
                self.assertEqual(frame['game']['seatPlays'][play['seat']]['cards'], play['after']['last']['cards'])
                path.unlink()
                path.with_suffix('.idx').unlink()
                self.assertTrue(restore_legacy(output, path, number, config, match))
                self.assertTrue(read(path, 0)[1]['legacy'])
                self.assertEqual(read(path, frames - 1)[1]['game']['winner'], match['winner'])

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
            DeepSeek('test-secret', 'deepseek-v4-pro', thinking=True).choose({'moves': ['a','b']}, 2)
            thinking=json.loads(opener.call_args.args[0].data)
            self.assertEqual(thinking['model'],'deepseek-v4-pro')
            self.assertEqual(thinking['thinking']['type'],'enabled')
            self.assertGreater(thinking['max_tokens'],body['max_tokens'])
            reply['choices'][0]['message']['content'] = '{"index":true}'
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(reply).encode()
            with self.assertRaisesRegex(ValueError, 'invalid_move_index'):
                adapter.choose({}, 2)

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
