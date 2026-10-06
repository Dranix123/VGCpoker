import unittest
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

    def test_cross_then_hook_can_intercept_out_of_turn(self):
        for mode in ('basic', 'standard'):
            g=table(mode);g.hands[0]=cards([5,8],prefix='a');g.hands[3]=cards([5,5,9],prefix='d');g.hands[1]=cards([5,10],prefix='b')
            g.action(0,'play',['a0']);g.action(3,'cross',['d0','d1'])
            self.assertEqual(g.turn,2)
            g.action(1,'hook',['b0'])
            self.assertEqual(g.last['special'],'hook');self.assertEqual(g.last_seat,1)

    def test_priority_pause_and_multiplayer_agreement(self):
        for mode in ('basic', 'standard'):
            g=table(mode);g.interactive=True
            g.hands[0]=cards([5,8],prefix='a');g.hands[1]=cards([5,5,9],prefix='b')
            g.action(0,'play',['a0'])
            self.assertIn(1,g.priority['pending'])
            with self.assertRaises(RuleError):g.action(3,'play',['30'])
            self.assertEqual(g.view(3)['priority']['moves'],[])
            g.action(1,'priority-play',['b0','b1'],special='cross')
            self.assertEqual(g.negotiation['target'],3);self.assertEqual(len(g.hands[1]),3)
            g.action(3,'reject');self.assertIsNone(g.priority);self.assertEqual(len(g.hands[1]),3)
            g.open_priority();g.action(1,'priority-play',['b0','b1'],special='cross');g.action(3,'accept')
            self.assertEqual(g.last_seat,1);self.assertEqual(len(g.hands[1]),1)

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
        self.assertEqual([len(deck(m)) for m in MODES], [54, 110, 86, 54])
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
                 ([4,4,4,7,7], '三带二'), ([3,4,5,6,7], '顺子'), ([3,3,4,4,5,5], '连对'),
                 ([3,3,3,4,4,4], '飞机'), ([3,3,3,4,4,4,6,7], '飞机带单'),
                 ([3,3,3,4,4,4,6,6,7,7], '飞机带对'), ([4,4,4,4,5,6], '四带二'),
                 ([4,4,4,4,5,5,6,6], '四带两对'), ([4,4,4,4], '炸弹'), ([16,17], '王炸')]
        for ranks, kind in cases:
            with self.subTest(ranks=ranks): self.assertEqual(classify(ranks)['kind'], kind)
        self.assertIsNone(classify([11,12,13,14,15]))
        self.assertIsNone(classify([3,4,5,6,7], 'standard', 3))
        self.assertGreater(classify([3], 'standard', 3)['value'], classify([15], 'standard', 3)['value'])

    def test_bomb_order(self):
        groups = [[5]*4, [16,17], [5]*5, [5]*6, [16,17,17], [5]*7, [5]*8, [16,16,17,17], [5]*9, [5]*10, [4,4,4,14,14], [4]*4+[14]*2]
        powers = [classify(r, 'standard')['power'] for r in groups]
        self.assertEqual(powers, sorted(set(powers)))
        self.assertEqual(classify([5]*3, 'basic')['kind'], '炸弹')
        self.assertEqual(classify([4,14,4], 'basic')['kind'], '4A4')

    def test_wildcards(self):
        wild = cards([14,14], 'S', 'w')
        self.assertTrue(any(c['kind']=='炸弹' for c in interpretations(cards([7,7])+wild,'standard',3)))
        self.assertTrue(any(c['kind']=='顺子' for c in interpretations(cards([5,6,7])+wild,'standard',3)))
        self.assertTrue(any(c['kind']=='三带二' for c in interpretations(cards([7,7,8])+wild,'standard',3)))
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
        g.hands[1]=cards([9]*4+[10],prefix='d');g.action(1,'play',['d0','d1','d2','d3'])
        self.assertEqual(g.last['kind'],'炸弹')

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

    def test_advanced_hui_and_urgent_negotiation_boundary(self):
        g=table(options={'advancedHui':True});g.hands[0]=cards([7,7,9],prefix='a');g.hands[3]=cards([5,5,9],prefix='b');g.hands[2]=cards([6,6,9],prefix='c')
        g.action(0,'play',['a0','a1']);g.action(3,'hui',['b0','b1']);g.action(2,'play',['c0','c1'])
        self.assertEqual(g.last['kind'],'对子')
        g=table();g.hands[0]=cards([7],prefix='a');g.hands[3]=cards([8,9],prefix='b');g.hands[2]=cards([18,6,7],prefix='c');g.hands[1]=cards([7,7,9],prefix='d')
        g.action(0,'play',['a0']);g.action(3,'play',['b0']);g.action(2,'urgent',['c0','c1'],target=3)
        with self.assertRaises(RuleError):g.action(1,'negotiate',['d0','d1'],special='cross')
        with self.assertRaises(RuleError):g.action(2,'urgent',['c2'],target=3)

    def test_rps_tie_and_4a4_equal_length_tiebreak(self):
        g=table();g.phase='rps';g.reveals=[0,1]
        g.action(0,'rps',value='rock');g.action(1,'rps',value='rock')
        self.assertEqual(g.phase,'rps');self.assertEqual(g.rps,{})
        g.action(0,'rps',value='scissors');g.action(1,'rps',value='paper')
        self.assertEqual(g.turn,0)
        low=classify([4]*5+[14]*2,'standard');high=classify([4]*4+[14]*3,'standard')
        self.assertEqual(low['power'],high['power']);self.assertLess(low['value'],high['value'])

    def test_urgent_and_announcements(self):
        g=table();g.hands[0]=cards([18,6,9],prefix='a')
        g.action(0,'urgent',['a0','a1'],target=3)
        self.assertEqual(g.turn,0);self.assertEqual(len(g.hands[3]),6)
        self.assertTrue(any('爆牌' in l for l in g.log))
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

    def test_team_winner_and_scoring(self):
        g=table();g.hands[0]=cards([5],prefix='a');g.hands[1]=cards([8],prefix='b');g.hands[2]=cards([7],prefix='c');g.hands[3]=cards([6],prefix='d')
        for seat in (0,3,2):g.action(seat,'play',[chr(97+seat)+'0'])
        self.assertEqual(g.winner,[0,2]);self.assertEqual(g.scores,[1,0]);self.assertEqual(g.next_main,4)
        g=table();g.finished=[0,1];g.hands[0]=[];g.hands[1]=[];g.hands[3]=cards([8],prefix='d');g.turn=3
        g.action(3,'play',['d0']);self.assertEqual(g.winner,[1,3])

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
