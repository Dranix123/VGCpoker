"""Server-authoritative card rules. Ranks: 3..14(A), 15(2), 16/17(jokers), 18(urgent)."""
import random
import itertools
from collections import Counter

RANKS = list(range(3, 16))
LABELS = {**{n: str(n) for n in range(3, 11)}, 11: 'J', 12: 'Q', 13: 'K', 14: 'A', 15: '2', 16: '小王', 17: '大王', 18: '急'}
MODES = {'landlord': 3, 'standard': 4, 'trio': 3, 'basic': 4}

def deck(mode, dlc=False):
    copies = 1 if mode in ('landlord', 'basic') else 2
    cards = []
    def add(rank, suit):
        cards.append({'id': str(len(cards)), 'rank': rank, 'suit': suit})
    for _ in range(copies):
        for s in 'SHCD':
            for r in RANKS:
                if mode == 'trio' and s == 'S' and r <= 13:
                    continue
                add(r, s)
        if mode != 'trio': add(16, 'J')
        add(17, 'J')
    if mode not in ('landlord', 'basic'):
        for _ in range(1 if mode == 'trio' else 2): add(18, 'U')
    if mode == 'trio': add(17, 'J')
    if dlc and mode == 'standard':
        for _ in range(5): add(14, 'S')
        for _ in range(2):
            for r in RANKS: add(r, 'T')
        add(16, 'J'); add(17, 'J')
        for _ in range(7): add(18, 'U')
    random.SystemRandom().shuffle(cards)
    return cards

def strength(rank, main=3, mode='standard'):
    if mode != 'landlord' and rank == main: return 15.5
    return rank

def classify(ranks, mode='landlord', main=3):
    n = len(ranks)
    if not n or 18 in ranks: return None
    counts = Counter(ranks)
    keys = sorted(counts)
    vals = sorted(counts.values())
    minimum = 3 if mode == 'basic' else 4
    def result(kind, value, power=0):
        return {'kind': kind, 'n': n, 'value': value, 'power': power, 'ranks': ranks}
    if mode != 'landlord' and set(keys) <= {4, 14}:
        a, four = counts[14], counts[4]
        if a >= (1 if mode == 'basic' else 2) and four >= (2 if mode == 'basic' else 3) and four > a:
            return result('4A4', a, 100 + n)
    if all(r >= 16 for r in keys):
        if mode == 'landlord' and n == 2 and keys == [16, 17]: return result('王炸', 0, 2)
        if mode != 'landlord' and n >= 2:
            return result('王炸', 0, {2: 4.5, 3: 6.5, 4: 8.5}.get(n, n + .5))
    if len(keys) == 1:
        value = strength(keys[0], main, mode)
        if n >= minimum: return result('炸弹', value, n if mode != 'landlord' else 1)
        return result({1: '单张', 2: '对子', 3: '三张'}.get(n, '无效'), value)
    if n == 4 and vals == [1, 3]: return result('三带一', strength(next(r for r in keys if counts[r] == 3), main, mode))
    if n == 5 and vals == [2, 3]: return result('三带二', strength(next(r for r in keys if counts[r] == 3), main, mode))
    sequence = keys[-1] < 15 and not (mode != 'landlord' and main in keys) and keys == list(range(keys[0], keys[-1] + 1))
    if sequence and len(set(vals)) == 1:
        v = vals[0]
        if (v == 1 and n >= 5) or (v == 2 and n >= 6) or (v == 3 and n >= 6):
            return result({1: '顺子', 2: '连对', 3: '飞机'}[v], keys[-1])
    for width in range(2, 7):
        if n not in (width * 4, width * 5): continue
        for start in range(3, 15 - width + 1):
            seq = list(range(start, start + width))
            if mode != 'landlord' and main in seq: continue
            if not all(counts[r] >= 3 for r in seq): continue
            rem = counts.copy()
            for r in seq: rem[r] -= 3
            rem = +rem
            if any(r in rem for r in seq): continue
            if n == width * 4 and sum(rem.values()) == width:
                return result('飞机带单', seq[-1])
            if n == width * 5 and len(rem) == width and all(v == 2 for v in rem.values()):
                return result('飞机带对', seq[-1])
    for r in keys:
        if counts[r] != 4: continue
        rem = [v for k, v in counts.items() if k != r]
        if n == 6: return result('四带二', strength(r, main, mode))
        if n == 8 and rem == [2, 2]: return result('四带两对', strength(r, main, mode))
    return None

def interpretations(cards, mode, main, wildcard=None):
    ranks = [c['rank'] for c in cards]
    wild = [i for i, c in enumerate(cards) if c['suit'] == 'S' and c['rank'] == 14]
    if wildcard is not None:
        if mode in ('landlord', 'basic') or len(cards) < 2 or not wild: return []
        if isinstance(wildcard, dict):
            allowed_ids = {cards[i]['id'] for i in wild}
            if not set(wildcard) <= allowed_ids or any(r not in RANKS for r in wildcard.values()): return []
            for i in wild: ranks[i] = wildcard.get(cards[i]['id'], 14)
        else:
            if wildcard not in RANKS: return []
            for i in wild: ranks[i] = wildcard
        combo = classify(ranks, mode, main)
        return [combo] if combo else []
    result = []
    natural = classify(ranks, mode, main)
    if natural: result.append(natural)
    if mode in ('landlord', 'basic') or len(cards) < 2 or not wild: return result
    fixed = Counter(ranks[i] for i in range(len(ranks)) if i not in wild)
    # Match target rank multisets to natural cards, then fill only missing ranks.
    targets = []
    n = len(cards)
    for r in RANKS:
        targets.append(Counter({r: n}))
        for wing in RANKS + [16, 17]:
            if wing == r: continue
            if n in (4, 5): targets.append(Counter({r: 3, wing: n - 3}))
    for a in range(2, n):
        if n - a > a and n - a >= 3: targets.append(Counter({4: n - a, 14: a}))
    for multiple in (1, 2, 3):
        if n % multiple: continue
        width = n // multiple
        for start in range(3, 15 - width + 1):
            targets.append(Counter({r: multiple for r in range(start, start + width)}))
    # Airplane and four-with-wings: preserve existing wing ranks and fill missing
    # wing cards deterministically, including wildcards needed for pairs.
    bodies = []
    for width in range(2, 7):
        if n in (width * 4, width * 5):
            for start in range(3, 15 - width + 1):
                bodies.append((Counter({r: 3 for r in range(start, start + width)}), width, n == width * 5))
    if n in (6, 8):
        bodies.extend((Counter({r: 4}), 2, n == 8) for r in RANKS)
    for body, wings, paired in bodies:
        if any(fixed[r] > body[r] for r in body): continue
        wing_fixed = Counter({r: v for r, v in fixed.items() if r not in body})
        if paired:
            if len(wing_fixed) > wings or any(v > 2 for v in wing_fixed.values()): continue
            extras = [r for r in RANKS if r not in body and r not in wing_fixed]
            target = body + Counter({r: 2 for r in wing_fixed}) + Counter({r: 2 for r in extras[:wings - len(wing_fixed)]})
        else:
            if sum(wing_fixed.values()) > wings: continue
            wing_rank = next(r for r in RANKS if r not in body)
            target = body + wing_fixed + Counter({wing_rank: wings - sum(wing_fixed.values())})
        targets.append(target)
    for target in targets:
        if any(target[r] < v for r, v in fixed.items()): continue
        missing = list((target - fixed).elements())
        if len(missing) != len(wild) or any(r >= 16 for r in missing): continue
        rr = ranks[:]
        for i, r in zip(wild, missing): rr[i] = r
        combo = classify(rr, mode, main)
        if combo and combo not in result: result.append(combo)
    return result

class RuleError(ValueError): pass

class Game:
    def __init__(self, mode, players, options=None, previous=None, interactive=False):
        self.mode, self.players, self.options = mode, players, options or {}
        self.main = (previous or {}).get('main', 3)
        self.next_main = self.main
        self.scores = (previous or {}).get('scores', [0, 0, 0] if mode == 'trio' else [0, 0])[:]
        self.first = (previous or {}).get('first')
        self.hands = [[] for _ in players]
        self.cards = deck(mode, self.options.get('dlc', False))
        self.bottom = self.cards[-3:] if mode == 'landlord' else []
        dealing = self.cards[:-3] if self.bottom else self.cards
        offset = self.first or 0
        for i, c in enumerate(dealing): self.hands[(i + offset) % len(players)].append(c)
        self.turn = offset
        self.last, self.last_seat = None, None
        self.seat_plays = [None for _ in players]
        self.play_number = 0
        self.passes, self.finished, self.log = set(), [], []
        self.hui_used = False
        self.landlord, self.bid, self.bids = None, 0, []
        self.promotions, self.reveals, self.rps = {}, [], {}
        self.urgent_last = []
        self.phase = 'bid' if mode == 'landlord' else 'setup'
        self.winner = None
        self.history = None
        self.negotiation = None
        self.interactive = interactive
        self.priority = None
        self.claims = {}
        self.display_seen = set()
        self.announce('牌已发出。' + ('请叫分。' if mode == 'landlord' else '可亮黑桃3，确认后开始。' if mode == 'basic' else '可升变、亮黑桃3，确认后开始。'))

    def announce(self, text):
        self.log.append(text)
        self.log = self.log[-45:]

    def next_seat(self, seat):
        for i in range(1, len(self.players) + 1):
            nxt = (seat - i) % len(self.players)
            if nxt not in self.finished: return nxt
        return seat

    def inherit_lead(self, seat):
        partner = (seat + 2) % len(self.players)
        if self.mode in ('basic', 'standard') and partner not in self.finished: return partner
        return self.next_seat(seat)

    def display_action(self, seat, play):
        if seat in self.display_seen:
            self.display_seen.clear()
            for finished in self.finished: self.seat_plays[finished] = None
        self.display_seen.add(seat)
        self.seat_plays[seat] = play

    def priority_moves(self, seat):
        return [m for m in self.candidates(seat) if m['action'] in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4')]

    def solo(self):
        return sum(not p.get('bot') for p in self.players) <= 1

    def priority_paused(self):
        return bool(self.priority and self.solo() and any(seat != self.turn for seat in self.priority['pending']))

    def snapshot(self):
        import copy
        return {k: copy.deepcopy(getattr(self, k)) for k in ('hands', 'turn', 'last', 'last_seat', 'seat_plays', 'play_number', 'display_seen', 'priority', 'passes', 'finished', 'hui_used', 'phase', 'winner', 'scores', 'main', 'log', 'urgent_last')}

    def open_priority(self):
        self.priority = None
        if not self.interactive or self.mode == 'landlord' or self.phase != 'play' or not self.last: return
        seats = [(self.last_seat - i) % len(self.players) for i in range(1, len(self.players))]
        eligible = [s for s in seats if s not in self.finished and self.priority_moves(s)]
        if eligible:
            self.priority = {'pending': [s for s in eligible if not self.players[s].get('bot')], 'bots': [s for s in eligible if self.players[s].get('bot')]}
            if not self.solo():
                for seat in self.priority['pending']: self.claims[seat] = {'snapshot': self.snapshot(), 'actors': [], 'moves': self.priority_moves(seat), 'order': self.play_number}

    def select(self, seat, ids):
        if not isinstance(ids, list) or len(set(ids)) != len(ids): raise RuleError('请选择不重复的牌。')
        by_id = {c['id']: c for c in self.hands[seat]}
        if any(i not in by_id for i in ids): raise RuleError('这些牌不在你的手中。')
        return [by_id[i] for i in ids]

    def infer_action(self, seat, cards, wildcard=None, priority_only=False):
        specials = ('dead4', 'dead', 'cross', 'hook', 'dot', 'press')
        for action in specials + (() if priority_only else ('play', 'hui')):
            try:
                self.validate_play(seat, cards, action, wildcard)
                return action
            except RuleError: pass
        raise RuleError('所选牌无法在当前局面出牌。')

    def action(self, seat, action, ids=None, **args):
        if self.phase == 'over': raise RuleError('本局已结束。')
        if seat in self.finished: raise RuleError('你已完成出牌。')
        if self.negotiation and action not in ('accept', 'reject'): raise RuleError('请先处理截牌协商。')
        if action == 'auto':
            if self.phase != 'play': raise RuleError('请先完成开局。')
            cards = self.select(seat, ids or [])
            wildcard = args.get('wildcard')
            def urgent(card):
                assigned = wildcard.get(card['id'], 14) if isinstance(wildcard, dict) else wildcard
                return card['rank'] == 18 or card['rank'] == 14 and card['suit'] == 'S' and assigned == 18
            if any(urgent(c) for c in cards): action = 'urgent'
            else:
                claim = self.claims.get(seat)
                if claim and claim['actors'] and any(set(m['ids']) == set(ids or []) for m in claim['moves']):
                    self.action(seat, 'negotiate', ids, wildcard=wildcard)
                    return
                try: special = self.infer_action(seat, cards, wildcard)
                except RuleError:
                    if seat not in self.claims: raise
                    self.action(seat, 'negotiate', ids, wildcard=wildcard)
                    return
                if self.priority and special in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4') and seat in self.priority['pending'] + self.priority['bots']:
                    action = 'priority-play'; args['special'] = special
                else:
                    if self.priority and self.solo() and seat in self.priority['pending']: self.priority = None
                    action = special
        if action == 'pass' and (seat in self.claims or self.priority and seat in self.priority['pending']):
            last = self.last
            self.claims.pop(seat, None)
            if self.priority and seat in self.priority['pending']: self.action(seat, 'priority-decline')
            if seat != self.turn or self.last_seat == seat: return
            window = self.priority; self.priority = None
            self.action(seat, 'pass')
            if self.last is last: self.priority = window
            return
        if self.priority_paused() and action not in ('priority-play', 'priority-decline', 'accept', 'reject'): raise RuleError('请先决定是否优先管牌。')
        if action == 'bid':
            if self.phase != 'bid' or self.turn != seat: raise RuleError('还没轮到你叫分。')
            value = int(args.get('value', 0))
            if value not in range(4) or (value and value <= self.bid): raise RuleError('叫分必须高于当前分数。')
            self.bids.append((seat, value))
            if value: self.bid, self.landlord = value, seat
            self.announce('%s：%s' % (self.players[seat]['name'], '不叫' if not value else str(value) + '分'))
            if value == 3 or len(self.bids) == len(self.players):
                if self.landlord is None: self.landlord, self.bid = self.turn, 1
                self.hands[self.landlord].extend(self.bottom)
                self.turn, self.phase = self.landlord, 'play'
                self.announce(self.players[self.landlord]['name'] + '成为地主。')
            else: self.turn = self.next_seat(seat)
            return
        if action in ('promote', 'reveal', 'confirm', 'rps'):
            if self.phase not in ('setup', 'rps'): raise RuleError('开局阶段已结束。')
            if action == 'promote':
                if self.phase != 'setup' or self.mode == 'basic': raise RuleError('当前不能升变。')
                rank = int(args.get('rank', 0))
                if rank not in RANKS or sum(c['rank'] == rank for c in self.hands[seat]) < 6: raise RuleError('升变需要至少六张原生同数值牌。')
                self.promotions[seat] = rank
                self.announce(self.players[seat]['name'] + '展示六张' + LABELS[rank] + '，申请升变。')
            elif action == 'reveal':
                if self.first is not None or self.phase != 'setup' or not any(c['rank'] == 3 and c['suit'] == 'S' for c in self.hands[seat]): raise RuleError('没有黑桃3可亮出。')
                if seat not in self.reveals: self.reveals.append(seat); self.announce(self.players[seat]['name'] + '亮出黑桃3。')
            elif action == 'confirm':
                self.rps[seat] = 'ready'
                if all(self.rps.get(s) == 'ready' for s in range(len(self.players))):
                    if self.promotions: self.main = max(self.promotions.values())
                    self.rps = {}
                    if self.first is None and len(self.reveals) > 1: self.phase = 'rps'; self.announce('亮牌玩家请猜拳。')
                    else:
                        self.turn = self.first if self.first is not None else (self.reveals[0] if self.reveals else random.randrange(len(self.players)))
                        self.phase = 'play'
            elif action == 'rps':
                value = args.get('value')
                if self.phase != 'rps' or seat not in self.reveals or value not in ('rock', 'paper', 'scissors'): raise RuleError('当前不能猜拳。')
                if seat in self.rps: raise RuleError('已出拳，等待其他玩家。')
                self.rps[seat] = value
                if all(s in self.rps for s in self.reveals):
                    choices = set(self.rps.values())
                    if len(choices) != 2: self.rps = {}; self.announce('猜拳平局，请重出。')
                    else:
                        winning = next(c for c in choices if {'rock': 'scissors', 'paper': 'rock', 'scissors': 'paper'}[c] in choices)
                        self.reveals = [s for s in self.reveals if self.rps[s] == winning]
                        self.rps = {}
                        if len(self.reveals) == 1: self.turn = self.reveals[0]; self.phase = 'play'
            return
        if self.phase != 'play': raise RuleError('请先完成开局。')
        if action in ('priority-play', 'priority-decline'):
            window = self.priority
            group = 'bots' if self.players[seat].get('bot') else 'pending'
            if not window or seat not in window[group] or group == 'bots' and self.priority_paused(): raise RuleError('没有轮到你响应的优先管牌机会。')
            if action == 'priority-decline':
                self.claims.pop(seat, None)
                window[group].remove(seat)
                if not window['pending'] and not window['bots']: self.priority = None
                return
            special = args.get('special')
            if special not in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4'): raise RuleError('请选择优先出法。')
            self.validate_play(seat, self.select(seat, ids or []), special, args.get('wildcard'))
            self.priority = None
            self.action(seat, special, ids, wildcard=args.get('wildcard'))
            return
        if action in ('accept', 'reject'):
            n = self.negotiation
            if not n or seat != n['target']: raise RuleError('没有需要你处理的协商。')
            self.negotiation = None
            if action == 'accept':
                self.claims = {}
                if n['snapshot']:
                    for key, value in n['snapshot'].items(): setattr(self, key, value)
                self.priority = None
                self.announce(self.players[seat]['name'] + '同意优先管牌。')
                self.action(n['seat'], n['action'], n['ids'], **n['args'])
            else:
                self.announce(self.players[seat]['name'] + '拒绝截牌协商。')
                self.claims.pop(n['seat'], None)
            return
        if action == 'negotiate':
            claim = self.claims.get(seat)
            h = {'seat': claim['actors'][-1], 'snapshot': claim['snapshot']} if claim and claim['actors'] else self.history
            if claim and not claim['actors']:
                special = self.infer_action(seat, self.select(seat, ids or []), args.get('wildcard'), priority_only=True)
                self.action(seat, 'priority-play', ids, special=special, wildcard=args.get('wildcard'))
                return
            if len(self.finished) >= 2 or not h or h['seat'] == seat or not claim and (not h['snapshot']['finished'] or h['snapshot']['last_seat'] not in h['snapshot']['finished']):
                raise RuleError('这次优先管牌机会已结束，或当前不能协商。')
            import copy
            before = copy.deepcopy(self)
            for key, value in h['snapshot'].items(): setattr(before, key, copy.deepcopy(value))
            special = args.get('special') or before.infer_action(seat, self.select(seat, ids or []), args.get('wildcard'), priority_only=True)
            if special not in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4'): raise RuleError('请选择可截牌的特殊出法。')
            before.validate_play(seat, self.select(seat, ids or []), special, args.get('wildcard'))
            self.negotiation = {'target': h['seat'], 'seat': seat, 'action': special, 'ids': ids, 'args': args, 'snapshot': copy.deepcopy(h['snapshot'])}
            self.announce(self.players[seat]['name'] + '请求收回上一手并截牌。')
            return
        if action == 'pass':
            if seat != self.turn or not self.last or self.last_seat == seat: raise RuleError('当前不能不出。')
            self.passes.add(seat)
            self.display_action(seat, {'kind': '不出', 'cards': [], 'ranks': [], 'order': self.play_number, 'passed': True})
            self.announce(self.players[seat]['name'] + '：不出。')
            active = set(range(len(self.players))) - set(self.finished) - {self.last_seat}
            if active <= self.passes:
                self.turn = self.last_seat if self.last_seat not in self.finished else self.inherit_lead(self.last_seat)
                self.last = None; self.passes = set(); self.hui_used = False; self.history = None
                self.display_seen.clear(); self.claims = {}
                for finished in self.finished: self.seat_plays[finished] = None
            else: self.turn = self.next_seat(seat)
            return
        cards = self.select(seat, ids or [])
        if action == 'urgent':
            if self.mode in ('landlord', 'basic') or seat != self.turn: raise RuleError('仅轮到你时可使用急牌。')
            target = int(args.get('target', -1))
            wildcard = args.get('wildcard')
            wild_ids = {c['id'] for c in cards if c['rank'] == 14 and c['suit'] == 'S'}
            if isinstance(wildcard, dict):
                if not set(wildcard) <= wild_ids or any(r not in RANKS + [18] for r in wildcard.values()): raise RuleError('混子指定无效。')
            elif wildcard is not None and wildcard not in RANKS + [18]: raise RuleError('黑桃A不能代替王。')
            def is_urgent(card):
                assigned = wildcard.get(card['id'], 14) if isinstance(wildcard, dict) else wildcard
                return card['rank'] == 18 or card['id'] in wild_ids and assigned == 18
            if len(cards) != 2 or sum(is_urgent(c) for c in cards) != 1 or target == seat or target not in range(len(self.players)) or target in self.finished:
                raise RuleError('选择一张急牌、一张非急牌和一位仍在场的玩家。')
            self.history = None; self.claims = {}
            self.remove(seat, cards)
            given = next(c for c in cards if not is_urgent(c))
            substituted = any(c['id'] in wild_ids and is_urgent(c) for c in cards)
            self.hands[target].append(given)
            given_label = {'S': '黑桃', 'H': '红桃', 'C': '梅花', 'D': '方块', 'T': 'Delta'}.get(given['suit'], '') + LABELS[given['rank']]
            self.announce(self.players[seat]['name'] + ('使用黑桃A代急牌向' if substituted else '使用急牌向') + self.players[target]['name'] + '赠送【' + given_label + '】；不占出牌次数。')
            self.report(target); self.finish(seat)
            if seat in self.finished and self.phase != 'over': self.turn = self.next_seat(seat)
            # Urgent consumes cards, not the current lead or response opportunity.
            return
        combo, direct = self.validate_play(seat, cards, action, args.get('wildcard'))
        self.history = {'seat': seat, 'snapshot': self.snapshot()}
        for claimant, claim in list(self.claims.items()):
            if seat not in claim['actors']: claim['actors'].append(seat)
            if claimant == seat or len(claim['actors']) >= 2: del self.claims[claimant]
        if self.last and self.last.get('direct') and self.last_seat == seat and action == 'play': self.hui_used = False
        if action in ('cross', 'hook'): self.claims = {}
        self.remove(seat, cards)
        self.last = {**combo, 'cards': cards, 'special': action, 'direct': direct}
        self.play_number += 1
        self.display_action(seat, {**self.last, 'order': self.play_number})
        self.last_seat = seat; self.passes = set()
        if action == 'hui': self.hui_used = True
        substitutions = [LABELS[c['rank']] + '→' + LABELS[r] for c, r in zip(cards, combo['ranks']) if c['rank'] != r]
        self.announce(self.players[seat]['name'] + '：' + combo['kind'] + ' ' + ' '.join(LABELS[c['rank']] for c in cards) + ('（混子 ' + '、'.join(substitutions) + '）' if substitutions else ''))
        self.finish(seat)
        if self.phase != 'over':
            self.turn = seat if direct and seat not in self.finished else self.next_seat(seat)
            if direct:
                self.passes = set()
                if seat in self.finished and action != 'dead':
                    self.turn = self.inherit_lead(seat)
                    self.last = None; self.hui_used = False
                    self.display_seen.clear()
                    for finished in self.finished: self.seat_plays[finished] = None
        self.open_priority()

    def validate_play(self, seat, cards, action='play', wildcard=None):
        if not cards or any(c['rank'] == 18 for c in cards): raise RuleError('急牌请通过赠牌使用。')
        if action not in ('play', 'cross', 'hook', 'dot', 'press', 'dead', 'dead4', 'hui'): raise RuleError('未知出牌方式。')
        old = self.last
        special = action != 'play'
        if old and old.get('direct') and seat == self.turn and not special:
            old = None
        if old and old.get('special') == 'cross' and action != 'hook': raise RuleError('叉牌只能用同点单牌勾。')
        if old and old.get('special') == 'hook': raise RuleError('勾牌不能再管，由勾牌者继续出牌。')
        if seat != self.turn:
            advanced_intercept = old and (action == 'dead4' and old.get('special') == 'dead' or action == 'dead' and old.get('special') == 'dot' or action == 'press' and old.get('special') == 'dot' and old.get('direct'))
            priority_intercept = old and action in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4')
            if not advanced_intercept and not priority_intercept: raise RuleError('还没轮到你出牌。')
        if old and self.last_seat == seat: raise RuleError('请等待其他玩家回应。')
        combos = interpretations(cards, self.mode, self.main, wildcard)
        if not combos: raise RuleError('混子指定或牌型无效；单张黑桃A不能代替其他点数。')
        if special:
            if self.mode == 'landlord' or not old: raise RuleError('当前不能使用此特殊出法。')
            if self.mode == 'basic' and action not in ('cross', 'hook'): raise RuleError('基础版仅支持叉、勾。')
            rank = old['ranks'][0]
            # Spade A may stand in for a rank in multi-card responses, never when played alone.
            matched = next((c for c in combos if len(set(c['ranks'])) == 1 and c['ranks'][0] == rank), None)
            chain = old.get('special')
            direct = False
            ok = False
            if action == 'cross': ok = old['n'] == 1 and chain in ('play', 'hui') and len(cards) == 2 and matched
            elif action == 'hook':
                ok = old['n'] == 2 and chain == 'cross' and len(cards) == 1 and matched
                direct = True
            elif action == 'dot':
                ok = old.get('baseKind', old['kind']) == '对子' and chain not in ('cross', 'hook') and len(cards) == 1 and matched
                direct = rank in (15, self.main)
            elif action == 'press':
                ok = chain == 'dot' and len(cards) == 1 and cards[0]['rank'] in (15, self.main, 16, 17)
                direct = True
            elif action == 'dead':
                ok = (old.get('baseKind', old['kind']) == '对子' or chain == 'dot') and chain not in ('cross', 'hook') and len(cards) == 3 and matched
                direct = True
            elif action == 'dead4':
                ok = self.options.get('advancedDead', False) and chain == 'dead' and len(cards) == 4 and matched
                direct = True
            elif action == 'hui':
                suit_ok = len({c['suit'] for c in cards + old['cards']}) == 1
                eligible = chain not in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4') and not self.hui_used
                matched = next((c for c in combos if c['kind'] == old.get('baseKind', old['kind']) and c['n'] == old['n']), None)
                ok = eligible and suit_ok and matched and (self.options.get('advancedHui', False) or old['n'] == 1 and old['ranks'][0] < 15 and old['ranks'][0] != self.main)
            if not ok: raise RuleError('所选牌不满足' + {'cross': '叉', 'hook': '勾', 'dot': '点', 'press': '压', 'dead': '死压', 'dead4': '进阶死压', 'hui': '回'}[action] + '的条件。')
            c = matched or combos[0]
            return {**c, 'baseKind': c['kind'], 'kind': {'cross': '叉', 'hook': '勾', 'dot': '点', 'press': '压', 'dead': '死压', 'dead4': '进阶死压', 'hui': '回'}[action]}, direct
        for combo in sorted(combos, key=lambda c: (c['power'], c['value'])):
            if not old: return combo, False
            if combo['power']:
                if not old['power'] or (combo['power'], combo['value']) > (old['power'], old['value']): return combo, False
            elif not old['power'] and old.get('special') in ('play', 'hui') and combo['kind'] == old.get('baseKind', old['kind']) and combo['n'] == old['n'] and combo['value'] > old['value']:
                return combo, False
        raise RuleError('牌型不合法，或无法管住上一手。')

    def remove(self, seat, cards):
        ids = {c['id'] for c in cards}
        self.hands[seat] = [c for c in self.hands[seat] if c['id'] not in ids]
        self.report(seat)

    def report(self, seat):
        n = len(self.hands[seat])
        if self.mode != 'landlord' and n <= 10: self.announce('爆牌 · %s剩余%d张。' % (self.players[seat]['name'], n))

    def finish(self, seat):
        if not self.hands[seat] and seat not in self.finished:
            self.finished.append(seat)
            self.announce(self.players[seat]['name'] + '完成出牌，第%d名。' % len(self.finished))
        # A lone urgent card is an automatic last place and removed from active play.
        urgent_last = [s for s, hand in enumerate(self.hands) if s not in self.finished and len(hand) == 1 and hand[0]['rank'] == 18]
        self.urgent_last = getattr(self, 'urgent_last', [])
        for s in urgent_last:
            self.urgent_last.append(s); self.finished.append(s)
            self.announce(self.players[s]['name'] + '仅剩急牌，判为末名。')
        if self.mode == 'landlord' and not self.hands[seat]:
            self.winner = [self.landlord] if seat == self.landlord else [s for s in range(len(self.players)) if s != self.landlord]
            self.phase = 'over'
        elif self.mode != 'landlord':
            active = [s for s in range(len(self.players)) if s not in self.finished]
            order = [s for s in self.finished if s not in self.urgent_last]
            if len(active) <= 1:
                order += active + self.urgent_last
                self.finished = order
                if self.mode == 'trio':
                    self.winner = order[:1]
                    self.scores[order[0]] += 1
                    self.next_main = RANKS[self.scores[order[0]] % len(RANKS)]
                else:
                    # Each team scores the number still on table when its second member finishes.
                    for team in (0, 1):
                        pos = max(order.index(s) for s in range(len(self.players)) if s % 2 == team)
                        self.scores[team] += len(self.players) - pos - 1
                    winning_team = min((0, 1), key=lambda t: max(order.index(s) for s in range(len(self.players)) if s % 2 == t))
                    self.winner = [s for s in range(len(self.players)) if s % 2 == winning_team]
                    score = self.scores[order[0] % 2]
                    self.next_main = RANKS[score % len(RANKS)]
                self.phase = 'over'
        if self.phase == 'over': self.announce('本局结束。')

    def candidates(self, seat):
        hand = self.hands[seat]
        groups = {}
        for c in hand:
            if c['rank'] != 18: groups.setdefault(c['rank'], []).append(c)
        sets = [[c] for c in hand if c['rank'] != 18]
        for group in groups.values():
            for n in range(2, len(group) + 1): sets.append(group[:n])
        for r, group in groups.items():
            if len(group) >= 3:
                for other, wing in groups.items():
                    if other != r:
                        sets.append(group[:3] + wing[:1])
                        if len(wing) >= 2: sets.append(group[:3] + wing[:2])
        for multiple, minimum in ((1, 5), (2, 3), (3, 2)):
            for start in range(3, 15):
                seq = []
                for end in range(start, 15):
                    if len(groups.get(end, [])) < multiple or self.mode != 'landlord' and end == self.main: break
                    seq += groups[end][:multiple]
                    if end - start + 1 >= minimum:
                        sets.append(seq[:])
                        if multiple == 3:
                            others = [g for r, g in groups.items() if r < start or r > end]
                            width = end - start + 1
                            singles = [c for g in others for c in g]
                            pairs = [g[:2] for g in others if len(g) >= 2]
                            if len(singles) >= width: sets.append(seq + singles[:width])
                            if len(pairs) >= width: sets.append(seq + [c for g in pairs[:width] for c in g])
        # Four-with-wings and same-suit alternatives matter for hints and advanced hui.
        for r, group in groups.items():
            if len(group) < 4: continue
            others = [g for rank, g in groups.items() if rank != r]
            singles = [c for g in others for c in g]
            pairs = [g[:2] for g in others if len(g) >= 2]
            if len(singles) >= 2: sets.append(group[:4] + singles[:2])
            if len(pairs) >= 2: sets.append(group[:4] + [c for g in pairs[:2] for c in g])
        suit_groups = {}
        for c in hand:
            if c['rank'] < 16: suit_groups.setdefault(c['suit'], {}).setdefault(c['rank'], []).append(c)
        for pool in suit_groups.values():
            for group in pool.values():
                for n in range(2, len(group) + 1): sets.append(group[:n])
            for multiple, minimum in ((1, 5), (2, 3), (3, 2)):
                for start in range(3, 15):
                    seq = []
                    for end in range(start, 15):
                        if len(pool.get(end, [])) < multiple or self.mode != 'landlord' and end == self.main: break
                        seq += pool[end][:multiple]
                        if end - start + 1 >= minimum: sets.append(seq[:])
        kings = [c for c in hand if c['rank'] in (16, 17)]
        for n in range(2, len(kings) + 1): sets.append(kings[:n])
        for a in range(1 if self.mode == 'basic' else 2, len(groups.get(14, [])) + 1):
            for four in range(max(a + 1, 2 if self.mode == 'basic' else 3), len(groups.get(4, [])) + 1):
                sets.append(groups[14][:a] + groups[4][:four])
        # Wildcard set candidates, including natural-card plus spade A bombs.
        wild = [c for c in hand if c['rank'] == 14 and c['suit'] == 'S']
        if self.mode not in ('landlord', 'basic') and wild:
            for r, group in groups.items():
                base = [c for c in group if c not in wild]
                for n in range(1, len(base) + 1):
                    for w in range(1, len(wild) + 1): sets.append(base[:n] + wild[:w])
        if self.mode not in ('landlord', 'basic') and wild:
            natural = {r: [c for c in group if c not in wild] for r, group in groups.items()}
            for multiple, minimum in ((1, 5), (2, 3), (3, 2)):
                for start in range(3, 15):
                    seq, needed = [], 0
                    for end in range(start, 15):
                        if end == self.main: break
                        available = natural.get(end, [])[:multiple]
                        seq += available
                        needed += multiple - len(available)
                        if needed > len(wild): break
                        if needed and end - start + 1 >= minimum: sets.append(seq + wild[:needed])
        output, seen = [], set()
        for cards in sets:
            key = tuple(sorted(c['id'] for c in cards))
            if key in seen: continue
            seen.add(key)
            for action in ('play', 'cross', 'hook', 'dot', 'press', 'dead', 'dead4', 'hui'):
                try:
                    combo, direct = self.validate_play(seat, cards, action)
                    output.append({'action': action, 'ids': [c['id'] for c in cards], 'label': combo['kind'], 'power': combo['power'], 'value': combo['value'], 'n': len(cards)})
                except RuleError: pass
        if seat == self.turn and self.mode not in ('landlord', 'basic'):
            urgent = next((c for c in hand if c['rank'] == 18), None)
            normal = next((c for c in hand if c['rank'] != 18), None)
            targets = [s for s in range(len(self.players)) if s != seat and s not in self.finished]
            if urgent and normal and targets: output.append({'action': 'urgent', 'ids': [urgent['id'], normal['id']], 'target': targets[0], 'label': '急牌', 'power': -1, 'value': 0, 'n': 2})
            if wild and targets:
                given = next((c for c in hand if c['rank'] != 18 and c['id'] != wild[0]['id']), None)
                if given: output.append({'action': 'urgent', 'ids': [wild[0]['id'], given['id']], 'target': targets[0], 'wildcard': {wild[0]['id']: 18}, 'label': '黑桃A代急牌', 'power': 1, 'value': 0, 'n': 2})
        return sorted(output, key=lambda x: (x['power'], -x['n'], x['value']))

    def bot_action(self, seat):
        if self.negotiation:
            return {'action': 'accept'} if self.negotiation['target'] == seat else None
        if self.priority:
            if self.priority_paused(): return None
            if seat not in self.priority['bots']:
                if self.solo(): return None
            else:
                moves = self.priority_moves(seat)
                if not moves: return {'action': 'priority-decline'}
                move = min(moves, key=lambda m: (len(self.hands[seat]) != m['n'], m['power'], -m['n'], m['value']))
                return {'action': 'priority-play', 'special': move['action'], 'ids': move['ids'], **({'wildcard': move['wildcard']} if 'wildcard' in move else {})}
        if self.phase == 'bid':
            if seat != self.turn: return None
            value = 3 if sum(c['rank'] >= 15 for c in self.hands[seat]) >= 5 else (self.bid + 1 if self.bid < 2 else 0)
            return {'action': 'bid', 'value': value}
        if self.phase == 'setup':
            if seat in self.rps: return None
            if self.mode != 'basic' and seat not in self.promotions:
                counts = Counter(c['rank'] for c in self.hands[seat])
                declared = max(self.promotions.values(), default=None)
                current = declared if declared is not None else self.main
                ranks = [r for r, n in counts.items() if n >= 6 and r in RANKS and r != current and (declared is None or r > declared)]
                def promotion_gain(rank):
                    return sum(n * (strength(r, rank, self.mode) - strength(r, current, self.mode)) for r, n in counts.items())
                if ranks:
                    rank = max(ranks, key=promotion_gain)
                    if promotion_gain(rank) > 4: return {'action': 'promote', 'rank': rank}
            if self.first is None and seat not in self.reveals and any(c['rank'] == 3 and c['suit'] == 'S' for c in self.hands[seat]): return {'action': 'reveal'}
            return {'action': 'confirm'}
        if self.phase == 'rps':
            return {'action': 'rps', 'value': random.choice(['rock', 'paper', 'scissors'])} if seat in self.reveals and seat not in self.rps else None
        if self.phase != 'play' or seat != self.turn or seat in self.finished: return None
        moves = self.candidates(seat)
        hand = self.hands[seat]
        def allied(other):
            return other != seat and ((self.mode == 'landlord' and seat != self.landlord and other != self.landlord) or self.mode in ('standard', 'basic') and other % 2 == seat % 2)
        opponents = [s for s in range(len(self.players)) if s != seat and s not in self.finished and not allied(s)]
        danger = min((len(self.hands[s]) for s in opponents), default=99)
        responding = self.last is not None and self.last_seat != seat
        urgent = [c for c in hand if c['rank'] == 18]
        # Evaluate every gift using only our cards, public hand counts and team seats.
        if urgent:
            moves = [m for m in moves if m['action'] != 'urgent'] + [
                {'action': 'urgent', 'ids': [urgent[0]['id'], c['id']], 'target': target, 'power': -1, 'value': 0, 'n': 2}
                for c in hand if c['rank'] != 18
                for target in range(len(self.players)) if target != seat and target not in self.finished]
        if not moves: return {'action': 'pass'}
        for move in moves:
            if len(move['ids']) == len(hand): return move
        safe_teammate = responding and allied(self.last_seat) and not self.last.get('direct') and not (danger <= self.last['n'] <= 2 and self.last['value'] < 15)
        minimum_bomb = 3 if self.mode == 'basic' else 4
        counts = Counter(c['rank'] for c in hand)
        costs = {}
        def hand_cost(remaining):
            key = tuple(sorted(Counter(c['rank'] for c in remaining).items()))
            if key in costs: return costs[key]
            best = float('inf')
            # Try both sequence-first and set-first decompositions. Count complete
            # future plays rather than simply maximizing cards shed this turn.
            for order in ((3, 2, 1), (1, 2, 3)):
                pool = Counter(dict(key)); turns = pool.pop(18, 0)
                if self.mode != 'landlord':
                    a = pool[14]; four = pool[4]
                    if a >= (1 if self.mode == 'basic' else 2) and four > a and four >= (2 if self.mode == 'basic' else 3):
                        pool[14] = pool[4] = 0; turns += 1
                for multiple in order:
                    minimum = 5 if multiple == 1 else 3 if multiple == 2 else 2
                    for start in range(3, 15):
                        sequence = []
                        for rank in range(start, 15):
                            if pool[rank] < multiple or pool[rank] >= minimum_bomb or self.mode != 'landlord' and rank == self.main: break
                            sequence.append(rank)
                        if len(sequence) >= minimum:
                            for rank in sequence: pool[rank] -= multiple
                            turns += 1
                            if multiple == 3:
                                wings = [r for r in RANKS if r not in sequence and pool[r] == 1 and strength(r, self.main, self.mode) < 15][:len(sequence)]
                                if len(wings) == len(sequence):
                                    for wing in wings: pool[wing] -= 1
                if pool[16] and pool[17]:
                    pool[16] = pool[17] = 0; turns += 1
                elif self.mode != 'landlord' and pool[16] + pool[17] >= 2:
                    pool[16] = pool[17] = 0; turns += 1
                for rank in RANKS:
                    if pool[rank] == 3 and self.mode != 'basic':
                        wing = next((r for r in RANKS if r != rank and pool[r] in (1, 2) and strength(r, self.main, self.mode) < 15), None)
                        if wing is not None: pool[wing] = 0
                        pool[rank] = 0; turns += 1
                turns += sum(1 for n in pool.values() if n)
                # Low isolated cards are harder to regain control with in the endgame.
                stranded = sum(.18 for r, n in pool.items() if n == 1 and strength(r, self.main, self.mode) < 12)
                best = min(best, turns + stranded)
            costs[key] = best
            return best
        def score(move):
            ids = set(move['ids']); chosen = [c for c in hand if c['id'] in ids]
            remaining = [c for c in hand if c['id'] not in ids]
            value = hand_cost(remaining) * 8
            used = Counter(c['rank'] for c in chosen)
            for rank, number in used.items():
                if 0 < number < counts[rank]:
                    value += 12 if counts[rank] >= minimum_bomb else 3 if counts[rank] >= 2 else 0
            controls = sum(strength(c['rank'], self.main, self.mode) >= 15 for c in chosen)
            value += controls * (1 if danger <= 2 else 4)
            value += sum(c['rank'] == 14 and c['suit'] == 'S' for c in chosen) * 3
            if move['action'] == 'urgent':
                gift = next(c for c in chosen if c['rank'] != 18 and move.get('wildcard', {}).get(c['id']) != 18)
                if not urgent: value += 8
                target = move['target']
                value += 4 if allied(target) else -2
                if allied(target) and strength(gift['rank'], self.main, self.mode) >= 15: value -= 5
                if allied(target) and len(self.hands[target]) <= 2: value += 8
                if not allied(target) and strength(gift['rank'], self.main, self.mode) >= 15: value += 10
                if len(remaining) == 1 and remaining[0]['rank'] == 18: value += 40
            else:
                value += (12 if danger > 2 else 3) if move['power'] else 0
                value += move['value'] * (.12 if not responding or danger > 2 else -.35)
                if responding and danger == 1 and move['n'] == 1 and controls: value -= 4
                if not responding and danger == 1 and move['n'] > 1: value -= 6
                if safe_teammate: value += 20
            return value, move.get('power', 0), move.get('value', 0)
        best = min(moves, key=score)
        if responding and not self.last.get('direct'):
            passing = hand_cost(hand) * 8 + (0 if safe_teammate else 14 if danger <= 2 else 5)
            if score(best)[0] >= passing: return {'action': 'pass'}
        return best

    def view(self, seat):
        response = None
        if self.phase == 'play' and seat not in self.finished:
            if seat in self.claims: response = {'key': self.claims[seat]['order'], 'moves': self.claims[seat]['moves']}
            elif self.priority and seat in self.priority['pending']: response = {'key': self.play_number, 'moves': self.priority_moves(seat)}
        return {'mode': self.mode, 'phase': self.phase, 'main': self.main, 'scores': self.scores, 'turn': self.turn, 'landlord': self.landlord, 'bid': self.bid,
                'bottom': self.bottom if self.phase != 'bid' else [], 'hand': sorted(self.hands[seat], key=lambda c: (strength(c['rank'], self.main, self.mode), c['suit'])),
                'counts': [len(h) for h in self.hands], 'finished': self.finished, 'last': self.last, 'lastSeat': self.last_seat,
                'seatPlays': self.seat_plays, 'playNumber': self.play_number, 'response': response,
                'winner': self.winner, 'log': self.log, 'reveals': self.reveals, 'ready': list(self.rps), 'promotions': self.promotions,
                'negotiation': {k: self.negotiation[k] for k in ('seat', 'target') if k in self.negotiation} if self.negotiation else None,
                'priority': {'pending': self.priority['pending'], 'moves': self.priority_moves(seat) if seat in self.priority['pending'] else [], 'requiresAgreement': sum(not p.get('bot') for p in self.players) > 1 and seat != self.turn and not self.players[self.turn].get('bot')} if self.priority else None,
                'options': self.options, 'openingFirst': self.first, 'nextMain': self.next_main, 'urgentLast': self.urgent_last}
