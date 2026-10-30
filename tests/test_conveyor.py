import copy
import itertools
import random
import unittest
from unittest.mock import patch
from conveyor import ConveyorGame
from conveyor_skills import SKILLS, available
from engine import RuleError


class ConveyorRules(unittest.TestCase):
    def game(self, *skills, recycle=True):
        keys=list(skills)
        keys += [s for s in SKILLS if s not in keys][:4-len(keys)]
        players=[dict(id=i,name='玩家'+str(i),bot=True,skill=s) for i,s in enumerate(keys)]
        return ConveyorGame('conveyor',players,{'skillDlc':[1,2,3,4],'recycle':recycle},interactive=False)

    def table(self, g, hands):
        c=g.core
        c.phase='play';c.pending=[];c.last=None;c.last_seat=None;c.turn=0;c.finished=[];c.complete_owners=[];c.log=[]
        cards=[]
        c.hands=[]
        for s,ranks in enumerate(hands):
            hand=[]
            for item in ranks:
                rank,suit=item if isinstance(item,tuple) else (item,'H')
                card=dict(id='fixture-'+str(len(cards)),rank=rank,suit=suit)
                cards.append(card);hand.append(card)
            c.hands.append(hand)
        c.pile=[dict(id='pile-'+str(i),rank=7+i%8,suit='C') for i in range(40)]
        c.discard=[];c.zones=[[] for _ in c.hands];c.all_cards={x['id']:x for x in cards+c.pile}
        c.seat_plays=[None for _ in c.hands];c.initial_counts=list(map(len,c.hands))
        for resource in c.resources: resource['turns']=2
        c.priority=None;c.claims={};c.start_turn=None;c.lead_key=None
        return c

    def conservation(self,g):
        c=g.core
        cards=c.pile+c.discard+sum(c.hands,[])+sum(c.zones,[])
        cards += [x for r in c.resources for x in r.get('markCards',[])]
        cards += [x for q in c.pending if q['kind'] in ('stars','retain') for x in q.get('cards',[])]
        ids=[x['id'] for x in cards]
        self.assertEqual(len(ids),len(set(ids)), 'duplicate physical card')
        self.assertEqual(set(ids),set(c.all_cards),'lost physical card')

    def test_catalog_and_selection(self):
        self.assertEqual(len(SKILLS),30)
        self.assertEqual(len({s['name'] for s in SKILLS.values()}),30)
        self.assertTrue(all(2<=len(s['name'])<=4 for s in SKILLS.values()))
        self.assertEqual(len(available({})),7)
        self.assertEqual(len(available({'skillDlc':[1,2,3,4]})),30)
        self.assertEqual(len(available({'disabledSkills':['balance']})),6)
        g=self.game('balance','anchor','leap','stars')
        for owner in range(4):
            c=g.core;s=g.actor(owner);keep=SKILLS[c.skills[s]]['keep']
            self.assertEqual(len(c.hands[s]),SKILLS[c.skills[s]]['deal'])
            g.action(owner,'keep',[x['id'] for x in c.hands[s][:keep]])
        self.assertEqual(g.phase,'setup');self.conservation(g)
        with self.assertRaises(RuleError):g.action(0,'promote',rank=7)

    def test_initial_filtering_and_no_infinite_rejection(self):
        g=self.game('clean','gather')
        self.assertTrue(all(c['rank'] not in (4,5,6) for c in g.core.hands[0]))
        self.assertTrue(all(c['rank'] not in (3,15,16,17) for c in g.core.hands[1]))
        c=self.table(g,[[8],[9],[10],[11]])
        c.pile=[dict(id='forbidden',rank=4,suit='S')];c.discard=[]
        self.assertEqual(c.gain(0,2),[])
        self.assertEqual(len(c.discard),1)

    def test_rank_mapping_and_no_temporary_maximum(self):
        g=self.game('leap','ascend');c=g.core;c.main=5
        self.assertEqual(c.effective_rank(0,3),6)
        self.assertEqual(c.effective_rank(0,13),15)
        self.assertEqual(c.effective_rank(0,14),5)
        self.assertEqual(c.effective_rank(0,5),5)
        self.assertEqual(c.effective_rank(0,16),17)
        self.assertEqual(c.effective_rank(1,4),6)
        c.resources[1]['boost']=20
        self.assertEqual(c.effective_rank(1,3),5)
        self.assertEqual(c.effective_rank(1,15),15)

    def test_play_then_deal_and_pass_then_deal(self):
        g=self.game();c=self.table(g,[[4,6],[7,9],[8,10],[5,11]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(len(c.hands[0]),2)
        self.assertEqual(c.turn,3)
        g.action(3,'pass')
        self.assertEqual(len(c.hands[3]),3)
        self.assertEqual(c.turn,2)

    def test_no_deal_when_finished_and_partner_settlement(self):
        g=self.game();c=self.table(g,[[4],[7],[8],[9]])
        before=len(c.pile)
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertIn(0,g.finished);self.assertEqual(len(c.pile),before)
        c.hands[2]=[];c.finish(2)
        self.assertEqual(g.phase,'over');self.assertEqual(g.winner,[0,2])
        self.assertEqual(c.next_main,5)
        self.assertEqual(g.view(0)['remainingHands'][1][0]['rank'],7)

    def test_unplayed_stash_blocks_finish_marks_do_not(self):
        g=self.game('stash');c=self.table(g,[[],[7],[8],[9]])
        c.zones[0]=[dict(id='zone',rank=4,suit='S')]
        c.finish(0);self.assertNotIn(0,g.finished)
        c.zones[0]=[];c.resources[0]['money']=8;c.finish(0)
        self.assertIn(0,g.finished)

    def test_urgent_alone_can_finish_and_choice_of_effect(self):
        for effect in ('draw','discard','ban','shield','maximum','rotate'):
            with self.subTest(effect=effect):
                g=self.game();c=self.table(g,[[18],[7,9],[8,10],[11,12]])
                args={'effect':effect}
                if effect in ('draw','ban','maximum'):args['target']=1
                g.action(0,'urgent',[c.hands[0][0]['id']],**args)
                if effect!='rotate':self.assertIn(0,g.finished)
                self.assertEqual(c.pile[-1]['rank'],18)

    def test_urgent_ban_stack_anchor_and_blocked_deal(self):
        g=self.game('balance','anchor');c=self.table(g,[[18,18,4],[7],[8],[9]])
        for _ in range(2):g.action(0,'urgent',[c.hands[0][0]['id']],effect='ban',target=1)
        self.assertEqual(c.resources[1]['ban'],2)
        self.assertEqual(c.turn,0)
        c.turn=1;before=len(c.hands[1]);g.action(1,'pass')
        self.assertEqual(c.resources[1]['ban'],1);self.assertEqual(len(c.hands[1]),before+1)

    def test_urgent_rotation_excludes_anchor_and_held_urgent(self):
        g=self.game('balance','anchor');c=self.table(g,[[18,4],[7],[8,18],[9]])
        held=c.hands[2][1]['id']
        g.action(0,'urgent',[c.hands[0][0]['id']],effect='rotate',direction='counterclockwise')
        self.assertEqual([x['rank'] for x in c.hands[1]],[7])
        self.assertIn(held,[x['id'] for x in c.hands[2]])
        self.assertEqual([x['rank'] for x in c.hands[3]],[4])

    def test_recycle_checkbox(self):
        for enabled in (True,False):
            g=self.game(recycle=enabled);c=self.table(g,[[4],[7],[8],[9]])
            c.pile=[];c.discard=[dict(id='old',rank=10,suit='S')]
            gained=c.gain(0,1)
            self.assertEqual(len(gained),0)

    def test_balance_replaces_ordinary_deal(self):
        g=self.game('balance');c=self.table(g,[[4,5,6],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']])
        self.assertEqual(len(c.hands[0]),3);self.assertEqual(len(c.pile)+sum(len(q.get('cards',[])) for q in c.pending if q['kind']=='stars'),39);self.assertEqual(c.turn,3)

    def test_gift_replaces_ordinary_deal(self):
        g=self.game('gift');c=self.table(g,[[4,5],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']],target=1)
        self.assertEqual(len(c.hands[0]),3);self.assertEqual(len(c.hands[1]),2);self.assertEqual(len(c.pile),38)

    def test_pressure_uses_actual_two(self):
        g=self.game('pressure');c=self.table(g,[[15,4],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']],target=1)
        self.assertEqual(len(c.hands[1]),5);self.assertEqual(c.turn,0)

    def test_stash_and_retrieve(self):
        g=self.game('stash');c=self.table(g,[[4,5,6],[7],[8],[9]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.pending[0]['kind'],'stash')
        ids=[x['id'] for x in c.hands[0]];g.action(0,'choice',ids)
        self.assertEqual(len(c.zones[0]),2);self.assertEqual(c.hands[0],[]);self.assertNotIn(0,g.finished)
        g.action(0,'skill',ids,effect='retrieve');self.assertEqual(len(c.hands[0]),2)

    def test_reflux_mass_deal_and_return_to_bottom(self):
        g=self.game('reflux');c=self.table(g,[[4,4,4,4,6],[7],[8],[9]])
        ids=[x['id'] for x in c.hands[0][:4]];g.action(0,'auto',ids)
        self.assertEqual(c.pending[0]['kind'],'reflux')
        g.action(0,'choice',ids[:2]);self.assertEqual(len(c.discard),2)
        self.assertEqual([len(c.hands[s]) for s in (1,2,3)],[3,3,3])

    def test_money_buy_removes_entity_keeps_display(self):
        g=self.game('balance','money');c=self.table(g,[[4,6],[7],[8],[9]])
        c.resources[1]['money']=4;id=c.hands[0][0]['id'];g.action(0,'auto',[id])
        self.assertEqual(c.pending[0]['kind'],'buy')
        g.action(1,'choice',[id])
        self.assertEqual(c.resources[1]['money'],0)
        self.assertIn(id,[x['id'] for x in c.hands[1]])
        self.assertIn(id,[x['id'] for x in c.seat_plays[0]['cards']])
        self.assertNotIn(id,[x['id'] for x in c.discard])

    def test_scavenge_first_two_own_turns(self):
        g=self.game('balance','scavenge');c=self.table(g,[[4,6],[7],[8],[9]])
        id=c.hands[0][0]['id'];g.action(0,'auto',[id]);c.turn=1
        c.resources[1]['turns']=0
        g.action(1,'pass');self.assertEqual(c.pending[0]['kind'],'scavenge')
        g.action(1,'choice',[id]);self.assertEqual(c.resources[1]['turns'],1)
        self.assertEqual(len(c.hands[1]),3)

    def test_double_includes_five_combines_and_counts_two(self):
        g=self.game('double');c=self.table(g,[[13,5,8],[7],[8],[9]])
        ids=[x['id'] for x in c.hands[0][:2]]
        g.action(0,'auto',ids,double={'id':ids[0],'ranks':[5,5],'suits':['S','D']})
        self.assertEqual(c.last['n'],3);self.assertEqual(c.last['ranks'],[5,5,5])
        self.assertEqual(len(c.last['cards']),3)
        self.assertEqual(len(c.discard),2)
        g=self.game('double');c=self.table(g,[[13,4],[7],[8],[9]]);c.main=5
        with self.assertRaises(RuleError):g.action(0,'auto',[c.hands[0][0]['id']],double={'id':c.hands[0][0]['id'],'ranks':[5,5],'suits':['S','D']})

    def test_seven_store_and_release(self):
        g=self.game('seven');c=self.table(g,[[3,3,4,4,5,5,6,10],[7],[8],[9]])
        ids=[x['id'] for x in c.hands[0][:7]];g.action(0,'skill',ids,effect='store')
        self.assertEqual(c.resources[0]['marks'],7)
        g.action(0,'skill',effect='release',ranks=[3,4,5,6,7,8,9])
        self.assertEqual(c.last['kind'],'顺子');self.assertEqual(c.resources[0]['marks'],0)

    def test_blood_resource_and_optional_end_deal(self):
        g=self.game('blood');c=self.table(g,[[4,6],[7],[8],[9]])
        c.resources[0]['blood']=2;g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.resources[0]['blood'],1)
        c.turn=1;c.gain(0,3);self.assertEqual(c.resources[0]['blood'],4)

    def test_ascend_marks_change_future_actual_values(self):
        g=self.game('ascend');c=self.table(g,[[15,4,6],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']]);self.assertEqual(c.resources[0]['boost'],1)
        self.assertEqual(c.effective_rank(0,4),6)
        self.assertEqual(g.view(0)['hand'][0]['effective'],6)

    def test_extra_gather_redirect_request_and_trade_deal_choices(self):
        for skill in ('extra','gather','redirect','request','trade'):
            with self.subTest(skill=skill):
                g=self.game(skill);c=self.table(g,[[4,6],[7,9,10],[8],[9]])
                g.action(0,'auto',[c.hands[0][0]['id']])
                self.assertEqual(c.pending[0]['kind'],'deal')
                if skill=='redirect':g.action(0,'choice',effect='redirect',target=1);self.assertEqual(len(c.hands[1]),4)
                elif skill=='request':
                    g.action(0,'choice',effect='request');self.assertEqual(c.pending[0]['kind'],'give')
                else:g.action(0,'choice',value=3 if skill in ('extra','gather') else 1)

    def test_all_aces_wild(self):
        g=self.game('wild');c=self.table(g,[[(14,'D'),5,5,8],[7],[8],[9]])
        g.action(0,'auto',[x['id'] for x in c.hands[0][:3]])
        self.assertEqual(c.last['ranks'],[5,5,5])

    def test_twins_independent_order_targeting_and_finish(self):
        g=self.game('twins');c=self.table(g,[[4,6],[7,8],[9],[10],[11]])
        self.assertEqual(c.owners,[0,0,1,2,3]);self.assertEqual(c.next_seat(0),1)
        g.action(0,'auto',[c.hands[0][0]['id']],actor=0);self.assertEqual(c.turn,1)
        c.hands[1]=[];c.finish(1);self.assertIn(0,g.finished)
        self.assertIn(0,c.finished);self.assertIn(1,c.finished)
        with self.assertRaises(RuleError):g.action(1,'focus',actor=0)

    def test_pursuit_draw_to_response_and_no_end_deal(self):
        g=self.game('balance','pursuit');c=self.table(g,[[7,6],[(4,'D')],[8],[9]])
        g.action(0,'auto',[c.hands[0][0]['id']]);c.turn=1;c.start_turn=None;c.enter_turn()
        self.assertGreater(len(c.hands[1]),1)
        move=c.candidates(1)[0];before=len(c.pile);g.action(1,move['action'],move['ids'])
        self.assertEqual(len(c.pile),before)

    def test_debt_marks_resolve_on_free_lead(self):
        g=self.game('debt');c=self.table(g,[[5,7],[4,8],[9],[10]])
        c.turn=1;g.action(1,'auto',[c.hands[1][0]['id']]);c.turn=0
        g.action(0,'play',[c.hands[0][0]['id']]);self.assertEqual(c.resources[1]['debt'],1)
        c.turn=0;c.last=None;c.free_lead();self.assertEqual(c.resources[1]['debt'],0)

    def test_judgment_virtual_success_and_bottom(self):
        g=self.game('judgment');c=self.table(g,[[(4,'D')],[7,8],[9],[10]])
        c.turn=1;g.action(1,'play',[c.hands[1][0]['id']]);c.turn=0
        c.pile.insert(0,dict(id='judge',rank=8,suit='S'))
        g.action(0,'skill');self.assertEqual(c.last['ranks'],[8]);self.assertEqual(c.last['suits'],['O'])
        self.assertEqual(c.pile[-1]['id'],'judge')

    def test_trade_card_cost_and_no_ordinary_deal(self):
        g=self.game('trade');c=self.table(g,[[17,4],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']]);self.assertEqual(len(c.hands[0]),6);self.assertEqual(c.turn,0)

    def test_bond_both_directions_no_recursion_and_private_hands(self):
        g=self.game('bond');c=self.table(g,[[4,6],[7,8,9],[10],[11]])
        g.action(0,'auto',[c.hands[0][0]['id']]);self.assertEqual(c.pending[0]['kind'],'bond')
        g.action(0,'choice',target=1)
        # Binding precedes the scheduled ordinary deal.
        g.action(0,'choice',value=1)
        before=len(c.hands[0]);c.gain(1,2);self.assertEqual(len(c.hands[0]),before+2)
        c.take(1,[c.hands[1][0]]);self.assertEqual(c.pending[0]['kind'],'discard')
        self.assertEqual(g.view(0)['conveyor']['boundHands'][0]['name'],c.name(1))
        self.assertEqual(g.view(2)['conveyor']['boundHands'],[])

    def test_duel_simultaneous_reveal_and_short_hand_finishes(self):
        g=self.game('duel');c=self.table(g,[[13,4],[5,6],[7,8],[9,10]])
        c.free_lead();g.action(0,'choice',value=True)
        for owner in range(4):g.action(owner,'choice',[c.hands[owner][0]['id']])
        self.assertTrue(any('拼点：' in s for s in c.log));self.assertTrue(c.pending or g.finished)
        while c.pending and c.phase!='over':
            q=c.pending[0];s=q['seat'];g.action(s,'choice',[q['cards'][0]['id']])
        self.assertGreaterEqual(len(g.finished),1)

    def test_formation_reduced_pattern_and_triple_bomb(self):
        g=self.game('formation');c=self.table(g,[[4,4,14,6],[7],[8],[9]])
        g.action(0,'auto',[x['id'] for x in c.hands[0][:3]])
        self.assertEqual(c.last['kind'],'4A4')
        g=self.game('formation');c=self.table(g,[[5,5,5]+[7]*10,[7],[8],[9]])
        g.action(0,'auto',[x['id'] for x in c.hands[0][:3]]);self.assertEqual(c.last['kind'],'炸弹')

    def test_suitmarks_majority_deferred_and_clear(self):
        g=self.game('suitmark');c=self.table(g,[[(8,'S'),(8,'S'),(8,'H'),(4,'D'),9],[7],[10],[11]])
        c.suit_lead=dict(seat=0,target=1,suit='S');c.turn=0;c.last=None;c.free_lead()
        self.assertEqual(c.resources[1]['suits'],['S']);c.resources[1]['suits'].append('S')
        c.turn=1;c.start_turn=None;before=len(c.hands[1]);c.enter_turn()
        self.assertEqual(len(c.hands[1]),before+2);self.assertEqual(c.resources[1]['suits'],[])

    def test_spectators_never_receive_hands_choices_or_zone_cards(self):
        g=self.game('twins');c=g.core
        c.offer(0,'retain','private',cards=[c.pile.pop(0)])
        view=g.view(None)
        self.assertEqual(view['hand'],[]);self.assertIsNone(view['conveyor']['choice'])
        self.assertEqual(view['conveyor']['zone'],[])
        self.assertNotIn('markCards',view['conveyor']['actors'][0]['resources'])

    def test_formless_ignores_suits_repeats_and_requires_three_cards(self):
        g=self.game('formless');c=self.table(g,[[(5,'C'),(5,'D'),9],[(7,'S'),(7,'H'),8],[10],[11]])
        c.turn=1;g.action(1,'play',[x['id'] for x in c.hands[1][:2]]);c.turn=0
        c.hui_used=True
        combo,_=c.validate_play(0,c.hands[0][:2],'hui')
        self.assertEqual(combo['kind'],'回')
        c.hands[0]=c.hands[0][:2]
        with self.assertRaises(RuleError):c.validate_play(0,c.hands[0],'hui')

    def test_lifted_small_joker_can_be_played_and_announced(self):
        g=self.game('leap');c=self.table(g,[[(16,'J'),4],[7],[8],[9]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.last['ranks'],[17])
        self.assertEqual(c.last['cards'][0]['rank'],16)

    def test_urgent_finish_keeps_intervening_players_in_order(self):
        g=self.game();c=self.table(g,[[15,4],[7],[8],[18,9]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        g.action(3,'urgent',[x['id'] for x in c.hands[3]],effect='discard')
        self.assertEqual(c.turn,2)
        g.action(2,'pass');g.action(1,'pass')
        self.assertEqual(c.turn,0);self.assertIsNone(c.last)
        g.action(0,'auto',[c.hands[0][0]['id']])

    def test_urgent_finish_after_everyone_else_passed_restores_free_lead(self):
        g=self.game();c=self.table(g,[[15,4],[18,9],[8],[7]])
        g.action(0,'auto',[c.hands[0][0]['id']]);g.action(3,'pass');g.action(2,'pass')
        g.action(1,'urgent',[x['id'] for x in c.hands[1]],effect='discard')
        self.assertEqual(c.turn,0);self.assertIsNone(c.last)
        g.action(0,'auto',[c.hands[0][0]['id']])

    def test_spade_ace_can_be_used_as_urgent_with_chosen_effect(self):
        g=self.game();c=self.table(g,[[(14,'S'),4],[7],[8],[9]])
        id=c.hands[0][0]['id'];g.action(0,'urgent',[id],wildcard={id:18},effect='shield')
        self.assertEqual(c.resources[0]['shield'],3)
        self.assertEqual(c.pile[-1]['id'],id)

    def test_filtering_also_applies_to_gifts_and_rotation(self):
        g=self.game('gift','clean');c=self.table(g,[[4,9],[7],[8],[10]])
        g.action(0,'skill',[c.hands[0][0]['id']],target=1)
        self.assertTrue(all(x['rank']!=4 for x in c.hands[1]))
        self.assertEqual(len(c.hands[1]),2)

    def test_spent_resource_can_finish_and_advances_turn(self):
        g=self.game('ascend');c=self.table(g,[[15],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']])
        self.assertIn(0,g.finished);self.assertNotEqual(c.turn,0)

    def test_finish_returns_suspended_reveal_cards(self):
        g=self.game('stars');c=self.table(g,[[4],[7],[8],[9]])
        c.free_lead();before=len(c.pile)+len(c.pending[0]['cards'])
        c.hands[0]=[];c.finish(0)
        self.assertEqual(len(c.pile),before);self.assertEqual(c.pending,[])

    def test_shield_duration_counts_own_turns_not_priority_plays(self):
        g=self.game();c=self.table(g,[[4],[7],[8],[9]])
        c.resources[0]['shield']=3;c.end_deal(0,own_turn=False)
        self.assertEqual(c.resources[0]['shield'],3)
        c.end_deal(0,own_turn=True);self.assertEqual(c.resources[0]['shield'],2)

    def test_next_round_bonus_deals_and_keeps_one_extra_for_first_and_next(self):
        players=[dict(id=i,name=str(i),bot=True,skill=k) for i,k in enumerate(['balance','anchor','leap','stars'])]
        g=ConveyorGame('conveyor',players,{},previous={'first':1,'main':4,'scores':[0,1]})
        self.assertEqual(g.core.deal_counts,[7,8,10,9])
        self.assertEqual(g.core.keep_counts,[7,6,8,6])

    def test_all_ten_suit_pairs_resolve_and_clear(self):
        for pair in itertools.combinations_with_replacement('SHCD',2):
            with self.subTest(pair=pair):
                g=self.game();c=self.table(g,[[4,5,6,7,8],[9],[10],[11]])
                c.resources[0]['suits']=list(pair);c.enter_turn()
                self.assertEqual(c.resources[0]['suits'],[])
                while c.pending and c.phase!='over':
                    q=c.pending[0];owner=c.owners[q['seat']]
                    move=g.bot_action(owner);self.assertIsNotNone(move);g.action(owner,**move)

    def test_invalid_choice_rolls_back_everything(self):
        g=self.game('stars');c=self.table(g,[[4],[7],[8],[9]])
        c.free_lead();before=copy.deepcopy(c.__dict__)
        with self.assertRaises(RuleError):g.action(0,'choice',['invalid'])
        self.assertEqual(g.core.pile,before['pile']);self.assertEqual(g.core.pending,before['pending'])

    def test_buy_choices_only_keep_cards_not_returned_by_reflux(self):
        g=self.game('reflux','money');c=self.table(g,[[4,4,4,4,8],[7],[9],[10]])
        c.resources[1]['money']=4
        ids=[x['id'] for x in c.hands[0][:4]]
        g.action(0,'auto',ids)
        self.assertEqual(c.pending[0]['kind'],'reflux')
        g.action(0,'choice',ids[:1])
        self.assertEqual(c.pending[0]['kind'],'buy')
        self.assertEqual({x['id'] for x in c.pending[0]['cards']},set(ids[1:]))
        g.action(1,'choice',ids[1:2])
        self.assertIn(ids[1],{x['id'] for x in c.hands[1]})

    def test_physical_conservation_through_bot_actions(self):
        random.seed(24)
        g=self.game('reflux','money','twins','stars');self.conservation(g)
        for _ in range(65):
            for owner in range(4):
                move=g.bot_action(owner)
                if move:
                    g.action(owner,**move);self.conservation(g);break
            else:self.fail('bots stalled')
            if g.phase=='over':break

    def test_normal_candidates_never_include_urgent_cards(self):
        g=self.game('gift','bond','debt','formless')
        c=self.table(g,[[7,8],[18,7,8,9,10,11,12],[7,8],[7,8]])
        c.turn=1
        for move in c.candidates(1):
            chosen=c.select(1,move['ids'])
            self.assertFalse(any(card['rank']==18 for card in chosen))
        move=g.bot_action(1)
        self.assertEqual(move['action'],'urgent')
        self.assertIn(move['effect'],('ban','discard'))
        g.action(1,**move)

    def test_first_two_empty_hands_refill_once_third_can_finish(self):
        for turns in (0,1,2):
            g=self.game();c=self.table(g,[[7],[8,9],[10,11],[12,13]])
            c.resources[0]['turns']=turns
            before=len(c.pile)
            g.action(0,'auto',[c.hands[0][0]['id']])
            if turns<2:
                self.assertNotIn(0,c.finished);self.assertEqual(len(c.hands[0]),1)
                self.assertEqual(len(c.pile),before-1)
            else:self.assertIn(0,c.finished)

    def test_twins_keep_seven_assigns_remaining_seven_to_second(self):
        g=self.game('twins','anchor','leap','stars');c=g.core
        ids=[x['id'] for x in c.hands[0][:7]];other=[x['id'] for x in c.hands[0][7:]]
        g.action(0,'keep',ids)
        self.assertEqual([x['id'] for x in c.hands[0]],ids)
        self.assertEqual([x['id'] for x in c.hands[1]],other)
        self.assertFalse(any(q['kind']=='split' for q in c.pending))

    def test_special_interrupt_deals_to_skipped_actor(self):
        g=self.game('balance','anchor','money','stars');c=self.table(g,[[7,8],[9,10],[7,11],[7,7,12]])
        g.action(0,'auto',[c.hands[0][0]['id']]);before=len(c.hands[3])
        # Turn order is 0,3,2,1: actor 2 interrupts actor 3 with a cross.
        c.hands[2][1]['rank']=7
        g.action(2,'auto',[x['id'] for x in c.hands[2] if x['rank']==7])
        self.assertEqual(len(c.hands[3]),before+1)

    def test_empty_pile_early_empty_turn_advances_without_stalling(self):
        g=self.game();c=self.table(g,[[],[7,8],[9,10],[11,12]])
        c.pile=[];c.resources[0]['turns']=0
        c.enter_turn()
        self.assertEqual(c.resources[0]['turns'],1)
        self.assertNotIn(0,c.finished)
        self.assertEqual(c.turn,3)
        c.turn=0;c.start_turn=None;c.enter_turn()
        self.assertEqual(c.resources[0]['turns'],2)
        c.turn=0;c.start_turn=None;c.enter_turn()
        self.assertIn(0,c.finished)

    def test_bot_with_two_urgent_cards_discards_only_ordinary_card(self):
        g=self.game();c=self.table(g,[[18,7,18],[8,9],[10,11],[12,13]])
        move=g.bot_action(0)
        self.assertEqual(move['effect'],'discard')
        self.assertEqual(len([x for x in c.select(0,move['ids']) if x['rank']==18]),1)
        g.action(0,**move)


if __name__=='__main__':unittest.main()
