import unittest
import itertools
from collections import Counter
from unittest.mock import patch
from engine import Game, MODES, RuleError, classify, deck, interpretations


def cards(ranks, suit='H', prefix='c'):
    return [{'id': prefix + str(i), 'rank': r, 'suit': suit} for i, r in enumerate(ranks)]


def table(mode='standard', options=None):
    g = Game(mode, [{'name': str(i)} for i in range(MODES[mode])], options)
    g.phase = 'play'
    g.hands = [cards([6, 7, 8, 9, 10], prefix=str(i)) for i in range(MODES[mode])]
    return g


class Rules(unittest.TestCase):
    def test_alternate_pattern_is_limited_to_selected_game(self):
        g=table(options={'_alternate':True,'advancedHui':True})
        g.hands[0]=cards([6,6,6,8,8,9],prefix='a')
        self.assertEqual(g.pattern,(6,8))
        combo=g.validate_play(0,g.hands[0][:5])[0]
        self.assertEqual((combo['kind'],combo['power']),('4A4',105))
        self.assertEqual(g.validate_play(0,cards([4,4,4,14,14]))[0]['power'],0)
        self.assertTrue(any(m['power']==105 and set(m['ids'])=={'a'+str(i) for i in range(5)} for m in g.candidates(0)))
        g.action(0,'auto',['a'+str(i) for i in range(5)]);self.assertEqual(g.last['power'],105)
        self.assertNotIn('_alternate',g.view(0)['options'])
        normal=table();self.assertEqual(normal.validate_play(0,cards([6,6,6,8,8]))[0]['power'],0)
        self.assertEqual(normal.validate_play(0,cards([4,4,4,14,14]))[0]['power'],105)

    def test_alternate_pattern_wildcards_and_core_ranking(self):
        g=table(options={'_alternate':True,'advancedHui':True})
        chosen=cards([6,6,8,8],prefix='a')+cards([14],'S','w')
        g.hands[0]=chosen+cards([10],prefix='z')
        self.assertEqual(g.validate_play(0,chosen,wildcard=6)[0]['power'],105)
        self.assertTrue(any(m['power']==105 and set(m['ids'])=={c['id'] for c in chosen} for m in g.candidates(0)))
        self.assertEqual(g.validate_play(0,cards([6]*5+[8]*2))[0]['power'],105)
        self.assertEqual(g.validate_play(0,cards([6]*4+[8]*3))[0]['power'],107)
        g.hands[0]=cards([8,8,10],'H','a');g.hands[3]=cards([5,5,9],'H','b')
        g.action(0,'play',['a0','a1']);g.action(3,'hui',['b0','b1']);self.assertEqual(g.last['special'],'hui')

    def test_next_deal_extra_cards_go_to_first_finisher_and_next_seat(self):
        for mode in ('basic', 'standard'):
            for first in range(4):
                g = Game(mode, [{'name': str(i)} for i in range(4)], previous={'first': first})
                minimum = len(g.cards) // 4
                expected = [minimum] * 4
                expected[first] += 1
                expected[(first - 1) % 4] += 1
                self.assertEqual(g.initial_counts, expected)
                self.assertEqual(sum(g.initial_counts), len(g.cards))
        self.assertEqual(Game('basic', [{'name': str(i)} for i in range(4)]).initial_counts, [14,14,13,13])

    def test_4a4a4_level_counts_only_complete_core(self):
        for mode in ('standard','trio'):
            core=classify([4]*3+[14]*2,mode)
            for extra in (1,2,5):
                combo=classify([4]*(3+extra)+[14]*2,mode)
                self.assertEqual((combo['power'],combo['value']),(core['power'],core['value']))
            self.assertGreater(classify([4]*4+[14]*3,mode)['power'],core['power'])
            self.assertIsNone(classify([4]*2+[14]*2,mode))
            g=table(mode);g.hands[0]=cards([4]*3+[14]*2+[8],prefix='a');g.hands[-1]=cards([4]*5+[14]*2+[9],prefix='d')
            g.action(0,'auto',['a'+str(i) for i in range(5)])
            with self.assertRaises(RuleError):g.action(len(g.players)-1,'auto',['d'+str(i) for i in range(7)])

    def test_main_rank_participates_in_sequences(self):
        for mode in ('basic','standard','trio'):
            for ranks,kind in (([3,4,5,6,7],'顺子'),([3,3,4,4,5,5],'连对'),([3]*3+[4]*3,'飞机')):
                self.assertEqual(classify(ranks,mode,3)['kind'],kind)
                g=table(mode);g.hands[0]=cards(ranks+[12],prefix='a')
                ids=[c['id'] for c in g.hands[0][:-1]]
                self.assertTrue(any(set(m['ids'])==set(ids) for m in g.candidates(0)))
                g.action(0,'auto',ids);self.assertEqual(g.last['kind'],kind)

    def test_tribute_is_opt_in_and_disabled_for_alternate_rooms(self):
        players=[{'name':str(i)} for i in range(4)]
        previous={'first':0,'main':5,'scores':[2,0],'captured':[1,3]}
        for mode in ('basic','standard'):
            for options in ({},{'tribute':False},{'tribute':True,'_alternate':True}):
                g=Game(mode,players,options=options,previous=previous)
                self.assertEqual(g.phase,'setup');self.assertIsNone(g.tribute)
                self.assertEqual([len(h) for h in g.hands],g.initial_counts)

    def test_tribute_single_and_double_before_setup(self):
        for mode in ('basic','standard'):
            for caught in ([1],[1,3]):
                g=Game(mode,[{'name':str(i)} for i in range(4)],options={'tribute':True},previous={'first':0,'main':5,'scores':[2,0],'captured':caught})
                self.assertEqual(g.phase,'tribute')
                with self.assertRaises(RuleError):g.action(0,'confirm')
                for offer in g.tribute['offers']:
                    donor=offer['donor'];maximum=max([offer['card']]+[c for c in g.hands[donor] if c['rank']!=18],key=lambda c: (15.5 if c['rank']==5 else c['rank']))
                    self.assertEqual(offer['card']['rank'],maximum['rank'])
                    self.assertNotEqual(offer['card']['rank'],18)
                if len(caught)==2:
                    g.action(2,'tribute-pick',target=3)
                    with self.assertRaises(RuleError):g.action(0,'tribute-pick',target=3)
                    g.action(0,'tribute-pick',target=1)
                offers=list(g.tribute['offers'])
                for offer in offers:
                    recipient=offer['recipient'];donor=offer['donor'];card=g.hands[recipient][0]
                    with self.assertRaises(RuleError):g.action(donor,'tribute-return',[card['id']])
                    g.action(recipient,'tribute-return',[card['id']])
                    self.assertIn(card,g.hands[donor])
                self.assertEqual(g.phase,'setup');self.assertIsNone(g.tribute)
                self.assertEqual([len(h) for h in g.hands],g.initial_counts)

    def test_capture_persists_and_ai_completes_tribute(self):
        for order,captured in (((0,2,1,3),[1,3]),((0,3,2,1),[1]),((0,1,3,2),[])):
            g=table()
            for seat in order:
                g.hands[seat]=[];g.finish(seat)
                if g.phase=='over':break
            self.assertEqual(g.captured,captured)
            following=Game('standard',[{'name':str(i),'bot':True} for i in range(4)],options={'tribute':True},previous={'first':0,'main':g.next_main,'scores':g.scores,'captured':captured})
            for _ in range(5):
                if following.phase!='tribute':break
                for seat in range(4):
                    move=following.bot_action(seat)
                    if move:following.action(seat,**move);break
            self.assertEqual(following.phase,'setup')

    def test_grade_caps_at_ace_then_completes_round(self):
        g=table();g.main=13;g.scores=[10,0]
        g.hands[0]=[];g.finish(0);g.hands[2]=[];g.finish(2)
        self.assertEqual(g.scores,[11,0]);self.assertEqual(g.next_main,14);self.assertFalse(g.round_complete)
        following=Game('standard',g.players,previous={'first':0,'main':14,'scores':g.scores})
        following.phase='play';following.hands[0]=[];following.finish(0);following.hands[2]=[];following.finish(2)
        self.assertTrue(following.round_complete);self.assertEqual(following.next_main,3)

    def test_landlord_keeps_two_play_exit_after_bomb(self):
        g=table('landlord');g.landlord=0;g.hands[0]=cards([12]*4+[3,4,5,6,7,8,8,9,9,10,10],prefix='a')
        g.action(0,'play',['a0','a1','a2','a3'])
        g.action(2,'pass');g.action(1,'pass')
        first=g.bot_action(0);self.assertIn(first['label'],('顺子','连对'))
        g.action(0,**first);g.action(2,'pass');g.action(1,'pass')
        second=g.bot_action(0);g.action(0,**second)
        self.assertEqual(g.phase,'over');self.assertEqual(g.winner,[0])

    def test_basic_short_sequences_and_hints(self):
        for ranks,kind in (([6,7,8],'顺子'),([6,6,7,7],'连对')):
            self.assertEqual(classify(ranks,'basic')['kind'],kind)
            for mode in ('standard','trio','landlord'):self.assertIsNone(classify(ranks,mode))
            g=table('basic');g.hands[0]=cards(ranks+[12],prefix='a')
            ids=[c['id'] for c in g.hands[0][:-1]]
            self.assertTrue(any(set(m['ids'])==set(ids) for m in g.candidates(0)))
            g.action(0,'auto',ids);self.assertEqual(g.last['kind'],kind)
            g=table('basic');g.hands[0]=cards(ranks,prefix='a')
            self.assertEqual(set(g.bot_action(0)['ids']),set(ids))
        for ranks in ([6,7],[6,6],[14,15,16],[6,6,8,8]):
            combo=classify(ranks,'basic')
            self.assertTrue(combo is None or combo['kind'] not in ('顺子','连对'))

    def test_initial_hand_counts_survive_play_for_music_threshold(self):
        g=Game('standard',[{'name':str(i)} for i in range(4)])
        counts=[len(hand) for hand in g.hands]
        g.hands[0]=g.hands[0][:3]
        self.assertEqual(g.view(0)['initialCounts'],counts)
        g=Game('landlord',[{'name':str(i)} for i in range(3)])
        g.action(0,'bid',value=3)
        self.assertEqual(g.view(0)['initialCounts'],[20,17,17])

    def test_auto_recognizes_normal_and_special_plays(self):
        for mode in ('basic','standard'):
            g=table(mode);g.hands[0]=cards([5,8],prefix='a');g.hands[3]=cards([5,5,9],prefix='d');g.hands[1]=cards([5,10],prefix='b')
            g.action(0,'auto',['a0']);self.assertEqual(g.last['special'],'play')
            g.action(3,'auto',['d0','d1']);self.assertEqual(g.last['special'],'cross')
            g.action(1,'auto',['b0']);self.assertEqual(g.last['special'],'hook')
        g=table(options={'advancedDead':True});g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([7,10],prefix='d');g.hands[1]=cards([7]*3+[10],prefix='b');g.hands[2]=cards([7]*4+[10],prefix='c')
        g.action(0,'auto',['a0','a1']);g.action(3,'auto',['d0']);self.assertEqual(g.last['special'],'dot')
        g.action(1,'auto',['b0','b1','b2']);self.assertEqual(g.last['special'],'dead')
        g.action(2,'auto',['c0','c1','c2','c3']);self.assertEqual(g.last['special'],'dead4')
        g=table();g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([7,10],prefix='d');g.hands[2]=cards([15,9],prefix='c')
        g.action(0,'auto',['a0','a1']);g.action(3,'auto',['d0']);g.action(2,'auto',['c0']);self.assertEqual(g.last['special'],'press')
        g=table();g.action(0,'auto',['01']);g.action(3,'auto',['32']);self.assertEqual(g.last['special'],'play')
        g=table();g.action(0,'auto',['01']);g.action(3,'auto',['30']);self.assertEqual(g.last['special'],'hui')
        g=table();g.hands[0]=cards([18,6,9],prefix='a');g.action(0,'auto',['a0','a1'],target=1)
        self.assertEqual(g.turn,0);self.assertIsNone(g.last);self.assertTrue(any(c['id']=='a1' for c in g.hands[1]))
        g=table('landlord');g.action(0,'auto',['00']);self.assertEqual(g.last['special'],'play')

    def test_auto_priority_before_any_followup_plays_immediately(self):
        g=table();g.interactive=True;g.hands[0]=cards([5,8],prefix='a');g.hands[1]=cards([5,5,9],prefix='b')
        g.action(0,'auto',['a0']);g.action(1,'auto',['b0','b1'])
        self.assertIsNone(g.negotiation);self.assertEqual(g.last['special'],'cross');self.assertEqual(len(g.hands[1]),1)

    def test_existing_priority_selection_requests_undo_even_if_normal_bomb_is_legal(self):
        g=table(options={'advancedDead':True});g.interactive=True;g.turn=3
        g.hands[3]=cards([7,7,8],prefix='d');g.hands[0]=cards([7]*3+[6]*4+[9],prefix='a');g.hands[1]=cards([7]*4+[9],prefix='b')
        g.action(3,'auto',['d0','d1']);g.action(0,'auto',['a0','a1','a2'])
        self.assertEqual(g.last['special'],'dead')
        g.action(0,'auto',['a3','a4','a5','a6']);g.action(1,'auto',['b0','b1','b2','b3'])
        self.assertEqual(g.negotiation['target'],0);self.assertEqual(g.negotiation['action'],'dead4')
        g.action(0,'accept');self.assertEqual(g.last['special'],'dead4');self.assertEqual(len(g.hands[0]),5)

    def test_solo_can_choose_normal_single_instead_of_cross(self):
        for mode in ('basic','standard'):
            for cross in (False,True):
                g=table(mode);g.interactive=True;g.turn=1
                for seat in (1,2,3):g.players[seat]['bot']=True
                g.hands[1]=cards([5,9],prefix='b');g.hands[0]=cards([5,5,8],prefix='a')
                g.action(1,'auto',['b0']);self.assertEqual(g.priority['pending'],[0]);self.assertFalse(g.priority_paused())
                with self.assertRaises(RuleError):g.action(0,'auto',['a0','a2'])
                self.assertEqual(g.priority['pending'],[0])
                g.action(0,'auto',['a0','a1'] if cross else ['a2'])
                self.assertEqual(g.last['special'],'cross' if cross else 'play');self.assertEqual(g.last['ranks'],[5,5] if cross else [8])
                self.assertIsNone(g.view(0)['response'])

    def test_solo_priority_does_not_pause_when_human_is_normal_next(self):
        g=table('basic');g.interactive=True;g.turn=1
        for seat in (1,2,3):g.players[seat]['bot']=True
        g.hands[1]=cards([5,9],prefix='b');g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,5,10],prefix='d')
        g.action(1,'auto',['b0']);self.assertEqual(g.turn,0);self.assertIn(0,g.priority['pending']);self.assertFalse(g.priority_paused())
        self.assertIsNone(g.bot_action(3))
        g.action(0,'pass')
        move=g.bot_action(3);self.assertEqual(move['action'],'priority-play')
        g.action(3,**move);self.assertEqual(g.last['special'],'cross');self.assertEqual(g.turn,2)
        self.assertTrue(g.priority_paused());self.assertIsNone(g.bot_action(2))

    def test_solo_pass_declines_priority_through_normal_controls(self):
        g=table('basic');g.interactive=True
        for seat in (1,2,3):g.players[seat]['bot']=True
        g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,5,9],prefix='d')
        g.action(0,'auto',['a0']);g.action(3,'priority-play',['d0','d1'],special='cross')
        self.assertEqual(g.priority['pending'],[0]);self.assertIsNone(g.bot_action(2))
        g.action(0,'pass');self.assertIsNone(g.priority);self.assertEqual(g.turn,2)
        self.assertEqual(len(g.hands[0]),2)

    def test_multiplayer_priority_expires_after_two_players_play(self):
        for mode in ('basic','standard'):
            def start():
                g=table(mode);g.interactive=True
                g.hands[0]=cards([5,9],prefix='a');g.hands[1]=cards([5,5,10],prefix='b')
                g.hands[3]=cards([6]*4+[9],prefix='d');g.hands[2]=cards([7]*4+[10],prefix='c')
                g.action(0,'auto',['a0']);return g
            g=start();g.action(3,'auto',['d0','d1','d2','d3'])
            self.assertIn(1,g.claims);self.assertEqual(g.claims[1]['actors'],[3])
            response=g.view(1)['response'];self.assertEqual(response['key'],1);self.assertEqual(response['moves'][0]['ids'],['b0','b1'])
            self.assertIsNone(g.view(2)['response'])
            g.action(1,'auto',['b0','b1']);self.assertEqual(g.negotiation['target'],3)
            g.action(3,'accept');self.assertEqual(g.last['special'],'cross');self.assertEqual(len(g.hands[3]),5)
            g=start();g.action(3,'auto',['d0','d1','d2','d3']);g.action(2,'auto',['c0','c1','c2','c3'])
            self.assertNotIn(1,g.claims)
            with self.assertRaises(RuleError):g.action(1,'auto',['b0','b1'])

    def test_multiplayer_decline_does_not_stop_normal_turn(self):
        g=table('basic');g.interactive=True;g.hands[0]=cards([5,8],prefix='a');g.hands[1]=cards([5,5,9],prefix='b')
        g.action(0,'auto',['a0']);self.assertIsNotNone(g.view(1)['response'])
        g.action(1,'pass');self.assertIsNone(g.view(1)['response']);self.assertEqual(g.turn,3)
        g.action(3,'auto',['30']);self.assertEqual(g.last_seat,3)

    def test_basic_opening_spade_three_and_random_fallback(self):
        players=[{'name':str(i),'bot':i!=0} for i in range(4)]
        g=Game('basic',players);self.assertEqual(g.phase,'setup')
        g.hands=[cards([6],prefix=str(i)) for i in range(4)]
        g.hands[2]=cards([3],'S','s')
        self.assertEqual(g.bot_action(2),{'action':'reveal'})
        g.action(2,'reveal')
        for seat in range(4):g.action(seat,'confirm')
        self.assertEqual(g.turn,2);self.assertEqual(g.phase,'play')
        for chosen in range(4):
            g=Game('basic',players)
            with patch('engine.random.randrange',return_value=chosen) as choose:
                for seat in range(4):g.action(seat,'confirm')
                choose.assert_called_once_with(4)
            self.assertEqual(g.turn,chosen)
        g=Game('basic',players,previous={'first':3})
        for seat in range(4):g.action(seat,'confirm')
        self.assertEqual(g.turn,3)
        g=Game('basic',players);g.hands[0]=cards([7]*6,prefix='a')
        with self.assertRaises(RuleError):g.action(0,'promote',rank=7)

    def test_finished_lead_passes_to_opposite_partner(self):
        for mode in ('basic', 'standard'):
            g=table(mode);g.hands[0]=cards([6],prefix='a')
            g.action(0,'play',['a0'])
            for seat in (3,2,1):g.action(seat,'pass')
            self.assertEqual(g.turn,2);self.assertIsNone(g.last)
            self.assertIsNone(g.seat_plays[0])
            self.assertTrue(all(g.seat_plays[s]['passed'] for s in (1,2,3)))
            g.action(2,'play',['20'])
        g=table();g.turn=3;g.hands[3]=cards([15,15,9],prefix='d');g.hands[0]=cards([15],prefix='a')
        g.action(3,'play',['d0','d1']);g.action(0,'dot',['a0'])
        self.assertEqual(g.turn,2);self.assertIsNone(g.last);self.assertIsNone(g.seat_plays[0])

    def test_bot_reserves_cards_for_urgent_gifts(self):
        g=table();g.interactive=True
        for p in g.players:p['bot']=True
        g.turn=2;g.hands[2]=cards([5,9],prefix='c');g.hands[3]=cards([5,5,8],prefix='d');g.hands[0]=cards([5,18,18],prefix='a')
        g.action(2,'play',['c0']);g.action(3,'priority-play',['d0','d1'],special='cross')
        self.assertEqual(g.bot_action(0),{'action':'priority-decline'})
        g=table();g.hands[0]=cards([6,7,18,18,18],prefix='a')
        move=g.bot_action(0);self.assertEqual(move['action'],'urgent');g.action(0,**move)
        self.assertEqual(sum(c['rank']!=18 for c in g.hands[0]),1)

    def test_basic_rejects_three_with_single_but_standard_allows_it(self):
        self.assertIsNone(classify([6,6,6,8],'basic'))
        self.assertEqual(classify([6,6,6,8],'standard')['kind'],'三带一')
        g=table('basic');g.hands[0]=cards([6,6,6,8,9],prefix='a')
        with self.assertRaises(RuleError):g.action(0,'auto',['a0','a1','a2','a3'])
        self.assertFalse(any(set(m['ids'])=={'a0','a1','a2','a3'} for m in g.candidates(0)))
        g=table();g.hands[0]=cards([6,6,6,8,9],prefix='a')
        g.action(0,'auto',['a0','a1','a2','a3']);self.assertEqual(g.last['kind'],'三带一')

    def test_custom_carried_units(self):
        for mode in ('standard', 'trio'):
            for size in range(3, 11):
                for count in range(1, size - 1):
                    for unit in (1, 2):
                        ranks = [6] * size + [r for r in range(7, 7 + count) for _ in range(unit)]
                        combo = classify(ranks, mode)
                        self.assertIsNotNone(combo, (mode, size, count, unit))
                        self.assertEqual(combo['power'], 0)
                        self.assertEqual(combo['value'], 6)
            self.assertIsNone(classify([6]*4 + [8,8,9], mode))
            self.assertIsNone(classify([6]*5 + [8,8,9,10], mode))
            self.assertIsNone(classify([6]*4 + [8,9,10], mode))
        self.assertIsNone(classify([6]*4 + [8], 'landlord'))
        self.assertIsNone(classify([6]*5 + [8,9], 'landlord'))

    def test_basic_rejects_all_carried_cards(self):
        for ranks in ([6,6,6,8], [6,6,6,8,8], [6]*4+[8,9], [6]*4+[8,8,9,9], [6]*3+[7]*3+[9,10], [6]*3+[7]*3+[9,9,10,10]):
            self.assertIsNone(classify(ranks, 'basic'), ranks)
            g=table('basic');g.hands[0]=cards(ranks+[12],prefix='a')
            ids=[c['id'] for c in g.hands[0][:-1]]
            with self.assertRaises(RuleError):g.action(0,'auto',ids)
            self.assertFalse(any(set(m['ids'])==set(ids) for m in g.candidates(0)))
        self.assertIsNotNone(classify([4,4,14], 'basic'))
        self.assertEqual(classify([6]*3+[7]*3, 'basic')['kind'], '飞机')

    def test_carried_shapes_and_candidates(self):
        for ranks, label in (([6]*3+[8], '三带一'), ([6]*3+[8,8], '三带一对'), ([6]*4+[8,9], '四带二'), ([6]*4+[8,8,9,9], '四带两对')):
            self.assertEqual(classify(ranks,'standard')['kind'],label)
        g=table();g.hands[0]=cards([6]*5+[8,8,9,9,10,10,12],prefix='a')
        moves=g.candidates(0)
        for kind in ('五带一', '五带二', '五带三', '五带一对', '五带两对', '五带三对'):
            self.assertTrue(any(m['label']==kind for m in moves),kind)
        g.action(0,'auto',['a'+str(i) for i in range(9)])
        self.assertEqual(g.last['kind'],'五带两对')
        with self.assertRaises(RuleError):g.validate_play(3,cards([7]*6+[10,11,12]),'play')
        self.assertEqual(g.validate_play(3,cards([7]*5+[10,10,11,11]),'play')[0]['kind'],'五带两对')

    def test_wildcard_carried_units(self):
        chosen=cards([6]*4+[8,8,9,9])+cards([14],'S','w')
        self.assertTrue(any(c['kind']=='五带两对' for c in interpretations(chosen,'standard',3)))
        chosen=cards([6]*5+[8,9])+cards([14],'S','w')
        self.assertTrue(any(c['kind']=='五带三' for c in interpretations(chosen,'standard',3)))
        g=table();g.hands[0]=cards([6]*4+[8,8,9,9,12])+cards([14],'S','w')
        self.assertTrue(any(m['label']=='五带两对' for m in g.candidates(0)))

    def test_unanswered_play_gives_unrestricted_fresh_lead(self):
        for mode in ('basic','standard','landlord'):
            g=table(mode);g.interactive=True
            g.hands[0]=cards([12,6,6,7],prefix='a')
            if mode != 'landlord':
                g.players[-1]['bot']=True
                g.hands[-1]=cards([12,12,8],prefix='d')
            g.action(0,'auto',['a0'])
            if mode != 'landlord':self.assertIsNotNone(g.priority)
            for seat in range(len(g.players)-1,0,-1):g.action(seat,'pass')
            self.assertEqual(g.turn,0)
            self.assertIsNone(g.last)
            self.assertIsNone(g.priority)
            self.assertEqual(g.claims,{})
            g.action(0,'auto',['a1','a2'])
            self.assertEqual(g.last['kind'],'对子')

    def test_cross_only_hook_and_unanswered_cross_keeps_lead(self):
        for mode in ('basic','standard','trio'):
            g=table(mode);last=len(g.players)-1
            g.hands[0]=cards([5,8],prefix='a');g.hands[last]=cards([5,5,9],prefix='d')
            g.action(0,'auto',['a0']);g.action(last,'auto',['d0','d1'])
            target=g.turn;g.hands[target]=cards([10]*4+[11],prefix='x')
            with self.assertRaises(RuleError):g.action(target,'auto',['x0','x1','x2','x3'])
            with self.assertRaises(RuleError):g.action(target,'auto',['x4'])
            for _ in range(len(g.players)-1):g.action(g.turn,'pass')
            self.assertEqual(g.turn,last);self.assertIsNone(g.last)
            g.action(last,'auto',['d2']);self.assertEqual(g.last['ranks'],[9])

    def test_hook_can_be_crossed_and_hooked_repeatedly(self):
        for mode in ('basic','standard'):
            g=table(mode);g.interactive=True
            g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,5,9],prefix='d');g.hands[1]=cards([5,4],prefix='b');g.hands[2]=cards([5,5]+[10]*4+[11],prefix='c')
            g.action(0,'auto',['a0']);g.action(3,'auto',['d0','d1']);g.action(1,'auto',['b0'])
            self.assertEqual(g.turn,1);self.assertIn(2,g.priority['pending'])
            with self.assertRaises(RuleError):g.action(2,'play',['c2','c3','c4','c5'])
            g.action(2,'auto',['c0','c1']);self.assertEqual(g.last['special'],'cross')
            g.action(0,'auto',['a1']);self.assertEqual(g.last['special'],'hook')
            self.assertIsNone(g.priority)
            g.action(0,'auto',['a2']);self.assertEqual(g.last['ranks'],[8]);self.assertEqual(g.last['special'],'play')

    def test_five_carries_pair_as_two_single_cards(self):
        for mode in ('standard','trio'):
            combo=classify([6]*5+[8,8,9],mode)
            self.assertEqual(combo['kind'],'五带三')
            self.assertIsNone(classify([6]*4+[8,8,9],mode))
            g=table(mode);g.hands[0]=cards([6]*5+[8,8,9,12],prefix='a')
            self.assertTrue(any(m['label']=='五带三' and set(m['ids'])=={'a'+str(i) for i in range(8)} for m in g.candidates(0)))
            g.action(0,'auto',['a'+str(i) for i in range(8)]);self.assertEqual(g.last['kind'],'五带三')
            chosen=cards([6]*4+[8,8,9],prefix='a')+cards([14],'S','w')
            self.assertTrue(any(c['kind']=='五带三' for c in interpretations(chosen,mode,3)))
            g=table(mode);g.hands[0]=chosen+cards([12],prefix='z')
            self.assertTrue(any(m['label']=='五带三' and set(m['ids'])=={c['id'] for c in chosen} for m in g.candidates(0)))

    def test_large_carried_singles_allow_repeated_attachment_ranks(self):
        for mode in ('standard','trio'):
            for body, wings, label in ((6,[8,8,9,10],'六带四'),(6,[8,8,8,9],'六带四'),(7,[8,8,9,9,10],'七带五'),(8,[8,8,8,9,9,10],'八带六')):
                chosen=cards([6]*body+wings,prefix='a')
                self.assertEqual(classify([6]*body+wings,mode)['kind'],label)
                g=table(mode);g.hands[0]=chosen+cards([12],prefix='z')
                self.assertTrue(any(m['label']==label and set(m['ids'])=={c['id'] for c in chosen} for m in g.candidates(0)))
                g.action(0,'auto',[c['id'] for c in chosen]);self.assertEqual(g.last['kind'],label)
                with self.assertRaises(RuleError):g.validate_play(len(g.players)-1,cards([7]*body+wings+[13]),'play')
            chosen=cards([6]*5+[8,8,8,9],prefix='a')+cards([14],'S','w')
            self.assertTrue(any(c['kind']=='六带四' for c in interpretations(chosen,mode,3)))

    def test_pairs_can_follow_carried_singles_when_counted_as_single_cards(self):
        for mode in ('standard','trio'):
            g=table(mode);seat=len(g.players)-1
            g.hands[0]=cards([6]*6+[8,9,10,11,12],prefix='a')
            g.hands[seat]=cards([7]*6+[12,12,13,13,10],prefix='b')
            g.action(0,'auto',['a'+str(i) for i in range(10)])
            self.assertEqual(g.last['kind'],'六带四')
            self.assertTrue(any(m['label']=='六带四' and set(m['ids'])=={'b'+str(i) for i in range(10)} for m in g.candidates(seat)))
            g.action(seat,'auto',['b'+str(i) for i in range(10)])
            self.assertEqual(g.last['kind'],'六带四')
            self.assertEqual(classify([7]*6+[12,12,13,13],mode)['kind'],'六带两对')

    def test_ai_priority_waits_for_human_in_multiplayer(self):
        for special,lead,human,bot in (('cross',[5],[5,5],[5,5]),('dot',[5,5],[5],[5]),('hook',[5,5],[5],[5])):
            g=table();g.interactive=True;g.players[3]['bot']=True
            g.hands[1]=cards(lead+[9],prefix='b');g.hands[0]=cards(human+[8],prefix='a');g.hands[3]=cards(bot+[10],prefix='d')
            g.turn=1
            if special=='hook':
                g.last={'kind':'单张','n':1,'power':0,'value':5,'ranks':[5],'cards':cards([5],prefix='x'),'special':'play'};g.last_seat=2
                g.action(1,'cross',['b0','b1'])
            else:g.action(1,'play',['b'+str(i) for i in range(len(lead))])
            self.assertIn(0,g.priority['pending']);self.assertIn(3,g.priority['bots'])
            self.assertFalse(g.priority_paused());self.assertIsNone(g.bot_action(3))
            with self.assertRaises(RuleError):g.action(3,'priority-play',['d'+str(i) for i in range(len(bot))],special=special)
            g.action(0,'pass')
            self.assertEqual(g.bot_action(3)['action'],'priority-play')

    def test_cross_then_hook_can_intercept_out_of_turn(self):
        for mode in ('basic', 'standard'):
            g=table(mode);g.hands[0]=cards([5,8],prefix='a');g.hands[3]=cards([5,5,9],prefix='d');g.hands[1]=cards([5,10],prefix='b')
            g.action(0,'play',['a0']);g.action(3,'cross',['d0','d1'])
            self.assertEqual(g.turn,2)
            g.action(1,'hook',['b0'])
            self.assertEqual(g.last['special'],'hook');self.assertEqual(g.last_seat,1)

    def test_priority_after_one_followup_accept_or_reject(self):
        for mode in ('basic', 'standard'):
            for accept in (False, True):
                g=table(mode);g.interactive=True
                g.hands[0]=cards([5,8],prefix='a');g.hands[1]=cards([5,5,9],prefix='b');g.hands[3]=cards([6,10],prefix='d')
                g.action(0,'auto',['a0'])
                self.assertEqual(g.view(3)['priority']['moves'],[])
                g.action(3,'auto',['d0']);g.action(1,'auto',['b0','b1'])
                self.assertEqual(g.negotiation['target'],3);self.assertEqual(len(g.hands[1]),3)
                g.action(3,'accept' if accept else 'reject')
                if accept:
                    self.assertEqual(g.last['special'],'cross');self.assertEqual(len(g.hands[1]),1);self.assertEqual(len(g.hands[3]),2)
                else:
                    self.assertEqual(g.last_seat,3);self.assertEqual(len(g.hands[1]),3);self.assertNotIn(1,g.claims)

    def test_display_pass_replaces_cards_and_next_round_hides_finished(self):
        g=table();g.hands[0]=cards([6],prefix='a')
        g.hands[3]=cards([7,10,13],prefix='d');g.hands[2]=cards([8,11,14],prefix='c');g.hands[1]=cards([9,12,15],prefix='b')
        g.action(0,'play',['a0']);g.action(3,'play',['d0']);g.action(2,'play',['c0']);g.action(1,'play',['b0'])
        self.assertIsNotNone(g.seat_plays[0])
        g.action(3,'play',['d1']);self.assertIsNone(g.seat_plays[0])
        g.action(2,'pass');self.assertEqual(g.seat_plays[2]['kind'],'不出');self.assertEqual(g.seat_plays[2]['cards'],[])

    def test_counterclockwise_turns_and_bidding(self):
        for mode in MODES:
            g=table(mode);last_seat=len(g.players)-1
            g.action(0,'play',['00']);self.assertEqual(g.turn,last_seat)
            with self.assertRaises(RuleError):g.action(1,'pass')
            for seat in range(last_seat,0,-1):
                self.assertEqual(g.turn,seat);g.action(seat,'pass')
            self.assertEqual(g.turn,0);self.assertIsNone(g.last)
            g.finished=[last_seat];self.assertEqual(g.next_seat(0),last_seat-1)
        g=Game('landlord',[{'name':str(i)} for i in range(3)])
        for seat in (0,2,1):
            self.assertEqual(g.turn,seat);g.action(seat,'bid',value=0)
        self.assertEqual(g.landlord,1);self.assertEqual(g.phase,'play')

    def test_decks(self):
        self.assertEqual([len(deck(m)) for m in MODES], [54, 110, 86, 54, 110])
        d = deck('trio')
        self.assertFalse(any(c['suit'] == 'S' and c['rank'] <= 13 for c in d))
        self.assertEqual(Counter(c['rank'] for c in d)[17], 3)
        dlc=deck('standard',True)
        self.assertEqual(len(dlc),150)
        self.assertEqual(Counter(c['rank'] for c in dlc if c['suit']=='T'),Counter({r:2 for r in range(3,16)}))
        self.assertEqual(sum(c['suit']=='S' and c['rank']==14 for c in dlc),7)
        self.assertEqual(sum(c['rank']==18 for c in dlc),9)

    def test_classic_combinations(self):
        cases = [([4], '单张'), ([4,4], '对子'), ([4,4,4], '三张'), ([4,4,4,7], '三带一'),
                 ([4,4,4,7,7], '三带一对'), ([3,4,5,6,7], '顺子'), ([3,3,4,4,5,5], '连对'),
                 ([3,3,3,4,4,4], '飞机'), ([3,3,3,4,4,4,6,7], '飞机带单'),
                 ([3,3,3,4,4,4,6,6,7,7], '飞机带对'), ([4,4,4,4,5,6], '四带二'),
                 ([4,4,4,4,5,5,6,6], '四带两对'), ([4,4,4,4], '炸弹'), ([16,17], '王炸')]
        for ranks, kind in cases:
            with self.subTest(ranks=ranks): self.assertEqual(classify(ranks)['kind'], kind)
        self.assertIsNone(classify([11,12,13,14,15]))
        self.assertEqual(classify([3,4,5,6,7], 'standard', 3)['kind'],'顺子')
        self.assertGreater(classify([3], 'standard', 3)['value'], classify([15], 'standard', 3)['value'])

    def test_bomb_order(self):
        groups = [[5]*4, [16,17], [5]*5, [5]*6, [16,17,17], [5]*7, [5]*8, [16,16,17,17], [5]*9, [5]*10, [4,4,4,14,14], [4]*4+[14]*2]
        powers = [classify(r, 'standard')['power'] for r in groups]
        self.assertEqual(powers, sorted(powers));self.assertEqual(powers[-1],powers[-2])
        self.assertEqual(classify([5]*3, 'basic')['kind'], '炸弹')
        self.assertEqual(classify([4,14,4], 'basic')['kind'], '4A4')

    def test_wildcards(self):
        wild = cards([14,14], 'S', 'w')
        self.assertTrue(any(c['kind']=='炸弹' for c in interpretations(cards([7,7])+wild,'standard',3)))
        self.assertTrue(any(c['kind']=='顺子' for c in interpretations(cards([5,6,7])+wild,'standard',3)))
        self.assertTrue(any(c['kind']=='三带一对' for c in interpretations(cards([7,7,8])+wild,'standard',3)))
        self.assertFalse(interpretations(wild[:1], 'standard', 3, 7))
        self.assertEqual(interpretations(wild[:1], 'standard', 3)[0]['ranks'],[14])
        for mode in ('standard','trio'):
            g=table(mode);following=len(g.players)-1;g.hands[0]=cards([13,6],prefix='a');g.hands[following]=cards([14,7],'S','b')
            g.action(0,'play',['a0']);g.action(following,'play',['b0'])
            self.assertEqual(g.last['kind'],'单张');self.assertEqual(g.last['ranks'],[14])
        self.assertFalse(interpretations(cards([17])+wild, 'standard', 3, 17))
        combo = interpretations(cards([5,6,7])+wild,'standard',3,{'w0':8,'w1':9})
        self.assertEqual(combo[0]['kind'],'顺子')

    def test_cross_hook_and_bomb(self):
        g=table()
        g.hands[0]=cards([7,8],prefix='a');g.hands[3]=cards([7,7,9],prefix='b');g.hands[2]=cards([7,10],prefix='c')
        g.action(0,'play',['a0']);g.action(3,'cross',['b0','b1']);g.action(2,'hook',['c0'])
        self.assertEqual(g.last['special'],'hook')
        with self.assertRaises(RuleError):g.action(1,'play',['10'])
        g.hands[1]=cards([9]*4+[10],prefix='d')
        with self.assertRaises(RuleError):g.action(1,'play',['d0','d1','d2','d3'])
        self.assertEqual(g.turn,2);g.action(2,'auto',['c1']);self.assertEqual(g.last['ranks'],[10])

    def test_dot_press_direct_lead(self):
        g=table();g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([7,9],prefix='b');g.hands[2]=cards([15,8,9],prefix='c')
        g.action(0,'play',['a0','a1']);g.action(3,'dot',['b0']);g.action(2,'press',['c0'])
        self.assertEqual(g.turn,2)
        g.action(2,'play',['c1']);self.assertEqual(g.last['kind'],'单张')
        g=table();g.hands[0]=cards([15,15,9],prefix='a');g.hands[3]=cards([15,9],prefix='b')
        g.action(0,'play',['a0','a1']);g.action(3,'dot',['b0']);self.assertEqual(g.turn,3)

    def test_dead_has_priority_over_dot(self):
        g=table();g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([7,9],prefix='b');g.hands[1]=cards([7,7,7,9],prefix='d')
        g.action(0,'play',['a0','a1']);g.action(3,'dot',['b0']);g.action(1,'dead',['d0','d1','d2'])
        self.assertEqual(g.turn,1)

    def test_next_round_allows_promotion(self):
        g=Game('standard',[{'name':str(i)} for i in range(4)],previous={'first':2,'main':5,'scores':[2,0]})
        self.assertEqual(g.phase,'setup')
        for s in range(4):g.action(s,'confirm')
        self.assertEqual(g.turn,2);self.assertEqual(g.main,5)

    def test_advanced_dead_interception(self):
        g=table(options={'advancedDead':True});g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([7,7,7,9],prefix='b');g.hands[1]=cards([7]*4+[9],prefix='d')
        g.action(0,'play',['a0','a1']);g.action(3,'dead',['b0','b1','b2']);self.assertEqual(g.turn,3)
        g.action(1,'dead4',['d0','d1','d2','d3']);self.assertEqual(g.turn,1)
        g.action(1,'play',['d4']);self.assertEqual(g.last['kind'],'单张')

    def test_hui_excludes_kings_two_and_main_on_both_sides(self):
        for mode in ('standard', 'trio'):
            for advanced in (False, True):
                cases = [([5], [15]), ([15], [5]), ([5], [7]), ([7], [5]), ([16], [17]), ([17], [16])]
                if advanced:
                    cases += [([5,5], [15,15]), ([15,15], [5,5]), ([5,5], [7,7]), ([7,7], [5,5]), ([16,16], [17,17]), ([5,6,7,8,9], [3,4,5,6,7])]
                for lead, reply in cases:
                    with self.subTest(mode=mode, advanced=advanced, lead=lead, reply=reply):
                        g=table(mode, {'advancedHui':advanced});g.main=7
                        source=cards(lead, 'J' if lead[0]>=16 else 'H', 'a')
                        response=cards(reply, 'J' if reply[0]>=16 else 'H', 'b')
                        g.hands[0]=source+cards([10],prefix='x');g.hands[-1]=response+cards([11],prefix='y')
                        g.action(0,'play',[c['id'] for c in source])
                        with self.assertRaises(RuleError):g.validate_play(len(g.players)-1,response,'hui')
                        self.assertFalse(any(m['action']=='hui' and set(m['ids'])=={c['id'] for c in response} for m in g.candidates(len(g.players)-1)))

    def test_hui_cannot_use_wildcard_to_bypass_excluded_ranks(self):
        g=table(options={'advancedHui':True});g.main=7
        g.hands[0]=cards([5,5,9],'S','a');g.hands[3]=cards([14,14,9],'S','b')
        g.action(0,'play',['a0','a1'])
        for rank in (7,15):
            with self.assertRaises(RuleError):g.validate_play(3,g.hands[3][:2],'hui',rank)
        self.assertEqual(g.validate_play(3,g.hands[3][:2],'hui',4)[0]['kind'],'回')

    def test_wildcard_declared_suit_controls_hui_and_candidates(self):
        for mode in ('standard','trio'):
            g=table(mode,{'advancedHui':True});seat=len(g.players)-1
            g.hands[0]=cards([8,8,10],'H','a')
            g.hands[seat]=cards([5,9],'H','b')+cards([14],'S','w')
            g.action(0,'play',['a0','a1'])
            selected=g.select(seat,['b0','w0'])
            with self.assertRaises(RuleError):g.validate_play(seat,selected,'hui',{'w0':{'rank':5,'suit':'S'}})
            declaration={'w0':{'rank':5,'suit':'H'}}
            self.assertEqual(g.validate_play(seat,selected,'hui',declaration)[0]['suits'],['H','H'])
            self.assertTrue(any(m['action']=='hui' and set(m['ids'])=={'b0','w0'} and m['wildcard']==declaration for m in g.candidates(seat)))
            g.action(seat,'auto',['b0','w0'],wildcard=declaration)
            self.assertEqual(g.last['special'],'hui');self.assertEqual(g.last['suits'],['H','H'])
            self.assertEqual(g.hands[seat][0]['rank'],9)

    def test_hui_uses_previous_wildcard_suit_and_validates_declarations(self):
        g=table(options={'advancedHui':True})
        g.hands[0]=cards([8,10],'H','a')+cards([14],'S','w');g.hands[3]=cards([5,5,9],'H','b')
        g.action(0,'play',['a0','w0'],wildcard={'w0':{'rank':8,'suit':'H'}})
        self.assertEqual(g.last['cards'][1]['suit'],'S')
        g.action(3,'hui',['b0','b1']);self.assertEqual(g.last['special'],'hui')
        selected=cards([5],'H','a')+cards([14],'S','w')
        for value in ({'rank':5,'suit':'J'},{'rank':17,'suit':'H'},{'rank':5,'suit':'H','extra':1}):
            self.assertFalse(interpretations(selected,'standard',3,{'w0':value}))
        self.assertFalse(interpretations(selected,'standard',3,{'a0':{'rank':5,'suit':'H'}}))
        g=table();g.hands[0]=cards([14],'S','w')+cards([6,9],'H','a')
        g.action(0,'auto',['w0','a0'],target=1,wildcard={'w0':{'rank':18,'suit':'H'}})
        self.assertTrue(any(c['id']=='a0' for c in g.hands[1]))
        self.assertEqual(g.turn,0)

    def test_hui_once_and_follow(self):
        g=table();g.hands[0]=cards([7,9],prefix='a');g.hands[3]=cards([5,10],prefix='b');g.hands[2]=cards([8,10],prefix='c');g.hands[1]=cards([6,10],prefix='d')
        g.action(0,'play',['a0']);g.action(3,'hui',['b0']);g.action(2,'play',['c0'])
        with self.assertRaises(RuleError):g.action(1,'hui',['d0'])

    def test_finished_player_intercept_and_negotiation(self):
        g=table();g.hands[0]=cards([7],prefix='a');g.hands[3]=cards([8,9],prefix='b');g.hands[2]=cards([7,7,10],prefix='c')
        g.action(0,'play',['a0']);g.action(3,'play',['b0'])
        g.action(2,'negotiate',['c0','c1'],special='cross')
        g.action(3,'accept')
        self.assertEqual(len(g.hands[3]),2);self.assertEqual(g.last_seat,2);self.assertEqual(g.last['special'],'cross')
        self.assertIsNone(g.seat_plays[3]);self.assertEqual(g.play_number,2)
        self.assertEqual(g.seat_plays[2]['order'],2)
        g=table();g.hands[0]=cards([7],prefix='a');g.hands[2]=cards([7,7,10],prefix='c')
        g.action(0,'play',['a0']);g.action(2,'cross',['c0','c1']);self.assertEqual(g.last_seat,2)

    def test_advanced_hui_matches_body_suits_and_ignores_wings(self):
        for mode in ('standard','trio'):
            g=table(mode,{'advancedHui':True});seat=len(g.players)-1
            lead=[{'id':'a'+str(i),'rank':13,'suit':s} for i,s in enumerate('SHC')]+cards([3],'D','wing-a')
            reply=[{'id':'b'+str(i),'rank':12,'suit':s} for i,s in enumerate('SHC')]+cards([3],'S','wing-b')
            g.hands[0]=lead+cards([10],prefix='x');g.hands[seat]=reply+cards([9],prefix='y')
            g.action(0,'play',[c['id'] for c in lead])
            self.assertTrue(any(m['action']=='hui' and set(m['ids'])=={c['id'] for c in reply} for m in g.candidates(seat)))
            for rank in (3,15,16,17):
                changed=reply[:3]+cards([rank],'D','wing')
                self.assertEqual(g.validate_play(seat,changed,'hui')[0]['kind'],'回')
            mismatch=[dict(c) for c in reply];mismatch[2]['suit']='D'
            with self.assertRaises(RuleError):g.validate_play(seat,mismatch,'hui')
            g.action(seat,'auto',[c['id'] for c in reply]);self.assertEqual(g.last['special'],'hui')

    def test_advanced_hui_airplane_compares_each_body_group(self):
        g=table(options={'advancedHui':True})
        lead=[{'id':'a'+str(i),'rank':r,'suit':s} for i,(r,s) in enumerate(zip([11]*3+[12]*3+[3,15],'SHCSHDHD'))]
        reply=[{'id':'b'+str(i),'rank':r,'suit':s} for i,(r,s) in enumerate(zip([9]*3+[10]*3+[16,17],'SHCSHDCS'))]
        g.hands[0]=lead+cards([8],prefix='x');g.hands[3]=reply+cards([7],prefix='y')
        g.action(0,'play',[c['id'] for c in lead])
        self.assertEqual(g.validate_play(3,reply,'hui')[0]['kind'],'回')
        mismatch=[dict(c) for c in reply];mismatch[2]['suit'],mismatch[5]['suit']=mismatch[5]['suit'],mismatch[2]['suit']
        with self.assertRaises(RuleError):g.validate_play(3,mismatch,'hui')

    def test_advanced_hui_wildcard_fills_body_suit_deficit(self):
        g=table(options={'advancedHui':True})
        lead=[{'id':'a'+str(i),'rank':13,'suit':s} for i,s in enumerate('SHC')]+cards([3],'D','u')
        reply=cards([12],'S','b')+cards([12],'H','c')+cards([14],'S','w')+cards([15],'D','v')
        g.hands[0]=lead+cards([10],prefix='x');g.hands[3]=reply+cards([9],prefix='y')
        g.action(0,'play',[c['id'] for c in lead])
        declaration={'w0':{'rank':12,'suit':'C'}}
        self.assertEqual(g.validate_play(3,reply,'hui',declaration)[0]['kind'],'回')
        with self.assertRaises(RuleError):g.validate_play(3,reply,'hui',{'w0':{'rank':12,'suit':'D'}})
        self.assertTrue(any(m['action']=='hui' and set(m['ids'])=={c['id'] for c in reply} and m['wildcard']==declaration for m in g.candidates(3)))

    def test_advanced_hui_and_urgent_negotiation_boundary(self):
        g=table(options={'advancedHui':True});g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([5,5,9],prefix='b');g.hands[2]=cards([6,6,9],prefix='c')
        g.action(0,'play',['a0','a1']);g.action(3,'hui',['b0','b1']);g.action(2,'play',['c0','c1'])
        self.assertEqual(g.last['kind'],'对子')
        g=table();g.hands[0]=cards([7],prefix='a');g.hands[3]=cards([8,9],prefix='b');g.hands[2]=cards([18,6,7],prefix='c');g.hands[1]=cards([7,7,9],prefix='d')
        g.action(0,'play',['a0']);g.action(3,'play',['b0']);g.action(2,'urgent',['c0','c1'],target=3)
        with self.assertRaises(RuleError):g.action(1,'negotiate',['d0','d1'],special='cross')
        with self.assertRaises(RuleError):g.action(2,'urgent',['c2'],target=3)

    def test_autoplay_handles_human_priority_and_can_return_to_manual(self):
        g=table('basic');g.interactive=True;g.turn=2
        for seat in (1,2,3):g.players[seat]['bot']=True
        g.hands[0]=cards([5,5,9],prefix='a');g.hands[1]=cards([6,8],prefix='b')
        g.hands[2]=cards([5,8],prefix='c');g.hands[3]=cards([6,8],prefix='d')
        g.action(2,'play',['c0']);self.assertTrue(g.priority_paused())
        g.players[0]['autoplay']=True
        self.assertFalse(g.priority_paused())
        move=g.bot_action(0);self.assertEqual(move['action'],'priority-play');self.assertEqual(move['special'],'cross')
        g.action(0,**move);self.assertEqual(g.last['special'],'cross')
        self.assertFalse(g.players[0].get('bot'));self.assertTrue(g.solo())
        g.players[0]['autoplay']=False

    def test_autoplay_waits_for_other_manual_priority_player(self):
        g=table();g.interactive=True;g.turn=1;g.players[0]['autoplay']=True
        g.hands[0]=cards([5,5,9],prefix='a');g.hands[1]=cards([5,8],prefix='b')
        g.hands[2]=cards([5,5,8],prefix='c');g.hands[3]=cards([6,8],prefix='d')
        g.action(1,'play',['b0'])
        with self.assertRaises(RuleError):g.action(0,'cross',['a0','a1'])
        move=g.bot_action(0)
        self.assertTrue(move is None or move['action'] not in ('cross','hook','priority-play'))
        g.action(2,'priority-decline')
        self.assertEqual(g.bot_action(0)['action'],'priority-play')

    def test_special_chain_skips_only_players_without_response_or_urgent(self):
        for mode in ('basic', 'standard'):
            g=table(mode); g.turn=0
            g.hands[0]=cards([5,9],prefix='a');g.hands[3]=cards([5,5,9],prefix='b')
            g.hands[2]=cards([6,7],prefix='c');g.hands[1]=cards([5,8],prefix='d')
            g.action(0,'play',['a0']);g.action(3,'cross',['b0','b1'])
            self.assertEqual(g.turn,2);self.assertTrue(g.forced_pass())
            g.action(g.turn,'pass');self.assertEqual(g.turn,1);self.assertFalse(g.forced_pass())
            g.action(1,'hook',['d0']);self.assertFalse(g.forced_pass())
            g.action(1,'play',['d1']);self.assertFalse(g.forced_pass())
        g=table();g.turn=0
        g.hands[0]=cards([5,9],prefix='a');g.hands[3]=cards([5,5,9],prefix='b')
        g.hands[2]=cards([18,7,8],prefix='c')
        g.action(0,'play',['a0']);g.action(3,'cross',['b0','b1'])
        self.assertFalse(g.forced_pass())
        g.action(2,'urgent',['c0','c1'],target=1)
        self.assertTrue(g.forced_pass())
        g.hands[2]=cards([14],'S','w')+cards([9],prefix='x')
        self.assertFalse(g.forced_pass())

    def test_declining_hook_does_not_ask_again_on_the_same_cross(self):
        for mode in ('basic', 'standard'):
            g=table(mode);g.interactive=True;g.turn=3
            for seat in (1,2,3):g.players[seat]['bot']=True
            g.hands[3]=cards([5,8],prefix='d');g.hands[2]=cards([5,5,9],prefix='c')
            g.hands[1]=cards([6,7],prefix='b');g.hands[0]=cards([5,9],prefix='a')
            g.action(3,'play',['d0']);g.action(2,'cross',['c0','c1'])
            self.assertEqual(g.priority['pending'],[0])
            g.action(0,'pass')
            self.assertTrue(g.forced_pass());g.action(1,'pass')
            self.assertEqual(g.turn,0)
            self.assertTrue(g.forced_pass(), 'a declined hook must not be requested a second time')
            with self.assertRaises(RuleError):g.action(0,'auto',['a0'])
            g.action(0,'pass');g.action(3,'pass')
            self.assertIsNone(g.last);self.assertEqual(g.turn,2)
            g.action(2,'play',['c2'])
            self.assertEqual(g.last['ranks'],[9])

    def test_declining_cross_keeps_normal_play_and_new_hand_opportunities(self):
        for next_play in (False, True):
            g=table();g.interactive=True;g.turn=2
            for seat in (1,2,3):g.players[seat]['bot']=True
            g.hands[2]=cards([5,9],prefix='c');g.hands[1]=cards([6,8],prefix='b')
            g.hands[0]=cards([5,5,6,6,8],prefix='a')
            g.action(2,'play',['c0']);g.action(0,'pass')
            if next_play:
                g.action(1,'play',['b0'])
                self.assertTrue(any(m['action']=='cross' for m in g.candidates(0)))
            else:
                g.action(1,'pass')
                self.assertTrue(any(m['action']=='play' and m['ids']==['a4'] for m in g.candidates(0)))
                self.assertFalse(any(m['action']=='cross' for m in g.candidates(0)))
            self.assertEqual(g.snapshot()['priority_declined'],{0:1})

    def test_declining_hook_keeps_urgent_gift_available(self):
        g=table();g.interactive=True;g.turn=3
        for seat in (1,2,3):g.players[seat]['bot']=True
        g.hands[3]=cards([5,8],prefix='d');g.hands[2]=cards([5,5,9],prefix='c')
        g.hands[1]=cards([6,7],prefix='b');g.hands[0]=cards([5,18,9],prefix='a')
        g.action(3,'play',['d0']);g.action(2,'cross',['c0','c1']);g.action(0,'pass');g.action(1,'pass')
        self.assertFalse(g.forced_pass())
        g.action(0,'urgent',['a1','a2'],target=1)
        self.assertTrue(g.forced_pass())

    def test_unanswered_cross_auto_passes_back_to_owner_or_partner(self):
        for finished in (False, True):
            g=table('basic');g.turn=0
            g.hands[0]=cards([5,9],prefix='a');g.hands[3]=cards([5,5]+([] if finished else [8]),prefix='b')
            g.hands[2]=cards([6,7],prefix='c');g.hands[1]=cards([6,8],prefix='d')
            g.action(0,'play',['a0']);g.action(3,'cross',['b0','b1'])
            skipped=[]
            while g.forced_pass():
                skipped.append(g.turn);g.action(g.turn,'pass')
            self.assertEqual(skipped,[2,1,0]);self.assertIsNone(g.last)
            self.assertEqual(g.turn,1 if finished else 3)
            self.assertFalse(g.forced_pass())
            g.action(g.turn,'play',[g.hands[g.turn][0]['id']])

    def test_dead_and_other_specials_keep_legal_responses_and_free_lead(self):
        g=table(options={'advancedDead':True});g.turn=0
        g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,5,5,9],prefix='b')
        g.action(0,'play',['a0','a1']);g.action(3,'dead',['b0','b1','b2'])
        self.assertEqual(g.turn,3);self.assertFalse(g.forced_pass())
        g.action(3,'play',['b3']);self.assertFalse(g.forced_pass())
        g=table(options={'advancedDead':True});g.turn=0
        g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,5,5],prefix='b')
        g.action(0,'play',['a0','a1']);g.action(3,'dead',['b0','b1','b2'])
        self.assertEqual(g.turn,1);self.assertFalse(g.forced_pass())
        g.action(1,'play',[g.hands[1][0]['id']])
        g=table();g.turn=0
        g.hands[0]=cards([5,5,8],prefix='a');g.hands[3]=cards([5,9],prefix='b')
        g.hands[2]=cards([6,7],prefix='c')
        g.action(0,'play',['a0','a1']);g.action(3,'dot',['b0'])
        self.assertTrue(g.forced_pass())
        g.hands[2]=cards([15,7],prefix='c');self.assertFalse(g.forced_pass())
        g.negotiation={'target':2};self.assertFalse(g.forced_pass())

    def test_four_card_airplanes_with_two_units_per_group(self):
        for mode in ('standard', 'trio'):
            for wings in ([8, 9, 10, 11], [8, 8, 9, 10], [8, 8, 9, 9, 10, 10, 11, 11]):
                ranks = [5]*4 + [6]*4 + wings
                combo = classify(ranks, mode)
                self.assertIsNotNone(combo)
                self.assertEqual((combo['bodySize'], combo['bodyWidth'], combo['power']), (4, 2, 0))
                g = table(mode); g.turn = 0
                g.hands[0] = cards(ranks, prefix='a') + cards([13], prefix='z')
                chosen = g.hands[0][:-1]
                self.assertTrue(any(set(m['ids']) == {c['id'] for c in chosen} for m in g.candidates(0)))
                g.action(0, 'auto', [c['id'] for c in chosen])
                following = cards([6]*4 + [7]*4 + wings)
                self.assertEqual(g.validate_play(g.turn, following)[0]['value'], 7)
                with self.assertRaises(RuleError): g.validate_play(g.turn, cards([5]*4 + [6]*4 + wings))
                self.assertIsNone(classify(ranks, 'landlord'))
                self.assertIsNone(classify(ranks, 'basic'))

    def test_extended_airplane_wildcards_hui_and_group_sizes(self):
        for size in (4, 5, 6):
            ranks = [5]*size + [6]*size + [9]*(2*(size-2))
            self.assertIsNotNone(classify(ranks, 'standard'))
        self.assertIsNone(classify([5]*4 + [6]*4 + [9]*5, 'standard'))
        g = table(options={'advancedHui': True})
        old = cards([7]*4 + [8]*4 + [9, 10, 11, 12])
        g.last = {**classify([c['rank'] for c in old], 'standard'), 'cards': old, 'special': 'play'}
        chosen = cards([5]*4 + [6]*3 + [9, 9, 10, 10], prefix='a') + cards([14], 'S', 'w')
        combo = g.validate_play(0, chosen, 'hui', {'w0': {'rank': 6, 'suit': 'H'}})[0]
        self.assertEqual(combo['baseKind'], '四张飞机带四单')
        g.last = None; g.hands[0] = chosen + cards([13], prefix='z')
        self.assertTrue(any(set(m['ids']) == {c['id'] for c in chosen} for m in g.candidates(0)))

    def test_rps_tie_and_4a4_equal_length_tiebreak(self):
        g=table();g.phase='rps';g.reveals=[0,1]
        g.action(0,'rps',value='rock');g.action(1,'rps',value='rock')
        self.assertEqual(g.phase,'rps');self.assertEqual(g.rps,{})
        g.action(0,'rps',value='scissors');g.action(1,'rps',value='paper')
        self.assertEqual(g.turn,0)
        self.assertEqual(g.phase,'play')
        self.assertIn('猜拳获胜：0，先出牌。', g.log)
        g.action(0,'auto',[g.hands[0][0]['id']])
        low=classify([4]*5+[14]*2,'standard');high=classify([4]*4+[14]*3,'standard')
        self.assertLess(low['power'],high['power']);self.assertLess(low['value'],high['value'])

    def test_report_announces_only_first_threshold_per_player_per_game(self):
        for mode in ('basic','standard','trio'):
            g=table(mode);g.hands[0]=cards([6]*11)
            g.report(0);self.assertNotIn(0,g.reported)
            g.hands[0].pop();g.report(0)
            g.hands[0].pop();g.report(0)
            g.hands[0]=cards([6]*12);g.report(0)
            g.hands[0]=cards([6]*8);g.report(0)
            g.report(1)
            self.assertEqual(g.report_counts[0],10)
            self.assertEqual(g.report_counts[1],len(g.hands[1]))
            self.assertEqual(g.reported,{0,1})
            fresh=table(mode);fresh.report(0);self.assertEqual(fresh.reported,{0})
        g=table('landlord');g.report(0);self.assertFalse(g.reported)

    def test_report_flag_is_restored_with_negotiation_snapshot(self):
        g=table();snapshot=g.snapshot();g.report(0)
        self.assertIn(0,g.reported)
        for key,value in snapshot.items():setattr(g,key,value)
        self.assertNotIn(0,g.reported)
        g.report(0);self.assertEqual(g.report_counts[0],len(g.hands[0]))

    def test_urgent_and_announcements(self):
        g=table();g.hands[0]=cards([18,6,9],prefix='a')
        g.action(0,'urgent',['a0','a1'],target=3)
        self.assertEqual(g.turn,0);self.assertEqual(len(g.hands[3]),6)
        self.assertEqual(g.report_counts[0],1)
        self.assertFalse(any('爆牌' in l for l in g.log))
        self.assertTrue(any('赠送【红桃6】' in l for l in g.log))
        self.assertIsNone(g.last)
        g.action(0,'play',['a2']);self.assertEqual(g.last['ranks'],[9])
        g=table();g.hands[0]=cards([8],prefix='a');g.hands[3]=cards([18,18,6,7,9],prefix='b')
        g.action(0,'play',['a0']);previous=g.last
        g.action(3,'urgent',['b0','b2'],target=2)
        g.action(3,'urgent',['b1','b3'],target=1)
        self.assertEqual(g.turn,3);self.assertEqual(g.last,previous)
        self.assertEqual(g.last_seat,0);self.assertEqual(g.passes,set())
        g.action(3,'play',['b4']);self.assertEqual(g.last['ranks'],[9])
        g=table();g.hands[0]=cards([18,6],prefix='a');g.action(0,'play',['a1'])
        self.assertIn(0,g.urgent_last);self.assertEqual(g.turn,3)
        g=table();g.hands[0]=cards([18,6],prefix='a');g.action(0,'urgent',['a0','a1'],target=3)
        self.assertEqual(g.turn,3)

    def test_each_seat_retains_only_latest_public_play(self):
        g=table();g.hands[0]=cards([6,10,11],prefix='a');g.hands[1]=cards([9,12],prefix='b');g.hands[2]=cards([8,13],prefix='c');g.hands[3]=cards([7,14],prefix='d')
        for s in (0,3,2,1):g.action(s,'play',[chr(97+s)+'0'])
        g.action(0,'play',['a1'])
        self.assertEqual(g.play_number,5)
        self.assertEqual([p['order'] for p in g.seat_plays],[5,4,3,2])
        self.assertEqual(g.seat_plays[0]['cards'][0]['id'],'a1')
        for s in (3,2,1):g.action(s,'pass')
        self.assertIsNone(g.last);self.assertEqual(g.play_number,5)
        view=g.view(2)
        self.assertEqual(len(view['seatPlays']),4)
        self.assertNotIn('a2',str(view['seatPlays']))
        self.assertNotIn('hands',view)
        self.assertEqual(Game('standard',g.players).seat_plays,[None]*4)

    def test_last_opposite_pair_settles_and_reveals_remaining_hands(self):
        for mode in ('basic','standard'):
            g=table(mode);g.hands[0]=cards([6],prefix='a');g.hands[2]=cards([8],prefix='c')
            self.assertIsNone(g.view(0)['remainingHands'])
            g.action(0,'auto',['a0']);g.action(3,'pass');g.action(2,'auto',['c0'])
            self.assertEqual(g.phase,'over');self.assertEqual(g.winner,[0,2]);self.assertEqual(g.scores,[2,0]);self.assertEqual(g.next_main,5)
            self.assertEqual(len(g.hands[1]),5);self.assertEqual(len(g.hands[3]),5)
            for viewer in range(4):
                revealed=g.view(viewer)['remainingHands']
                self.assertEqual([len(h) for h in revealed],[0,5,0,5])
                self.assertEqual({c['id'] for c in revealed[1]},{c['id'] for c in g.hands[1]})
            with self.assertRaises(RuleError):g.action(1,'pass')
        g=table();g.hands[0]=cards([6],prefix='a');g.hands[3]=cards([7],prefix='d')
        g.action(0,'auto',['a0']);g.action(3,'auto',['d0'])
        self.assertEqual(g.phase,'play');self.assertIsNone(g.view(0)['remainingHands'])

    def test_team_winner_and_scoring(self):
        g=table();g.hands[0]=cards([5],prefix='a');g.hands[1]=cards([8],prefix='b');g.hands[2]=cards([7],prefix='c');g.hands[3]=cards([6],prefix='d')
        for seat in (0,3,2):g.action(seat,'play',[chr(97+seat)+'0'])
        self.assertEqual(g.winner,[0,2]);self.assertEqual(g.scores,[1,0]);self.assertEqual(g.next_main,4)
        g=table();g.finished=[0,1];g.hands[0]=[];g.hands[1]=[];g.hands[3]=cards([8],prefix='d');g.turn=3
        g.action(3,'play',['d0']);self.assertEqual(g.winner,[0,2]);self.assertEqual(g.scores,[0,0]);self.assertEqual(g.next_main,3)

    def test_first_finisher_team_upgrade_all_orders(self):
        for mode in ('basic','standard'):
            for order in itertools.permutations(range(4)):
                g=table(mode);g.scores=[4,7]
                for seat in order:
                    g.hands[seat]=[];g.finish(seat)
                    if g.phase=='over':break
                team=order[0]%2
                caught=3-order.index((order[0]+2)%4)
                expected=[4,7];expected[team]+=caught
                self.assertEqual(g.winner,[s for s in range(4) if s%2==team],order)
                self.assertEqual(g.scores,expected,order)
                self.assertEqual(g.next_main, list(range(3,16))[expected[team]%13],order)
                following=Game(mode,g.players,previous={'first':order[0],'main':g.next_main,'scores':g.scores})
                self.assertEqual(following.main,g.next_main)
                self.assertEqual(following.scores,expected)

    def test_team_main_tracks_each_team_across_rounds(self):
        g=table();g.scores=[8,5]
        for order, expected, next_main in (((0,2,1,3),[10,5],13),((1,0,3,2),[10,6],9),((0,1,3,2),[10,6],13)):
            g=Game('standard',g.players,previous={'main':g.next_main,'scores':g.scores})
            g.phase='play'
            for seat in order:
                g.hands[seat]=[];g.finish(seat)
                if g.phase=='over':break
            self.assertEqual(g.scores,expected)
            self.assertEqual(g.next_main,next_main)

    def test_setup_promote_and_rps(self):
        g=Game('standard',[{'name':str(i)} for i in range(4)])
        g.hands[0]=cards([7]*6+[3],prefix='a');g.hands[0][-1]['suit']='S'
        g.hands[1]=cards([8]*6+[3],prefix='b');g.hands[1][-1]['suit']='S'
        g.action(0,'promote',rank=7);g.action(1,'promote',rank=8)
        g.action(0,'reveal');g.action(1,'reveal')
        for s in range(4):g.action(s,'confirm')
        self.assertEqual(g.phase,'rps');self.assertEqual(g.main,8)
        g.action(0,'rps',value='paper');g.action(1,'rps',value='rock')
        self.assertEqual(g.phase,'play');self.assertEqual(g.turn,0)

    def test_promotion_is_optional_for_humans_and_bots(self):
        g=table();g.phase='setup';g.hands[0]=cards([15]*6+[3,3],prefix='a')
        self.assertEqual(g.bot_action(0),{'action':'confirm'})
        for seat in range(4):g.action(seat,'confirm')
        self.assertEqual(g.main,3)
        g=table();g.phase='setup';g.hands[0]=cards([4]*6+[3],prefix='a')
        self.assertEqual(g.bot_action(0),{'action':'promote','rank':4})
        g.promotions[1]=15
        self.assertEqual(g.bot_action(0),{'action':'confirm'})
        # A human remains free to choose a legal promotion even if the bot would decline.
        g=table();g.phase='setup';g.hands[0]=cards([15]*6+[3,3],prefix='a')
        g.action(0,'promote',rank=15)
        for seat in range(4):g.action(seat,'confirm')
        self.assertEqual(g.main,15)

    def test_hint_candidates_include_wild_sequences_and_suit_responses(self):
        g=table();g.hands[0]=cards([5,6,8,9],prefix='a')+cards([14],'S','w')
        moves=g.candidates(0)
        self.assertTrue(any(m['label']=='顺子' and len(m['ids'])==5 for m in moves))
        g=table(options={'advancedHui':True});g.hands[0]=cards([7,7,9],prefix='a')
        g.hands[3]=cards([5,5],'C','b')+cards([5,5],'H','c')
        g.action(0,'play',['a0','a1'])
        self.assertTrue(any(m['action']=='hui' and set(m['ids'])=={'c0','c1'} for m in g.candidates(3)))
        g=table('landlord');g.hands[0]=cards([6,6,6,6,8,9],prefix='a')
        self.assertTrue(any(m['label']=='四带二' and len(m['ids'])==6 for m in g.candidates(0)))

    def test_spade_ace_can_substitute_urgent_but_never_a_joker(self):
        g=table();g.hands[0]=cards([14],'S','w')+cards([6,9],prefix='a')
        g.action(0,'urgent',['w0','a0'],target=1,wildcard={'w0':18})
        self.assertEqual([c['id'] for c in g.hands[0]],['a1'])
        self.assertTrue(any(c['id']=='a0' for c in g.hands[1]))
        self.assertTrue(any('黑桃A代急牌' in log for log in g.log))
        g=table();g.hands[0]=cards([14,14],'S','w')+cards([18],prefix='u')
        with self.assertRaises(RuleError):g.action(0,'urgent',['w0','u0'],target=1,wildcard=18)
        with self.assertRaises(RuleError):g.action(0,'urgent',['w0','w1'],target=1,wildcard=17)
        moves=g.candidates(0)
        move=next(m for m in moves if m['label']=='黑桃A代急牌')
        g.action(0,**move)
        self.assertTrue(any(c['id']=='w1' for c in g.hands[1]))

    def test_full_bot_games(self):
        for mode in MODES:
            for options in ({}, {'advancedHui':True,'advancedDead':True,'dlc':True}):
                with self.subTest(mode=mode,options=options):
                    g=Game(mode,[{'name':str(i),'bot':True} for i in range(MODES[mode])],options,interactive=True)
                    initial=len(g.cards)
                    for step in range(1000):
                        if g.phase=='over':break
                        for seat in range(len(g.players)):
                            move=g.bot_action(seat)
                            if move:g.action(seat,**move);break
                        else:self.fail('No legal bot action')
                        live_ids=[c['id'] for h in g.hands for c in h]
                        self.assertEqual(len(live_ids),len(set(live_ids)))
                        self.assertLessEqual(len(live_ids),initial)
                    self.assertEqual(g.phase,'over')
                    self.assertTrue(g.winner)

    def test_bot_preserves_groups_and_uses_sufficient_responses(self):
        g=table('landlord');g.landlord=0
        g.hands[0]=cards([3,4,5,6,7,8,8,8,9,9,15],prefix='a')
        move=g.bot_action(0)
        self.assertEqual([c['rank'] for c in g.hands[0] if c['id'] in move['ids']],[3,4,5,6,7])
        g=table('landlord');g.landlord=0;g.turn=2
        g.hands[2]=cards([6,8],prefix='c');g.action(2,'play',['c0'])
        g.hands[1]=cards([7,7,9,15,16,17],prefix='b')
        # Farmers pass on a safe partner's lead, even with playable larger cards.
        self.assertEqual(g.bot_action(1),{'action':'pass'})
        g.landlord=2;g.hands[2]=cards([8,10,11,12],prefix='c')
        move=g.bot_action(1)
        self.assertEqual(move['ids'],['b2'])
        g.hands[1]=cards([7,7,7,7,9,15],prefix='b')
        self.assertEqual(g.bot_action(1)['ids'],['b4'])
        g.hands[2]=cards([8],prefix='c')
        self.assertEqual(g.bot_action(1)['ids'],['b5'])
        # Hidden opponent ranks do not affect the decision; their public count does.
        g.hands[2]=cards([17],prefix='c')
        self.assertEqual(g.bot_action(1)['ids'],['b5'])
        g.hands[1]=cards([7],prefix='b')
        self.assertEqual(g.bot_action(1)['ids'],['b0'])

if __name__=='__main__':unittest.main()
