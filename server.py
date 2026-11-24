#!/usr/bin/env python3
import copy
import hashlib
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
import ipaddress
import socket
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from engine import Game, RuleError, MODES, LABELS, printed_rank
from conveyor import ConveyorGame
from conveyor_skills import SKILLS, available as conveyor_skills
from analytics import Analytics
from admin import start_admin
from playtest_web import WebPlaytest, initialize_access, set_access

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'data' / 'poker.sqlite3'
ROOMS, MODEL_CONFIG, ATTEMPTS = {}, {}, {}
WATCHING = {}
RESERVED_ROOM = '001255'
LOCK = threading.RLock()
BOT_BUSY = set()

def db():
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection

STATS = Analytics(db)
WEB_PLAYTEST = WebPlaytest()

def initialize():
    DB_PATH.parent.mkdir(exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, salt TEXT NOT NULL, password TEXT NOT NULL, points INTEGER NOT NULL DEFAULT 1000, wins INTEGER NOT NULL DEFAULT 0, games INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, room TEXT NOT NULL, mode TEXT NOT NULL, outcome TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS rating_events(result_id TEXT NOT NULL REFERENCES results(id), user_id INTEGER NOT NULL REFERENCES users(id), delta INTEGER NOT NULL, PRIMARY KEY(result_id,user_id));
        ''')
        initialize_access(c)
        c.execute('DELETE FROM sessions WHERE expires < ?', (int(time.time()),))
    STATS.initialize()

def rank(points):
    return next(name for limit, name in ((800, '纸牌学徒'), (1100, '墨线新秀'), (1400, '银笔高手'), (1800, '黑金大师'), (2400, '牌桌宗师'), (10**9, '无冕传奇')) if points < limit)

def user_view(row):
    return {'id': row['id'], 'name': row['username'], 'points': row['points'], 'rank': rank(row['points']), 'wins': row['wins'], 'games': row['games']}

def persist_result(room, reason='normal'):
    g = room['game']
    if g.phase != 'over' or room.get('settled'): return
    rated = all(not p.get('bot') for p in room['players'])
    room['rated'] = rated
    delta = 24 if g.mode == 'landlord' else 20
    with db() as c:
        c.execute('INSERT INTO results VALUES(?,?,?,?,?)', (room['matchId'], room['code'], g.mode, json.dumps({'winner': g.winner, 'rated': rated, 'order': g.finished}), int(time.time())))
        if rated:
            for seat, player in enumerate(room['players']):
                won = seat in g.winner
                change = delta if won else -delta
                c.execute('UPDATE users SET points = MAX(0,points+?), games=games+1, wins=wins+? WHERE id=?', (change, int(won), player['id']))
                c.execute('INSERT INTO rating_events VALUES(?,?,?)', (room['matchId'], player['id'], change))
    STATS.finish(room, 'completed', reason)
    room['settled'] = True
    g.announce('真人对局已结算积分。' if rated else '练习对局：含AI玩家，本局不计积分。')

def room_of(uid):
    return next((r for r in ROOMS.values() if any(p['id'] == uid and not p.get('departed') for p in r['players'])), None)

def leave_room(room, uid):
    if room.get('game') and room['game'].phase != 'over' and not room.get('single'):
        player = next(p for p in room['players'] if p['id'] == uid)
        player.update(departed=True, autoplay=True, connected=False, audioEnabled=False, seen=0)
        humans = [p for p in room['players'] if not p.get('bot') and not p.get('departed')]
        if room['host'] == uid: room['host'] = humans[0]['id'] if humans else None
        if not humans:
            STATS.finish(room, 'interrupted', 'leave')
            ROOMS.pop(room['code'], None)
        return
    if room.get('game') and room['game'].phase != 'over': STATS.finish(room, 'interrupted', 'leave')
    room['players'] = [p for p in room['players'] if p['id'] != uid]
    room['game'] = None; room.pop('audioEvent', None)
    humans = [p for p in room['players'] if not p.get('bot') and not p.get('departed')]
    if not humans: del ROOMS[room['code']]
    elif room['host'] == uid:
        room['host'] = humans[0]['id']
        if room['options'].get('_alternate'):
            room.pop('modelConfig', None)
            if room['host'] in MODEL_CONFIG: room['modelConfig'] = MODEL_CONFIG[room['host']].copy()

def audio_waiting(room):
    event = room.get('audioEvent')
    if not event: return False
    active = {p['id'] for p in room['players'] if not p.get('bot') and p.get('audioEnabled') and time.time() - p.get('seen', 0) < 15}
    return bool((set(event['listeners']) & active) - set(event['acknowledged']))

def queue_audio(room, items):
    room['audioSequence'] = room.get('audioSequence', 0) + 1
    room['audioEvent'] = {'id': room['audioSequence'], 'items': items, 'listeners': [p['id'] for p in room['players'] if not p.get('bot') and p.get('audioEnabled')], 'acknowledged': []}
    g = room.get('game')
    if room.get('priorityClock') and (audio_waiting(room) or g and g.mode == 'conveyor' and g.core.pending):
        room['priorityClock'].setdefault('pausedAt', time.time())

def confirmation_seat(room):
    g = room.get('game')
    if not g or g.phase != 'setup': return None
    core = g.core if g.mode == 'conveyor' else g
    pending = [s for s in core.confirmation_seats() if s not in core.rps]
    start = core.first or 0
    if g.mode == 'conveyor': start = core.owners[start]
    if g.mode == 'conveyor': pending = [core.owners[s] for s in pending]
    return min(pending, key=lambda s: (start - s) % len(room['players']), default=None)

def update_priority_clock(room, expire=True):
    g = room.get('game')
    if not g or g.phase != 'play' or room.get('single') or not g.priority or not g.priority['pending']:
        room.pop('priorityClock', None); return
    actor = g.core.priority['pending'][0] if g.mode == 'conveyor' else g.priority['pending'][0]
    seat = g.core.owners[actor] if g.mode == 'conveyor' else actor
    key = (room.get('matchId'), g.play_number, actor)
    clock = room.get('priorityClock')
    now = time.time()
    if not clock or clock['key'] != key:
        clock = room['priorityClock'] = dict(key=key, seat=seat, actor=actor, expires=now+5)
        room['revision'] += 1
    if audio_waiting(room) or g.mode == 'conveyor' and g.core.pending:
        clock.setdefault('pausedAt', now)
        return
    if 'pausedAt' in clock: clock['expires'] += now - clock.pop('pausedAt')
    if expire and now >= clock['expires']:
        perform_game_action(room, seat, {'action':'priority-decline', **({'actor':actor} if g.mode == 'conveyor' else {})})
        room.pop('priorityClock', None); room['revision'] += 1

def perform_game_action(room, seat, move):
    clock = room.get('priorityClock')
    g = room['game']
    pressure = g.mode == 'conveyor' and move.get('action') == 'skill' and g.core.skills[g.actor(seat, move.get('actor'))] == 'pressure'
    choice = g.mode == 'conveyor' and move.get('action') == 'choice' and g.core.pending and g.core.owners[g.core.pending[0]['seat']] == seat
    urgent = g.mode == 'conveyor' and move.get('action') == 'urgent'
    if clock and not pressure and not choice and not urgent and room['game'].priority and clock['key'][1] == room['game'].play_number and (clock['seat'] != seat or room['game'].mode == 'conveyor' and room['game'].actor(seat,move.get('actor')) != clock['actor']): raise RuleError('等待优先管牌倒计时结束。')
    if audio_waiting(room): raise RuleError('等待本次行动播报完成。')
    if g.phase == 'setup' and move['action'] in ('confirm','reveal','promote') and confirmation_seat(room) != seat: raise RuleError('请等待逆时针轮到你确认。')
    previous = g.last_voice_play; old_phase = g.phase
    reported = set(g.reported) if g.mode != 'conveyor' else set()
    g.action(seat, **move)
    if g.mode != 'conveyor': g.finish_setup()
    if g.mode != 'conveyor':
        for reporter in g.reported - reported:
            room.setdefault('bubbles', {})[room['players'][reporter]['id']] = dict(text='我只剩%d张牌了' % g.report_counts[reporter], expires=time.time()+6)
    room.pop('idleWait', None)
    action = move['action']; items = []
    labels = {'pass': 'pass', 'priority-decline': 'pass', 'bid': 'bid-' + str(move.get('value', 0)), 'reveal': 'reveal', 'confirm': 'confirm', 'rps': 'rps', 'promote': 'promote', 'urgent': 'urgent', 'auto': 'urgent', 'tribute-pick': 'tribute-pick', 'tribute-return': 'tribute-return'}
    if g.last_voice_play is not previous:
        play = g.last_voice_play; kind = play['kind']
        key = kind + '-' + str(printed_rank(play['ranks'][0])) if kind in ('单张', '对子') else kind
        if '张飞机' in kind: key = '飞机带对' if kind.endswith('对') else '飞机带单' if '带' in kind else '飞机'
        items += [{'effect': 'play'}, {'voice': key}]
    else:
        items.append({'voice': labels.get(action, action)})
        if action == 'promote': items.append({'voice': '单张-' + str(move['rank'])})
    if g.phase == 'over' and old_phase != 'over': items.append({'effect': 'result'})
    if room.get('mode') == 'conveyor':
        reports = getattr(g.core, 'action_reports', [])
        played = g.last_voice_play is not previous
        actor = move.get('actor', g.actor(seat))
        if not played:
            key = 'cv-urgent-' + move.get('effect', 'discard') if action == 'urgent' else 'cv-skill-' + g.core.skills[actor] if action == 'skill' else 'cv-choice' if action == 'choice' else 'cv-keep' if action == 'keep' else labels.get(action, 'cv-action')
            if key in ('cv-urgent-silence', 'cv-urgent-judge-boost', 'cv-urgent-judge-color'): key = 'cv-action'
            items = [{'voice': key}]
        for report in reports:
            count = re.search(r'获得(\d+)张牌', report)
            if count: continue
            elif '牌堆已轮回' in report: items.append({'voice':'cv-recycle'})
            elif '完成出牌，第' in report: items.append({'voice':'cv-finish'})
            for verb in ('买入', '拾取', '赠送', '弃置'):
                if verb not in report: continue
                detail = report.split(verb, 1)[1]
                for suit, label in re.findall(r'(黑桃|红桃|梅花|方片)?(小王|大王|急|10|[3-9JQKA2])', detail):
                    if suit: items.append({'voice':'cv-suit-' + {'黑桃':'S','红桃':'H','梅花':'C','方片':'D'}[suit]})
                    rank = next((r for r, name in LABELS.items() if name == label), None)
                    if rank and rank != 18: items.append({'voice':'单张-' + str(rank)})
                break
        for target, count in getattr(g.core, 'action_gains', []):
            items.append({'dealTo':g.core.owners[target], 'count':count})
            items.append({'voice':'cv-deal-' + str(count) if count <= 30 else 'cv-deal', 'recipient':room['players'][g.core.owners[target]]['id'], 'dealTo':g.core.owners[target], 'count':count})
        if g.phase == 'over' and old_phase != 'over' and not any(i.get('effect') == 'result' for i in items): items.append({'effect':'result'})
    queue_audio(room, items)

CHAT_PHRASES = ('悲', '你能秒我？', '给阿姨倒一杯卡布奇诺')

def matchable(room, mode=None):
    return (room['code'] != RESERVED_ROOM and not room.get('single') and not room['options'].get('_alternate')
            and room['options'].get('allowMatching') is True and (mode is None or room['mode'] == mode)
            and (not room.get('game') or room['game'].phase == 'over') and len(room['players']) < MODES[room['mode']]
            and any(p['id'] == room['host'] and not p.get('bot') and p.get('connected') and time.time() - p.get('seen', 0) < 15 for p in room['players']))

def match_counts():
    return {mode: sum(matchable(r, mode) for r in ROOMS.values()) for mode in MODES}

def room_view(room, uid):
    seat = next((i for i, p in enumerate(room['players']) if p['id'] == uid and not p.get('departed')), None)
    spectator = seat is None
    if room.get('game'): update_priority_clock(room, expire=False)
    game = room['game'].view(seat) if room.get('game') else None
    if game:
        g = room['game']
        core = g.core if g.mode == 'conveyor' else g
        shown = room.get('shownSeats', ()) if room.get('shownMatch') == room.get('matchId') else ()
        watching = spectator and room['options'].get('allowSpectators') and not room.get('single')
        game['publicHands'] = core.public_hands(None if watching else shown)
        game['confirmTurn'] = confirmation_seat(room)
        if game['phase'] == 'setup':
            game['confirmationSeats'] = sorted({core.owners[s] if g.mode == 'conveyor' else s for s in core.confirmation_seats()})
        clock = room.get('priorityClock')
        game['priorityClock'] = {'seat':clock['seat'], 'actor':clock['actor'], 'paused':'pausedAt' in clock, 'remaining':max(0, __import__('math').ceil(clock['expires']-clock.get('pausedAt', time.time())))} if clock else None
    if spectator and game: game['response'] = None; game['priority'] = None

    return {'single': bool(room.get('single')), 'code': room['code'], 'mode': room['mode'], 'host': room['host'], 'seat': seat, 'players': [{k: p.get(k) for k in ('id', 'name', 'bot', 'model', 'connected', 'autoplay', 'skill', 'botSkill')} for p in room['players']],
            'skills': conveyor_skills(room['options']) if room['mode'] == 'conveyor' else [], 'spectator': spectator, 'matchId': room.get('matchId'), 'capacity': MODES[room['mode']], 'options': {k:v for k,v in room['options'].items() if not k.startswith('_')}, 'rated': all(not p.get('bot') for p in room['players']), 'canLeave': bool(room['options'].get('_alternate')),
            'audioEvent': {'id':room['audioEvent']['id'], 'items':[{k:v for k,v in item.items() if k != 'recipient'} for item in room['audioEvent']['items'] if 'recipient' not in item or item['recipient'] == uid]} if room.get('audioEvent') and not spectator else None, 'audioWaiting': audio_waiting(room) if not spectator else False, 'bubbles': {str(i): room['bubbles'][p['id']]['text'] for i, p in enumerate(room['players']) if room.get('bubbles', {}).get(p['id'], {}).get('expires', 0) > time.time()}, 'game': game, 'revision': room['revision']}

def validate_endpoint(endpoint):
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise RuleError('模型地址应为 HTTPS API 地址，不含账号、查询参数或片段。')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): raise RuleError('模型API必须使用公网地址。')
    except socket.gaierror: raise RuleError('无法解析模型API地址。')
    return endpoint.rstrip('/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def model_move(config, g, seat):
    if g.priority and not g.priority['pending'] and seat in g.priority['bots']:
        moves = [{'action': 'priority-play', 'special': m['action'], 'ids': m['ids'], **({'wildcard': m['wildcard']} if 'wildcard' in m else {})} for m in g.priority_moves(seat)[:50]] + [{'action': 'priority-decline'}]
    else:
        moves = g.candidates(seat)[:50]
        if g.last and g.last_seat != seat: moves.append({'action': 'pass'})
    if not moves: return {'action': 'pass'}
    endpoint = validate_endpoint(config['endpoint'])
    if not endpoint.endswith('/chat/completions'): endpoint += '/chat/completions'
    # Only this bot's hand and public table state are shared with its configured provider.
    prompt = {'table': g.view(seat), 'legal_moves': [{**m, 'index': i} for i, m in enumerate(moves)]}
    system = 'You are a card-game player. Choose one legal_moves index to maximize your winning chance. Return only JSON: {"index": 0}.'
    if g.mode == 'conveyor': system += ' This is free-for-all: there are no teammates; first place gains two levels, second place one, others none.'
    payload = {'model': config['model'], 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)}], 'temperature': .2, 'max_tokens': 80}
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['key']})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=12) as response:
        raw = response.read(65537)
        if len(raw) > 65536: raise ValueError('Response too large')
        content = json.loads(raw)['choices'][0]['message']['content'].strip()
        if content.startswith('```'): content = content.strip('`').removeprefix('json').strip()
        index = json.loads(content)['index']
        if not isinstance(index, int) or index not in range(len(moves)): raise ValueError('Invalid move')
        return moves[index]

def tick_bot(code, seat, version, snapshot, config, match_id=None):
    try:
        began = time.monotonic(); failed = False
        try: move = model_move(config, snapshot, seat)
        except Exception: failed = True; move = snapshot.bot_action(seat)
        seconds = time.monotonic() - began
        with LOCK:
            STATS.ai(config.get('model', 'unknown'), failed, seconds)
            room = ROOMS.get(code)
            if room and room['revision'] == version and (match_id is None or room.get('matchId') == match_id) and move and not audio_waiting(room):
                try:
                    perform_game_action(room, seat, move)
                    room['revision'] += 1
                    persist_result(room)
                except RuleError: pass
    finally:
        with LOCK: BOT_BUSY.discard(code)

def update_autoplay(room):
    g = room.get('game')
    if room.get('single') or not g or g.phase == 'over':
        room.pop('idleWait', None)
        return
    now = time.time()
    def take_over(seat):
        player = room['players'][seat]
        if player.get('bot') or player.get('autoplay') or seat in g.finished: return
        player['autoplay'] = True
        room['revision'] += 1
        g.announce(player['name'] + '已自动托管。')
    for seat, player in enumerate(room['players']):
        if player['id'] == room['host'] and now - player.get('seen', 0) >= 15:
            player['connected'] = False
            take_over(seat)
    if audio_waiting(room) or g.phase != 'play':
        room.pop('idleWait', None)
        return
    if room.get('mode') == 'conveyor' and g.core.pending: waiting = [g.core.owners[g.core.pending[0]['seat']]]
    else: waiting = g.priority['pending'] if g.priority_paused() else [g.turn]
    old = room.get('idleWait', {})
    room['idleWait'] = {seat: old.get(seat, now) for seat in waiting if seat not in g.finished and not (room['players'][seat].get('bot') or room['players'][seat].get('autoplay'))}
    for seat, since in room['idleWait'].items():
        if now - since >= 60: take_over(seat)

def bot_loop():
    while True:
        time.sleep(.9)
        with LOCK:
            for room in list(ROOMS.values()):
                g = room.get('game')
                if not g or g.phase == 'over': continue
                update_autoplay(room)
                update_priority_clock(room)
                if room['code'] in BOT_BUSY or audio_waiting(room): continue
                clock = room.get('priorityClock') if not (g.mode == 'conveyor' and g.core.pending) else None
                if clock and not room['players'][clock['seat']].get('autoplay'): continue
                if g.priority_paused(): continue
                if not clock and g.forced_pass():
                    perform_game_action(room, g.turn, {'action': 'pass'})
                    room['revision'] += 1
                    continue
                for seat, p in enumerate(room['players']):
                    if clock and clock['seat'] != seat: continue
                    if not (p.get('bot') or p.get('autoplay')): continue
                    if g.phase == 'setup' and confirmation_seat(room) != seat: continue
                    move = g.bot_action(seat)
                    if not move: continue
                    config = room.get('modelConfig') if p.get('bot') and p.get('model') else None
                    if config and g.phase == 'play' and not (room['mode'] == 'conveyor' and g.core.pending):
                        BOT_BUSY.add(room['code'])
                        threading.Thread(target=tick_bot, args=(room['code'], seat, room['revision'], copy.deepcopy(g), config.copy(), room['matchId']), daemon=True).start()
                    else:
                        try:
                            perform_game_action(room, seat, move)
                            room['revision'] += 1
                            persist_result(room)
                        except RuleError as e: g.announce('AI出牌失败：' + str(e))
                    break

class Handler(BaseHTTPRequestHandler):
    server_version = 'PaperPoker/1.0'
    def log_message(self, format, *args):
        # Avoid logging request bodies, model keys, passwords, or cookies.
        if '/api/state' not in args[0]: super().log_message(format, *args)

    def respond(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        cookie = http.cookies.SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: return None
        token = cookie.get('poker_session')
        if not token: return None
        with db() as c:
            return c.execute('''SELECT users.*, EXISTS(SELECT 1 FROM playtest_access WHERE user_id=users.id) AS can_playtest
                                FROM users JOIN sessions ON users.id=sessions.user_id WHERE token=? AND expires>?''',
                             (token.value, int(time.time()))).fetchone()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/playtest' or path.startswith('/api/playtest/'):
            return WEB_PLAYTEST.get(self, DB_PATH.parent, self.session(), path)
        if path.startswith('/api/'):
            with LOCK:
                user = self.session()
                if path == '/api/health': return self.respond({'ok': True, 'port': self.server.server_port})
                if path == '/api/state':
                    if not user: return self.respond({'user': None, 'room': None, 'matchCounts': match_counts(), 'features': {'wildUrgent': True, 'conveyorSkills': list(SKILLS.values()), 'chatPhrases': CHAT_PHRASES}})
                    if self.headers.get('X-Poker-Audio') != '0': STATS.activity(user['id'])
                    room = room_of(user['id'])
                    if room:
                        p = next(p for p in room['players'] if p['id'] == user['id'])
                        p['connected'] = True; p['seen'] = time.time(); p['audioEnabled'] = self.headers.get('X-Poker-Audio') == '1'
                        for p in room['players']:
                            if not p.get('bot'): p['connected'] = time.time() - p.get('seen', 0) < 15
                    if not room:
                        room = ROOMS.get(WATCHING.get(user['id']))
                        if room and not room['options'].get('allowSpectators'): room = None
                        if not room: WATCHING.pop(user['id'], None)
                    return self.respond({'matchCounts': match_counts(), 'features': {'wildUrgent': True, 'conveyorSkills': list(SKILLS.values()), 'chatPhrases': CHAT_PHRASES, 'playtest': bool(user['can_playtest'])}, 'user': user_view(user), 'room': room_view(room, user['id']) if room else None, 'preferences': {'configured': user['id'] in MODEL_CONFIG, **{k: v for k, v in MODEL_CONFIG.get(user['id'], {}).items() if k != 'key'}}})
                if not user: return self.respond({'error': '请先登录。'}, 401)
                if path == '/api/leaderboard':
                    with db() as c: users = c.execute('SELECT * FROM users ORDER BY points DESC, wins DESC LIMIT 50').fetchall()
                    return self.respond({'players': [user_view(u) for u in users]})
                if path == '/api/history':
                    with db() as c:
                        rows = c.execute('SELECT results.mode, results.created, rating_events.delta FROM rating_events JOIN results ON result_id=results.id WHERE user_id=? ORDER BY created DESC LIMIT 20', (user['id'],)).fetchall()
                    return self.respond({'history': [dict(r) for r in rows]})
                return self.respond({'error': '接口不存在。'}, 404)
        filename = 'index.html' if path == '/' else path.lstrip('/')
        file = (ROOT / 'public' / filename).resolve()
        if not file.is_relative_to(ROOT / 'public') or not file.is_file(): return self.respond({'error': '页面不存在。'}, 404)
        content = file.read_bytes()
        if file.name == 'index.html':
            for asset in ('app.js', 'conveyor.js', 'audio.js', 'style.css', 'splashes.js', 'playtest.js'):
                version = hashlib.sha256((ROOT / 'public' / asset).read_bytes()).hexdigest()[:12]
                content = content.replace(('/' + asset + '"').encode(), ('/' + asset + '?v=' + version + '"').encode())
        self.send_response(200)
        self.send_header('Content-Type', {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4'}.get(file.suffix, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('CDN-Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers(); self.wfile.write(content)

    def do_POST(self):
        # Reject cross-origin requests even if a browser attaches a session cookie.
        origin = self.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'): return self.respond({'error': '跨站请求被拒绝。'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384: return self.respond({'error': '请求大小无效。'}, 400)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict): raise ValueError()
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/playtest' or path.startswith('/api/playtest/'):
                return WEB_PLAYTEST.post(self, DB_PATH.parent, self.session(), path, body)
            with LOCK: self.post(path, body)
        except (RuleError, ValueError, TypeError, KeyError) as e:
            self.respond({'error': str(e) if isinstance(e, RuleError) else '请求参数无效。'}, 400)
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond({'error': '服务暂时无法处理请求。'}, 500)

    def post(self, path, b):
        if path in ('/api/register', '/api/login'):
            ip = self.client_address[0]
            attempts = ATTEMPTS.setdefault(ip, [])
            attempts[:] = [t for t in attempts if time.time() - t < 60]
            if len(attempts) >= 20: return self.respond({'error': '请求过于频繁，请稍后再试。'}, 429)
            attempts.append(time.time())
            name, password = b.get('name', ''), b.get('password', '')
            if not isinstance(name, str) or not isinstance(password, str): raise RuleError('昵称与密码格式无效。')
            name = name.strip()
            if not 2 <= len(name) <= 18 or not 8 <= len(password) <= 128: raise RuleError('昵称为2–18个字符，密码为8–128个字符。')
            if any(ord(c) < 32 for c in name): raise RuleError('昵称包含无效字符。')
            with db() as c:
                if path == '/api/register':
                    salt = secrets.token_hex(16)
                    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
                    try: c.execute('INSERT INTO users(username,salt,password,created) VALUES(?,?,?,?)', (name, salt, hashed, int(time.time())))
                    except sqlite3.IntegrityError: raise RuleError('这个昵称已被注册。')
                user = c.execute('SELECT * FROM users WHERE username=?', (name,)).fetchone()
                if not user or not secrets.compare_digest(user['password'], hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(user['salt']), 600000).hex()): raise RuleError('昵称或密码不正确。')
                token = secrets.token_urlsafe(32)
                c.execute('INSERT INTO sessions VALUES(?,?,?)', (token, user['id'], int(time.time()) + 7 * 86400))
            secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' or self.headers.get('Origin', '').startswith('https://') else ''
            STATS.activity(user['id'])
            return self.respond({'user': user_view(user)}, cookie='poker_session=' + token + '; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800' + secure)
        user = self.session()
        if not user: return self.respond({'error': '请先登录。'}, 401)
        uid = user['id']
        if path != '/api/play-preview' and self.headers.get('X-Poker-Audio') != '0': STATS.activity(uid)
        if path == '/api/logout':
            WATCHING.pop(uid, None)
            room = room_of(uid)
            if room and room['options'].get('_alternate'):
                leave_room(room, uid); room['revision'] += 1
            cookie = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
            with db() as c: c.execute('DELETE FROM sessions WHERE token=?', (cookie['poker_session'].value,))
            return self.respond({'ok': True}, cookie='poker_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
        if path == '/api/model-settings':
            if b.get('clear') is True:
                MODEL_CONFIG.pop(uid, None)
                for r in ROOMS.values():
                    if r['host'] == uid: r.pop('modelConfig', None); r['revision'] += 1
                return self.respond({'ok': True})
            endpoint = validate_endpoint(str(b.get('endpoint', '')))
            key = str(b.get('key', '')).strip() or MODEL_CONFIG.get(uid, {}).get('key', '')
            model = str(b.get('model', '')).strip()
            if not key or not model or len(key) > 4096 or len(model) > 100 or '\n' in key or '\r' in key: raise RuleError('请输入有效的API密钥和模型名称。')
            MODEL_CONFIG[uid] = {'endpoint': endpoint, 'key': key, 'model': model}
            for r in ROOMS.values():
                if r['host'] == uid: r['modelConfig'] = MODEL_CONFIG[uid].copy(); r['revision'] += 1
            return self.respond({'ok': True})
        if path == '/api/account':
            current = b.get('currentPassword', '')
            if not isinstance(current, str) or not secrets.compare_digest(user['password'], hashlib.pbkdf2_hmac('sha256', current.encode(), bytes.fromhex(user['salt']), 600000).hex()): raise RuleError('当前密码不正确。')
            name, password = b.get('name', user['username']), b.get('newPassword', '')
            if not isinstance(name, str) or not isinstance(password, str): raise RuleError('账号信息格式无效。')
            name = name.strip()
            if not 2 <= len(name) <= 18 or any(ord(c) < 32 for c in name): raise RuleError('昵称为2–18个字符，不含控制字符。')
            if password and not 8 <= len(password) <= 128: raise RuleError('新密码为8–128个字符。')
            salt, hashed = user['salt'], user['password']
            if password:
                salt = secrets.token_hex(16)
                hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
            with db() as c:
                try: c.execute('UPDATE users SET username=?,salt=?,password=? WHERE id=?', (name, salt, hashed, uid))
                except sqlite3.IntegrityError: raise RuleError('这个昵称已被注册。')
                if password:
                    cookie = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
                    c.execute('DELETE FROM sessions WHERE user_id=? AND token!=?', (uid, cookie['poker_session'].value))
            for r in ROOMS.values():
                for p in r['players']:
                    if p['id'] == uid: p['name'] = name; r['revision'] += 1
            return self.respond({'ok': True})
        room = room_of(uid)
        if path == '/api/watch':
            if room: raise RuleError('请先离开当前房间。')
            target = ROOMS.get(str(b.get('code', '')).strip())
            if not target or target.get('single') or not target['options'].get('allowSpectators'): raise RuleError('房间不存在或不允许观战。')
            WATCHING[uid] = target['code']
            return self.respond({'ok': True, 'room': room_view(target, uid)})
        if path == '/api/leave' and not room and uid in WATCHING:
            WATCHING.pop(uid, None)
            return self.respond({'ok': True, 'room': None})
        if path == '/api/match':
            if room: raise RuleError('请先离开当前房间。')
            mode = b.get('mode')
            if mode not in MODES: raise RuleError('未知玩法。')
            target = next((r for r in ROOMS.values() if matchable(r, mode)), None)
            if not target: raise RuleError('暂无可匹配房间，可先创建房间。')
            b = {'code': target['code']}; path = '/api/join'
        reserved = path == '/api/join' and str(b.get('code', '')).strip() == RESERVED_ROOM
        single = path == '/api/join' and b.get('single') is True
        if single and not reserved: raise RuleError('房间不存在，请检查六位房间号。')
        if path == '/api/create' or reserved and (single or RESERVED_ROOM not in ROOMS):
            if room: raise RuleError('请先离开当前房间。')
            mode = 'standard' if reserved else b.get('mode', 'landlord')
            if mode not in MODES: raise RuleError('未知玩法。')
            code = ''.join(secrets.choice('0123456789') for _ in range(6))
            while code in ROOMS or code == RESERVED_ROOM: code = ''.join(secrets.choice('0123456789') for _ in range(6))
            if reserved and not single: code = RESERVED_ROOM
            if not isinstance(b.get('options', {}), dict): raise RuleError('房间选项格式无效。')
            options = {k: b.get('options', {}).get(k) is True for k in ('advancedHui', 'advancedDead', 'dlc', 'tribute')}
            for key in ('advancedHui', 'advancedDead'): options[key] = mode in ('standard', 'trio', 'conveyor') and b.get('options', {}).get(key, True) is True
            for key in ('allowMatching', 'allowSpectators'): options[key] = not reserved and not b.get('single') and b.get('options', {}).get(key) is True
            if mode == 'conveyor':
                options['dlc'] = False
                options['tribute'] = False
                options['recycle'] = False
                options['firstOutEndsRound'] = b.get('options', {}).get('firstOutEndsRound') is True
                groups = b.get('options', {}).get('skillDlc', [])
                disabled = b.get('options', {}).get('disabledSkills', [])
                if not isinstance(groups, list) or any(type(n) is not int or n not in (1, 2, 3, 4, 5) for n in groups): raise RuleError('技能 DLC 选项无效。')
                if not isinstance(disabled, list) or any(k not in SKILLS for k in disabled): raise RuleError('禁用技能选项无效。')
                options['skillDlc'] = list(set(groups)); options['disabledSkills'] = list(set(disabled))
                if not conveyor_skills(options): raise RuleError('传送带至少需要开放一个技能。')
            if reserved: options = {'advancedHui': True, 'advancedDead': False, 'dlc': False, 'tribute': False, '_alternate': True}
            room = {'code': code, 'mode': mode, 'host': uid, 'players': [{'id': uid, 'name': user['username'], 'seen': time.time(), 'connected': True, 'audioEnabled': self.headers.get('X-Poker-Audio') == '1'}], 'options': options, 'game': None, 'revision': 1}
            if b.get('single') is True: room['single'] = True
            WATCHING.pop(uid, None)
            if uid in MODEL_CONFIG: room['modelConfig'] = MODEL_CONFIG[uid].copy()
            ROOMS[code] = room
            if single:
                room['single'] = True
                for number in range(1, 4): room['players'].append({'id': 'bot-' + secrets.token_hex(4), 'name': str(number) + '号', 'bot': True, 'model': False, 'connected': True})
                room['game'] = Game('standard', room['players'], options, interactive=True)
                room['game'].finish_setup()
                room.pop('idleWait', None)
                room['settled'] = False; room['matchId'] = secrets.token_hex(16)
                STATS.start(room)
                queue_audio(room, [{'effect': 'deal'}, {'voice': 'deal'}])
        elif path == '/api/join':
            if room: raise RuleError('请先离开当前房间。')
            code = str(b.get('code', '')).strip()
            room = ROOMS.get(code)
            if not room: raise RuleError('房间不存在，请检查六位房间号。')
            if room.get('single'): raise RuleError('房间不可加入。')
            if room['game'] and room['game'].phase != 'over': raise RuleError('本房间正在对局。')
            if len(room['players']) >= MODES[room['mode']]: raise RuleError('房间已满。')
            room['game'] = None
            WATCHING.pop(uid, None)
            room['players'].append({'id': uid, 'name': user['username'], 'seen': time.time(), 'connected': True, 'audioEnabled': self.headers.get('X-Poker-Audio') == '1'})
            room['revision'] += 1
        else:
            if not room: raise RuleError('你还没有加入房间。')
            host = room['host'] == uid
            seat = next(i for i, p in enumerate(room['players']) if p['id'] == uid)
            if path == '/api/play-preview':
                g = room['game']
                if not g or g.phase != 'play' or seat in g.finished or room['players'][seat].get('autoplay'):
                    return self.respond({'kind': None})
                if b.get('revision') != room['revision']:
                    return self.respond({'stale': True})
                ids = b.get('ids')
                if not isinstance(ids, list) or not ids or len(ids) > 128 or any(not isinstance(i, str) for i in ids):
                    raise RuleError('请选择手牌。')
                args = {k: b[k] for k in ('actor', 'double') if g.mode == 'conveyor' and k in b}
                try:
                    kind = g.preview_play(seat, ids, b.get('wildcard'), **args)
                except RuleError as error:
                    return self.respond({'kind':None, 'reason':str(error)})
                return self.respond({'kind':kind})
            room['players'][seat]['seen'] = time.time()
            if self.headers.get('X-Poker-Audio') is not None: room['players'][seat]['audioEnabled'] = self.headers.get('X-Poker-Audio') == '1'
            if path == '/api/skill':
                if room['mode'] != 'conveyor' or room.get('game') and room['game'].phase != 'over': raise RuleError('请在开局前选择技能。')
                key = b.get('skill')
                available_keys = [s['id'] for s in conveyor_skills(room['options'])]
                target = b.get('botSeat')
                if 'botSeat' in b:
                    if not host or type(target) is not int or not 0 <= target < len(room['players']) or not room['players'][target].get('bot'):
                        raise RuleError('只有房主可以为本房间的 AI 指定技能。')
                    if key is not None and key not in available_keys: raise RuleError('该技能未开放。')
                    room['players'][target]['botSkill'] = key
                else:
                    if key not in available_keys: raise RuleError('该技能未开放。')
                    room['players'][seat]['skill'] = key
                room['revision'] += 1
                return self.respond({'ok':True, 'room':room_view(room, uid)})
            if path == '/api/autoplay':
                if not isinstance(b.get('enabled'), bool): raise RuleError('托管状态无效。')
                if b['enabled'] and (not room.get('game') or room['game'].phase == 'over'): raise RuleError('请在对局中开启托管。')
                room['players'][seat]['autoplay'] = b['enabled']
                room.get('idleWait', {}).pop(seat, None)
                room['revision'] += 1
                return self.respond({'ok': True, 'room': room_view(room, uid)})
            if path == '/api/show-hand':
                if not room.get('game') or room['game'].phase == 'over': raise RuleError('请在对局中明牌。')
                if room.get('shownMatch') != room.get('matchId'):
                    room['shownMatch'] = room.get('matchId'); room['shownSeats'] = []
                if seat not in room['shownSeats']: room['shownSeats'].append(seat)
                room['revision'] += 1
                return self.respond({'ok':True, 'room':room_view(room, uid)})
            if path == '/api/chat':
                text = b.get('text')
                if text not in CHAT_PHRASES: raise RuleError('请选择预设发言。')
                if not room.get('game'): raise RuleError('请在牌桌中发言。')
                bubbles = room.setdefault('bubbles', {})
                if bubbles.get(uid, {}).get('sent', 0) > time.time() - 2: raise RuleError('发言太快，请稍候。')
                bubbles[uid] = {'text': text, 'sent': time.time(), 'expires': time.time() + 6}
                return self.respond({'ok': True, 'room': room_view(room, uid)})
            if path == '/api/audio-ack':
                if b.get('code', room['code']) != room['code'] or b.get('matchId', room.get('matchId')) != room.get('matchId'): return self.respond({'ok': True})
                event = room.get('audioEvent')
                if event and b.get('event') == event['id'] and uid not in event['acknowledged']: event['acknowledged'].append(uid)
                return self.respond({'ok': True})
            viewing_hand = path == '/api/action' and room['mode'] == 'conveyor' and b.get('action') == 'focus'
            if path in ('/api/start', '/api/action') and audio_waiting(room) and not viewing_hand: raise RuleError('等待本次行动播报完成。')
            if path == '/api/leave':
                leave_room(room, uid)
            elif path == '/api/bot':
                if not host: raise RuleError('只有房主可以添加AI。')
                if room['game'] and room['game'].phase != 'over': raise RuleError('对局中不能变更玩家。')
                if len(room['players']) >= MODES[room['mode']]: raise RuleError('房间已满。')
                model = b.get('model', False) is True
                if model and not room.get('modelConfig'): raise RuleError('请先配置模型API。')
                number = next(n for n in range(1, MODES[room['mode']]) if str(n) + '号' not in [p['name'] for p in room['players'] if p.get('bot')])
                room['players'].append({'id': 'bot-' + secrets.token_hex(4), 'name': str(number) + '号', 'bot': True, 'model': model, 'connected': True})
                room['game'] = None
            elif path == '/api/remove':
                if not host: raise RuleError('只有房主可以移除AI。')
                if room['game'] and room['game'].phase != 'over': raise RuleError('对局中不能变更玩家。')
                target = int(b.get('seat', -1))
                if target not in range(len(room['players'])) or not room['players'][target].get('bot'): raise RuleError('请选择AI玩家。')
                room['players'].pop(target); room['game'] = None
            elif path == '/api/start':
                if not host: raise RuleError('只有房主可以开始对局。')
                if len(room['players']) != MODES[room['mode']]: raise RuleError('请等待玩家加入或补充AI。')
                if room['game'] and room['game'].phase != 'over': raise RuleError('游戏已经开始。')
                for p in room['players']:
                    if p.get('departed'): p.update(id='bot-' + secrets.token_hex(4), bot=True, model=False)
                prev = room.get('game')
                previous = {'first': next((s for s in prev.finished if s not in getattr(prev, 'urgent_last', [])), 0), 'main': prev.next_main, 'scores': prev.scores, 'captured': prev.captured} if prev and prev.mode != 'landlord' else None
                if prev and prev.round_complete: previous = {'first': None, 'main': 3, 'scores': [0] * (4 if prev.mode == 'conveyor' else 2), 'captured': []}
                if room['mode'] == 'conveyor':
                    choices = [s['id'] for s in conveyor_skills(room['options'])]
                    if any(not p.get('skill') for p in room['players'] if not p.get('bot')): raise RuleError('请等待所有玩家选择技能。')
                    for p in room['players']:
                        if p.get('bot'):
                            p['skill'] = p.get('botSkill') or secrets.choice(choices)
                    if all(p.get('skill') == 'scavenge' for p in room['players']):
                        bot = next((p for p in room['players'] if p.get('bot') and not p.get('botSkill')), None)
                        starters = [key for key in choices if key != 'scavenge']
                        if bot and starters: bot['skill'] = secrets.choice(starters)
                    room['game'] = ConveyorGame(room['mode'], room['players'], room['options'], previous, interactive=True)
                else:
                    room['game'] = Game(room['mode'], room['players'], room['options'], previous, interactive=True)
                    room['game'].finish_setup()
                room.pop('idleWait', None)
                room['settled'] = False; room['matchId'] = secrets.token_hex(16)
                STATS.start(room)
                queue_audio(room, [{'effect': 'deal'}, {'voice': 'deal'}])
            elif path == '/api/hint':
                if not room['game'] or room['game'].phase != 'play': raise RuleError('请先开始出牌。')
                g = room['game']
                waiting = room['mode'] == 'conveyor' and bool(g.core.pending) or g.priority and g.solo() and seat not in g.priority['pending']
                moves = [] if waiting else g.candidates(seat)
                reason = '等待优先管牌处理完成。' if waiting else '还没轮到你出牌。' if seat != g.turn and not moves else '当前没有能管住上一手的牌。' if not moves else ''
                return self.respond({'moves': moves[:80], 'reason': reason})
            elif path == '/api/action':
                if room['players'][seat].get('autoplay'): raise RuleError('请先取消托管。')
                if not room['game']: raise RuleError('对局尚未开始。')
                if b.get('revision') != room['revision']: raise RuleError('牌桌已变化，请按最新局面出牌。')
                args = {k: v for k, v in b.items() if k in ('action', 'ids', 'value', 'rank', 'target', 'wildcard', 'special', 'actor', 'effect', 'direction', 'double', 'ranks', 'suits', 'suit')}
                if room['mode'] == 'conveyor' and args.get('action') == 'focus': room['game'].action(seat, **args)
                else: perform_game_action(room, seat, args)
                persist_result(room)
            elif path == '/api/resign':
                g = room.get('game')
                if not g or g.phase == 'over': raise RuleError('没有正在进行的对局。')
                if not room.get('single'):
                    leave_room(room, uid)
                    room['revision'] += 1
                    return self.respond({'ok':True, 'room':None})
                if g.mode == 'landlord': g.winner = [s for s in range(len(g.players)) if (s == g.landlord) != (seat == g.landlord)]
                elif g.mode == 'conveyor': g.winner = []
                elif g.mode == 'trio': g.winner = [s for s in range(len(g.players)) if s != seat]
                else: g.winner = [s for s in range(len(g.players)) if s % 2 != seat % 2]
                g.phase = 'over'; g.announce(user['username'] + '认输。'); queue_audio(room, [{'voice': 'resign'}, {'effect': 'result'}]); persist_result(room, reason='resign')
            else: return self.respond({'error': '接口不存在。'}, 404)
            room['revision'] += 1
        return self.respond({'ok': True, 'room': room_view(room, uid) if any(p['id'] == uid and not p.get('departed') for p in room['players']) else None})

def admin_snapshot():
    with LOCK: return STATS.report(list(ROOMS.values()))

def main():
    port = int(os.getenv('PORT', '4141'))
    server = ThreadingHTTPServer((os.getenv('HOST', '127.0.0.1'), port), Handler)
    initialize()
    admin = start_admin(admin_snapshot, DB_PATH.parent / 'admin-token', int(os.getenv('ADMIN_PORT', '4143')))
    threading.Thread(target=bot_loop, daemon=True).start()
    print('VGC 运行于 http://localhost:%s' % port, flush=True)
    print('本机统计后台：http://localhost:%s（管理口令：data/admin-token）' % admin.server_port, flush=True)
    server.serve_forever()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='VGC game server')
    parser.add_argument('command', nargs='?', choices=('grant-playtest', 'revoke-playtest'))
    parser.add_argument('accounts', nargs='*')
    args = parser.parse_args()
    if args.command:
        if not args.accounts:
            parser.error('请指定至少一个已注册账号。')
        try:
            with db() as connection:
                initialize_access(connection)
                for account in args.accounts:
                    set_access(connection, account, args.command == 'grant-playtest')
        except ValueError as error:
            parser.error(str(error))
        print(('已开通自动对局：' if args.command == 'grant-playtest' else '已关闭自动对局：') + '、'.join(args.accounts))
    else:
        main()
