"""Account-scoped access to the headless test runner."""

import re
import threading

from playtest import BOOLEAN_OPTIONS, DEEPSEEK_MODELS, DeepSeek, PlaytestService, run_config, send_log
from playtest_replay import read, replay_path, restore_legacy
from engine import MODES


def initialize_access(db):
    db.execute('''CREATE TABLE IF NOT EXISTS playtest_access (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE
    )''')


def set_access(db, username, granted):
    row = db.execute('SELECT id FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    if not row:
        raise ValueError(f'账号不存在：{username}')
    statement = ('INSERT OR IGNORE INTO playtest_access(user_id) VALUES (?)' if granted
                 else 'DELETE FROM playtest_access WHERE user_id = ?')
    db.execute(statement, (row[0],))


class WebPlaytest:
    def __init__(self):
        self.lock = threading.Lock()
        self.services = {}
        self.keys = {}

    def account(self, root, user_id):
        owner = root / 'playtests' / str(user_id)
        with self.lock:
            return owner, self.services.setdefault(owner, PlaytestService(owner)), self.keys.get(owner)

    def get(self, handler, root, user, path):
        if not user or not user['can_playtest']:
            return handler.respond({'error': '此账号未开通自动对局。'}, 403 if user else 401)
        _, service, key = self.account(root, user['id'])
        if path == '/api/playtest':
            return handler.respond({'configured': bool(key), 'models': DEEPSEEK_MODELS,
                                    'rules': BOOLEAN_OPTIONS, 'runs': service.recent()})
        replay = re.fullmatch(r'/api/playtest/runs/([0-9a-f]{16})/matches/([1-9][0-9]?)(?:/frames/(0|[1-9][0-9]{0,3}))?', path)
        if replay:
            run, number, frame = replay.groups()
            return self.replay(handler, service, run, int(number), None if frame is None else int(frame))
        route = re.fullmatch(r'/api/playtest/runs/([0-9a-f]{16})(/log)?', path)
        if route:
            run, log = route.groups()
            summary = service.summary(run)
            if summary:
                if log:
                    return send_log(handler, service.output / run / 'events.jsonl', f'vgc-playtest-{run}.jsonl')
                return handler.respond(summary)
        return handler.respond({'error': '找不到测试任务。'}, 404)

    def replay(self, handler, service, run, number, frame):
        summary = service.summary(run)
        if not summary:
            return handler.respond({'error': '找不到测试任务。'}, 404)
        result = next((m for m in summary.get('matches', []) if m['match'] == number), None)
        if result is None and summary['status'] in ('failed', 'interrupted') and summary.get('currentMatch') == number:
            result = dict(status=summary['status'])
        if result is None:
            return handler.respond({'error': '这局暂时没有回放。'}, 404)
        directory = service.output / run
        path = replay_path(directory, number)
        config = summary['config']
        try:
            with service.lock:
                if not path.exists():
                    restore_legacy(directory, path, number, config, result)
                record = read(path, 0 if frame is None else frame)
        except FileNotFoundError:
            record = None
        if record is None:
            return handler.respond({'error': '找不到回放画面。'}, 404)
        frames, view = record
        if frame is not None:
            return handler.respond(view)
        mode = config['mode']
        skills = result.get('skills', config['skills'])
        if mode == 'conveyor':
            skills = [next(a['skill'] for a in view['game']['conveyor']['actors'] if a['owner'] == s) for s in range(MODES[mode])]
        players = [dict(name=f'{s+1}号', bot=True, connected=True, skill=skills[s]) for s in range(MODES[mode])]
        room = dict(replay=True, spectator=True, seat=None, players=players, mode=mode,
                    capacity=MODES[mode], matchId=f'{run}/{number}', code='replay', options=config['options'])
        return handler.respond(dict(room=room, status=result['status'], frames=frames, first=view))

    def post(self, handler, root, user, path, body):
        if not user or not user['can_playtest']:
            return handler.respond({'error': '此账号未开通自动对局。'}, 403 if user else 401)
        owner, service, key = self.account(root, user['id'])
        if path == '/api/playtest/credential':
            if body == {'clear': True}:
                with self.lock:
                    self.keys.pop(owner, None)
                return handler.respond({'configured': False})
            key = body.get('key')
            if (set(body) != {'key'} or not isinstance(key, str) or
                    not re.fullmatch(r'[!-~]{1,512}', key.strip())):
                return handler.respond({'error': '请输入有效的 DeepSeek API Key。'}, 400)
            with self.lock:
                self.keys[owner] = key.strip()
            return handler.respond({'configured': True})
        if path == '/api/playtest/runs':
            config = dict(body)
            model = config.pop('model', DEEPSEEK_MODELS[0])
            thinking = config.pop('thinking', False)
            if model not in DEEPSEEK_MODELS or type(thinking) is not bool:
                return handler.respond({'error': '请选择有效模型和思考模式。'}, 400)
            if config.get('driver', 'deepseek') == 'deepseek' and key is None:
                return handler.respond({'error': '请先在本页保存你的 DeepSeek API Key。'}, 400)
            try:
                config = run_config(config, bool(key))
            except ValueError as error:
                return handler.respond({'error': str(error)}, 400)
            adapter = DeepSeek(key, model, thinking) if config['driver'] == 'deepseek' else None
            run = service.launch(config, model=adapter)
            if run is None:
                return handler.respond({'error': '已有任务在运行。'}, 409)
            return handler.respond({'id': run}, 202)
        match = re.fullmatch(r'/api/playtest/runs/([0-9a-f]{16})/cancel', path)
        if match and service.cancel(match[1]):
            return handler.respond({'ok': True})
        return handler.respond({'error': '没有可停止的任务。'}, 404)
