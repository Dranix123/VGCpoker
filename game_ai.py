"""Legal decisions shared by simulated games and room bots."""

import copy
import json
from collections import Counter
from engine import RANKS
from conveyor_skills import SKILLS


MAX_MOVES = 40
MOVE_FIELDS = {
    'action', 'ids', 'value', 'rank', 'target', 'wildcard', 'special', 'effect',
    'direction', 'double', 'ranks', 'suits', 'suit',
}
GOALS = {
    'landlord': '斗地主。地主先出完则地主胜，任一农民先出完则农民共同获胜。根据你的身份争胜。',
    'basic': '4A4。与对家组队，帮助本队最先有人出完，再争取让对家尽早出完以多升级。',
    'standard': '4A4A4。与对家组队，帮助本队最先有人出完，再争取让对家尽早出完以多升级。',
    'trio': '三人 4A4A4。个人竞赛，先出完自己的手牌获胜。',
    'conveyor': '传送带。各自为战，尽早出完手牌及展示区的未出牌。第三次行动起才能走完。'
                '第一名升两级，第二名升一级。如影随形任一身份先走完即完成。',
}
MODEL_INSTRUCTIONS = (
    '按 goal 争胜。独立判断当前局面，参考 recentRounds 中按时间排列的最近三个完整牌权回合。'
    '从 moves 选择一个编号，返回 {"index":0}。'
    '选牌、排序、发动技能或指定赖子也可以返回 {"move":{...}}，'
    '动作名取自 moveTypes，牌用实际牌 ID，target 用身份编号。'
    '守望的 ids 按牌堆从顶到底排列。回收和聚宝的空 ids 表示放弃。'
    'hand 是当前身份的全部手牌。你可以保留某些牌，选择对子、顺子等组合来规划后续行动。'
    'otherOwnHands 是同账号的另一个身份，仅供规划。提交动作时使用当前身份的牌。'
    'play 和 auto 可给 wildcard（牌 ID 到点数或 {rank,suit} 的映射）或 double（{id,ranks,suits}）。'
    '技能使用 action=skill，技能窗口使用 action=choice。'
    '若要自选牌、排列牌或挑目标，沿用同类候选的字段，按实际牌 ID 或座位 ID 替换。'
    '技能和待选窗口按说明操作，动作必须符合牌桌规则。'
)


def move_args(move):
    return {key: value for key, value in move.items() if key in MOVE_FIELDS
            and (key != 'value' or move['action'] in ('bid', 'rps', 'choice'))}


def decode_selection(content, count):
    result = json.loads(content)
    if isinstance(result, dict) and set(result) == {'move'} and isinstance(result['move'], dict):
        return result['move']
    index = result.get('index') if isinstance(result, dict) else None
    if type(index) is not int or not 0 <= index < count:
        raise ValueError('invalid_move_index')
    return index


def card_selections(cards, minimum, maximum):
    """Represent each legal size and each single-card choice without expanding all subsets."""
    ids = [card['id'] for card in cards]
    maximum = min(maximum, len(ids))
    for size in range(minimum, maximum + 1):
        if size == 1:
            yield from ([card_id] for card_id in ids)
        else:
            yield ids[:size]
            if 0 < size < len(ids):
                yield ids[-size:]


def choice_moves(core, actor, choice):
    kind = choice['kind']
    hand = sorted(core.hands[actor], key=lambda c: core.card_value(actor, c))
    cards = choice.get('cards', hand)
    size = len(cards)
    if kind == 'stars':
        ids = [card['id'] for card in cards]
        yield dict(action='choice', ids=ids)
        yield dict(action='choice', ids=list(reversed(ids)))
        for i in range(1, len(ids)):
            yield dict(action='choice', ids=[ids[i], *ids[:i], *ids[i+1:]])
    elif kind == 'suitmark':
        for suit in choice['suits']:
            yield dict(action='choice', suit=suit)
    elif kind == 'bond':
        if not choice.get('required'):
            yield dict(action='choice')
        for target in core.active():
            if core.owners[target] != core.owners[actor]:
                yield dict(action='choice', target=target)
    elif kind in ('deal', 'pursuit', 'duel-start'):
        values = range(1, choice['maximum'] + 1) if kind == 'deal' else range(11) if kind == 'pursuit' else (False, True)
        for value in values:
            yield dict(action='choice', value=value)
        skill = choice.get('skill')
        if kind == 'deal' and skill in ('trade', 'request'):
            yield dict(action='choice', effect='judge' if skill == 'trade' else 'request')
        if kind == 'deal' and skill == 'redirect':
            for target in core.active():
                if target != actor:
                    yield dict(action='choice', effect='redirect', target=target)
    elif kind == 'scavenge':
        live_ids = {card['id'] for card in cards}
        for other, play in enumerate(core.seat_plays):
            if other != actor and play:
                subset = [card for card in play['cards'] if card['id'] in live_ids]
                for ids in card_selections(subset, 1, choice['maximum']):
                    yield dict(action='choice', ids=ids)
    else:
        if kind in ('maximum', 'urgent-max', 'duel'):
            low = high = 1
        elif kind in ('discard', 'give'):
            low = high = min(choice['count'], size)
        elif kind == 'split':
            low, high = 1, size - 1
        else:
            low = 0
            high = 1 if kind in ('retain', 'buy') else choice.get('maximum', size)
        for ids in card_selections(cards, low, high):
            yield dict(action='choice', ids=ids)


def skill_moves(core, actor, ordinary):
    key = core.active_skill(actor)
    if core.resources[actor]['ban'] or actor in core.finished:
        return
    hand = sorted(core.hands[actor], key=lambda card: core.card_value(actor, card))
    targets = [seat for seat in core.active() if seat != actor]
    if key == 'pressure':
        for card in hand:
            if core.effective_rank(actor, card['rank']) == 15:
                if any(q['kind'] == 'duel' for q in core.pending) and card in core.duel['choices'].values():
                    continue
                for target in targets:
                    if core.can_draw(core.draw_limit(target, 4)):
                        yield dict(action='skill', ids=[card['id']], target=target)
    if actor != core.turn or core.pending:
        return
    if key == 'balance':
        counts = Counter(card['rank'] for card in hand)
        ordered = sorted(hand, key=lambda card: counts[card['rank']])
        maximum = min(len(core.pile), core.draw_limit(actor, len(hand)))
        for ids in card_selections(ordered, 1, maximum):
            yield dict(action='skill', ids=ids)
    elif key == 'gift' and core.can_draw(core.draw_limit(actor, 2)):
        for target in targets:
            for card in hand:
                yield dict(action='skill', ids=[card['id']], target=target)
    elif key == 'stash':
        for ids in card_selections(core.zones[actor], 1, len(core.zones[actor])):
            yield dict(action='skill', effect='retrieve', ids=ids)
    elif key == 'scavenge' and core.last:
        yield dict(action='skill')
    elif key == 'ascend':
        twos = [card for card in hand if card['rank'] == 15]
        for ids in card_selections(twos, 1, len(twos)):
            yield dict(action='skill', ids=ids)
    elif key == 'seven':
        marks = core.resources[actor].get('marks', 0)
        small = [card for card in hand if card['rank'] in (3, 4, 5, 6)]
        for ids in card_selections(small, 1, 7 - marks):
            yield dict(action='skill', effect='store', ids=ids)
        if marks == 7:
            for start in range(3, 9):
                yield dict(action='skill', effect='release', ranks=list(range(start, start + 7)))
    elif key == 'judgment' and not ordinary and core.pile and core.higher_combos():
        yield dict(action='skill')
    elif key == 'trade':
        for card in hand:
            rank = core.effective_rank(actor, card['rank'])
            count = 5 if rank in (16, 17) else 4 if rank == core.main else 3 if rank == 15 else 0
            if count and core.can_draw(core.draw_limit(actor, count)):
                yield dict(action='skill', ids=[card['id']])
    elif key == 'bond':
        yield dict(action='skill')


def urgent_moves(core, actor, conveyor):
    hand = core.hands[actor]
    for card in hand:
        rank = core.effective_rank(actor, card['rank']) if conveyor else card['rank']
        wild = (card['rank'] == 14 and card['suit'] == 'S' and
                not (conveyor and core.skill(actor, 'wild')))
        if rank != 18 and not wild:
            continue
        card_id = card['id']
        declaration = {'wildcard': {card_id: 18}} if wild else {}
        targets = [s for s in range(len(core.players)) if s not in core.finished]
        other_cards = [c for c in hand if c != card and (core.effective_rank(actor, c['rank']) if conveyor else c['rank']) != 18]
        if not conveyor:
            for target in targets:
                if target != actor:
                    for gift in other_cards:
                        yield dict(action='urgent', ids=[card_id, gift['id']], target=target, **declaration)
            continue
        for direction in ('counterclockwise', 'clockwise'):
            yield dict(action='urgent', ids=[card_id], effect='rotate', direction=direction, **declaration)
        if core.urgent_uses.get(card_id, 0) >= 3:
            continue
        for effect in ('shield', 'judge-boost', 'judge-color'):
            yield dict(action='urgent', ids=[card_id], effect=effect, **declaration)
        for effect in ('draw', 'ban', 'maximum', 'silence'):
            for target in targets:
                yield dict(action='urgent', ids=[card_id], effect=effect, target=target, **declaration)
        for ids in card_selections(other_cards, 0, min(2, len(hand) - 2)):
            yield dict(action='urgent', ids=[card_id, *ids], effect='discard', **declaration)


def bot_turn_order(game):
    seats = list(range(len(game.players)))
    if game.mode == 'conveyor' and game.phase == 'play' and not game.core.pending and not game.core.priority:
        seats.remove(game.turn)
        seats.append(game.turn)
    return seats


def reaction_move(core, seat):
    if (seat not in core.active() or core.owners[seat] == core.owners[core.turn]
            or core.pending or core.priority or core.resources[seat]['ban']
            or core.ai_reactions.get(seat) == core.reaction_key()):
        return None
    if core.ai_model_reactions or core.players[seat].get('model'):
        if (next(skill_moves(core, seat, []), None)
                or next(urgent_moves(core, seat, True), None)):
            return {'action': 'reaction-decline'}
    elif len(core.hands[core.turn]) <= 2 and not core.resources[core.turn]['ban']:
        for move in skill_moves(core, seat, []):
            if move.get('target') == core.turn:
                return move
        for move in urgent_moves(core, seat, True):
            if move.get('effect') == 'ban' and move['target'] == core.turn and 'wildcard' not in move:
                return move
    return None


def alternatives(game, core, actor, fallback):
    moves = [fallback]
    phase = core.phase
    pending = getattr(core, 'pending', [])
    if pending:
        moves.extend(choice_moves(core, actor, pending[0]))
        if game.mode == 'conveyor' and phase == 'play' and core.skill(actor, 'pressure'):
            moves.extend(skill_moves(core, actor, []))
    elif phase == 'draft':
        keep = len(fallback.get('ids', ()))
        for ids in card_selections(core.visible_hand(actor), keep, keep):
            moves.append(dict(action='keep', ids=ids))
    elif phase == 'tribute':
        if fallback['action'] == 'tribute-pick':
            moves.extend(dict(action='tribute-pick', target=o['donor'])
                         for o in core.tribute['offers'] if o['recipient'] is None)
        else:
            moves.extend(dict(action='tribute-return', ids=[c['id']]) for c in core.visible_hand(actor))
    elif phase == 'setup':
        moves.append(dict(action='confirm'))
        if core.can_reveal(actor) and actor not in core.reveals:
            moves.append(dict(action='reveal'))
        if game.mode not in ('landlord', 'basic', 'conveyor') and actor not in core.promotions:
            moves.extend(dict(action='promote', rank=rank) for rank in RANKS
                         if sum(c['rank'] == rank for c in core.hands[actor]) >= 6 and rank != core.main)
    elif phase == 'bid':
        moves.extend(dict(action='bid', value=n) for n in [0, *range(core.bid + 1, 4)])
    elif phase == 'rps':
        moves.extend(dict(action='rps', value=v) for v in ('rock', 'paper', 'scissors'))
    elif phase == 'play':
        if game.mode == 'conveyor' and core.resources[actor]['ban']:
            return moves
        if game.mode == 'conveyor' and core.must_scavenge(actor):
            return moves
        priority = core.priority
        if priority and (actor in priority['bots'] or actor in priority['pending']):
            moves.append(dict(action='priority-decline'))
            moves.extend({**m, 'action':'priority-play', 'special':m['action']} for m in core.priority_moves(actor))
            if game.mode == 'conveyor' and actor != core.turn:
                moves.extend(skill_moves(core, actor, []))
                moves.extend(urgent_moves(core, actor, game.mode == 'conveyor'))
        if actor == core.turn and (not priority or not core.priority_paused()):
            ordinary = core.candidates(actor)
            if rules_can_pass(core, actor):
                moves.append(dict(action='pass'))
            if game.mode == 'conveyor':
                moves.extend(skill_moves(core, actor, ordinary))
            if game.mode in ('standard', 'trio', 'conveyor'):
                moves.extend(urgent_moves(core, actor, game.mode == 'conveyor'))
            moves.extend(ordinary)
        elif game.mode == 'conveyor' and fallback['action'] == 'reaction-decline':
            moves.extend(skill_moves(core, actor, []))
            moves.extend(urgent_moves(core, actor, game.mode == 'conveyor'))
        elif game.mode == 'conveyor' and fallback['action'] in ('urgent', 'skill'):
            if fallback['action'] == 'urgent':
                moves.extend(urgent_moves(core, actor, game.mode == 'conveyor'))
            else:
                moves.extend(skill_moves(core, actor, []))
    # Keep diversity when many card IDs lead to the same kind of decision.
    groups, seen = {}, set()
    for move in moves:
        key = json.dumps(move_args(move), sort_keys=True)
        if key not in seen:
            seen.add(key)
            group = (move['action'], move.get('effect'), move.get('special'))
            groups.setdefault(group, []).append(move)
    return [group[i] for i in range(MAX_MOVES) for group in groups.values() if i < len(group)][:MAX_MOVES]


def rules_can_pass(core, actor):
    return bool(core.last and core.last_seat != actor)


def rule_choice(core, actor, choice, fallback):
    kind = choice['kind']
    cards = choice.get('cards', [])
    if kind == 'reflux' and cards:
        if len(core.pile) < len(core.active()):
            return dict(action='choice', ids=[card['id'] for card in cards])
        if len(core.hands[actor]) >= 5:
            card = min(cards, key=lambda c: core.card_value(actor, c))
            return dict(action='choice', ids=[card['id']])
    if kind == 'buy' and cards and core.resources[actor]['money'] >= 4:
        hand = core.hands[actor]
        card = max(cards, key=lambda c: (sum(h['rank'] == c['rank'] for h in hand), core.card_value(actor, c)))
        if any(h['rank'] == card['rank'] for h in hand) or core.card_value(actor, card) >= 15:
            return dict(action='choice', ids=[card['id']])
    if kind == 'retain' and cards:
        return dict(action='choice', ids=[max(cards, key=lambda c: core.card_value(actor, c))['id']])
    if kind == 'duel-start' and any(core.card_value(actor, c) >= 15 for c in core.hands[actor]):
        return dict(action='choice', value=True)
    if kind == 'duel' and core.hands[actor]:
        card = max(core.hands[actor], key=lambda c: core.card_value(actor, c))
        return dict(action='choice', ids=[card['id']])
    if kind == 'stash' and not core.zones[actor] and len(core.hands[actor]) >= 6:
        card = min(core.hands[actor], key=lambda c: core.card_value(actor, c))
        return dict(action='choice', ids=[card['id']])
    if kind == 'deal':
        targets = [seat for seat in core.active() if core.owners[seat] != core.owners[actor]]
        if choice.get('skill') == 'redirect' and targets:
            target = min(targets, key=lambda seat: len(core.hands[seat]))
            return dict(action='choice', effect='redirect', target=target)
        if choice.get('skill') == 'request' and targets and all(len(core.hands[seat]) >= 6 for seat in targets):
            if len(core.hands[actor]) <= 2:
                return dict(action='choice', effect='request')
    return fallback


def model_context(game, core, actor, moves):
    owners = getattr(core, 'owners', list(range(len(core.players))))
    teammates = []
    if game.mode in ('basic', 'standard'):
        teammates = [(actor + 2) % len(owners)]
    elif game.mode == 'landlord' and core.landlord is not None and actor != core.landlord:
        teammates = [s for s in range(len(owners)) if s not in (core.landlord, actor)]
    goal = GOALS[game.mode]
    if game.mode == 'conveyor' and game.options.get('firstOutEndsRound'):
        goal += '本桌首位走完即结算，由第一名升两级。'
    context = dict(goal=goal, recentRounds=[round_actions[:] for round_actions in core.ai_recent_rounds],
                   currentRound=core.ai_current_round[:],
                   mode=game.mode, phase=core.phase, turn=core.turn, actor=actor, player=owners[actor],
                   teammates=teammates, main=core.main, landlord=core.landlord, bid=core.bid, last=core.last,
                   lastActor=core.last_seat, recentPlays=core.seat_plays, scores=core.scores,
                   players=[dict(actor=i, owner=owners[i], count=len(h), finished=i in core.finished)
                            for i, h in enumerate(core.hands)],
                   hand=core.visible_hand(actor), moves=moves, moveTypes=sorted(move_types(moves)))
    if game.mode == 'landlord' and core.phase == 'play':
        context['bottom'] = core.bottom
    if game.mode == 'conveyor':
        pending = core.pending[0] if core.pending and core.pending[0]['seat'] == actor else None
        context.update(skill=SKILLS[core.skills[actor]], pile=len(core.pile), zone=core.zones[actor], choice=pending,
                       otherOwnHands=[dict(actor=i, hand=core.visible_hand(i), zone=core.zones[i])
                                      for i, owner in enumerate(owners) if owner == owners[actor] and i != actor],
                       publicSkills=[SKILLS[key]['name'] for key in core.skills],
                       resources={k: v for k, v in core.resources[actor].items() if k != 'markCards'},
                       boundHands=[dict(actor=target, hand=core.visible_hand(target), zone=core.zones[target])
                                   for bond in core.active_bonds() if actor in bond['seats']
                                   for target in bond['seats'] if target != actor],
                       firstOutEndsRound=game.options.get('firstOutEndsRound', False))
    return context


def move_types(moves):
    actions = {move['action'] for move in moves}
    if actions & {'play', 'hui', 'cross', 'hook', 'dot', 'press', 'dead', 'dead4', 'priority-play'}:
        actions.add('auto')
    return actions


def select_model_move(game, seat, actor, moves, selection):
    move = moves[selection] if type(selection) is int and 0 <= selection < len(moves) else selection
    if not isinstance(move, dict) or move.get('action') not in move_types(moves):
        raise ValueError('invalid_move_action')
    if isinstance(selection, dict) and set(selection) - MOVE_FIELDS:
        raise ValueError('invalid_move_fields')
    args = move_args(move)
    ids = args.get('ids', [])
    if not isinstance(ids, list) or len(ids) > 128 or not all(isinstance(i, str) for i in ids):
        raise ValueError('invalid_move_cards')
    probe = copy.deepcopy(game)
    if game.mode == 'conveyor':
        probe.action(seat, actor=actor, **args)
    else:
        probe.action(seat, **args)
    return move
