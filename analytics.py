import time
from collections import Counter
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


class Analytics:
    def __init__(self, connect):
        self.connect = connect
        self.seen = {}
        self.written = {}

    def initialize(self):
        now = time.time()
        self.seen.clear(); self.written.clear()
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS usage_meta(key TEXT PRIMARY KEY, value REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage_daily(day TEXT NOT NULL, user_id INTEGER NOT NULL,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY(day,user_id));
                CREATE TABLE IF NOT EXISTS usage_matches(id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                    variant TEXT NOT NULL, channel TEXT NOT NULL, humans INTEGER NOT NULL,
                    bots INTEGER NOT NULL, models INTEGER NOT NULL, started REAL NOT NULL,
                    ended REAL, status TEXT NOT NULL, reason TEXT);
                CREATE INDEX IF NOT EXISTS usage_matches_started ON usage_matches(started);
                CREATE TABLE IF NOT EXISTS usage_ai(day TEXT NOT NULL, model TEXT NOT NULL,
                    requests INTEGER NOT NULL, failures INTEGER NOT NULL, seconds REAL NOT NULL,
                    PRIMARY KEY(day,model));
            ''')
            columns = {row[1] for row in c.execute('PRAGMA table_info(usage_ai)')}
            for column in ('cache_hits', 'cache_misses'):
                if column not in columns:
                    c.execute(f'ALTER TABLE usage_ai ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
            c.execute("INSERT OR IGNORE INTO usage_meta VALUES('since',?)", (now,))
            c.execute("UPDATE usage_matches SET ended=?,status='interrupted',reason='restart' WHERE status='running'", (now,))

    def activity(self, uid):
        now = time.time()
        day = datetime.fromtimestamp(now, TZ).date().isoformat()
        self.seen[uid] = now
        previous = self.written.get(uid)
        if previous and previous[0] == day and now - previous[1] < 60: return
        with self.connect() as c:
            c.execute('''INSERT INTO usage_daily VALUES(?,?,?,?)
                ON CONFLICT(day,user_id) DO UPDATE SET last_seen=excluded.last_seen''', (day, uid, now, now))
        self.written[uid] = (day, now)

    def start(self, room):
        humans = sum(not p.get('bot') for p in room['players'])
        bots = len(room['players']) - humans
        models = sum(bool(p.get('model')) for p in room['players'] if p.get('bot'))
        variant = 'alternate' if room['options'].get('_alternate') else 'dlc' if room['options'].get('dlc') else 'default'
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO usage_matches VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (room['matchId'], room['mode'], variant, 'single' if humans == 1 else 'multi',
                       humans, bots, models, time.time(), None, 'running', None))

    def finish(self, room, status, reason):
        if not room.get('matchId'): return
        with self.connect() as c:
            c.execute("UPDATE usage_matches SET ended=?,status=?,reason=? WHERE id=? AND status='running'",
                      (time.time(), status, reason, room['matchId']))

    def ai(self, model, failed, seconds, usage=None):
        day = datetime.fromtimestamp(time.time(), TZ).date().isoformat()
        usage = usage or {}
        hits = usage.get('prompt_cache_hit_tokens', 0)
        misses = usage.get('prompt_cache_miss_tokens', 0)
        with self.connect() as c:
            c.execute('''INSERT INTO usage_ai(day,model,requests,failures,seconds,cache_hits,cache_misses)
                VALUES(?,?,1,?,?,?,?) ON CONFLICT(day,model) DO UPDATE SET
                requests=requests+1,failures=failures+excluded.failures,seconds=seconds+excluded.seconds,
                cache_hits=cache_hits+excluded.cache_hits,cache_misses=cache_misses+excluded.cache_misses''',
                      (day, model, int(failed), seconds, hits, misses))

    def report(self, rooms):
        now = time.time()
        today = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        days = [(today - timedelta(days=i)).date().isoformat() for i in range(29, -1, -1)]
        online = {uid for uid, seen in self.seen.items() if now - seen < 60}
        active = Counter()
        running = 0
        playing = set()
        for room in rooms:
            if not room.get('game') or room['game'].phase == 'over': continue
            running += 1
            present = {p['id'] for p in room['players'] if not p.get('bot')} & online
            if not present: continue
            playing.update(present)
            humans = sum(not p.get('bot') for p in room['players'])
            variant = 'alternate' if room['options'].get('_alternate') else 'dlc' if room['options'].get('dlc') else 'default'
            active[(room['mode'], variant, 'single' if humans == 1 else 'multi')] += 1
        with self.connect() as c:
            since = c.execute("SELECT value FROM usage_meta WHERE key='since'").fetchone()[0]
            users = c.execute('SELECT COUNT(*),COALESCE(SUM(created>=?),0) FROM users', (today.timestamp(),)).fetchone()
            dau = c.execute('SELECT COUNT(*) FROM usage_daily WHERE day=?', (days[-1],)).fetchone()[0]
            wau = c.execute('SELECT COUNT(DISTINCT user_id) FROM usage_daily WHERE day>=? AND day<=?', (days[-7], days[-1])).fetchone()[0]
            mau = c.execute('SELECT COUNT(DISTINCT user_id) FROM usage_daily WHERE day>=? AND day<=?', (days[0], days[-1])).fetchone()[0]
            totals = dict(c.execute('''SELECT COUNT(*) AS started,
                COALESCE(SUM(status='completed'),0) AS completed,
                COALESCE(SUM(status='interrupted'),0) AS interrupted,
                COALESCE(SUM(status='completed' AND reason='resign'),0) AS resigned,
                COALESCE(SUM(started>=?),0) AS today_started,
                COALESCE(SUM(humans),0) AS player_visits,
                AVG(CASE WHEN status='completed' THEN ended-started END) AS average_seconds
                FROM usage_matches''', (today.timestamp(),)).fetchone())
            rows = [dict(r) for r in c.execute('''SELECT mode,variant,channel,COUNT(*) AS started,
                SUM(status='completed') AS completed,SUM(status='interrupted') AS interrupted,
                SUM(started>=?) AS today_started,SUM(humans) AS player_visits,
                AVG(CASE WHEN status='completed' THEN ended-started END) AS average_seconds
                FROM usage_matches GROUP BY mode,variant,channel''', (today.timestamp(),))]
            daily_users = dict(c.execute('SELECT day,COUNT(*) FROM usage_daily WHERE day>=? GROUP BY day', (days[0],)))
            daily_matches = {r['day']:dict(r) for r in c.execute('''SELECT date(started,'unixepoch','+8 hours') AS day,
                COUNT(*) AS started,SUM(channel='single') AS single,SUM(channel='multi') AS multi
                FROM usage_matches WHERE started>=? GROUP BY day''', ((today-timedelta(days=29)).timestamp(),))}
            daily_signups = dict(c.execute("SELECT date(created,'unixepoch','+8 hours'),COUNT(*) FROM users WHERE created>=? GROUP BY 1", ((today-timedelta(days=29)).timestamp(),)))
            historical = c.execute('SELECT COUNT(*) FROM results WHERE id NOT IN (SELECT id FROM usage_matches)').fetchone()[0]
            ai = dict(c.execute('''SELECT COALESCE(SUM(requests),0) AS requests,
                COALESCE(SUM(failures),0) AS failures,COALESCE(SUM(seconds),0) AS seconds,
                COALESCE(SUM(cache_hits),0) AS cache_hits,COALESCE(SUM(cache_misses),0) AS cache_misses
                FROM usage_ai WHERE day=?''', (days[-1],)).fetchone())
        keys = {(r['mode'],r['variant'],r['channel']) for r in rows}
        for mode in ('landlord','basic','standard','trio'):
            for channel in ('single','multi'):
                key = (mode,'default',channel)
                if key not in keys:
                    rows.append(dict(mode=mode,variant='default',channel=channel,started=0,completed=0,interrupted=0,today_started=0,player_visits=0,average_seconds=None))
        for r in rows: r['active'] = active[(r['mode'],r['variant'],r['channel'])]
        return dict(now=now,since=since,timezone='Asia/Shanghai',online=len(online),playing=len(playing),
                    active_games=sum(active.values()),running_games=running,rooms=len(rooms),users=users[0],new_users=users[1],
                    dau=dau,wau=wau,mau=mau,totals=totals,historical_completed=historical,ai=ai,
                    modes=sorted(rows,key=lambda r:(r['mode'],r['variant'],r['channel'])),
                    days=[dict(day=day,dau=daily_users.get(day,0),signups=daily_signups.get(day,0),
                               started=daily_matches.get(day,{}).get('started',0),single=daily_matches.get(day,{}).get('single',0),
                               multi=daily_matches.get(day,{}).get('multi',0)) for day in days])
