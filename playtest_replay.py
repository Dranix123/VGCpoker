"""Per-match spectator frames for automated tests."""

import json
import struct
from contextlib import contextmanager

from engine import MODES


OFFSET = struct.Struct('>Q')


def replay_path(directory, match):
    return directory / 'replays' / f'{match}.jsonl'


@contextmanager
def record(path):
    path.parent.mkdir(exist_ok=True)
    with path.open('wb') as data, path.with_suffix('.idx').open('wb') as index:
        def append(step, game, *, seat=None, actor=None, action=None, message=None, legacy=False):
            frame = dict(step=step, game=game, seat=seat, actor=actor, action=action, message=message, legacy=legacy)
            offset = data.tell()
            data.write(json.dumps(frame, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
            data.flush()
            index.write(OFFSET.pack(offset))
            index.flush()
        yield append


def read(path, frame):
    with path.with_suffix('.idx').open('rb') as index:
        frames = index.seek(0, 2) // OFFSET.size
        if not 0 <= frame < frames:
            return None
        index.seek(frame * OFFSET.size)
        offset, = OFFSET.unpack(index.read(OFFSET.size))
    with path.open('rb') as data:
        data.seek(offset)
        return frames, json.loads(data.readline())


def spectator_view(game, core):
    view = game.view(None)
    view.update(publicHands=[], response=None, priority=None, confirmTurn=None)
    owners = getattr(core, 'owners', range(len(game.players)))
    if view['phase'] == 'setup':
        eligible = core.confirmation_seats()
        view['confirmationSeats'] = sorted({owners[s] for s in eligible})
        start = owners[core.first or 0]
        pending = [owners[s] for s in eligible if s not in core.rps]
        view['confirmTurn'] = min(pending, key=lambda seat: (start - seat) % len(game.players), default=None)
    if view['phase'] == 'play' and core.priority and core.priority['pending']:
        actor = core.priority['pending'][0]
        view['priorityClock'] = dict(seat=owners[actor], actor=actor, remaining=None)
    return view


def restore_legacy(directory, path, match, config, result):
    """Index an older log using the state and actions it actually recorded."""
    mode = config['mode']
    capacity = MODES[mode]
    log, revealed, ready, drafted = [], [], [], set()
    plays = None
    promotions = {}
    play_number, landlord, bid = 0, None, 0
    with (directory / 'events.jsonl').open(encoding='utf-8') as source:
        for line in source:
            event = json.loads(line)
            if event.get('match') != match:
                continue
            if event['event'] == 'match_started':
                skills = event['skills']
                owners = [s for s, skill in enumerate(skills) for _ in range(2 if skill == 'twins' else 1)]
                plays = [None] * len(owners)
                initial = [len(hand) for hand in event['state']['hands']]
                log.extend(event.get('announcements', []))
                break
        if plays is None:
            return False

        def view(state):
            counts = [len(hand) for hand in state['hands']]
            finished = {owners[s] for s in state['finished']}
            over = state['phase'] == 'over'
            game = dict(mode=mode, phase=state['phase'], main=state['main'], scores=state['scores'],
                        turn=owners[state['turn']], landlord=landlord, bid=bid, bottom=[], hand=[],
                        counts=[sum(counts[s] for s, owner in enumerate(owners) if owner == p) for p in range(capacity)],
                        finished=list(dict.fromkeys(owners[s] for s in state['finished'])),
                        last=None, seatPlays=plays, playNumber=state['playNumber'], log=log[-45:],
                        winner=result.get('winner', []) if over else [], urgentLast=[],
                        reveals=revealed, ready=ready, promotions=promotions, openingFirst=None,
                        tribute=state['tribute'], roundComplete=result.get('roundComplete', False),
                        nextMain=result.get('nextMain', state['main']))
            if mode != 'conveyor':
                game['remainingHands'] = state['hands'] if over else None
                return game
            waiting = state['pending'][0]['seat'] if state['pending'] else None
            game['conveyor'] = dict(
                actor=None, turnActor=state['turn'], waitingActor=waiting, waiting=None if waiting is None else True,
                choice=None, skill=None, zone=[], boundHands=[], pile=state['pileSize'], discard=state['discardSize'],
                remainingActorHands=state['hands'] if over else None,
                actors=[dict(id=s, owner=owner, name=f'{owner + 1}号' + (
                    f' · {owners[:s+1].count(owner)}' if skills[owner] == 'twins' else ''),
                    count=counts[s], initialCount=initial[s], zoneCount=len(state['zones'][s]),
                    skill=skills[owner], play=plays[s], finished=owner in finished, drafted=owner in drafted,
                    confirmed=owner in ready,
                    resources={k: v for k, v in state['resources'][s].items() if k != 'markCards'})
                    for s, owner in enumerate(owners)])
            return game

        with record(path) as append:
            append(0, view(event['state']), legacy=True)
            for line in source:
                event = json.loads(line)
                if event.get('match') != match:
                    break
                if event['event'] != 'action':
                    continue
                state, move = event['after'], event['move']
                action, actor, seat = move['action'], event['actor'], event['seat']
                if action == 'keep':
                    drafted.add(seat)
                if action == 'reveal' and seat not in revealed:
                    revealed.append(seat)
                if action == 'promote':
                    promotions[seat] = move.get('rank')
                if action in ('rps', 'confirm') and seat not in ready:
                    ready.append(seat)
                if action == 'bid':
                    bid = max(bid, move.get('value', 0))
                    if state['phase'] == 'play':
                        landlord = state['turn']
                if state['playNumber'] != play_number and state['last']:
                    plays[actor] = {**state['last'], 'order': state['playNumber']}
                elif action == 'pass':
                    plays[actor] = dict(kind='不出', cards=[], ranks=[], order=state['playNumber'], passed=True)
                play_number = state['playNumber']
                announcements = event.get('announcements', [])
                log.extend(announcements)
                append(event['step'], view(state), seat=seat, actor=actor, action=action,
                       message=announcements[-1] if announcements else None, legacy=True)
    return True
