"""Conveyor rounds and skills; shared 4A4A4 patterns stay in engine.py.

A physical card exists in exactly one hand, zone, draw pile, discard pile, or
pending reveal. Table displays are snapshots and never own physical cards.
"""
import copy
import itertools
import random
from collections import Counter
from engine import Game, RuleError, LABELS, RANKS, deck, strength, classifications, wildcard_rank, valid_wildcard
from conveyor_skills import SKILLS, available

SPECIALS = ('cross', 'hook', 'dot', 'press', 'dead', 'dead4')
SUITS = {'S': '黑桃', 'H': '红桃', 'C': '梅花', 'D': '方片', 'J': '', 'U': ''}


def card_name(card):
    return SUITS.get(card['suit'], '') + LABELS[card['rank']]


class ConveyorRound(Game):
    def __init__(self, players, options=None, previous=None, interactive=True):
        options = {**(options or {}), 'tribute': False, 'dlc': False}
        super().__init__('standard', players, options, previous, interactive)
        self.owners = [p['owner'] for p in players]
        self.skills = [p['skill'] for p in players]
        self.turn_order = [s for owner in (0, 3, 2, 1) for s, p in enumerate(players) if p['owner'] == owner]
        self.pile = deck('standard', options.get('dlc', False))
        self.all_cards = {c['id']: c for c in self.pile}
        self.discard = []
        self.destroyed = []
        self.urgent_uses = {}
        self.hands = [[] for _ in players]
        self.zones = [[] for _ in players]
        self.resources = [dict(money=0, blood=0, boost=0, ban=0, shield=0, turns=0, debt=0, suits=[], bloodReady=False) for _ in players]
        self.pending = []
        self.bonds = []
        self.complete_owners = []
        self.drafted = set()
        self.split = set()
        self.suit_lead = None
        self.lead_key = None
        self.start_turn = None
        self.phase = 'draft'
        self.log = []
        self.last_effective = None
        self.defer_finish = False
        self.extra_args = {}
        self._generating = False
        bonus = set()
        self.deal_counts = [0 if p.get('second') else SKILLS[p['skill']]['deal'] + int(p['owner'] in bonus) for p in players]
        self.keep_counts = [0 if p.get('second') else SKILLS[p['skill']]['keep'] + int(p['owner'] in bonus) for p in players]
        order = self.turn_order[:]
        if self.first is not None:
            start = order.index(self.first); order = order[start:] + order[:start]
        for index in range(max(self.deal_counts)):
            for s in order:
                if index < self.deal_counts[s]: self.gain(s, 1, initial=True, main_choice=False)
        for s in order:
            if self.skill(s, 'clean'):
                optional = [c for c in self.hands[s] if c['rank'] == self.main and c['rank'] in (3, 4, 5, 6)]
                if optional: self.offer(s, 'clean-main', '净化：选择保留的主牌，其余换牌', cards=copy.deepcopy(optional))
        self.initial_counts = [len(h) for h in self.hands]
        if self.first is not None and self.skill(self.first, 'scavenge'): self.first = self.next_seat(self.first)
        self.announce('请选择开局保留的牌。')

    def announce(self, text):
        super().announce(text)
        if hasattr(self, 'action_reports'): self.action_reports.append(text)

    def report(self, seat):
        pass

    def solo(self):
        return len({self.owners[s] for s, p in enumerate(self.players) if not p.get('bot')}) <= 1

    def name(self, seat):
        return self.players[seat]['name']

    def active(self):
        return [s for s in range(len(self.players)) if s not in self.finished]

    def skill(self, seat, key):
        return self.skills[seat] == key

    def next_seat(self, seat):
        pos = self.turn_order.index(seat)
        for i in range(1, len(self.turn_order) + 1):
            nxt = self.turn_order[(pos + i) % len(self.turn_order)]
            if nxt not in self.finished: return nxt
        return seat

    def inherit_lead(self, seat):
        partner = next((s for s in self.active() if self.owners[s] == (self.owners[seat] + 2) % 4), None)
        return partner if partner is not None else self.next_seat(seat)

    def recycle(self):
        # Only urgent hand rotation returns the played cards to the pile.
        return

    def draw_card(self):
        self.recycle()
        return self.pile.pop(0) if self.pile else None

    def bottom_cards(self, cards):
        ids = {c['id'] for c in cards}
        self.discard = [c for c in self.discard if c['id'] not in ids]
        cards = list(cards)
        random.shuffle(cards)
        self.pile.extend(cards)

    def effective_rank(self, seat, rank):
        key = self.skills[seat]
        if key == 'leap' and rank in (16, 17): return 17
        if rank >= 15 or rank == self.main: return rank
        amount = 2 if key == 'leap' else 1 + self.resources[seat]['boost'] if key == 'ascend' else 0
        ladder = RANKS + [self.main]
        return ladder[min(ladder.index(rank) + amount, len(ladder) - 1)]

    def maximum(self, seat):
        cards = [c for c in self.hands[seat] if c['rank'] != 18]
        value = max((self.card_value(seat, c) for c in cards), default=None)
        return [c for c in cards if self.card_value(seat, c) == value]

    def card_value(self, seat, card):
        rank = self.effective_rank(seat, card['rank'])
        return 16 if rank == self.main else rank + 1 if rank in (16, 17) else rank

    def allowed_card(self, seat, card):
        if self.skill(seat, 'clean'):
            return card['rank'] not in (3, 4, 5, 6) or card['rank'] == self.main
        if self.skill(seat, 'gather'):
            return card['rank'] not in (15, self.main, 16, 17)
        return True

    def gain(self, seat, number, initial=False, mirror=True, main_choice=True, blood_mark=None):
        if seat in self.finished or self.phase == 'over': return []
        obtained = []
        rejected = []
        # Rejected cards cannot recur within this batch, even with recycling.
        for _ in range(number):
            while True:
                card = self.draw_card()
                if card is None: break
                if not self.allowed_card(seat, card):
                    rejected.append(card)
                    continue
                obtained.append(card)
                break
            if card is None: break
        self.discard.extend(rejected)
        self.hands[seat].extend(obtained)
        if main_choice and self.skill(seat, 'clean'):
            optional = [c for c in obtained if c['rank'] == self.main and c['rank'] in (3, 4, 5, 6)]
            if optional: self.offer(seat, 'clean-main', '净化：选择保留的主牌，其余换牌', cards=copy.deepcopy(optional))
        if not initial and obtained:
            if hasattr(self, 'action_gains'): self.action_gains.append((seat, len(obtained)))
            self.announce(self.name(seat) + '获得%d张牌。' % len(obtained))
            if self.skill(seat, 'blood') and (blood_mark if blood_mark is not None else seat != getattr(self, '_playing_seat', None)): self.resources[seat]['blood'] += len(obtained)
            if mirror: self.mirror(seat, len(obtained))
            self.report(seat)
        return obtained

    def receive(self, seat, cards, mirror=True):
        accepted = [c for c in cards if self.allowed_card(seat, c)]
        rejected = [c for c in cards if not self.allowed_card(seat, c)]
        self.hands[seat].extend(accepted)
        self.discard.extend(rejected)
        replacements = self.gain(seat, len(rejected), mirror=False) if rejected else []
        if mirror: self.mirror(seat, len(accepted) + len(replacements))
        if self.skill(seat, 'blood') and seat != getattr(self, '_playing_seat', None): self.resources[seat]['blood'] += len(accepted)
        if self.skill(seat, 'clean'):
            optional = [c for c in accepted if c['rank'] == self.main and c['rank'] in (3,4,5,6)]
            if optional: self.offer(seat, 'clean-main', '净化：选择保留的主牌，其余换牌', cards=copy.deepcopy(optional))
        self.report(seat)

    def take(self, seat, cards, destination='discard', mirror=True):
        ids = {c['id'] for c in cards}
        self.hands[seat] = [c for c in self.hands[seat] if c['id'] not in ids]
        if destination == 'discard': self.discard.extend(cards)
        elif destination == 'zone': self.zones[seat].extend(cards)
        elif destination == 'bottom': self.bottom_cards(cards)
        if mirror: self.mirror(seat, -len(cards))
        self.report(seat)

    def remove(self, seat, cards):
        physical = self.select(seat, [c['id'] for c in cards])
        self.take(seat, physical)

    def mirror(self, seat, delta):
        for bond in self.bonds:
            if seat not in bond['seats']: continue
            other = next(s for s in bond['seats'] if s != seat)
            if other in self.finished: continue
            if delta > 0: self.gain(other, delta, mirror=False)

    def offer(self, seat, kind, title, **data):
        if seat not in self.finished and self.phase != 'over':
            self.pending.append(dict(seat=seat, kind=kind, title=title, **data))

    def finish(self, seat):
        if self.defer_finish or self.hands[seat] or self.zones[seat] or seat in self.finished: return
        if self.resources[seat]['turns'] < 2:
            self.gain(seat, 1)
            self.resources[seat]['earlyRefill'] = True
            return
        owner = self.owners[seat]
        if owner in self.complete_owners: return
        self.complete_owners.append(owner)
        for s, o in enumerate(self.owners):
            if o == owner and s not in self.finished: self.finished.append(s)
        self.cancel_choices(lambda q: q['seat'] in self.finished)
        if self.priority:
            for group in ('pending', 'bots'): self.priority[group] = [s for s in self.priority[group] if s not in self.finished]
            if not self.priority['pending'] and not self.priority['bots']: self.priority = None
        self.claims = {s: claim for s, claim in self.claims.items() if s not in self.finished}
        self.announce(self.name(seat) + '完成出牌，第%d名。' % len(self.complete_owners))
        active_owners = [o for o in range(4) if o not in self.complete_owners]
        if len(active_owners) <= 1 or len(active_owners) == 2 and active_owners[0] % 2 == active_owners[1] % 2:
            order = self.complete_owners + active_owners
            team = order[0] % 2
            partner = (order[0] + 2) % 4
            caught = 3 - order.index(partner)
            self.scores[team] = min(11, self.scores[team] + caught)
            self.winner = [s for s, o in enumerate(self.owners) if o % 2 == team]
            self.round_complete = self.main == 14
            self.next_main = 3 if self.round_complete else RANKS[self.scores[team]]
            self.captured = []
            self.phase = 'over'
            self.cancel_choices(lambda q: True)
            self.announce('本局结束。')

    def cancel_choices(self, predicate):
        kept = []
        for q in self.pending:
            if not predicate(q): kept.append(q); continue
            if q['kind'] == 'stars': self.pile = q['cards'] + self.pile
            elif q['kind'] == 'retain': self.bottom_cards(q['cards'])
        self.pending = kept

    def transformed(self, seat, cards, args=None):
        result = [{**c, 'rank': self.effective_rank(seat, c['rank'])} for c in cards]
        if self.skill(seat, 'wild'):
            for c in result:
                if c['rank'] == 14: c['suit'] = 'S'
        pair = (args or {}).get('double')
        if pair:
            if not self.skill(seat, 'double') or not isinstance(pair, dict): raise RuleError('没有拆解技能。')
            chosen = next((c for c in cards if c['id'] == pair.get('id')), None)
            ranks, suits = pair.get('ranks'), pair.get('suits')
            if not chosen or chosen['rank'] not in (13, 14, 15, self.main) or not isinstance(ranks, list) or len(ranks) != 2 or any(r not in (3, 4, 5) or r == self.main for r in ranks): raise RuleError('拆解需要一张 K、A、2 或主牌，指定两张 3 至 5 的非主牌。')
            if not isinstance(suits, list) or len(suits) != 2 or any(s not in 'SHCD' for s in suits): raise RuleError('请选择两张牌的花色。')
            result = [c for c in result if c['id'] != chosen['id']]
            result.extend(dict(id=chosen['id'] + ':' + str(i), rank=r, suit=s) for i, (r, s) in enumerate(zip(ranks, suits)))
        return result

    def validate_play(self, seat, cards, action='play', wildcard=None):
        self._validating_seat = seat
        transformed = self.transformed(seat, cards, self.extra_args)
        if any(c['rank'] == 18 for c in transformed): raise RuleError('急牌请单独选择效果使用。')
        old_hui, old_pattern = self.hui_used, self.pattern
        old_advanced = self.options.get('advancedHui', False)
        if self.skill(seat, 'formless') and action == 'hui':
            if len(self.hands[seat]) < 3: raise RuleError('少于三张手牌时不能回。')
            self.hui_used = False
            self.options['advancedHui'] = True
        try:
            if self.skill(seat, 'formation'):
                eligible = {c['id'] for c in transformed if c['rank'] == 14 and c['suit'] == 'S'}
                if isinstance(wildcard, dict) and (not set(wildcard) <= eligible or any(not valid_wildcard(v) for v in wildcard.values())): raise RuleError('赖子指定无效。')
                if wildcard is not None and not isinstance(wildcard, dict) and not valid_wildcard(wildcard): raise RuleError('赖子指定无效。')
                declared = [wildcard.get(c['id'], 14) if isinstance(wildcard, dict) else wildcard or 14 for c in transformed]
                rr = [wildcard_rank(v) if c['id'] in eligible else c['rank'] for c, v in zip(transformed, declared)]
                suits = [v.get('suit', c['suit']) if c['id'] in eligible and isinstance(v, dict) else c['suit'] for c, v in zip(transformed, declared)]
                reduced = len(rr) >= 3 and set(rr) <= {4, 14} and rr.count(4) >= 2 and rr.count(14) >= 1 and rr.count(4) > rr.count(14)
                if action == 'play' and reduced:
                    normalized = next(c for c in classifications(rr + [4, 14], 'standard', self.main) if c['kind'] == '4A4')
                    combo = {**normalized, 'n':len(rr), 'ranks':rr, 'suits':suits}
                    old = self.last if not (self.last and self.last.get('direct') and seat == self.turn) else None
                    if seat == self.turn and (not old or old.get('special') not in ('cross', 'hook') and (old['power'], old['value']) < (combo['power'], combo['value'])): return combo, False
                if action == 'play' and len(self.hands[seat]) > 12 and len(transformed) == 3 and len(set(rr)) == 1:
                    old = self.last if not (self.last and self.last.get('direct') and seat == self.turn) else None
                    if seat == self.turn and (not old or old.get('special') not in ('cross', 'hook') and not old['power']):
                        return dict(kind='炸弹', n=3, value=strength(rr[0], self.main), power=3, ranks=rr, suits=suits), False
            combo, direct = super().validate_play(seat, transformed, action, wildcard)
            # Restore natural suits for unassigned all-A wildcards.
            declared = wildcard if isinstance(wildcard, dict) else {}
            combo['suits'] = [declared.get(c['id'], {}).get('suit', c['suit']) if isinstance(declared.get(c['id']), dict) else c['suit'] for c in transformed]
            combo['displayCards'] = [dict(c) for c in transformed]
            return combo, direct
        finally:
            self.hui_used, self.pattern = old_hui, old_pattern
            self.options['advancedHui'] = old_advanced

    def hui_profile(self, combo, cards):
        profile = super().hui_profile(combo, cards)
        if profile is not None and self.skill(getattr(self, '_validating_seat', self.turn), 'formless'):
            return tuple(sum(n for _, n in group) for group in profile)
        return profile

    def candidates(self, seat):
        if self.phase != 'play' or seat in self.finished or self.resources[seat]['ban']: return []
        if self._generating: return []
        previous_args = self.extra_args
        self._generating = True
        self._validating_seat = seat
        try:
            moves = [m for m in super().candidates(seat) if m['action'] != 'urgent']
            # Generate using effective rank groups too; candidate validation still
            # reads physical cards and applies the transform exactly once.
            hand = self.hands[seat]
            transformed = self.transformed(seat, hand)
            groups = {}
            for c in transformed:
                if c['rank'] != 18: groups.setdefault(c['rank'], []).append(c['id'])
            sets = []
            for group in groups.values():
                sets.extend(group[:n] for n in range(1, len(group) + 1))
            if self.skill(seat, 'formation'):
                for fours in range(2, len(groups.get(4, [])) + 1):
                    for aces in range(1, min(fours - 1, len(groups.get(14, []))) + 1):
                        sets.append(groups[4][:fours] + groups[14][:aces])
            for multiple, minimum in ((1, 5), (2, 3), (3, 2)):
                for start in range(3, 15):
                    ids = []
                    for end in range(start, 15):
                        if len(groups.get(end, [])) < multiple: break
                        ids += groups[end][:multiple]
                        if end - start + 1 >= minimum: sets.append(ids[:])
            if len(hand) <= 8:
                for n in range(1, len(hand) + 1):
                    sets.extend([c['id'] for c in part] for part in itertools.combinations(hand, n))
            seen = {(m['action'], tuple(sorted(m['ids']))) for m in moves}
            for ids in sets:
                for action in ('play', 'hui') + SPECIALS:
                    if (action, tuple(sorted(ids))) in seen: continue
                    try:
                        combo, _ = self.validate_play(seat, self.select(seat, ids), action)
                        moves.append(dict(action=action, ids=ids, label=combo['kind'], n=combo['n'], value=combo['value'], power=combo['power']))
                        seen.add((action, tuple(sorted(ids))))
                    except RuleError: pass
            if self.skill(seat, 'double'):
                lows = [r for r in (3, 4, 5) if r != self.main]
                for card in hand:
                    if card['rank'] not in (13, 14, 15, self.main): continue
                    others = [c for c in hand if c['id'] != card['id'] and c['rank'] != 18]
                    sets = [[card]] + [[card] + [c for c in others if c['rank'] == r][:n] for r in lows for n in range(1, 7)]
                    if len(others) <= 7:
                        sets += [[card] + list(part) for n in range(1, len(others) + 1) for part in itertools.combinations(others, n)]
                    for pair in itertools.combinations_with_replacement(lows, 2):
                        declaration = dict(id=card['id'], ranks=list(pair), suits=[card['suit']] * 2)
                        self.extra_args = {'double': declaration}
                        for chosen in sets:
                            for action in ('play', 'hui') + SPECIALS:
                                try:
                                    combo, _ = self.validate_play(seat, chosen, action)
                                    moves.append(dict(action=action, ids=[c['id'] for c in chosen], double=declaration, label=combo['kind'], n=combo['n'], value=combo['value'], power=combo['power']))
                                except RuleError: pass
                self.extra_args = {}
            return sorted(moves, key=lambda m: (m['power'], -m['n'], m['value']))
        finally:
            self.extra_args = previous_args
            self._generating = False

    def forced_pass(self):
        if self.pending: return False
        if self.phase == 'play' and self.resources[self.turn]['ban']: return True
        if self.phase == 'play' and self.skill(self.turn, 'scavenge') and self.resources[self.turn]['turns'] < 2: return True
        return super().forced_pass()

    def priority_paused(self):
        return bool(self.pending and not (self.players[self.pending[0]['seat']].get('bot') or self.players[self.pending[0]['seat']].get('autoplay'))) or super().priority_paused()

    def open_priority(self):
        if getattr(self, '_defer_priority', False): return
        super().open_priority()
        if self.priority:
            for group in ('pending', 'bots'):
                self.priority[group] = [s for s in self.priority[group] if not self.resources[s]['ban']]
            if not self.priority['pending'] and not self.priority['bots']: self.priority = None

    def priority_paused(self):
        return not self.pending and super().priority_paused()

    def free_lead(self, previous=None):
        if self.phase != 'play' or not (self.last is None or self.last.get('direct') and self.last_seat == self.turn): return
        key = (self.turn, self.play_number)
        if key == self.lead_key: return
        self.lead_key = key
        seat = self.turn
        if self.skill(seat, 'stars'):
            count = len(self.active())
            self.recycle()
            if self.pile:
                cards, self.pile = self.pile[:count], self.pile[count:]
                self.offer(seat, 'stars', '守望：排列牌堆顶部', cards=cards)
        if self.skill(seat, 'duel'):
            self.offer(seat, 'duel-start', '是否发起死斗？')
        if self.skill(seat, 'debt'):
            for target in self.active():
                number = self.resources[target]['debt']
                self.resources[target]['debt'] = 0
                if target != seat and number: self.gain(target, number)
        record = self.suit_lead
        if record and record['seat'] == seat:
            suits = record['suits']
            self.offer(seat, 'suitmark', '烙印：选择赋予对方的花色', target=record['target'], suits=suits)
        self.suit_lead = None

    def enter_turn(self):
        if self.phase != 'play' or self.start_turn == (self.turn, self.resources[self.turn]['turns']): return
        self.start_turn = (self.turn, self.resources[self.turn]['turns'])
        seat = self.turn
        if not self.hands[seat] and not self.zones[seat]:
            self.finish(seat)
            if self.phase == 'over': return
            if seat in self.finished or not self.hands[seat]:
                if seat not in self.finished: self.resources[seat]['turns'] += 1
                self.turn = self.next_seat(seat); self.enter_turn()
                return
        if self.skill(seat, 'pursuit') and not self.resources[seat]['ban']:
            if self.last and not (self.last.get('direct') and self.last_seat == seat) and not self.candidates(seat):
                for _ in range(10):
                    if not self.gain(seat, 1) or self.candidates(seat): break

    def suit_effect(self, seat, pair):
        code = ''.join(pair)
        self.announce(self.name(seat) + '结算烙印。')
        draws = {'SS': 2, 'HS': 2, 'CS': 1, 'DS': 4}.get(code, 0)
        if draws: self.gain(seat, draws)
        discard = {'HH': 2, 'HS': 1, 'CH': 1, 'DH': 3}.get(code, 0)
        if discard: self.discard_max(seat, discard)
        choices = {'CC': 2, 'CS': 1, 'CH': 1, 'CD': 3}.get(code, 0)
        if choices:
            revealed = []
            for _ in range(choices):
                c = self.draw_card()
                if c: revealed.append(c)
            if revealed: self.offer(seat, 'retain', '烙印：至多保留一张', cards=revealed)

    def discard_max(self, seat, count):
        if count <= 0 or seat in self.finished: return
        maximum = self.maximum(seat)
        if not maximum: return
        if len(maximum) > 1:
            self.offer(seat, 'maximum', '选择弃置的一张最大牌', cards=copy.deepcopy(maximum), left=count)
            return
        self.take(seat, maximum)
        self.finish(seat)
        if seat not in self.finished: self.discard_max(seat, count - 1)

    def end_deal(self, seat, played=True, immediate=False, own_turn=True):
        if self.pending and not immediate:
            self.pending.append(dict(seat=seat, kind='_end-deal', played=played, own_turn=own_turn))
            return
        if seat in self.finished or self.phase == 'over': return
        state, key = self.resources[seat], self.skills[seat]
        if state.pop('earlyRefill', False):
            if key == 'blood': self.trim_blood(seat)
            return
        if state['shield']:
            if own_turn: state['shield'] -= 1
            self.announce(self.name(seat) + '免本次发牌。')
            if key == 'blood': self.trim_blood(seat)
            return
        if key == 'pursuit': return
        if key == 'stash' and len(self.hands[seat]) < 5: return
        if key == 'blood':
            self.gain(seat, 1, blood_mark=not played)
            self.trim_blood(seat)
        elif key in ('extra', 'gather', 'redirect', 'request', 'trade') or any(seat in b['seats'] for b in self.bonds):
            maximum = 3 if key == 'extra' else 5 if key == 'gather' else 2 if any(seat in b['seats'] for b in self.bonds) else 1
            self.offer(seat, 'deal', '选择结束发牌方式', maximum=maximum, skill=key)
        else: self.gain(seat, 1)

    def trim_blood(self, seat):
        count = len(self.hands[seat]) - self.resources[seat]['blood']
        if count > 0:
            self.offer(seat, 'discard', '重铸·嗜血：弃置%d张，保留%d张' % (count, self.resources[seat]['blood']), count=count)

    def after_action(self, seat, old_last, old_play, ordinary):
        if self.play_number != old_play:
            play = self.seat_plays[seat]
            # Expanded representations retain their originals for display.
            if play and play.get('displayCards'):
                physical = {c['id']: c for c in self.discard + self.pile}
                play['cards'] = [{**physical.get(c['id'].split(':')[0], c), 'id': c['id']} for c in play['displayCards']]
                self.last['cards'] = play['cards']
            if self.skill(seat, 'blood'): self.resources[seat]['blood'] = max(0, self.resources[seat]['blood'] - 1)
            if self.skill(seat, 'money'): self.resources[seat]['money'] += play['n']
            if old_last and self.skill(seat, 'debt'): self.resources[old_last['seat']]['debt'] += 1
            self.suit_lead = None
            if old_last and self.skill(seat, 'suitmark'):
                suits = [s for s in play.get('suits', []) if s in 'SHCD']
                counts = Counter(suits)
                if len(counts) > 1:
                    self.suit_lead = dict(seat=seat, target=old_last['seat'], suits=list(counts))
            if self.skill(seat, 'reflux'):
                cards = [c for c in self.discard if c['id'] in {x['id'].split(':')[0] for x in play['cards']}]
                if cards: self.offer(seat, 'reflux', '回收：选择置于牌堆底的已出牌', cards=copy.deepcopy(cards))
            if self.skill(seat, 'stash') and self.hands[seat]: self.offer(seat, 'stash', '藏拙：选择存入展示区的手牌')
            self.bonds = [b for b in self.bonds if b['owner'] != seat]
            if self.skill(seat, 'bond'): self.offer(seat, 'bond', '灵魂绑定：选择绑定对象或取消')
            for other in self.active():
                if other != seat and self.skill(other, 'money') and self.resources[other]['money'] >= 4:
                    cards = [c for c in self.discard if c['id'] in {x['id'].split(':')[0] for x in play['cards']}]
                    if cards: self.offer(other, 'buy', '聚宝：花四金钱买一张，或放弃', cards=copy.deepcopy(cards))
            if self.skill(seat, 'reflux') and play['n'] >= 4 and self.phase != 'over':
                self.pending.append(dict(seat=seat, kind='_reflux-draw', count=play['n'] - 2))
        if ordinary:
            self.resources[seat]['turns'] += 1
            if self.resources[seat]['turns'] >= 3: self.finish(seat)
        if ordinary or self.play_number != old_play:
            self.end_deal(seat, played=self.play_number != old_play, own_turn=ordinary)
        if not self.pending:
            self.free_lead(old_last)
            self.enter_turn()

    def action(self, seat, action, ids=None, **args):
        if getattr(self, '_in_action', False): return Game.action(self, seat, action, ids, **args)
        self._in_action = True
        self._acting = seat
        try:
            result = self.execute_action(seat, action, ids, **args)
            self.settle()
            return result
        finally:
            self._in_action = False
            self._acting = None
            self._playing_seat = None
            for target, resource in enumerate(self.resources):
                if not any(q['kind'] == '_end-deal' and q['seat'] == target for q in self.pending): resource.pop('earlyRefill', None)

    def settle(self):
        if self.phase == 'play' and self.last and set(self.active()) - {self.last_seat} <= self.passes:
            self.turn = self.last_seat if self.last_seat not in self.finished else self.inherit_lead(self.last_seat)
            self.last = None; self.passes.clear(); self.priority = None; self.claims = {}; self.hui_used = False
            self.display_seen.clear()
            for finished in self.finished: self.seat_plays[finished] = None
        if self.phase == 'play' and self.turn in self.finished: self.turn = self.next_seat(self.turn)
        while self.pending and self.pending[0]['kind'] in ('_end-deal', '_reflux-draw'):
            q = self.pending.pop(0)
            if q['kind'] == '_end-deal': self.end_deal(q['seat'], q['played'], immediate=True, own_turn=q.get('own_turn', True))
            else:
                for other in self.active():
                    if other != q['seat']: self.gain(other, q['count'])
        if self.pending and self.pending[0]['kind'] in ('maximum', 'urgent-max'):
            q = self.pending[0]
            q['cards'] = copy.deepcopy(self.maximum(q['seat']))
            if not q['cards'] or q['kind'] == 'urgent-max' and len(self.hands[q['seat']]) <= 1:
                self.pending.pop(0); self.settle(); return
        if self.pending and self.pending[0]['kind'] in ('buy', 'scavenge', 'reflux'):
            q = self.pending[0]
            live = {c['id'] for c in self.discard}
            q['cards'] = [c for c in q['cards'] if c['id'] in live]
            if not q['cards']:
                self.pending.pop(0)
                if q['kind'] == 'scavenge': self.skip_action(q['seat'])
                self.settle()
                return
        if not self.pending and self.phase == 'play':
            self.free_lead()
            self.enter_turn()

    def execute_action(self, seat, action, ids=None, **args):
        ids = ids or []
        if seat not in range(len(self.players)): raise RuleError('玩家不存在。')
        if self.phase == 'over': raise RuleError('本局已结束。')
        if self.phase == 'play' and action == 'skill' and self.skill(seat, 'pressure'):
            if self.resources[seat]['ban']: raise RuleError('禁手期间不能使用技能。')
            self.use_skill(seat, ids, **args)
            return
        if self.pending:
            if action != 'choice' or self.pending[0]['seat'] != seat: raise RuleError('请等待当前选择完成。')
            self.resolve(seat, ids, **args)
            return
        if self.phase == 'draft':
            if action != 'keep' or self.players[seat].get('second') or seat in self.drafted: raise RuleError('请选择开局保留的牌。')
            cards = self.select(seat, ids)
            keep = self.keep_counts[seat] // 2 if self.skill(seat, 'twins') else self.keep_counts[seat]
            if len(cards) != min(keep, len(self.hands[seat])): raise RuleError('需保留%d张牌。' % min(keep, len(self.hands[seat])))
            rejected = [c for c in self.hands[seat] if c not in cards]
            if self.skill(seat, 'twins'):
                second = next(i for i,p in enumerate(self.players) if p.get('second') and self.owners[i] == self.owners[seat])
                self.hands[seat] = cards
                self.hands[second] = rejected
                self.split.add(seat)
            else: self.take(seat, rejected, 'bottom', mirror=False)
            self.drafted.add(seat)
            if self.skill(seat, 'blood'): self.offer(seat, 'blood', '重铸·嗜血：选择零至五张牌作为血')
            self.draft_ready()
            return
        if action == 'promote': raise RuleError('传送带不使用升变。')
        if self.phase in ('setup', 'rps'):
            if action == 'reveal' and self.skill(seat, 'scavenge'): raise RuleError('顺手牵羊不能作为首位出牌者。')
            super().action(seat, action, ids, **args)
            if self.phase == 'play':
                if self.skill(self.turn, 'scavenge'): self.turn = self.next_seat(self.turn)
                self.free_lead(); self.enter_turn()
            return
        if action == 'skill':
            if self.resources[seat]['ban']: raise RuleError('禁手期间不能使用技能。')
            self.use_skill(seat, ids, **args)
            return
        if self.phase != 'play': raise RuleError('尚未开始出牌。')
        if action == 'auto':
            declaration = args.get('wildcard')
            def urgent_card(card):
                assigned = wildcard_rank(declaration.get(card['id'], 14)) if isinstance(declaration, dict) else declaration
                return card['rank'] == 18 or card['rank'] == 14 and (card['suit'] == 'S' or self.skill(seat, 'wild')) and assigned == 18
            if any(urgent_card(c) for c in self.select(seat, ids)): action = 'urgent'
        if action == 'urgent':
            if seat != self.turn or self.resources[seat]['ban']: raise RuleError('只能在自己的非禁手阶段使用急牌。')
            self.urgent(seat, ids, **args)
            return
        if self.resources[seat]['ban']:
            if seat != self.turn or action != 'pass': raise RuleError('禁手期间只能结束行动。')
            self.resources[seat]['ban'] -= 1
            self.announce(self.name(seat) + '禁手，跳过出牌。')
            self.display_action(seat, dict(kind='禁手', cards=[], ranks=[], passed=True, order=self.play_number))
            self.passes.add(seat)
            self.resources[seat]['turns'] += 1
            self.end_deal(seat, False)
            self.advance_pass(seat)
            return
        if seat == self.turn and self.skill(seat, 'scavenge') and (self.resources[seat]['turns'] < 2 or action == 'pass'):
            self.scavenge(seat)
            return
        old_last = {**self.last, 'seat': self.last_seat} if self.last else None
        old_play = self.play_number
        prior_turn = self.turn
        ordinary = seat == self.turn and action not in ('priority-decline', 'priority-play', 'accept', 'reject', 'negotiate')
        self.extra_args = args
        self._defer_priority = True
        self._validating_seat = seat
        self._playing_seat = seat if ids and action not in ('pass', 'priority-decline', 'accept', 'reject', 'negotiate') else None
        try:
            super().action(seat, action, ids, **{k: v for k, v in args.items() if k != 'double'})
        finally:
            self.extra_args = {}
            self._defer_priority = False
        if self.play_number != old_play and self.last and self.last.get('special') in ('cross','hook','dot','press','dead','dead4'):
            cursor = prior_turn if prior_turn != seat else (self.next_seat(seat) if self.turn == seat else seat)
            visited = set()
            while cursor != seat and cursor not in visited:
                visited.add(cursor)
                if cursor not in self.finished:
                    self.resources[cursor]['turns'] += 1
                    self.end_deal(cursor, False)
                cursor = self.next_seat(cursor)
        self.after_action(seat, old_last, old_play, ordinary)
        if self.play_number != old_play: self.open_priority()

    def advance_pass(self, seat):
        active = set(self.active()) - {self.last_seat}
        if self.last and active <= self.passes:
            self.turn = self.last_seat if self.last_seat not in self.finished else self.inherit_lead(self.last_seat)
            self.last = None; self.passes.clear(); self.priority = None; self.claims = {}; self.hui_used = False
        else: self.turn = self.next_seat(seat)
        self.free_lead(); self.enter_turn()

    def draft_ready(self):
        primary = {s for s, p in enumerate(self.players) if not p.get('second')}
        if primary <= self.drafted and not self.pending:
            self.phase = 'setup'
            self.initial_counts = [len(h) for h in self.hands]
            self.announce('选牌完成，可亮黑桃3并确认开始。')

    def urgent(self, seat, ids, **args):
        chosen = self.select(seat, ids)
        wildcard = args.get('wildcard')
        eligible = {c['id'] for c in chosen if c['rank'] == 14 and (c['suit'] == 'S' or self.skill(seat, 'wild'))}
        if isinstance(wildcard, dict) and (not set(wildcard) <= eligible or any(not valid_wildcard(v, urgent=True) for v in wildcard.values())): raise RuleError('赖子指定无效。')
        if self.skill(seat, 'wild') and any((wildcard_rank(wildcard.get(i)) if isinstance(wildcard, dict) else wildcard) == 18 for i in eligible): raise RuleError('千变不能代替急牌。')
        urgent = [c for c in chosen if c['rank'] == 18 or c['id'] in eligible and (wildcard_rank(wildcard.get(c['id'])) if isinstance(wildcard, dict) else wildcard) == 18]
        effect = args.get('effect')
        if len(urgent) != 1 or effect not in ('draw', 'discard', 'ban', 'shield', 'maximum', 'rotate'): raise RuleError('选择一张急牌并选择效果。')
        rest = [c for c in chosen if c not in urgent]
        if self.urgent_uses.get(urgent[0]['id'], 0) >= 3 and effect != 'rotate': raise RuleError('这张急牌已使用三次，必须轮换并销毁。')
        target = args.get('target')
        if effect in ('draw', 'ban', 'maximum') and target not in self.active(): raise RuleError('请选择在场目标。')
        if effect != 'discard' and rest or effect == 'discard' and len(rest) > 2: raise RuleError('此效果至多附带弃置两张牌。')
        if effect == 'discard' and len(chosen) == len(self.hands[seat]): raise RuleError('急牌弃牌后必须保留至少一张手牌。')
        direction = args.get('direction', 'counterclockwise')
        if effect == 'rotate' and direction not in ('clockwise', 'counterclockwise'): raise RuleError('轮换方向无效。')
        self.take(seat, urgent, None if effect == 'rotate' else 'bottom')
        if effect == 'rotate': self.destroyed.extend(urgent)
        else: self.urgent_uses[urgent[0]['id']] = self.urgent_uses.get(urgent[0]['id'], 0) + 1
        if rest: self.take(seat, rest)
        self.announce(self.name(seat) + '使用急牌：' + {'draw':'加牌','discard':'弃牌','ban':'禁手','shield':'免发牌','maximum':'弃最大牌','rotate':'轮换并销毁'}[effect] + ('，目标' + self.name(target) if target is not None and effect in ('draw', 'ban', 'maximum') else '') + ('，弃置' + '、'.join(map(card_name, rest)) if rest else '') + '。')
        if effect == 'draw': self.gain(target, 1 if self.skill(target, 'anchor') else 2)
        elif effect == 'ban': self.resources[target]['ban'] += 1 if self.skill(target, 'anchor') else 2
        elif effect == 'shield': self.resources[seat]['shield'] += 3
        elif effect == 'maximum':
            cards = self.maximum(target)
            if len(self.hands[target]) > 1 and cards: self.offer(target, 'urgent-max', '急牌：选择一张最大牌放回牌堆底', cards=copy.deepcopy(cards))
        elif effect == 'rotate':
            ring = [s for s in self.turn_order if s in self.active() and not self.skill(s, 'anchor')]
            before = {s: self.hands[s][:] for s in ring}
            step = 1 if direction == 'counterclockwise' else -1
            for i, source in enumerate(ring):
                destination = ring[(i + step) % len(ring)]
                fixed = [c for c in before[destination] if c['rank'] == 18]
                self.hands[destination] = fixed + [c for c in before[source] if c['rank'] != 18]
            self.bottom_cards([card for card in self.discard if card['rank'] != 18])
            for s in ring:
                received = self.hands[s][:]; self.hands[s] = []
                self.receive(s, received, mirror=False)
                self.finish(s)
        self.finish(seat)
        if seat in self.finished and self.phase != 'over': self.turn = self.next_seat(seat); self.enter_turn()

    def scavenge(self, seat):
        cards = []
        live = {c['id'] for c in self.discard}
        for other, play in enumerate(self.seat_plays):
            if other != seat and play: cards.extend(c for c in play['cards'] if c['id'] in live)
        if cards: self.offer(seat, 'scavenge', '顺手牵羊：获取一名玩家最近一手的至少一张牌', cards=copy.deepcopy(cards))
        else: self.skip_action(seat)

    def use_skill(self, seat, ids, **args):
        key, effect = self.skills[seat], args.get('effect')
        if key == 'stash' and effect == 'retrieve':
            by_id = {c['id']: c for c in self.zones[seat]}
            if not ids or len(set(ids)) != len(ids) or any(i not in by_id for i in ids): raise RuleError('请选择展示区中的牌。')
            cards = [by_id[i] for i in ids]
            self.zones[seat] = [c for c in self.zones[seat] if c['id'] not in ids]
            self.hands[seat].extend(cards)
            self.announce(self.name(seat) + '从展示区取回%d张牌。' % len(cards))
            return
        if seat != self.turn and key != 'pressure': raise RuleError('只能在自己的行动阶段使用此技能。')
        cards = self.select(seat, ids)
        if key == 'scavenge':
            self.scavenge(seat)
        elif key == 'balance':
            if not self.can_draw(len(cards)): raise RuleError('牌堆不足，无法完成转换。')
            self.take(seat, cards)
            self.gain(seat, len(cards))
            self.announce(self.name(seat) + '使用转换。')
            self.finish(seat)
            self.skip_action(seat)
        elif key == 'gift':
            target = args.get('target')
            if len(cards) != 1 or target not in self.active() or target == seat: raise RuleError('请选择一张牌和另一名玩家。')
            if not self.can_draw(2): raise RuleError('牌堆不足，无法完成恩赐。')
            self.take(seat, cards, destination=None)
            self.receive(target, cards)
            self.gain(seat, 2)
            self.announce(self.name(seat) + '向' + self.name(target) + '赠送' + card_name(cards[0]) + '。')
            self.finish(seat)
            self.skip_action(seat)
        elif key == 'pressure':
            target = args.get('target')
            if len(cards) != 1 or self.effective_rank(seat, cards[0]['rank']) != 15 or target not in self.active() or target == seat: raise RuleError('请选择一张 2 和另一名玩家。')
            if any(q['kind'] == 'duel' for q in self.pending) and any(card['id'] == cards[0]['id'] for card in self.duel['choices'].values()): raise RuleError('这张牌已用于死斗判定，请等待公开。')
            if not self.can_draw(4): raise RuleError('牌堆不足，无法施压。')
            self.take(seat, cards); self.gain(target, 4); self.finish(seat)
            self.announce(self.name(seat) + '使用施压。')
        elif key == 'ascend':
            if not cards or any(c['rank'] != 15 for c in cards): raise RuleError('请选择印面为 2 的牌。')
            self.take(seat, cards, 'zone')
            self.resources[seat]['boost'] += len(cards)
            # These are spent resources, not unplayed stash cards.
            self.discard.extend(self.zones[seat]); self.zones[seat] = []
            self.announce(self.name(seat) + '增加%d级实际牌值。' % len(cards))
            self.finish(seat)
        elif key == 'seven':
            if effect == 'store':
                if not cards or any(c['rank'] not in (3, 4, 5, 6) for c in cards): raise RuleError('仅可储存 3、4、5、6。')
                if self.resources[seat].get('marks', 0) + len(cards) > 7: raise RuleError('至多存七枚印记。')
                self.take(seat, cards)
                # Mark cards remain owned resources until spent, but do not count
                # towards the unplayed obligation.
                self.resources[seat].setdefault('markCards', []).extend(cards)
                used = {c['id'] for c in cards}; self.discard = [c for c in self.discard if c['id'] not in used]
                self.resources[seat]['marks'] = len(self.resources[seat]['markCards'])
                self.finish(seat)
            elif effect == 'release':
                rr = args.get('ranks'); suits = args.get('suits', ['S'] * 7)
                marks = self.resources[seat].get('markCards', [])
                if len(marks) != 7 or not isinstance(rr, list) or len(rr) != 7 or any(r not in RANKS + [16, 17] for r in rr) or len(suits) != 7 or any(s not in 'SHCD' for s in suits): raise RuleError('需七枚印记并指定七张牌。')
                combos = [c for c in classifications(rr, 'standard', self.main) if c['kind'] == '顺子' and c['n'] == 7]
                if not combos: raise RuleError('七音印记只能组成七连顺子。')
                self.virtual_play(seat, combos, rr, suits)
                self.discard.extend(marks); self.resources[seat]['markCards'] = []; self.resources[seat]['marks'] = 0
            else: raise RuleError('请选择储存或使用重铸·七音。')
        elif key == 'judgment':
            if self.candidates(seat): raise RuleError('有能管上的牌时不能使用投骰。')
            combos = self.higher_combos()
            if not combos: raise RuleError('此牌型不能通过投骰提高一级。')
            card = self.draw_card()
            if not card: raise RuleError('牌堆已耗尽。')
            self.discard.append(card)
            self.announce(self.name(seat) + '投骰判定：' + card_name(card) + '。')
            if card['suit'] == 'S' and (card['rank'] == 15 or 3 <= card['rank'] <= 9):
                self.virtual_play(seat, combos, combos[0]['ranks'], self.last.get('suits', [c['suit'] for c in self.last['cards']])[:])
            else:
                self.gain(seat, 5); self.skip_action(seat, deal=True)
        elif key == 'trade':
            if len(cards) != 1: raise RuleError('请选择一张王、主牌或 2。')
            rank = self.effective_rank(seat, cards[0]['rank'])
            count = 5 if rank in (16, 17) else 4 if rank == self.main else 3 if rank == 15 else 0
            if not count: raise RuleError('请选择一张王、主牌或 2。')
            if not self.can_draw(count): raise RuleError('牌堆不足，无法换牌。')
            self.take(seat, cards); self.gain(seat, count); self.finish(seat)
            self.announce(self.name(seat) + '使用献祭。')
        else: raise RuleError('此技能在对应时机自动提示。')

    def can_draw(self, number):
        return len(self.pile) >= number

    def skip_action(self, seat, deal=False):
        if self.phase == 'over': return
        self.resources[seat]['turns'] += 1
        self.display_action(seat, dict(kind='跳过', cards=[], ranks=[], passed=True, order=self.play_number))
        if deal: self.end_deal(seat, False)
        if self.last:
            self.passes.add(seat)
            self.advance_pass(seat)
        else:
            self.turn = self.next_seat(seat); self.enter_turn()

    def higher_combos(self):
        old = self.last
        if not old or old['power'] and old['kind'] != '炸弹' or old.get('special') not in ('play', 'hui'): return []
        kind = old.get('baseKind', old['kind'])
        body = self.body_groups(old)
        body_ids = {i for group in body for i in group}
        body_ranks = sorted({old['ranks'][i] for i in body_ids})
        for step in range(1, 15):
            if len(body_ranks) == 1:
                ladder = [r for r in RANKS if r != self.main] + [self.main]
                idx = ladder.index(body_ranks[0]) if body_ranks[0] in ladder else len(ladder)
                if idx + step >= len(ladder): return []
                mapping = {body_ranks[0]: ladder[idx + step]}
            else:
                if max(body_ranks) + step >= 15: return []
                mapping = {r: r + step for r in body_ranks}
            rr = [mapping[r] if i in body_ids else r for i, r in enumerate(old['ranks'])]
            combos = [c for c in classifications(rr, 'standard', self.main) if c['kind'] == kind and c['n'] == old['n'] and c['value'] > old['value'] and c['power'] == old['power']]
            if combos: return combos
        return []

    def virtual_play(self, seat, combos, ranks, suits):
        old = self.last
        if old and old.get('special') in ('cross', 'hook') and not (old.get('direct') and self.last_seat == seat): raise RuleError('勾叉流程不能用此技能管牌。')
        combo = next((c for c in combos if not old or old.get('direct') and self.last_seat == seat or c['power'] and (c['power'], c['value']) > (old['power'], old['value']) or not c['power'] and not old['power'] and c['kind'] == old.get('baseKind', old['kind']) and c['n'] == old['n'] and c['value'] > old['value']), None)
        if not combo: raise RuleError('此牌型不能管住上一手。')
        cards = [dict(id='virtual-%d-%d' % (self.play_number + 1, i), rank=r, suit=s) for i, (r, s) in enumerate(zip(ranks, suits))]
        self.last = {**combo, 'cards': cards, 'suits': suits, 'special': 'play', 'direct': False}
        self.last_seat = seat; self.passes.clear(); self.play_number += 1
        self.last_voice_play = dict(kind=combo['kind'], ranks=ranks, seat=seat)
        self.display_action(seat, {**self.last, 'order': self.play_number})
        self.announce(self.name(seat) + '：' + combo['kind'] + '。')
        self.turn = self.next_seat(seat)
        self.finish(seat)
        self.resources[seat]['turns'] += 1
        self.end_deal(seat); self.open_priority(); self.enter_turn()

    def resolve(self, seat, ids, **args):
        q = self.pending[0]
        kind, value = q['kind'], args.get('value')
        chosen = []
        if 'cards' in q:
            by_id = {c['id']: c for c in q['cards']}
            if len(set(ids)) != len(ids) or any(i not in by_id for i in ids): raise RuleError('请选择窗口中提供的牌。')
            chosen = [by_id[i] for i in ids]
        self.pending.pop(0)
        if kind == 'split':
            cards = self.select(seat, ids)
            if not cards or len(cards) == len(self.hands[seat]): raise RuleError('两手都必须至少有一张牌。')
            second = next(s for s, p in enumerate(self.players) if p.get('second') and p['owner'] == self.owners[seat])
            self.take(seat, cards, destination=None, mirror=False); self.hands[second] = cards
            self.split.add(seat)
        elif kind == 'blood':
            cards = self.select(seat, ids)
            if len(cards) > 5: raise RuleError('至多选择五张牌。')
            self.take(seat, cards); self.resources[seat]['blood'] = len(cards); self.resources[seat]['bloodReady'] = True
        elif kind == 'discard':
            cards = self.select(seat, ids)
            count = min(q['count'], len(self.hands[seat]))
            if len(cards) != count: raise RuleError('请选择%d张牌。' % count)
            self.take(seat, cards, mirror=q.get('mirror', True)); self.finish(seat)
        elif kind == 'suitmark':
            suit = args.get('suit')
            if suit not in q['suits']: raise RuleError('请选择这手牌包含的花色。')
            target = q['target']
            if target in self.active():
                marks = self.resources[target]['suits']
                marks.append(suit)
                self.announce(self.name(target) + '获得' + SUITS[suit] + '烙印。')
                while len(marks) >= 2:
                    pair = sorted(marks[:2]); del marks[:2]
                    self.suit_effect(target, pair)
        elif kind in ('maximum', 'urgent-max'):
            if len(chosen) != 1 or chosen[0] not in self.maximum(seat): raise RuleError('请选择一张最大牌。')
            self.take(seat, chosen, 'bottom' if kind == 'urgent-max' else 'discard')
            self.announce(self.name(seat) + '弃置' + card_name(chosen[0]) + '。')
            self.finish(seat)
            if kind == 'maximum': self.discard_max(seat, q['left'] - 1)
        elif kind == 'stars':
            if set(ids) != {c['id'] for c in q['cards']}: raise RuleError('请排列全部牌。')
            self.pile = chosen + self.pile
        elif kind == 'clean-main':
            rejected = [c for c in q['cards'] if c['id'] not in ids]
            self.take(seat, rejected, mirror=False)
            self.gain(seat, len(rejected), initial=self.phase == 'draft', mirror=False)
        elif kind == 'retain':
            if len(chosen) > 1: raise RuleError('至多保留一张。')
            self.discard.extend(c for c in q['cards'] if c not in chosen)
            for c in chosen:
                if self.allowed_card(seat, c): self.hands[seat].append(c); self.mirror(seat, 1)
                else: self.discard.append(c); self.gain(seat, 1)
        elif kind in ('reflux', 'buy', 'scavenge'):
            live = {c['id'] for c in self.discard}
            if any(c['id'] not in live for c in chosen): raise RuleError('牌已经被取走。')
            if kind == 'reflux': self.bottom_cards(chosen)
            else:
                if kind == 'buy' and len(chosen) > 1: raise RuleError('每次只能买一张。')
                if kind == 'scavenge':
                    if not chosen: raise RuleError('顺手牵羊至少取一张。')
                    sources = [p for s, p in enumerate(self.seat_plays) if s != seat and p and {c['id'] for c in chosen} <= {c['id'] for c in p['cards']}]
                    if not sources: raise RuleError('必须来自同一名玩家的最近一手。')
                if chosen:
                    if kind == 'buy': self.resources[seat]['money'] -= 4
                    ids_set = set(ids); self.discard = [c for c in self.discard if c['id'] not in ids_set]
                    self.receive(seat, chosen)
                    self.announce(self.name(seat) + ('买入' if kind == 'buy' else '拾取') + '、'.join(map(card_name, chosen)) + '。')
                if kind == 'scavenge': self.skip_action(seat)
        elif kind == 'stash':
            cards = self.select(seat, ids); self.take(seat, cards, 'zone', mirror=False)
        elif kind == 'bond':
            target = args.get('target')
            if target is not None:
                if target not in self.active() or target == seat: raise RuleError('请选择另一名在场玩家。')
                self.bonds.append(dict(owner=seat, seats=[seat, target]))
                self.announce(self.name(seat) + '与' + self.name(target) + '绑定。')
        elif kind == 'duel-start':
            if value:
                self.duel = dict(owner=seat, choices={})
                for s in self.active():
                    if self.hands[s]: self.offer(s, 'duel', '死斗：选择一张牌，全部选择后公开')
        elif kind == 'duel':
            cards = self.select(seat, ids)
            if len(cards) != 1 or cards[0]['rank'] == 18: raise RuleError('请选择一张非急牌。')
            self.duel['choices'][seat] = cards[0]
            if not any(p['kind'] == 'duel' for p in self.pending):
                owner = self.duel['owner']; choices = self.duel['choices']
                self.announce('死斗：' + '；'.join(self.name(s) + ' ' + card_name(c) for s, c in choices.items()) + '。')
                threshold = self.card_value(owner, choices[owner])
                for s, c in choices.items(): self.take(s, [c]); self.finish(s)
                for s, c in choices.items():
                    if s != owner and self.card_value(s, c) <= threshold:
                        remaining = len(self.hands[s])
                        self.discard_max(s, 3 if remaining >= 3 else max(0, remaining - 1))
        elif kind == 'pursuit':
            if not isinstance(value, int) or not 0 <= value <= 10: raise RuleError('请选择零至十张。')
            self.gain(seat, value)
        elif kind == 'deal':
            effect = args.get('effect', 'normal')
            if effect == 'redirect' and self.skill(seat, 'redirect'):
                target = args.get('target')
                if target not in self.active() or target == seat: raise RuleError('请选择另一名玩家。')
                self.gain(target, 1)
            elif effect == 'request' and self.skill(seat, 'request'):
                for target in self.active():
                    if target != seat: self.offer(target, 'give', '窃取：选择交给' + self.name(seat) + '的牌', recipient=seat, count=min(2, len(self.hands[target])))
            elif effect == 'judge' and self.skill(seat, 'trade'):
                card = self.draw_card()
                if not card: raise RuleError('牌堆已耗尽。')
                self.discard.append(card); self.announce('献祭判定：' + card_name(card) + '。')
                self.gain(seat, 1)
                if card['suit'] in ('S', 'C'): self.offer(seat, 'trade-extra', '献祭：额外获得零至十三张', maximum=13)
            else:
                if not isinstance(value, int) or not 1 <= value <= q['maximum']: raise RuleError('发牌数量无效。')
                self.gain(seat, value)
        elif kind == 'trade-extra':
            if not isinstance(value, int) or not 0 <= value <= 13: raise RuleError('请选择零至十三张。')
            self.gain(seat, value)
        elif kind == 'give':
            cards = self.select(seat, ids)
            if len(cards) != min(q['count'], len(self.hands[seat])): raise RuleError('请选择需要交出的牌。')
            self.take(seat, cards, destination=None)
            self.receive(q['recipient'], cards)
            self.announce(self.name(seat) + '交给' + self.name(q['recipient']) + '：' + '、'.join(map(card_name, cards)) + '。')
            self.finish(seat)
        else: raise RuleError('未知选择。')
        if self.phase == 'draft': self.draft_ready()
        if self.phase == 'play' and not self.pending: self.free_lead(); self.enter_turn()

    def bot_action(self, seat):
        if self.pending:
            q = self.pending[0]
            if q['seat'] != seat: return None
            kind = q['kind']; ids = []; args = {}
            hand = sorted(self.hands[seat], key=lambda c: strength(self.effective_rank(seat, c['rank']), self.main))
            if kind in ('split', 'blood', 'discard', 'give', 'duel', 'stash'):
                count = len(hand) // 2 if kind == 'split' else 0 if kind in ('blood', 'stash') else 1 if kind == 'duel' else min(q['count'], len(hand))
                ids = [c['id'] for c in hand if kind != 'duel' or c['rank'] != 18][:count]
            elif kind in ('maximum', 'urgent-max'): ids = [q['cards'][0]['id']]
            elif kind == 'stars': ids = [c['id'] for c in sorted(q['cards'], key=lambda c: -strength(c['rank'], self.main))]
            elif kind == 'scavenge': ids = [q['cards'][0]['id']]
            elif kind == 'clean-main': ids = [c['id'] for c in q['cards']]
            elif kind == 'retain': ids = []
            elif kind == 'suitmark': args = dict(suit=q['suits'][0])
            elif kind == 'deal': args = dict(value=1)
            elif kind in ('pursuit', 'trade-extra'): args = dict(value=0)
            elif kind == 'duel-start': args = dict(value=False)
            return dict(action='choice', ids=ids, **args)
        if self.phase == 'draft':
            if self.players[seat].get('second') or seat in self.drafted: return None
            keep = self.keep_counts[seat] // 2 if self.skill(seat, 'twins') else self.keep_counts[seat]
            # Preserve groups, controls and easy urgent exits in the opening hand.
            counts = Counter(self.effective_rank(seat, c['rank']) for c in self.hands[seat])
            chosen = sorted(self.hands[seat], key=lambda c: (counts[self.effective_rank(seat, c['rank'])], strength(self.effective_rank(seat, c['rank']), self.main)), reverse=True)[:keep]
            return dict(action='keep', ids=[c['id'] for c in chosen])
        if self.phase == 'setup':
            if seat in self.rps: return None
            if self.first is None and not self.skill(seat, 'scavenge') and seat not in self.reveals and any(c['rank'] == 3 and c['suit'] == 'S' for c in self.hands[seat]): return {'action':'reveal'}
            return {'action':'confirm'}
        if self.phase == 'rps': return super().bot_action(seat)
        if self.phase != 'play' or seat in self.finished: return None
        if seat == self.turn:
            if self.resources[seat]['ban'] or self.skill(seat, 'scavenge') and self.resources[seat]['turns'] < 2: return {'action':'pass'}
            urgent = next((c for c in self.hands[seat] if c['rank'] == 18), None)
            if urgent:
                if self.urgent_uses.get(urgent['id'], 0) >= 3: return dict(action='urgent', ids=[urgent['id']], effect='rotate')
                others = sorted((s for s in self.active() if self.owners[s] % 2 != self.owners[seat] % 2), key=lambda s: len(self.hands[s]))
                if 1 < len(self.hands[seat]) <= 3:
                    return dict(action='urgent', ids=[urgent['id']] + [c['id'] for c in self.hands[seat] if c['rank'] != 18][:len(self.hands[seat])-2], effect='discard')
                if others: return dict(action='urgent', ids=[urgent['id']], effect='ban', target=others[0])
            if self.skill(seat, 'stash') and self.zones[seat] and len(self.hands[seat]) < 3:
                return dict(action='skill', effect='retrieve', ids=[c['id'] for c in self.zones[seat]])
            hand = self.hands[seat]
            key = self.skills[seat]
            normal_moves = self.candidates(seat)
            if key == 'seven':
                marks = self.resources[seat].get('marks', 0)
                storable = [c for c in hand if c['rank'] in (3, 4, 5, 6)][:7-marks]
                if storable: return dict(action='skill', effect='store', ids=[c['id'] for c in storable])
                if marks == 7 and (not self.last or self.last.get('special') not in ('cross', 'hook')):
                    for start in range(3, 9):
                        ranks = list(range(start, start + 7))
                        combo = classifications(ranks, 'standard', self.main)[0]
                        old = self.last
                        if not old or old.get('direct') and self.last_seat == seat or not old['power'] and old.get('baseKind', old['kind']) == '顺子' and old['n'] == 7 and combo['value'] > old['value']:
                            return dict(action='skill', effect='release', ranks=ranks)
            if key == 'ascend' and self.resources[seat]['boost'] < 3:
                twos = [c for c in hand if c['rank'] == 15]
                if twos: return dict(action='skill', ids=[twos[0]['id']])
            targets = [s for s in self.active() if self.owners[s] % 2 != self.owners[seat] % 2]
            if key == 'pressure' and targets and self.can_draw(4):
                twos = [c for c in hand if c['rank'] == 15]
                target = min(targets, key=lambda s: len(self.hands[s]))
                if twos and (len(self.hands[target]) <= 5 or len(hand) == 1): return dict(action='skill', ids=[twos[0]['id']], target=target)
            if not normal_moves and self.last:
                if key == 'balance':
                    counts = Counter(c['rank'] for c in hand)
                    swap = sorted((c for c in hand if counts[c['rank']] == 1), key=lambda c: strength(c['rank'], self.main))[:3]
                    if swap and self.can_draw(len(swap)): return dict(action='skill', ids=[c['id'] for c in swap])
                if key == 'gift' and targets and self.can_draw(2):
                    card = min(hand, key=lambda c: strength(c['rank'], self.main))
                    return dict(action='skill', ids=[card['id']], target=max(targets,key=lambda s:len(self.hands[s])))
            if self.skill(seat, 'judgment') and self.last and not self.candidates(seat) and self.higher_combos() and self.can_draw(1): return dict(action='skill')
        if self.priority:
            group = 'bots' if self.players[seat].get('bot') else 'pending'
            if seat in self.priority[group] and (not self.priority['pending'] or group == 'pending' and self.players[seat].get('autoplay')):
                moves = self.priority_moves(seat)
                if moves:
                    best = min(moves, key=lambda m: (m['power'], -m['n'], m['value']))
                    return {**best, 'action':'auto'}
                return dict(action='priority-decline')
        if seat != self.turn: return None
        moves = self.candidates(seat)
        if not moves: return dict(action='pass')
        counts = Counter(c['rank'] for c in self.hands[seat])
        def cost(move):
            left = [c for c in self.hands[seat] if c['id'] not in move['ids']]
            remaining = Counter(c['rank'] for c in left)
            split = sum(2 for r, n in remaining.items() if n < counts[r])
            return (bool(left or self.zones[seat]), len(remaining) * 6 + split + move['power'] * .6 + move['value'] * .08 - move['n'])
        return min(moves, key=cost)

    def snapshot(self):
        state = super().snapshot()
        for key in ('pile', 'discard', 'destroyed', 'urgent_uses', 'zones', 'resources', 'pending', 'bonds', 'complete_owners', 'suit_lead', 'lead_key', 'start_turn'):
            state[key] = copy.deepcopy(getattr(self, key))
        return state


class ConveyorGame:
    """Translate four account seats to independent internal actors (twins = two)."""
    def __init__(self, mode, players, options=None, previous=None, interactive=True):
        self.players = players
        self.mode = 'conveyor'
        self.options = {**(options or {}), 'tribute':False, 'dlc':False}
        choices = {s['id'] for s in available(self.options)}
        chosen = [p.get('skill') for p in players]
        if len(set(chosen)) != 4 or any(s not in choices for s in chosen): raise RuleError('每位玩家须选择一个不同且已启用的技能。')
        actors = []
        for owner, p in enumerate(players):
            actors.append({**p, 'owner':owner})
            if p['skill'] == 'twins':
                actors[-1]['name'] += ' · 1'
                actors.append({**p, 'owner':owner, 'name':p['name'] + ' · 2', 'second':True})
        prev = copy.deepcopy(previous)
        if prev and prev.get('first') is not None:
            prev['first'] = next(s for s, p in enumerate(actors) if p['owner'] == prev['first'])
        self.core = ConveyorRound(actors, self.options, prev, interactive)
        self.focus = {o: next(s for s, p in enumerate(actors) if p['owner'] == o) for o in range(4)}

    def __getattr__(self, key):
        core = self.__dict__.get('core')
        if core is None: raise AttributeError(key)
        if key == 'turn': return core.owners[core.turn]
        if key == 'finished': return core.complete_owners
        if key == 'winner': return sorted({core.owners[s] for s in core.winner}) if core.winner else core.winner
        if key == 'last_seat': return core.owners[core.last_seat] if core.last_seat is not None else None
        if key == 'priority':
            if not core.priority: return None
            return {k:sorted({core.owners[s] for s in v}) for k, v in core.priority.items()}
        if key == 'negotiation':
            return {**core.negotiation, 'target':core.owners[core.negotiation['target']], 'seat':core.owners[core.negotiation['seat']]} if core.negotiation else None
        return getattr(core, key)

    @property
    def phase(self): return self.core.phase
    @phase.setter
    def phase(self, value): self.core.phase = value
    @property
    def winner(self): return sorted({self.core.owners[s] for s in self.core.winner}) if self.core.winner else self.core.winner
    @winner.setter
    def winner(self, value): self.core.winner = [s for s, o in enumerate(self.core.owners) if o in value]

    def sync_players(self):
        for p in self.core.players:
            source = self.players[p['owner']]
            for key in ('bot', 'autoplay', 'connected'): p[key] = source.get(key, False)

    def actor(self, seat, requested=None):
        candidates = [s for s, o in enumerate(self.core.owners) if o == seat]
        if requested is not None:
            if requested not in candidates: raise RuleError('不能操作其他玩家的手牌。')
            return requested
        if self.core.pending and self.core.pending[0]['seat'] in candidates: return self.core.pending[0]['seat']
        if self.core.turn in candidates: return self.core.turn
        return self.focus[seat]

    def action(self, seat, action, ids=None, actor=None, **args):
        self.sync_players()
        selected = self.actor(seat, actor)
        if action == 'focus': self.focus[seat] = selected; return
        state = copy.deepcopy(self.core.__dict__)
        try:
            self.core.action_reports = []; self.core.action_gains = []
            old_turn = self.core.turn
            if action == 'confirm' and self.core.phase == 'setup':
                for target, owner in enumerate(self.core.owners):
                    if owner == seat and target not in self.core.rps: self.core.action(target, action, ids, **args)
            else: self.core.action(selected, action, ids, **args)
            self.focus[seat] = selected
            if old_turn != self.core.turn: self.focus[self.core.owners[self.core.turn]] = self.core.turn
        except (RuleError, ValueError, TypeError, KeyError, IndexError) as e:
            self.core.__dict__ = state
            if isinstance(e, RuleError): raise
            raise RuleError('技能参数无效，请重新选择。') from e

    def candidates(self, seat):
        actor = self.actor(seat, self.focus[seat])
        return [{**m, 'actor':actor} for m in self.core.candidates(actor)]

    def priority_moves(self, seat):
        return [m for m in self.candidates(seat) if m['action'] in SPECIALS]

    def priority_paused(self):
        self.sync_players()
        return self.core.priority_paused()

    def forced_pass(self): return self.core.forced_pass()
    def solo(self): return self.core.solo()

    def bot_action(self, seat):
        self.sync_players()
        actors = [s for s, o in enumerate(self.core.owners) if o == seat]
        if self.core.priority: actors.sort(key=lambda s: s not in self.core.priority['pending'])
        for actor in actors:
            move = self.core.bot_action(actor)
            if move: return {**move, 'actor':actor}
        return None

    def view(self, seat):
        self.sync_players()
        actor = self.actor(seat, self.focus[seat]) if seat is not None else None
        if seat is not None and self.core.pending and self.core.owners[self.core.pending[0]['seat']] == seat: actor = self.core.pending[0]['seat']
        if seat is not None and self.core.priority and actor not in self.core.priority['pending']:
            actor = next((s for s in self.core.priority['pending'] if self.core.owners[s] == seat), actor)
        view = self.core.view(actor)
        c = self.core
        view.update(mode='conveyor', turn=c.owners[c.turn], finished=c.complete_owners, winner=self.winner,
                    counts=[sum(len(h) for s, h in enumerate(c.hands) if c.owners[s] == o) for o in range(4)],
                    initialCounts=[sum(n for s, n in enumerate(c.initial_counts) if c.owners[s] == o) for o in range(4)],
                    remainingHands=[sum((h for s, h in enumerate(c.hands) if c.owners[s] == o), []) for o in range(4)] if c.phase == 'over' else None,
                    seatPlays=[next((c.seat_plays[s] for s in reversed(range(len(c.players))) if c.owners[s] == o and c.seat_plays[s]), None) for o in range(4)],
                    reveals=list(dict.fromkeys(c.owners[s] for s in c.reveals)), ready=list(dict.fromkeys(c.owners[s] for s in c.rps)),
                    openingFirst=c.owners[c.first] if c.first is not None else None, priority=self.priority, negotiation=self.negotiation)
        if view['response']: view['response']['key'] = str(actor) + '/' + str(view['response']['key'])
        view['hand'] = [{**card, 'effective':c.effective_rank(actor, card['rank']), 'urgentUses':c.urgent_uses.get(card['id'], 0)} for card in view['hand']] if actor is not None else []
        q = c.pending[0] if c.pending else None
        own_q = q if q and seat is not None and c.owners[q['seat']] == seat else None
        view['conveyor'] = dict(actor=actor, turnActor=c.turn, skill=c.skills[actor] if actor is not None else None,
            pile=len(c.pile), discard=len(c.discard), drafted=actor in c.drafted if actor is not None else False,
            keep=min(c.keep_counts[actor] // 2 if c.skill(actor, 'twins') else c.keep_counts[actor], len(c.hands[actor])) if actor is not None else 0,
            zone=copy.deepcopy(c.zones[actor]) if actor is not None else [],
            resources=copy.deepcopy(c.resources[actor]) if actor is not None else None, destroyed=len(c.destroyed),
            actors=[dict(id=s, owner=o, confirmed=s in c.rps, drafted=s in c.drafted, name=c.name(s), count=len(c.hands[s]), initialCount=c.initial_counts[s], zoneCount=len(c.zones[s]),
                         finished=s in c.finished, skill=c.skills[s], boundTo=[c.name(target) for bond in c.bonds if s in bond['seats'] for target in bond['seats'] if target != s], resources={k:v for k,v in c.resources[s].items() if k not in ('markCards',)}, play=c.seat_plays[s]) for s, o in enumerate(c.owners)],
            choice=copy.deepcopy(own_q), waiting=c.name(q['seat']) if q else None, waitingActor=q['seat'] if q else None,
            remainingActorHands=[copy.deepcopy(h) for h in c.hands] if c.phase == 'over' else None,
            boundHands=[dict(name=c.name(s), cards=copy.deepcopy(c.hands[s])) for b in c.bonds if actor in b['seats'] for s in b['seats'] if s != actor] if actor is not None else [])
        if own_q is None and q:
            view['response'] = None
        if actor is not None and c.players[actor].get('second'): view['conveyor']['drafted'] = True
        return view
