"""Server-authoritative card rules. Ranks: 3..14(A), 15(2), 16/17(jokers), 18(urgent)."""
import random
import itertools
import json
from collections import Counter

RANKS = list(range(3, 16))
LABELS = {**{n: str(n) for n in range(3, 11)}, 11: 'J', 12: 'Q', 13: 'K', 14: 'A', 15: '2', 16: '小王', 17: '大王', 18: '急'}
PLAIN_RANK_OFFSET = 20
LABELS.update({n + PLAIN_RANK_OFFSET: LABELS[n] for n in RANKS})

def printed_rank(rank):
    return rank - PLAIN_RANK_OFFSET if rank > PLAIN_RANK_OFFSET else rank
MODES = {'landlord': 3, 'standard': 4, 'trio': 3, 'basic': 4, 'conveyor': 4}
PRIORITY_ACTIONS = ('cross', 'hook', 'dot', 'dead', 'dead4')

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
    return printed_rank(rank)

def airplane_wings(ranks, mode):
    if mode == 'basic' or 18 in ranks: return
    counts = Counter(map(printed_rank, ranks))
    for width in range(2, len(RANKS)):
        for unit, kind in ((1, '飞机带单'), (2, '飞机带对')):
            if len(ranks) != width * (3 + unit): continue
            for start in range(3, 16 - width):
                body = range(start, start + width)
                if not all(counts[r] == 3 for r in body): continue
                wings = [n for r, n in counts.items() if r not in body]
                if unit == 2 and (len(wings) != width or any(n != 2 for n in wings)): continue
                yield dict(kind=kind, n=len(ranks), value=body[-1], power=0, ranks=ranks)

def wide_airplanes(ranks, counts, single_wings):
    numerals = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九', 10: '十'}
    n = len(ranks)
    for size in range(4, max(counts.values()) + 1):
        for width in range(min(12, n // size), 1, -1):
            for start in range(3, 16 - width):
                body = range(start, start + width)
                if any(counts[r] != size for r in body): continue
                wings = [count for r, count in counts.items() if r not in body]
                paired = not single_wings and bool(wings) and all(v == 2 for v in wings)
                units = len(wings) if paired else sum(wings)
                if units and (units % width or not 1 <= units // width <= size - 2): continue
                label = numerals.get(size, str(size)) + '张飞机'
                if units: label += '带' + numerals.get(units, str(units)) + ('对' if paired else '单')
                yield dict(kind=label, n=n, value=body[-1], power=0, ranks=ranks, bodySize=size, bodyWidth=width)

def classify(ranks, mode='landlord', main=3, single_wings=False, pattern=(4, 14)):
    n = len(ranks)
    if not n or 18 in ranks: return None
    counts = Counter(ranks)
    keys = sorted(counts)
    vals = sorted(counts.values())
    minimum = 3 if mode == 'basic' else 4
    def result(kind, value, power=0):
        return {'kind': kind, 'n': n, 'value': value, 'power': power, 'ranks': ranks}
    if mode != 'landlord' and pattern and set(keys) <= set(pattern):
        a, four = counts[pattern[1]], counts[pattern[0]]
        if a >= (1 if mode == 'basic' else 2) and four >= (2 if mode == 'basic' else 3) and four > a:
            return result('4A4', a, 100 + (n if mode == 'basic' else 2 * a + 1))
    if all(r in (16, 17) for r in keys):
        if mode == 'landlord' and n == 2 and keys == [16, 17]: return result('王炸', 0, 2)
        if mode != 'landlord' and n >= 2:
            return result('王炸', 0, {2: 4.5, 3: 6.5, 4: 8.5}.get(n, n + .5))
    if len(keys) == 1:
        value = strength(keys[0], main, mode)
        if n >= minimum: return result('炸弹', value, n if mode != 'landlord' else 1)
        return result({1: '单张', 2: '对子', 3: '三张'}.get(n, '无效'), value)
    if mode == 'landlord' and n == 4 and vals == [1, 3]: return result('三带一', strength(next(r for r in keys if counts[r] == 3), main, mode))
    if mode == 'landlord' and n == 5 and vals == [2, 3]: return result('三带一对', strength(next(r for r in keys if counts[r] == 3), main, mode))
    if mode not in ('landlord', 'basic'):
        numerals = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九', 10: '十'}
        for rank in keys:
            body = counts[rank]
            wings = [counts[r] for r in keys if r != rank]
            if body < 3 or not wings: continue
            paired = not single_wings and all(v == 2 for v in wings)
            count = len(wings) if paired else sum(wings)
            if not 1 <= count <= body - 2: continue
            units = '两' if paired and count == 2 else numerals.get(count, str(count))
            kind = numerals.get(body, str(body)) + '带' + units + ('对' if paired else '')
            return result(kind, strength(rank, main, mode))
    if mode != 'landlord':
        counts = Counter(map(printed_rank, ranks))
        keys, vals = sorted(counts), sorted(counts.values())
    sequence = keys[-1] < 15 and keys == list(range(keys[0], keys[-1] + 1))
    if sequence and len(set(vals)) == 1:
        v = vals[0]
        if (v == 1 and n >= (3 if mode == 'basic' else 5)) or (v == 2 and n >= (4 if mode == 'basic' else 6)) or (v == 3 and n >= 6):
            return result({1: '顺子', 2: '连对', 3: '飞机'}[v], keys[-1])
    wings = next(airplane_wings(ranks, mode), None)
    if wings: return wings
    if mode in ('standard', 'trio'):
        wide = next(wide_airplanes(ranks, counts, single_wings), None)
        if wide: return wide
    for r in keys:
        if mode != 'landlord': break
        if counts[r] != 4: continue
        rem = [v for k, v in counts.items() if k != r]
        if n == 6: return result('四带二', strength(r, main, mode))
        if n == 8 and rem == [2, 2]: return result('四带两对', strength(r, main, mode))
    return None

def classifications(ranks, mode, main, pattern=(4, 14)):
    result = []
    for singles in (False, True) if mode in ('standard', 'trio') else (False,):
        combo = classify(ranks, mode, main, single_wings=singles, pattern=pattern)
        if combo and combo not in result: result.append(combo)
    return result

def wildcard_rank(value):
    return value.get('rank') if isinstance(value, dict) else value

def valid_wildcard(value):
    if isinstance(value, dict) and (set(value) - {'rank', 'suit'} or value.get('suit', 'S') not in ('S', 'H', 'C', 'D', 'T')): return False
    return wildcard_rank(value) in RANKS

def interpretations(cards, mode, main, wildcard=None, pattern=(4, 14), all_aces=False):
    ranks = [c['rank'] for c in cards]
    original = [c.get('printedRank', c['rank']) for c in cards]
    wild = [i for i, c in enumerate(cards) if original[i] == 14 and (all_aces or c['suit'] == 'S')]
    if original and all(rank == 14 for rank in original):
        return classifications(original, mode, main, pattern) if wildcard is None else []
    if wildcard is not None:
        if mode in ('landlord', 'basic') or len(cards) < 2 or not wild: return []
        if isinstance(wildcard, dict):
            allowed_ids = {cards[i]['id'] for i in wild}
            if not set(wildcard) <= allowed_ids or any(not valid_wildcard(r) for r in wildcard.values()): return []
            for i in wild: ranks[i] = wildcard_rank(wildcard.get(cards[i]['id'], 14))
        else:
            if wildcard not in RANKS: return []
            for i in wild: ranks[i] = wildcard
        result = classifications(ranks, mode, main, pattern)
        if isinstance(wildcard, dict):
            for combo in result: combo['suits'] = [wildcard.get(c['id'], {}).get('suit', c['suit']) if isinstance(wildcard.get(c['id']), dict) else c['suit'] for c in cards]
        return result
    result = classifications(ranks, mode, main, pattern)
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
    if pattern:
        for a in range(2, n):
            if n - a > a and n - a >= 3: targets.append(Counter({pattern[0]: n - a, pattern[1]: a}))
    for multiple in (1, 2, 3):
        if n % multiple: continue
        width = n // multiple
        for start in range(3, 15 - width + 1):
            targets.append(Counter({r: multiple for r in range(start, start + width)}))
    # Carried groups and airplanes: preserve existing wing ranks and fill missing
    # wing cards deterministically, including wildcards needed for pairs.
    bodies = []
    for width in range(2, len(RANKS)):
        if n in (width * 4, width * 5):
            for start in range(3, 15 - width + 1):
                bodies.append((Counter({r: 3 for r in range(start, start + width)}), width, n == width * 5, False))
    for size in range(4, n // 2 + 1):
        for width in range(2, min(12, n // size) + 1):
            for unit in (1, 2):
                wings, remainder = divmod(n - size * width, unit)
                if remainder or wings % width or not 0 <= wings // width <= size - 2: continue
                for start in range(3, 15 - width + 1):
                    body = Counter({r: size for r in range(start, start + width)})
                    if sum((body - fixed).values()) <= len(wild): bodies.append((body, wings, unit == 2, False))
    for size in range(3, n):
        for unit in (1, 2):
            wings, remainder = divmod(n - size, unit)
            if not remainder and 1 <= wings <= size - 2:
                bodies.extend((Counter({r: size}), wings, unit == 2, True) for r in RANKS)
    for body, wings, paired, unique in bodies:
        if any(fixed[r] > body[r] for r in body): continue
        wing_fixed = Counter({r: v for r, v in fixed.items() if r not in body})
        if paired:
            if len(wing_fixed) > wings or any(v > 2 for v in wing_fixed.values()): continue
            extras = [r for r in RANKS if r not in body and r not in wing_fixed]
            target = body + Counter({r: 2 for r in wing_fixed}) + Counter({r: 2 for r in extras[:wings - len(wing_fixed)]})
        elif unique:
            if sum(wing_fixed.values()) > wings: continue
            extras = [r for r in RANKS if r not in body and r not in wing_fixed]
            target = body + wing_fixed + Counter(extras[:wings - sum(wing_fixed.values())])
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
        for combo in classifications(rr, mode, main, pattern):
            if combo not in result: result.append(combo)
    return result

class RuleError(ValueError): pass

class Game:
    def __init__(self, mode, players, options=None, previous=None, interactive=False):
        self.mode, self.players, self.options = mode, players, options or {}
        self.pattern = (6, 8) if mode == 'standard' and self.options.get('_alternate') else (4, 14)
        self.main = (previous or {}).get('main', 3)
        self.next_main = self.main
        self.scores = (previous or {}).get('scores', [0, 0, 0] if mode == 'trio' else [0, 0])[:]
        self.first = (previous or {}).get('first')
        self.hands = [[] for _ in players]
        self.cards = deck(mode, self.options.get('dlc', False))
        self.bottom = self.cards[-3:] if mode == 'landlord' else []
        dealing = self.cards[:-3] if self.bottom else self.cards
        offset = self.first or 0
        direction = -1 if mode in ('basic', 'standard') and self.first is not None else 1
        for i, c in enumerate(dealing): self.hands[(offset + direction * i) % len(players)].append(c)
        self.initial_counts = [len(hand) for hand in self.hands]
        self.turn = offset
        self.last, self.last_seat = None, None
        self.seat_plays = [None for _ in players]
        self.play_number = 0
        self.last_voice_play = None
        self.passes, self.finished, self.log = set(), [], []
        self.ai_older_rounds, self.ai_recent_rounds, self.ai_current_round = [], [], []
        self.hui_used = False
        self.landlord, self.bid, self.bids = None, 0, []
        self.promotions, self.reveals, self.rps = {}, [], {}
        self.rps_round = 0
        self.urgent_last = []
        self.reported = set()
        self.report_counts = {}
        self.phase = 'bid' if mode == 'landlord' else 'setup'
        self.winner = None
        self.interactive = interactive
        self.priority = None
        self.priority_declined = {}
        self.round_complete = False
        self.captured = []
        self.tribute = None
        captured = (previous or {}).get('captured', []) if mode in ('basic', 'standard') and self.options.get('tribute') is True and not self.options.get('_alternate') else []
        if captured:
            offers = []
            for donor in captured:
                strongest = max((c for c in self.hands[donor] if c['rank'] != 18), key=lambda c: strength(c['rank'], self.main, mode))
                self.hands[donor].remove(strongest)
                offers.append({'donor': donor, 'card': strongest, 'recipient': None, 'returned': False})
            receivers = [self.first] if len(captured) == 1 else [s for s in range(len(players)) if s % 2 == self.first % 2]
            self.tribute = {'offers': offers, 'receivers': receivers, 'stage': 'choose' if len(offers) == 2 else 'return'}
            if len(offers) == 1:
                offers[0]['recipient'] = self.first
                self.hands[self.first].append(offers[0]['card'])
            self.phase = 'tribute'
        if mode == 'landlord':
            self.announce('牌已发出。请叫分。')
        else:
            opening = '可亮黑桃3' if mode == 'basic' else '可升变、亮黑桃3'
            ending = '，倒计时结束后自动继续。' if self.options.get('_timedOpening') else '，确认后开始。'
            self.announce('牌已发出。' + opening + ending)

    def announce(self, text):
        self.log.append(text)
        self.log = self.log[-45:]
        self.ai_current_round.append(text)

    def can_reveal(self, seat):
        return self.first is None and any(c['rank'] == 3 and c['suit'] == 'S' for c in self.hands[seat])

    def confirmation_seats(self):
        if self.phase != 'setup': return []
        return [s for s, hand in enumerate(self.hands) if self.can_reveal(s) or self.mode != 'basic'
                and any(n >= 6 and rank in RANKS for rank, n in Counter(c['rank'] for c in hand).items())]

    def finish_setup(self, expired=False):
        if self.phase != 'setup': return
        eligible = self.confirmation_seats()
        if not expired and eligible and (self.options.get('_timedOpening') or any(s not in self.rps for s in eligible)): return
        if self.promotions: self.main = max(self.promotions.values())
        self.rps = {}
        if self.first is None and len(self.reveals) > 1:
            self.phase = 'rps'
            self.announce('亮牌玩家请猜拳。')
        else:
            self.turn = self.first if self.first is not None else (self.reveals[0] if self.reveals else self.random_opening_seat())
            self.phase = 'play'

    def random_opening_seat(self):
        return random.randrange(len(self.players))

    def resolve_rps(self, expired=False):
        if self.phase != 'rps' or not expired and any(s not in self.rps for s in self.reveals): return
        if expired:
            # A missing response forfeits this round. If nobody responds,
            # select a starter so an unattended table still progresses.
            self.reveals = [s for s in self.reveals if s in self.rps] or [random.choice(self.reveals)]
        choices = {self.rps[s] for s in self.reveals if s in self.rps}
        if len(choices) == 2:
            beats = {'rock': 'scissors', 'paper': 'rock', 'scissors': 'paper'}
            winning = next(c for c in choices if beats[c] in choices)
            self.reveals = [s for s in self.reveals if self.rps[s] == winning]
        self.rps = {}
        self.rps_round += 1
        if len(self.reveals) == 1:
            self.turn = self.reveals[0]; self.phase = 'play'
            self.announce('猜拳获胜：' + self.players[self.turn]['name'] + '，先出牌。')
        elif len(choices) != 2:
            self.announce('猜拳平局，请重出。')
        else:
            self.announce('猜拳胜者：' + '、'.join(self.players[s]['name'] for s in self.reveals) + '，继续猜拳。')

    def expire_opening(self):
        if self.phase == 'setup':
            self.finish_setup(expired=True)
        elif self.phase == 'rps':
            self.resolve_rps(expired=True)

    def next_seat(self, seat):
        for i in range(1, len(self.players) + 1):
            nxt = (seat - i) % len(self.players)
            if nxt not in self.finished: return nxt
        return seat

    def inherit_lead(self, seat):
        partner = (seat + 2) % len(self.players)
        if self.mode in ('basic', 'standard') and partner not in self.finished: return partner
        return self.next_seat(seat)

    def announce_free_lead(self, seat):
        if self.play_number and self.ai_current_round:
            self.ai_recent_rounds.append(self.ai_current_round)
            if len(self.ai_recent_rounds) > 3:
                self.ai_older_rounds.append(json.dumps(self.ai_recent_rounds.pop(0), ensure_ascii=False))
            self.ai_current_round = []
        self.announce(self.players[seat]['name'] + '获得自由牌权。')

    def display_action(self, seat, play):
        self.seat_plays[seat] = play
        if self.phase == 'play':
            self.ai_current_round.append({
                'actor': seat, 'kind': play['kind'],
                'cards': [dict(card) for card in play['cards']],
                'ranks': play['ranks'][:], 'suits': list(play.get('suits', ())),
            })

    def priority_moves(self, seat):
        if self.priority_declined.get(seat) == self.play_number: return []
        return [m for m in self.candidates(seat) if m['action'] in PRIORITY_ACTIONS]

    def solo(self):
        return sum(not p.get('bot') for p in self.players) <= 1

    def priority_paused(self):
        return bool(self.priority and self.solo() and any(seat != self.turn and not self.players[seat].get('autoplay') for seat in self.priority['pending']))

    def forced_pass(self):
        if self.phase != 'play' or self.mode == 'landlord' or self.priority_paused(): return False
        if not self.last or self.last.get('special') in (None, 'play') or self.turn == self.last_seat: return False
        return not self.candidates(self.turn)

    def open_priority(self):
        self.priority = None
        if not self.interactive or self.mode == 'landlord' or self.phase != 'play' or not self.last: return
        seats = [(self.last_seat - i) % len(self.players) for i in range(1, len(self.players))]
        eligible = [s for s in seats if s not in self.finished and self.priority_moves(s)]
        if eligible:
            self.priority = {'pending': [s for s in eligible if not self.players[s].get('bot')], 'bots': [s for s in eligible if self.players[s].get('bot')]}

    def select(self, seat, ids):
        if not isinstance(ids, list) or len(set(ids)) != len(ids): raise RuleError('请选择不重复的牌。')
        by_id = {c['id']: c for c in self.hands[seat]}
        if any(i not in by_id for i in ids): raise RuleError('这些牌不在你的手中。')
        return [by_id[i] for i in ids]

    def infer_play(self, seat, cards, wildcard=None):
        specials = ('dead4', 'dead', 'cross', 'hook', 'dot', 'press')
        for action in specials + ('play', 'hui'):
            try:
                combo, _ = self.validate_play(seat, cards, action, wildcard)
                return action, combo
            except RuleError: pass
        raise RuleError('所选牌无法在当前局面出牌。')

    def infer_action(self, seat, cards, wildcard=None):
        return self.infer_play(seat, cards, wildcard)[0]

    def preview_play(self, seat, ids, wildcard=None):
        cards = self.select(seat, ids)
        return self.infer_play(seat, cards, wildcard)[1]['kind']

    def action(self, seat, action, ids=None, **args):
        if self.phase == 'over': raise RuleError('本局已结束。')
        if seat in self.finished: raise RuleError('你已完成出牌。')
        if self.phase == 'tribute':
            tribute = self.tribute
            if action == 'tribute-pick':
                if tribute['stage'] != 'choose' or seat not in tribute['receivers'] or any(o['recipient'] == seat for o in tribute['offers']): raise RuleError('当前不能选择贡牌。')
                offer = next((o for o in tribute['offers'] if o['donor'] == args.get('target') and o['recipient'] is None), None)
                if not offer: raise RuleError('这张贡牌已被选走。')
                offer['recipient'] = seat; self.hands[seat].append(offer['card'])
                self.announce(self.players[seat]['name'] + '收取' + self.players[offer['donor']]['name'] + '的贡牌。')
                if all(o['recipient'] is not None for o in tribute['offers']): tribute['stage'] = 'return'
            elif action == 'tribute-return':
                offer = next((o for o in tribute['offers'] if o['recipient'] == seat and not o['returned']), None)
                if tribute['stage'] != 'return' or not offer: raise RuleError('当前不能还牌。')
                chosen = self.select(seat, ids or [])
                if len(chosen) != 1: raise RuleError('请选择一张牌返还。')
                self.hands[seat].remove(chosen[0]); self.hands[offer['donor']].append(chosen[0]); offer['returned'] = True
                self.announce(self.players[seat]['name'] + '向' + self.players[offer['donor']]['name'] + '还牌。')
                if all(o['returned'] for o in tribute['offers']):
                    self.tribute = None; self.phase = 'setup'; self.announce('进贡完成。')
            else: raise RuleError('请先完成进贡和还牌。')
            return
        if action == 'auto':
            if self.phase != 'play': raise RuleError('请先完成开局。')
            cards = self.select(seat, ids or [])
            wildcard = args.get('wildcard')
            if any(c['rank'] == 18 for c in cards): action = 'urgent'
            else:
                special = self.infer_action(seat, cards, wildcard)
                if self.priority and special in PRIORITY_ACTIONS and seat in self.priority['pending'] + self.priority['bots']:
                    action = 'priority-play'; args['special'] = special
                else:
                    if self.priority and self.solo() and seat in self.priority['pending']: self.priority = None
                    action = special
        if action == 'pass' and self.priority and seat in self.priority['pending']:
            last = self.last
            self.action(seat, 'priority-decline')
            if seat != self.turn or self.last_seat == seat: return
            window = self.priority; self.priority = None
            self.action(seat, 'pass')
            if self.last is last: self.priority = window
            return
        if self.priority_paused() and action not in ('priority-play', 'priority-decline'): raise RuleError('请先决定是否优先管牌。')
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
                self.initial_counts[self.landlord] = len(self.hands[self.landlord])
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
                if self.phase != 'setup' or not self.can_reveal(seat): raise RuleError('没有黑桃3可亮出。')
                if seat in self.reveals and self.options.get('_timedOpening'): raise RuleError('已亮出黑桃3。')
                if seat not in self.reveals: self.reveals.append(seat); self.announce(self.players[seat]['name'] + '亮出黑桃3。')
            elif action == 'confirm':
                if self.phase != 'setup' or seat not in self.confirmation_seats(): raise RuleError('你无需确认开局。')
                self.rps[seat] = 'ready'
                self.finish_setup()
            elif action == 'rps':
                value = args.get('value')
                if self.phase != 'rps' or seat not in self.reveals or value not in ('rock', 'paper', 'scissors'): raise RuleError('当前不能猜拳。')
                if seat in self.rps: raise RuleError('已出拳，等待其他玩家。')
                self.rps[seat] = value
                self.resolve_rps()
            return
        if self.phase != 'play': raise RuleError('请先完成开局。')
        if action in ('priority-play', 'priority-decline'):
            window = self.priority
            group = 'bots' if self.players[seat].get('bot') else 'pending'
            if not window or seat not in window[group] or group == 'bots' and self.priority_paused(): raise RuleError('没有轮到你响应的优先管牌机会。')
            if action == 'priority-decline':
                self.priority_declined[seat] = self.play_number
                window[group].remove(seat)
                if not window['pending'] and not window['bots']: self.priority = None
                return
            special = args.get('special')
            if special not in PRIORITY_ACTIONS: raise RuleError('请选择优先出法。')
            self.validate_play(seat, self.select(seat, ids or []), special, args.get('wildcard'))
            self.priority = None
            self.action(seat, special, ids, wildcard=args.get('wildcard'))
            return
        if action == 'pass':
            if seat != self.turn or not self.last or self.last_seat == seat: raise RuleError('当前不能不出。')
            self.passes.add(seat)
            self.display_action(seat, {'kind': '不出', 'cards': [], 'ranks': [], 'order': self.play_number, 'passed': True})
            self.announce(self.players[seat]['name'] + '：不出。')
            active = set(range(len(self.players))) - set(self.finished) - {self.last_seat}
            if active <= self.passes:
                self.turn = self.last_seat if self.last_seat not in self.finished else self.inherit_lead(self.last_seat)
                self.last = None; self.passes = set(); self.hui_used = False; self.priority = None
                self.announce_free_lead(self.turn)
            else: self.turn = self.next_seat(seat)
            return
        cards = self.select(seat, ids or [])
        if action == 'urgent':
            if self.mode in ('landlord', 'basic') or seat != self.turn: raise RuleError('仅轮到你时可使用急牌。')
            target = int(args.get('target', -1))
            if args.get('wildcard') is not None: raise RuleError('急牌赠牌按原牌点数处理。')
            if len(cards) != 2 or sum(c['rank'] == 18 for c in cards) != 1 or target == seat or target not in range(len(self.players)) or target in self.finished:
                raise RuleError('选择一张急牌、一张非急牌和一位仍在场的玩家。')
            self.remove(seat, cards)
            given = next(c for c in cards if c['rank'] != 18)
            self.hands[target].append(given)
            given_label = {'S': '黑桃', 'H': '红桃', 'C': '梅花', 'D': '方块', 'T': 'Delta'}.get(given['suit'], '') + LABELS[given['rank']]
            self.announce(self.players[seat]['name'] + '使用急牌向' + self.players[target]['name'] + '赠送【' + given_label + '】；不占出牌次数。')
            self.report(target); self.finish(seat)
            if seat in self.finished and self.phase != 'over': self.turn = self.next_seat(seat)
            # Urgent consumes cards, not the current lead or response opportunity.
            return
        combo, direct = self.validate_play(seat, cards, action, args.get('wildcard'))
        if self.last and self.last.get('direct') and self.last_seat == seat and action == 'play': self.hui_used = False
        self.remove(seat, cards)
        self.last = {**combo, 'cards': cards, 'special': action, 'direct': direct}
        self.play_number += 1
        self.last_voice_play = {'kind': combo['kind'], 'ranks': combo['ranks'], 'seat': seat}
        self.display_action(seat, {**self.last, 'order': self.play_number})
        self.last_seat = seat; self.passes = set()
        if action == 'hui': self.hui_used = True
        substitutions = [LABELS[c['rank']] + '→' + LABELS[r] + {'S':'♠','H':'♥','C':'♣','D':'♦','T':'Δ'}.get(s, '') for c, r, s in zip(cards, combo['ranks'], combo.get('suits', [c['suit'] for c in cards])) if c['rank'] != r or c['suit'] != s]
        self.announce(self.players[seat]['name'] + '：' + combo['kind'] + ' ' + ' '.join(LABELS[c['rank']] for c in cards) + ('（混子 ' + '、'.join(substitutions) + '）' if substitutions else ''))
        self.finish(seat)
        if self.phase != 'over':
            self.turn = seat if direct and seat not in self.finished else self.next_seat(seat)
            if direct:
                self.passes = set()
                if seat in self.finished and action not in ('dead', 'hook'):
                    self.turn = self.inherit_lead(seat)
                    self.last = None; self.hui_used = False
                elif seat in self.finished and action in ('dead', 'hook'): self.turn = self.inherit_lead(seat)
                self.announce_free_lead(self.turn)
        self.open_priority()

    def body_groups(self, combo):
        kind = combo.get('baseKind', combo['kind'])
        mapped = list(map(printed_rank, combo['ranks']))
        if combo.get('bodyWidth'):
            ranks = range(combo['value'] - combo['bodyWidth'] + 1, combo['value'] + 1)
        elif kind in ('飞机带单', '飞机带对'):
            width = combo['n'] // (4 if kind == '飞机带单' else 5)
            ranks = range(combo['value'] - width + 1, combo['value'] + 1)
        elif '带' in kind:
            mapped = combo['ranks']
            value = combo['value']
            plain = value + PLAIN_RANK_OFFSET
            ranks = [self.main if value == 15.5 else plain if value == self.main and plain in mapped else value]
        elif kind in ('顺子', '连对', '飞机'):
            ranks = sorted(set(mapped))
        else:
            mapped = combo['ranks']
            ranks = sorted(set(mapped))
        return [[i for i, rank in enumerate(mapped) if rank == r] for r in ranks]

    def hui_profile(self, combo, cards):
        groups = self.body_groups(combo)
        if any(printed_rank(combo['ranks'][i]) >= 15 or combo['ranks'][i] == self.main for group in groups for i in group): return None
        suits = combo.get('suits', [c['suit'] for c in cards])
        return tuple(sorted(Counter(suits[i] for group in groups for i in group).items()))

    def validate_play(self, seat, cards, action='play', wildcard=None, *, all_aces=False):
        if not cards or any(c['rank'] == 18 for c in cards): raise RuleError('急牌请通过赠牌使用。')
        if action not in ('play', 'cross', 'hook', 'dot', 'press', 'dead', 'dead4', 'hui'): raise RuleError('未知出牌方式。')
        if action in PRIORITY_ACTIONS and self.priority_declined.get(seat) == self.play_number:
            if seat != self.turn or action not in ('cross', 'hook', 'dot'): raise RuleError('已放弃这次优先管牌。')
        if self.priority and any(not self.players[s].get('autoplay') for s in self.priority['pending']) and (self.players[seat].get('bot') or self.players[seat].get('autoplay')) and action in PRIORITY_ACTIONS: raise RuleError('等待真人优先决定管牌。')
        old = self.last
        special = action != 'play'
        if old and old.get('special') == 'dot' and old.get('direct') and (seat != self.last_seat or special):
            raise RuleError('2 或主牌死点后直接获得牌权，不能再管。')
        if old and old.get('direct') and seat == self.turn and not special:
            old = None
        if old and old.get('special') == 'cross' and action != 'hook': raise RuleError('叉牌只能用同点单牌勾。')
        if old and old.get('special') == 'hook' and action != 'cross': raise RuleError('勾牌只能用同点对子叉。')
        if old and old.get('special') in ('dot', 'press', 'dead', 'dead4') and not special:
            raise RuleError('只能用对应的特殊出法接牌。')
        if seat != self.turn:
            if not old or action not in PRIORITY_ACTIONS:
                raise RuleError('还没轮到你出牌。')
        if old and self.last_seat == seat: raise RuleError('请等待其他玩家回应。')
        combos = interpretations(cards, self.mode, self.main, wildcard, self.pattern, all_aces)
        if not combos: raise RuleError('混子指定或牌型无效；单张黑桃A不能代替其他点数。')
        old_kind = old.get('baseKind', old['kind']) if old else ''
        if old_kind in ('飞机带单', '飞机带对') or '张飞机' in old_kind:
            for combo in combos[:]:
                ranks = combo['ranks']
                counts = Counter(map(printed_rank, ranks))
                options = airplane_wings(ranks, self.mode) if old_kind.startswith('飞机') else (
                    option for singles in (False, True) for option in wide_airplanes(ranks, counts, singles))
                for wings in options:
                    if wings['kind'] != old_kind: continue
                    if 'suits' in combo: wings['suits'] = combo['suits']
                    if wings not in combos: combos.append(wings)
        if special:
            if self.mode == 'landlord' or not old: raise RuleError('当前不能使用此特殊出法。')
            if self.mode == 'basic' and action not in ('cross', 'hook'): raise RuleError('基础版仅支持叉、勾。')
            rank = old['ranks'][0]
            # Spade A may stand in for a rank in multi-card responses, never when played alone.
            matched = next((c for c in combos if len(set(c['ranks'])) == 1 and c['ranks'][0] == rank), None)
            chain = old.get('special')
            direct = False
            ok = False
            if action == 'cross': ok = old['n'] == 1 and chain in ('play', 'hui', 'hook') and len(cards) == 2 and matched
            elif action == 'hook':
                ok = old['n'] == 2 and chain == 'cross' and len(cards) == 1 and matched
                direct = True
            elif action == 'dot':
                ok = old.get('baseKind', old['kind']) == '对子' and chain in ('play', 'hui') and len(cards) == 1 and matched
                direct = rank in (15, self.main)
            elif action == 'press':
                ok = chain == 'dot' and len(cards) == 1 and cards[0]['rank'] in (15, self.main, 16, 17)
                direct = True
            elif action == 'dead':
                ok = old.get('baseKind', old['kind']) == '对子' and chain in ('play', 'hui') and len(cards) == 3 and matched
                direct = True
            elif action == 'dead4':
                ok = self.options.get('advancedDead', False) and chain == 'dead' and len(cards) == 4 and matched
                direct = True
            elif action == 'hui':
                profile = self.hui_profile(old, old['cards'])
                eligible = chain not in ('cross', 'hook', 'dot', 'press', 'dead', 'dead4') and not self.hui_used and profile is not None
                matched = next((c for c in combos if c['kind'] == old.get('baseKind', old['kind']) and c['n'] == old['n'] and self.hui_profile(c, cards) == profile), None)
                ok = eligible and matched and (self.options.get('advancedHui', False) or old['n'] == 1)
            if not ok: raise RuleError('所选牌不满足' + {'cross': '叉', 'hook': '勾', 'dot': '点', 'press': '压', 'dead': '死压', 'dead4': '进阶死压', 'hui': '回'}[action] + '的条件。')
            c = matched or combos[0]
            kind = {'cross': '叉', 'hook': '勾', 'dot': '死点' if direct else '点',
                    'press': '压', 'dead': '死压', 'dead4': '进阶死压', 'hui': '回'}[action]
            return {**c, 'baseKind': c['kind'], 'kind': kind}, direct
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
        if self.mode != 'landlord' and n <= 10 and seat not in self.reported:
            self.reported.add(seat)
            self.report_counts[seat] = n

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
            if len(active) <= 1 or self.mode in ('basic', 'standard') and len(active) == 2 and active[0] % 2 == active[1] % 2:
                order += active + self.urgent_last
                self.finished = order
                if self.mode == 'trio':
                    self.winner = order[:1]
                    self.scores[order[0]] += 1
                    self.next_main = RANKS[self.scores[order[0]] % len(RANKS)]
                else:
                    # The first finisher's team wins; its partner determines how many are caught.
                    winning_team = order[0] % 2
                    partner = (order[0] + 2) % len(self.players)
                    caught = len(self.players) - order.index(partner) - 1
                    self.captured = order[order.index(partner) + 1:]
                    self.scores[winning_team] = min(11, self.scores[winning_team] + caught)
                    self.winner = [s for s in range(len(self.players)) if s % 2 == winning_team]
                    score = self.scores[winning_team]
                    self.round_complete = self.main == 14
                    self.next_main = 3 if self.round_complete else RANKS[score]
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
            if self.mode != 'basic' and len(group) >= 3:
                for other, wing in groups.items():
                    if other != r:
                        sets.append(group[:3] + wing[:1])
                        if len(wing) >= 2: sets.append(group[:3] + wing[:2])
        for multiple, minimum in ((1, 3 if self.mode == 'basic' else 5), (2, 2 if self.mode == 'basic' else 3), (3, 2)):
            for start in range(3, 15):
                seq = []
                for end in range(start, 15):
                    if len(groups.get(end, [])) < multiple: break
                    seq += groups[end][:multiple]
                    if end - start + 1 >= minimum:
                        sets.append(seq[:])
                        if multiple == 3 and self.mode != 'basic':
                            others = [g for r, g in groups.items() if r < start or r > end]
                            width = end - start + 1
                            singles = [c for g in others for c in g]
                            pairs = [g[:2] for g in others if len(g) >= 2]
                            if len(singles) >= width: sets.append(seq + singles[:width])
                            if len(pairs) >= width: sets.append(seq + [c for g in pairs[:width] for c in g])
        if self.mode in ('standard', 'trio'):
            for size in range(4, max((len(g) for g in groups.values()), default=0) + 1):
                for start in range(3, 14):
                    seq = []
                    for end in range(start, 15):
                        if len(groups.get(end, [])) < size: break
                        seq += groups[end][:size]
                        width = end - start + 1
                        if width < 2: continue
                        sets.append(seq[:])
                        others = [g for r, g in groups.items() if r < start or r > end]
                        for units in ([[c] for g in others for c in g], [g[:2] for g in others if len(g) >= 2]):
                            for count in range(1, size - 1):
                                needed = width * count
                                if len(units) >= needed: sets.append(seq + [c for g in units[:needed] for c in g])
        # Carried units are uniformly singles or pairs in the custom rules.
        for r, group in groups.items():
            if self.mode == 'basic' or len(group) < 4: continue
            others = [g for rank, g in groups.items() if rank != r]
            singles = [c for g in others for c in g]
            pairs = [g[:2] for g in others if len(g) >= 2]
            if self.mode == 'landlord':
                if len(singles) >= 2: sets.append(group[:4] + singles[:2])
                if len(pairs) >= 2: sets.append(group[:4] + [c for g in pairs[:2] for c in g])
            else:
                for size in range(4, len(group) + 1):
                    for units in ([[g[0]] for g in others], [[c] for g in others for c in g], pairs):
                        for count in range(1, min(size - 2, len(units)) + 1):
                            sets.append(group[:size] + [c for g in units[:count] for c in g])
        suit_groups = {}
        for c in hand:
            if c['rank'] < 16: suit_groups.setdefault(c['suit'], {}).setdefault(c['rank'], []).append(c)
        for pool in suit_groups.values():
            for group in pool.values():
                for n in range(2, len(group) + 1): sets.append(group[:n])
            for multiple, minimum in ((1, 3 if self.mode == 'basic' else 5), (2, 2 if self.mode == 'basic' else 3), (3, 2)):
                for start in range(3, 15):
                    seq = []
                    for end in range(start, 15):
                        if len(pool.get(end, [])) < multiple: break
                        seq += pool[end][:multiple]
                        if end - start + 1 >= minimum: sets.append(seq[:])
        kings = [c for c in hand if c['rank'] in (16, 17)]
        for n in range(2, len(kings) + 1): sets.append(kings[:n])
        for a in range(1 if self.mode == 'basic' else 2, len(groups.get(self.pattern[1], [])) + 1):
            for four in range(max(a + 1, 2 if self.mode == 'basic' else 3), len(groups.get(self.pattern[0], [])) + 1):
                sets.append(groups[self.pattern[1]][:a] + groups[self.pattern[0]][:four])
        # Wildcard set candidates, including natural-card plus spade A bombs.
        wild = [c for c in hand if c['rank'] == 14 and c['suit'] == 'S']
        if self.mode not in ('landlord', 'basic') and wild:
            for r, group in groups.items():
                base = [c for c in group if c not in wild]
                for n in range(1, len(base) + 1):
                    for w in range(1, len(wild) + 1): sets.append(base[:n] + wild[:w])
        if self.mode not in ('landlord', 'basic') and wild:
            natural = {r: [c for c in group if c not in wild] for r, group in groups.items()}
            for rank, group in natural.items():
                if rank not in RANKS: continue
                others = [g for r, g in natural.items() if r != rank and g]
                for size in range(3, len(group) + len(wild) + 1):
                    needed = max(1, size - len(group))
                    if needed > len(wild) or size - needed > len(group): continue
                    body = group[:size - needed] + wild[:needed]
                    for units in ([[g[0]] for g in others], [[c] for g in others for c in g], [g[:2] for g in others if len(g) >= 2]):
                        for count in range(1, min(size - 2, len(units)) + 1):
                            sets.append(body + [c for g in units[:count] for c in g])
            multiples = [(1, 5), (2, 3), (3, 2)] + [(size, 2) for size in range(4, max((len(g) for g in natural.values()), default=0) + len(wild) + 1)]
            for multiple, minimum in multiples:
                for start in range(3, 15):
                    seq, needed = [], 0
                    for end in range(start, 15):
                        available = natural.get(end, [])[:multiple]
                        seq += available
                        needed += multiple - len(available)
                        if needed > len(wild): break
                        width = end - start + 1
                        if needed and width >= minimum:
                            body = seq + wild[:needed]
                            sets.append(body)
                            if multiple >= 4:
                                others = [g for r, g in natural.items() if r < start or r > end]
                                for units in ([[c] for g in others for c in g], [g[:2] for g in others if len(g) >= 2]):
                                    for count in range(1, multiple - 1):
                                        total = width * count
                                        if len(units) >= total: sets.append(body + [c for g in units[:total] for c in g])
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
            if self.mode in ('standard', 'trio') and any(c['rank'] == 14 and c['suit'] == 'S' for c in cards):
                for combo in interpretations(cards, self.mode, self.main, pattern=self.pattern):
                    declaration = {c['id']: r for c, r in zip(cards, combo['ranks']) if c['rank'] == 14 and c['suit'] == 'S'}
                    try:
                        matched, direct = self.validate_play(seat, cards, 'play', declaration)
                        output.append({'action': 'play', 'ids': [c['id'] for c in cards], 'wildcard': declaration, 'label': matched['kind'], 'power': matched['power'], 'value': matched['value'], 'n': len(cards)})
                    except RuleError: pass
            if self.last and self.mode in ('standard', 'trio') and any(c['rank'] == 14 and c['suit'] == 'S' for c in cards):
                old_suits = self.last.get('suits', [c['suit'] for c in self.last['cards']])
                expected = Counter(old_suits[i] for group in self.body_groups(self.last) for i in group)
                for combo in interpretations(cards, self.mode, self.main, pattern=self.pattern):
                    declaration = {c['id']: {'rank': r, 'suit': c['suit']} for c, r in zip(cards, combo['ranks']) if c['rank'] == 14 and c['suit'] == 'S'}
                    body = [i for group in self.body_groups(combo) for i in group]
                    natural = Counter(cards[i]['suit'] for i in body if cards[i]['id'] not in declaration)
                    missing = list((expected - natural).elements())
                    wild_body = [i for i in body if cards[i]['id'] in declaration]
                    if natural - expected or len(missing) != len(wild_body): continue
                    for i, suit in zip(wild_body, missing): declaration[cards[i]['id']]['suit'] = suit
                    try:
                        matched, direct = self.validate_play(seat, cards, 'hui', declaration)
                        output.append({'action': 'hui', 'ids': [c['id'] for c in cards], 'wildcard': declaration, 'label': matched['kind'], 'power': matched['power'], 'value': matched['value'], 'n': len(cards)})
                        break
                    except RuleError: pass
        if seat == self.turn and self.mode not in ('landlord', 'basic'):
            urgent = next((c for c in hand if c['rank'] == 18), None)
            normal = next((c for c in hand if c['rank'] != 18), None)
            targets = [s for s in range(len(self.players)) if s != seat and s not in self.finished]
            if urgent and normal and targets: output.append({'action': 'urgent', 'ids': [urgent['id'], normal['id']], 'target': targets[0], 'label': '急牌', 'power': -1, 'value': 0, 'n': 2})
        return sorted(output, key=lambda x: (x['power'], -x['n'], x['value']))

    def play_damage(self, hand, move):
        """Value formations lost by spending these cards in a different shape."""
        used = set(move.get('ids', ()))
        left = [c for c in hand if c['id'] not in used]
        if not left or not used:
            return {}
        old = Counter(c.get('effective', c['rank']) for c in hand)
        new = Counter(c.get('effective', c['rank']) for c in left)
        damage = {}
        label = move.get('label')
        if self.mode != 'landlord' and self.pattern and label != '4A4':
            body, wing = self.pattern
            before = Counter(c['rank'] for c in hand)
            after = Counter(c['rank'] for c in left)
            minimum = 1 if self.mode == 'basic' else 2
            size = min(before[wing], before[body] - 1)
            if size >= minimum and min(after[wing], after[body] - 1) < size:
                damage['拆顶级组合'] = 13
        bomb_size = 3 if self.mode == 'basic' else 4
        if label not in ('炸弹', '4A4') and any(
                count >= bomb_size and new[rank] < count for rank, count in old.items() if 3 <= printed_rank(rank) <= 15):
            damage['拆同点炸弹'] = 10
        has_rocket = (old[16] and old[17]) if self.mode == 'landlord' else old[16] + old[17] >= 2
        rocket_survives = (new[16] and new[17]) if self.mode == 'landlord' else new[16] + new[17] >= 2
        if has_rocket and not rocket_survives and label != '王炸':
            damage['拆王炸'] = 10
        if label not in ('顺子', '连对') and '飞机' not in (label or ''):
            old_ranks = Counter(map(printed_rank, old.elements()))
            new_ranks = Counter(map(printed_rank, new.elements()))
            for width, amount, name in ((2 if self.mode == 'basic' else 3, 2, '拆连对'),
                                        (3 if self.mode == 'basic' else 5, 1, '拆顺子')):
                if any(all(old_ranks[r] >= amount for r in run) and
                       any(new_ranks[r] < amount for r in run)
                       for run in (range(start, start + width) for start in range(3, 16 - width))):
                    damage[name] = 4
        return damage

    def allied_seats(self, seat, other):
        owners = getattr(self, 'owners', None)
        if owners is not None:
            return owners[seat] == owners[other]
        if self.mode == 'landlord':
            return seat != self.landlord and other != self.landlord
        return self.mode in ('basic', 'standard') and other % 2 == seat % 2

    def can_soon_finish(self, seat):
        if seat in self.finished or not 0 < len(self.hands[seat]) <= 2:
            return False
        resources = getattr(self, 'resources', None)
        return resources is None or (resources[seat]['turns'] >= 2 and not resources[seat]['ban'] and not self.zones[seat])

    def lead_shape(self, seat, cards):
        """A legal shape for the remaining physical cards if we regain the lead."""
        if not cards or any(c['rank'] == 18 for c in cards):
            return None
        combo = classify([c['rank'] for c in cards], self.mode, self.main, pattern=self.pattern)
        if combo:
            return combo['kind']
        if self.mode in ('standard', 'trio') and any(c['rank'] == 14 and c['suit'] == 'S' for c in cards):
            combos = interpretations(cards, self.mode, self.main, pattern=self.pattern)
            if combos:
                return combos[0]['kind']
        return None

    def priorities_worth_taking(self, seat, moves):
        hand = self.visible_hand(seat)
        conveyor = hasattr(self, 'owners')
        danger = any(other != seat and not self.allied_seats(seat, other) and self.can_soon_finish(other)
                     for other in range(len(self.players)))
        teammate_leads = self.last_seat is not None and self.allied_seats(seat, self.last_seat)
        team_can_finish = teammate_leads and self.can_soon_finish(self.last_seat)
        def gain(move):
            used = set(move['ids'])
            rest = [c for c in hand if c['id'] not in used]
            zone_empty = not conveyor or not self.zones[seat]
            if not rest and zone_empty and (not conveyor or self.resources[seat]['turns'] >= 2):
                return 100
            exit_route = 0 < len(rest) <= 12 and zone_empty and self.lead_shape(seat, rest)
            gains_lead = move['action'] in ('hook', 'dead', 'dead4') or move.get('label') == '死点'
            # Compare contesting with leaving the lead as it stands.
            urgency = (13 if danger else 0) - (9 if team_can_finish else 3 if teammate_leads else 0)
            penalty = sum(self.play_damage(hand, move).values())
            return len(used) * 2 + (3 if gains_lead else 0) + urgency + (12 if exit_route else 0) - penalty
        evaluated = [(gain(move), move) for move in moves]
        return [move for score, move in sorted(evaluated, key=lambda item: item[0], reverse=True) if score > 0]

    def opening_reserves(self, seat, moves):
        """Ordinary opening leads that retain a ready 4A4 for regaining control."""
        if self.play_number or self.last or self.mode == 'landlord' or self.phase != 'play' or seat != self.turn:
            return []
        controls = [set(m['ids']) for m in moves if m.get('label') == '4A4']
        if not controls:
            return []
        hand = self.visible_hand(seat)
        resources = getattr(self, 'resources', None)
        if any(len(h) <= 2 and (resources is None or resources[i]['turns'] >= 2)
               for i, h in enumerate(self.hands) if i != seat and i not in self.finished):
            return []
        if resources is None or resources[seat]['turns'] >= 2:
            if any(len(m.get('ids', ())) == len(hand) and m['action'] in ('play', 'auto') for m in moves):
                return []
        if resources is None or resources[seat]['turns'] >= 1:
            for used in controls:
                left = [c for c in hand if c['id'] not in used]
                if not left or self.lead_shape(seat, left):
                    return []
        return [i for i, m in enumerate(moves) if m['action'] in ('play', 'auto') and not m.get('power')
                and any(used.isdisjoint(m['ids']) for used in controls)]

    def keeps_urgent_playable(self, seat, move):
        remaining = [c for c in self.hands[seat] if c['id'] not in move.get('ids', [])]
        urgent = sum(c['rank'] == 18 for c in remaining)
        return urgent <= 1 or len(remaining) - urgent >= urgent - 1

    def landlord_two_play_exit(self, seat, moves, allow_contested=False):
        """Prefer a provable two-play finish using only our hand and public information."""
        if self.mode != 'landlord' or self.phase != 'play' or seat != self.turn:
            return None
        hand = self.hands[seat]
        exits = []
        for move in moves:
            if move['action'] != 'play' or not all(k in move for k in ('label', 'n', 'value', 'power')):
                continue
            used = set(move['ids'])
            left = [c['rank'] for c in hand if c['id'] not in used]
            if used and classify(left, 'landlord'):
                exits.append(move)
        if not exits:
            return None
        unseen = Counter({**dict.fromkeys(RANKS, 4), 16: 1, 17: 1})
        unseen.subtract(c['rank'] for c in hand)
        for trick in itertools.chain(map(json.loads, self.ai_older_rounds), self.ai_recent_rounds, [self.ai_current_round]):
            for event in trick:
                if isinstance(event, dict):
                    unseen.subtract(c['rank'] for c in event['cards'])
        largest = max((len(h) for s, h in enumerate(self.hands) if s != seat), default=0)
        rocket = largest >= 2 and unseen[16] > 0 and unseen[17] > 0
        bombs = [rank for rank in RANKS if largest >= 4 and unseen[rank] >= 4]
        for move in exits:
            kind, value = move['label'], move['value']
            if kind == '王炸':
                return move
            if rocket or any(kind != '炸弹' or rank > value for rank in bombs):
                continue
            if kind == '炸弹' or move['n'] > largest:
                return move
            multiplicity = {'单张': 1, '对子': 2, '三张': 3, '三带一': 3, '三带一对': 3}.get(kind)
            if multiplicity and not any(rank > value and n >= multiplicity for rank, n in unseen.items()):
                return move
        if allow_contested:
            return min(exits, key=lambda m: (m['power'], -m['n'], m['value']))
        return None

    def bot_action(self, seat):
        if self.priority:
            if self.priority_paused(): return None
            pending = self.priority['pending']
            controlled = seat in self.priority['bots'] and not pending or seat in pending and self.players[seat].get('autoplay') and not any(not self.players[s].get('autoplay') for s in pending)
            if controlled:
                moves = [m for m in self.priority_moves(seat) if self.keeps_urgent_playable(seat, m)]
                moves = self.priorities_worth_taking(seat, moves)
                if not moves: return {'action': 'priority-decline'}
                move = moves[0]
                return {'action': 'priority-play', 'special': move['action'], 'ids': move['ids'], **({'wildcard': move['wildcard']} if 'wildcard' in move else {})}
            if self.solo(): return None
        if self.phase == 'tribute':
            tribute = self.tribute
            if tribute['stage'] == 'choose' and seat in tribute['receivers'] and not any(o['recipient'] == seat for o in tribute['offers']):
                offer = max((o for o in tribute['offers'] if o['recipient'] is None), key=lambda o: strength(o['card']['rank'], self.main, self.mode))
                return {'action': 'tribute-pick', 'target': offer['donor']}
            if tribute['stage'] == 'return' and any(o['recipient'] == seat and not o['returned'] for o in tribute['offers']):
                returned = min(self.hands[seat], key=lambda c: strength(c['rank'], self.main, self.mode))
                return {'action': 'tribute-return', 'ids': [returned['id']]}
            return None
        if self.phase == 'bid':
            if seat != self.turn: return None
            value = 3 if sum(c['rank'] >= 15 for c in self.hands[seat]) >= 5 else (self.bid + 1 if self.bid < 2 else 0)
            return {'action': 'bid', 'value': value}
        if self.phase == 'setup':
            if seat in self.rps or seat not in self.confirmation_seats(): return None
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
        if self.priority and self.priority['pending'] and (self.players[seat].get('bot') or self.players[seat].get('autoplay')):
            if self.solo(): return None
            moves = [m for m in moves if m['action'] not in PRIORITY_ACTIONS]
        hand = self.hands[seat]
        def allied(other):
            return other != seat and self.allied_seats(seat, other)
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
        moves = [m for m in moves if self.keeps_urgent_playable(seat, m)]
        if not moves: return {'action': 'pass'}
        for move in moves:
            if len(move['ids']) == len(hand): return move
        if self.mode == 'landlord':
            exit_move = self.landlord_two_play_exit(seat, moves, allow_contested=not responding)
            if exit_move:
                return exit_move
        reserve_openers = {tuple(moves[i]['ids']) for i in self.opening_reserves(seat, moves)}
        safe_teammate = responding and allied(self.last_seat) and not self.last.get('direct') and not (danger <= self.last['n'] <= 2 and self.last['value'] < 15)
        visible = self.visible_hand(seat)
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
                if self.mode != 'landlord' and self.pattern:
                    body, wing = self.pattern
                    count = min(pool[wing], pool[body] - 1)
                    if count >= (1 if self.mode == 'basic' else 2):
                        pool[wing] -= count; pool[body] -= count + 1; turns += 1
                for multiple in order:
                    minimum = (3 if self.mode == 'basic' else 5) if multiple == 1 else (2 if self.mode == 'basic' else 3) if multiple == 2 else 2
                    for start in range(3, 15):
                        sequence = []
                        for rank in range(start, 15):
                            if pool[rank] < multiple or pool[rank] >= minimum_bomb: break
                            sequence.append(rank)
                        if len(sequence) >= minimum:
                            for rank in sequence: pool[rank] -= multiple
                            turns += 1
                            if multiple == 3 and self.mode != 'basic':
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
            value = hand_cost(remaining) * 8 + sum(self.play_damage(visible, move).values())
            if reserve_openers and tuple(move['ids']) not in reserve_openers:
                value += 10
            used = Counter(c['rank'] for c in chosen)
            for rank, number in used.items():
                if 0 < number < counts[rank]:
                    value += 3 if counts[rank] >= 2 else 0
            controls = sum(strength(c['rank'], self.main, self.mode) >= 15 for c in chosen)
            value += controls * (1 if danger <= 2 else 4)
            value += sum(c['rank'] == 14 and c['suit'] == 'S' for c in chosen) * 3
            if move['action'] == 'urgent':
                gift = next(c for c in chosen if c['rank'] != 18)
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

    def visible_hand(self, seat):
        return sorted(self.hands[seat], key=lambda c: (strength(c['rank'], self.main, self.mode), c['suit']))

    def public_hands(self, shown=None):
        owners = getattr(self, 'owners', range(len(self.hands)))
        return [dict(owner=owner, actor=actor, cards=self.visible_hand(actor))
                for actor, owner in enumerate(owners) if shown is None or owner in shown]

    def view(self, seat):
        response = None
        if self.phase == 'play' and seat is not None and seat not in self.finished:
            if self.priority and seat in self.priority['pending']: response = {'key': self.play_number, 'moves': self.priority_moves(seat)}
        return {'mode': self.mode, 'phase': self.phase, 'main': self.main, 'scores': self.scores, 'turn': self.turn, 'landlord': self.landlord, 'bid': self.bid,
                'bottom': self.bottom if self.phase != 'bid' else [], 'hand': self.visible_hand(seat) if seat is not None else [],
                'counts': [len(h) for h in self.hands], 'initialCounts': self.initial_counts, 'remainingHands': [sorted(h, key=lambda c: (strength(c['rank'], self.main, self.mode), c['suit'])) for h in self.hands] if self.phase == 'over' else None, 'finished': self.finished, 'last': self.last, 'lastSeat': self.last_seat,
                'seatPlays': self.seat_plays, 'playNumber': self.play_number, 'response': response,
                'winner': self.winner, 'log': self.log, 'reveals': self.reveals, 'ready': list(self.rps), 'promotions': self.promotions,
                'priority': {'pending': self.priority['pending'], 'moves': self.priority_moves(seat) if seat in self.priority['pending'] else []} if self.priority else None,
                'roundComplete': self.round_complete, 'tribute': self.tribute, 'captured': self.captured, 'options': {k:v for k,v in self.options.items() if not k.startswith('_')}, 'openingFirst': self.first, 'nextMain': self.next_main, 'urgentLast': self.urgent_last}
