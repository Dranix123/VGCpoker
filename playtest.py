#!/usr/bin/env python3
"""Local, headless VGC playtesting over the production rule engines."""

import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import traceback
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from conveyor import ConveyorGame
from conveyor_skills import SKILLS, available
from engine import Game, MODES, RuleError
from playtest_replay import record, replay_path, spectator_view


OUTPUT = Path(__file__).resolve().parent / 'output' / 'playtests'
DEEPSEEK_MODELS = ('deepseek-flash', 'deepseek-v4-pro')
BOOLEAN_OPTIONS = {
    'landlord': (),
    'basic': ('tribute',),
    'standard': ('advancedHui', 'advancedDead', 'tribute', 'dlc'),
    'trio': ('advancedHui', 'advancedDead'),
    'conveyor': ('advancedHui', 'advancedDead', 'firstOutEndsRound'),
}


def run_config(body, model_enabled):
    fields = {'mode', 'driver', 'games', 'skills', 'options', 'maxSteps', 'maxModelCalls'}
    if not isinstance(body, dict) or set(body) - fields:
        raise ValueError('配置包含未知字段。')
    mode, driver = body.get('mode', 'conveyor'), body.get('driver', 'deepseek')
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('未知玩法。请查看 GET /options。')
    if driver not in ('deepseek', 'rules'):
        raise ValueError('driver 必须为 deepseek 或 rules。')
    if driver == 'deepseek' and not model_enabled:
        raise ValueError('请在启动测试服务时设置 DEEPSEEK_API_KEY，或使用 rules。')
    limits = {}
    for field, default, lower, upper in (
        ('games', 1, 1, 30), ('maxSteps', 600, 1, 5000), ('maxModelCalls', 250, 1, 10000),
    ):
        value = body.get(field, default)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f'{field} 必须为 {lower} 到 {upper} 之间的整数。')
        limits[field] = value
    supplied = body.get('options', {})
    allowed = set(BOOLEAN_OPTIONS[mode]) | ({'skillDlc', 'disabledSkills'} if mode == 'conveyor' else set())
    if not isinstance(supplied, dict) or set(supplied) - allowed:
        raise ValueError('options 中含有该玩法不支持的选项。')
    options = {name: supplied.get(name, name.startswith('advanced')) for name in BOOLEAN_OPTIONS[mode]}
    if any(type(value) is not bool for value in options.values()):
        raise ValueError('规则开关必须是布尔值。')
    skills = body.get('skills', [None] * MODES[mode])
    if mode == 'conveyor':
        names = {s['name']: s['id'] for s in SKILLS.values()}
        if not isinstance(skills, list) or len(skills) != MODES[mode] or any(s is not None and not isinstance(s, str) for s in skills):
            raise ValueError('传送带的 skills 必须为四项数组，每项为技能名、技能编号或 null。')
        skills = [names.get(s, s) for s in skills]
        if any(s is not None and s not in SKILLS for s in skills):
            raise ValueError('技能不存在。请查看 GET /options。')
        groups = supplied.get('skillDlc', sorted({SKILLS[s]['group'] for s in skills if s and SKILLS[s]['group']}))
        disabled = supplied.get('disabledSkills', [])
        if not isinstance(groups, list) or any(type(g) is not int or not 1 <= g <= 5 for g in groups):
            raise ValueError('skillDlc 是由 1 到 5 的整数构成的数组。')
        if not isinstance(disabled, list) or any(not isinstance(s, str) or s not in SKILLS for s in disabled):
            raise ValueError('disabledSkills 必须是技能编号数组。')
        options.update(skillDlc=sorted(set(groups)), disabledSkills=disabled)
        enabled = {s['id'] for s in available(options)}
        if not enabled or any(s is not None and s not in enabled for s in skills):
            raise ValueError('指定的技能未启用，或没有开放的技能。')
        if all(s == 'scavenge' for s in skills) or enabled == {'scavenge'}:
            raise ValueError('至少需要一名可以首出的玩家。')
    elif 'skills' in body:
        raise ValueError('只有传送带可以指定技能。')
    return dict(mode=mode, driver=driver, skills=skills, options=options, **limits)


class DeepSeek:
    endpoint = 'https://api.deepseek.com/chat/completions'

    def __init__(self, key, model, thinking=False):
        self.key, self.model, self.thinking = key, model, thinking

    def choose(self, context, count):
        body = {
            'model': self.model,
            'thinking': {'type': 'enabled' if self.thinking else 'disabled'},
            'response_format': {'type': 'json_object'},
            'max_tokens': 2048 if self.thinking else 64,
            'messages': [
                {'role': 'system', 'content': '你正在玩 VGC 扑克。按当前身份及阵营争胜。'
                 '只能从 moves 选择一项，索引从 0 开始。返回 JSON，如 {"index":0}。'},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, separators=(',', ':'))},
            ],
        }
        request = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(),
                                         headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('response_too_large')
        result = json.loads(raw)
        index = json.loads(result['choices'][0]['message']['content'])['index']
        if type(index) is not int or not 0 <= index < count:
            raise ValueError('invalid_move_index')
        usage = result.get('usage') or {}
        return index, {key: usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                       if type(usage.get(key)) is int}


def start_match(config, previous):
    mode, options = config['mode'], config['options']
    players = [dict(id=i, name=f'{i + 1}号', bot=True, connected=True) for i in range(MODES[mode])]
    if mode == 'conveyor':
        pool = [s['id'] for s in available(options)]
        for player, skill in zip(players, config['skills']):
            player['skill'] = skill or secrets.choice(pool)
        if all(p['skill'] == 'scavenge' for p in players):
            random_seat = config['skills'].index(None)
            players[random_seat]['skill'] = secrets.choice([s for s in pool if s != 'scavenge'])
        game = ConveyorGame(mode, players, options, previous, interactive=True)
        return game, game.core
    game = Game(mode, players, options, previous, interactive=True)
    game.finish_setup()
    return game, game


def next_action(game, core):
    if core.phase == 'play' and not getattr(core, 'pending', []) and game.forced_pass():
        return game.turn, core.turn, {'action': 'pass'}, True
    if core.phase == 'setup':
        start = core.first or 0
        owners = getattr(core, 'owners', list(range(len(core.players))))
        seats = [owners[i] for i in sorted(core.confirmation_seats(), key=lambda i: (start - i) % len(owners))
                 if i not in core.rps]
    else:
        seats = range(len(game.players))
    for seat in seats:
        move = game.bot_action(seat)
        if move:
            return seat, move.pop('actor', seat), move, False
    raise RuleError('规则 AI 未返回行动。')


def move_args(move):
    fields = {'label', 'power', 'n'}
    if move['action'] not in ('bid', 'rps', 'choice'):
        fields.add('value')
    return {k: v for k, v in move.items() if k not in fields}


def alternatives(game, core, actor, fallback):
    pending = getattr(core, 'pending', [])
    moves = [fallback]
    if pending:
        choice = pending[0]
        if choice['kind'] == 'deal':
            moves.extend(dict(action='choice', value=n) for n in range(1, choice['maximum'] + 1))
            if choice.get('skill') in ('trade', 'request'):
                moves.append(dict(action='choice', effect='judge' if choice['skill'] == 'trade' else 'request'))
            if choice.get('skill') == 'redirect':
                moves.extend(dict(action='choice', effect='redirect', target=s) for s in core.active() if s != actor)
    elif core.phase == 'bid':
        moves.extend(dict(action='bid', value=n) for n in [0, *range(core.bid + 1, 4)])
    elif core.phase == 'rps':
        moves.extend(dict(action='rps', value=v) for v in ('rock', 'paper', 'scissors'))
    elif core.phase == 'play':
        if game.mode == 'conveyor' and (core.resources[actor]['ban'] or core.must_scavenge(actor)):
            return moves
        if core.priority and actor in core.priority['bots']:
            moves.append({'action': 'priority-decline'})
            moves.extend({**m, 'action': 'priority-play', 'special': m['action']} for m in core.priority_moves(actor))
        elif actor == core.turn:
            if core.last and core.last_seat != actor:
                moves.append({'action': 'pass'})
            moves.extend(core.candidates(actor))
    unique = {}
    for move in moves:
        unique.setdefault(json.dumps(move_args(move), sort_keys=True), move)
        if len(unique) >= 40:
            break
    return list(unique.values())


def model_context(game, core, actor, moves):
    owners = getattr(core, 'owners', list(range(len(core.players))))
    teammates = []
    if game.mode in ('basic', 'standard'):
        teammates = [(actor + 2) % len(owners)]
    elif game.mode == 'landlord' and core.landlord is not None and actor != core.landlord:
        teammates = [s for s in range(len(owners)) if s not in (core.landlord, actor)]
    context = dict(mode=game.mode, phase=core.phase, actor=actor, player=owners[actor],
                   teammates=teammates, main=core.main, landlord=core.landlord, bid=core.bid, last=core.last,
                   lastActor=core.last_seat, recentPlays=core.seat_plays,
                   players=[dict(actor=i, owner=owners[i], count=len(h), finished=i in core.finished)
                            for i, h in enumerate(core.hands)],
                   hand=core.visible_hand(actor), moves=moves)
    if game.mode == 'conveyor':
        context.update(skill=SKILLS[core.skills[actor]], pile=len(core.pile),
                       zone=core.zones[actor], choice=core.pending[0] if core.pending else None,
                       resources={k: v for k, v in core.resources[actor].items() if k != 'markCards'},
                       firstOutEndsRound=game.options.get('firstOutEndsRound', False))
    return context


def encode_state(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f'Cannot serialize {type(value).__name__}')


def snapshot(core):
    return copy.deepcopy(dict(
        phase=core.phase, turn=core.turn, main=core.main, scores=core.scores, winner=core.winner,
        finished=core.finished, hands=core.hands, playNumber=core.play_number, last=core.last,
        pending=getattr(core, 'pending', []), priority=core.priority, zones=getattr(core, 'zones', []),
        resources=getattr(core, 'resources', []), pileSize=len(getattr(core, 'pile', [])),
        discardSize=len(getattr(core, 'discard', [])), tribute=core.tribute,
    ))


def apply_move(game, core, seat, actor, move):
    args = move_args(move)
    if game.mode == 'conveyor':
        game.action(seat, actor=actor, **args)
    else:
        previous = copy.deepcopy(core.__dict__)
        try:
            game.action(seat, **args)
            game.finish_setup()
        except RuleError:
            core.__dict__ = previous
            raise


def new_messages(before, after):
    for length in range(min(len(before), len(after)), 0, -1):
        if before[-length:] == after[:length]:
            return after[length:]
    return after


def play_batch(run, directory, config, model, save, cancelled=None):
    summary = dict(id=run, status='running', config=config, model=model.model if model else None,
                   calls=0, fallbacks=0, tokens={}, matches=[])
    if model:
        summary['thinking'] = getattr(model, 'thinking', False)
    save(summary)
    with (directory / 'events.jsonl').open('w', encoding='utf-8') as log, ExitStack() as replay:
        def event(kind, **data):
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')
            print(json.dumps(dict(time=stamp, event=kind, **data), ensure_ascii=False, default=encode_state),
                  file=log, flush=True)

        event('run_started', config=config, model=summary['model'])
        previous = None
        core = None
        steps = 0
        recording = False
        try:
            for number in range(1, config['games'] + 1):
                if cancelled and cancelled.is_set():
                    break
                summary.update(currentMatch=number, currentStep=0)
                core, steps = None, 0
                recording = False
                game, core = start_match(config, previous)
                skills = [p.get('skill') for p in game.players]
                append = replay.enter_context(record(replay_path(directory, number)))
                append(0, spectator_view(game, core))
                recording = True
                event('match_started', match=number, skills=skills, state=snapshot(core), announcements=core.log)
                save(summary)
                for step in range(1, config['maxSteps'] + 1):
                    if game.phase == 'over' or cancelled and cancelled.is_set():
                        break
                    steps = step
                    summary['currentStep'] = step
                    before, messages = snapshot(core), core.log[:]
                    seat, actor, fallback, forced = next_action(game, core)
                    move, source, api = fallback, 'forced' if forced else 'rules', None
                    options = [fallback]
                    if model and not forced and not summary.get('modelDisabledReason') and summary['calls'] < config['maxModelCalls']:
                        options = alternatives(game, core, actor, fallback)
                        if len(options) > 1:
                            summary['calls'] += 1
                            started = time.monotonic()
                            try:
                                index, usage = model.choose(model_context(game, core, actor, options), len(options))
                                move, source = options[index], 'deepseek'
                                api = dict(index=index, usage=usage)
                                for key, count in usage.items():
                                    summary['tokens'][key] = summary['tokens'].get(key, 0) + count
                            except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                                summary['fallbacks'] += 1
                                source = 'fallback'
                                api = dict(error=type(error).__name__)
                                if isinstance(error, urllib.error.HTTPError):
                                    api['status'] = error.code
                                    if error.code in (401, 403):
                                        summary['modelDisabledReason'] = f'http_{error.code}'
                                elif type(error) is ValueError and str(error) in ('invalid_move_index', 'response_too_large'):
                                    api['reason'] = str(error)
                            api['milliseconds'] = round((time.monotonic() - started) * 1000)
                    try:
                        apply_move(game, core, seat, actor, move)
                    except RuleError as error:
                        event('move_rejected', match=number, step=step, seat=seat, actor=actor, source=source,
                              move=move, reason=str(error), api=api, alternatives=options, before=before)
                        if move == fallback:
                            raise
                        summary['fallbacks'] += 1
                        move, source = fallback, 'fallback'
                        apply_move(game, core, seat, actor, move)
                    announcements = new_messages(messages, core.log)
                    event('action', match=number, step=step, seat=seat, actor=actor, source=source,
                          move=move, alternatives=options, api=api, before=before, after=snapshot(core),
                          announcements=announcements)
                    append(step, spectator_view(game, core), seat=seat, actor=actor, action=move['action'],
                           message=announcements[-1] if announcements else None)
                    save(summary)
                complete = game.phase == 'over'
                status = 'completed' if complete else 'cancelled' if cancelled and cancelled.is_set() else 'step_limit'
                result = dict(match=number, status=status, steps=steps,
                              skills=skills, winner=game.winner, finished=game.finished, scores=game.scores,
                              roundComplete=game.round_complete, nextMain=game.next_main)
                summary['matches'].append(result)
                event('match_finished', **result, state=snapshot(core))
                replay.close()
                save(summary)
                previous = None
                if complete and not game.round_complete and game.mode != 'landlord':
                    first = next((s for s in game.finished if s not in game.urgent_last), None)
                    previous = dict(first=first, main=game.next_main, scores=game.scores, captured=game.captured)
            if cancelled and cancelled.is_set() and (len(summary['matches']) < config['games'] or summary['matches'][-1]['status'] == 'cancelled'):
                summary['status'] = 'cancelled'
            else:
                summary['status'] = 'completed' if all(m['status']=='completed' for m in summary['matches']) else 'step_limit'
        except Exception as error:
            summary['status'] = 'failed'
            replay.close()
            if recording and not any(result['match'] == number for result in summary['matches']):
                summary['matches'].append(dict(match=number, status='failed', skills=skills, steps=steps))
            summary['error'] = dict(type=type(error).__name__)
            if isinstance(error, RuleError):
                summary['error']['reason'] = str(error)
            stack = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                     for frame in traceback.extract_tb(error.__traceback__)[-8:]]
            event('run_failed', match=number, step=steps, state=snapshot(core) if core else None,
                  stack=stack, **summary['error'])
        summary['modelBudgetReached'] = bool(model and summary['calls'] >= config['maxModelCalls'])
        event('run_finished', **summary)
    save(summary)


class PlaytestService:
    def __init__(self, output, model=None):
        self.output, self.model = output, model
        self.lock = threading.Lock()
        self.active = None
        self.cancelled = None

    def launch(self, config, *, model=None):
        with self.lock:
            if self.active is not None:
                return None
            run = secrets.token_hex(8)
            directory = self.output / run
            directory.mkdir(parents=True, mode=0o700)
            self.active = run
            cancelled = self.cancelled = threading.Event()
            adapter = (model or self.model) if config['driver'] == 'deepseek' else None
            def save(summary):
                draft = directory / 'summary.tmp'
                draft.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
                draft.replace(directory / 'summary.json')
            save(dict(id=run, status='queued', config=config))
            def worker():
                try:
                    play_batch(run, directory, config, adapter, save, cancelled)
                finally:
                    with self.lock:
                        self.active = None
                        self.cancelled = None
            threading.Thread(target=worker, daemon=True, name='vgc-playtest').start()
            return run

    def cancel(self, run):
        with self.lock:
            if self.active != run:
                return False
            self.cancelled.set()
            return True

    def summary(self, run):
        if not re.fullmatch(r'[0-9a-f]{16}', run):
            return None
        try:
            data = json.loads((self.output / run / 'summary.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        if data['status'] in ('queued', 'running'):
            with self.lock:
                if self.active == run and self.cancelled.is_set():
                    data['status'] = 'cancelling'
                elif self.active != run:
                    data['status'] = 'interrupted'
        return data

    def recent(self, limit=20):
        if not self.output.exists():
            return []
        directories = sorted(self.output.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
        runs = [self.summary(path.name) for path in directories[:limit]]
        return [run for run in runs if run]


def send_log(handler, path, filename=None):
    try:
        stream = path.open('rb')
    except FileNotFoundError:
        return handler.respond({'error': '暂时没有日志。'}, 404)
    with stream:
        remaining = os.fstat(stream.fileno()).st_size
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        handler.send_header('Content-Length', str(remaining))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            handler.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        handler.end_headers()
        while remaining:
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


def serve(port, service):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, data, status=200, mime='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            host = self.headers.get('Host')
            port = self.server.server_port
            return host in (f'127.0.0.1:{port}', f'localhost:{port}') and self.headers.get('Origin') in (None, 'http://' + host)

        def do_GET(self):
            if not self.local():
                return self.respond({'error': '仅允许本机访问。'}, 403)
            if self.path == '/options':
                return self.respond(dict(modes=MODES, rules=BOOLEAN_OPTIONS, skills=list(SKILLS.values()),
                                         deepseek=service.model.model if service.model else None))
            match = re.fullmatch(r'/runs/([0-9a-f]{16})(/log)?', self.path)
            if not match:
                return self.respond({'error': '接口不存在。'}, 404)
            run, log = match.groups()
            directory = service.output / run
            summary = service.summary(run)
            if not summary:
                return self.respond({'error': '找不到测试任务。'}, 404)
            if log:
                file = directory / 'events.jsonl'
                return send_log(self, file)
            return self.respond(summary)

        def do_POST(self):
            if not self.local():
                return self.respond({'error': '仅允许本机访问。'}, 403)
            if self.path != '/runs':
                return self.respond({'error': '接口不存在。'}, 404)
            if self.headers.get_content_type() != 'application/json':
                return self.respond({'error': '请发送 application/json。'}, 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8192:
                    raise ValueError('请求大小无效。')
                config = run_config(json.loads(self.rfile.read(size)), bool(service.model))
            except (ValueError, UnicodeError) as error:
                return self.respond({'error': str(error)}, 400)
            run = service.launch(config)
            if run is None:
                return self.respond({'error': '已有测试在运行。'}, 409)
            self.respond(dict(id=run, status=f'/runs/{run}', log=f'/runs/{run}/log'), 202)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4144)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    adapter = DeepSeek(key, os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash')) if key else None
    with serve(args.port, PlaytestService(args.output, adapter)) as host:
        print(f'VGC playtest: http://127.0.0.1:{host.server_port}', flush=True)
        try:
            host.serve_forever()
        except KeyboardInterrupt:
            pass
