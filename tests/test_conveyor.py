import copy
import itertools
import json
import random
import unittest
from unittest.mock import patch
from conveyor import ConveyorGame
from conveyor_skills import SKILLS, available
from engine import RuleError


class ConveyorRules(unittest.TestCase):
    def game(self, *skills, recycle=True, first_out=False):
        keys=list(skills)
        keys += [s for s in SKILLS if s not in keys][:4-len(keys)]
        players=[dict(id=i,name='玩家'+str(i),bot=True,skill=s) for i,s in enumerate(keys)]
        return ConveyorGame('conveyor',players,{'skillDlc':[1,2,3,4,5],'recycle':recycle,'firstOutEndsRound':first_out},interactive=False)

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
        for resource in c.resources: resource.update(turns=2,turnStart=2)
        c.priority=None;c.start_turn=None;c.lead_key=None
        return c

    def conservation(self,g):
        c=g.core
        cards=c.pile+c.discard+sum(c.hands,[])+sum(c.zones,[])
        cards += c.destroyed
        cards += [x for r in c.resources for x in r.get('markCards',[])]
        cards += [x for q in c.pending if q['kind'] in ('stars','retain') for x in q.get('cards',[])]
        ids=[x['id'] for x in cards]
        self.assertEqual(len(ids),len(set(ids)), 'duplicate physical card')
        self.assertEqual(set(ids),set(c.all_cards),'lost physical card')

    def test_catalog_and_selection(self):
        self.assertEqual(len(SKILLS),36)
        self.assertEqual(len({s['name'] for s in SKILLS.values()}),36)
        self.assertEqual([s['name'] for s in SKILLS.values()], ['转换','稳阵','跨级','守望','回收','净化','聚宝','恩赐','藏拙','顺手牵羊','施压','烙印','拆解','重铸·七音','重铸·万化','重铸·嗜血','重铸·至高强化','重铸·丰收','替身','窃取','取舍','千变','如影随形','追猎','奉还','投骰','献祭','灵魂绑定','死斗','节流','救赎之力','追击之力','平衡之力','阴影之力','禁锢之力','激励之力'])
        self.assertEqual(len(available({})),7)
        self.assertEqual(len(available({'skillDlc':[1,2,3,4,5]})),36)
        self.assertEqual(len(available({'disabledSkills':['balance']})),6)
        g=self.game('balance','anchor','leap','stars')
        for owner in range(4):
            c=g.core;s=g.actor(owner);keep=SKILLS[c.skills[s]]['keep']
            self.assertEqual(len(c.hands[s]),SKILLS[c.skills[s]]['deal'])
            g.action(owner,'keep',[x['id'] for x in c.hands[s][:keep]])
        self.assertIn(g.phase,('setup','play'));self.conservation(g)
        with self.assertRaises(RuleError):g.action(0,'promote',rank=7)

    def test_repeated_skills_and_multiple_twins_keep_independent_actors(self):
        for key in ('balance', 'twins'):
            g = self.game(*([key] * 4))
            self.assertEqual(len(g.core.players), 8 if key == 'twins' else 4)
            for owner in range(4):
                seat = g.actor(owner)
                keep = SKILLS[key]['keep'] // (2 if key == 'twins' else 1)
                g.action(owner, 'keep', [c['id'] for c in g.core.hands[seat][:keep]])
            self.assertIn(g.phase, ('setup','play'))
            if key == 'twins': self.assertEqual(list(map(len, g.core.hands)), [7] * 8)
            self.conservation(g)

    def test_all_scavenge_cannot_start_without_a_legal_opener(self):
        with self.assertRaisesRegex(RuleError, '首出'):
            self.game(*(['scavenge']*4))

    def test_stars_requires_ordering_and_counts_each_active_identity(self):
        g=self.game('stars','twins','twins','anchor')
        c=self.table(g,[[4,5],[7,8,9],[10],[11,12],[13],[14]])
        c.free_lead()
        self.assertEqual(len(c.pending[0]['cards']),6)
        with self.assertRaisesRegex(RuleError,'当前选择'):
            g.action(0,'play',[c.hands[0][0]['id']])
        ordered = [card['id'] for card in reversed(c.pending[0]['cards'])]
        g.action(0,'choice',ordered)
        self.assertEqual([card['id'] for card in c.pile[:6]],ordered)
        self.conservation(g)

    def test_chase_force_depends_on_finishers_instead_of_remaining_cards(self):
        g=self.game('chase_force');c=self.table(g,[[7,18],[8],[9],[10]])
        c.resources[0]['turns']=0
        self.assertEqual(c.effective_rank(0,7),6)
        c.resources[0]['turns']=2
        c.gain(1, 8)
        self.assertEqual(c.effective_rank(0,7),6)
        c.take(3, c.hands[3][:]);c.finish(3)
        self.assertEqual(c.effective_rank(0,7),8)
        c.take(2, c.hands[2][:]);c.finish(2)
        self.assertEqual(c.effective_rank(0,7),10)
        self.assertEqual(c.effective_rank(0,15),c.main)
        self.assertEqual(c.effective_rank(0,16),16)

    def test_chase_force_counts_twins_once_and_adds_four_when_they_finish(self):
        g=self.game('chase_force','twins','anchor','balance')
        c=self.table(g,[[7,18],[8],[9],[10],[11]])
        self.assertEqual(c.effective_rank(0,7),11)
        self.assertEqual(c.effective_rank(0,18),18)
        c.take(1, c.hands[1][:]);c.finish(1)
        self.assertEqual(c.finished,[1,2])
        self.assertEqual(c.effective_rank(0,7),15)

    def test_chase_urgent_can_demote_but_other_cards_cannot_become_urgent(self):
        g=self.game('chase_force');c=self.table(g,[[18],[7],[8],[9]])
        card=c.hands[0][0]
        g.action(0,'auto',[card['id']])
        self.assertEqual(c.seat_plays[0]['ranks'],[17])
        g=self.game('chase_force');c=self.table(g,[[17,7],[8],[9],[10]])
        c.take(3, c.hands[3][:]);c.finish(3)
        card=c.hands[0][0];self.assertEqual(c.effective_rank(0,17),17)
        with self.assertRaises(RuleError):g.action(0,'urgent',[card['id']],effect='ban',target=1)
        g.action(0,'auto',[card['id']])
        self.assertEqual(c.seat_plays[0]['ranks'],[17])
        self.conservation(g)

    def test_request_empty_stash_hand_finishes_and_discards_zone(self):
        g=self.game('request','stash');c=self.table(g,[[7],[8],[9],[10]])
        c.zones[1]=[c.pile.pop()]
        c.offer(1,'give','窃取',recipient=0,count=1)
        g.action(1,'choice',[c.hands[1][0]['id']])
        self.assertIn(1,c.finished);self.assertFalse(c.zones[1]);self.conservation(g)

    def test_equilibrium_caps_batch_gains_and_blocks_cross_pattern_at_nine_cards(self):
        g=self.game('equilibrium');c=self.table(g,[[9],[7]*10,[8],[10]])
        self.assertTrue(c.cross_pattern_disabled(1));self.assertEqual(c.effective_rank(1,7),7)
        before=len(c.hands[1]);self.assertEqual(len(c.gain(1,4)),1)
        self.assertEqual(len(c.hands[1]),before+1);self.assertEqual(c.effective_rank(1,7),6)
        c.turn=2;g.action(2,'play',[c.hands[2][0]['id']]);c.turn=1
        with self.assertRaisesRegex(RuleError,'跨牌型'):g.action(1,'play',[x['id'] for x in c.hands[1][:4]])
        c.last=None;g.action(1,'play',[x['id'] for x in c.hands[1][:4]])
        c.hands[1]=c.hands[1][:9];self.assertFalse(c.cross_pattern_disabled(1))
        c.resources[0]['skillBan']=1
        self.assertEqual(len(c.gain(1,4)),4)

    def test_imprison_batch_gain_marks_and_ordinary_end_exemption(self):
        g=self.game('imprison');c=self.table(g,[[4],[7],[8],[9]])
        c.gain(1,1);self.assertEqual(c.resources[1]['prison'],1)
        c.gain(1,3);self.assertEqual(c.resources[1]['prison'],0);self.assertEqual(c.resources[1]['ban'],3)
        c.gain(2,4,end=True);self.assertEqual(c.resources[2]['prison'],0)
        self.conservation(g)

    def test_shadow_suppresses_target_skills_until_skipped_action_ends(self):
        g=self.game('shadow','leap','balance','ascend');c=self.table(g,[[4,5],[7],[8],[9]])
        c.resources[0]['covered']=1;c.free_lead()
        self.assertEqual(c.resources[1]['skillBan'],1);self.assertEqual(c.resources[3]['skillBan'],1)
        self.assertFalse(c.skill(1,'leap'));self.assertEqual(c.effective_rank(1,7),7)
        c.turn=1;g.action(1,'pass')
        self.assertEqual(c.resources[1]['skillBan'],0);self.assertTrue(c.skill(1,'leap'))
        self.assertEqual(len(c.hands[1]),2)
        self.assertEqual(c.resources[3]['skillBan'],1)

    def test_shadow_stacks_each_disable_but_deduplicates_targets_per_trigger(self):
        g=self.game('shadow','balance','shadow','pursuit');c=self.table(g,[[4,5],[7],[8],[9]])
        c.resources[0]['covered']=3;c.free_lead()
        self.assertEqual((c.resources[3]['skillBan'],c.resources[3]['ban']),(1,1))
        c.turn=2;c.resources[2]['covered']=3;c.free_lead()
        self.assertEqual((c.resources[3]['skillBan'],c.resources[3]['ban']),(2,2))
        for remaining in (1,0):
            c.turn=3
            with self.assertRaises(RuleError): g.action(3,'auto',[c.hands[3][0]['id']])
            before=len(c.hands[3]);g.action(3,'pass')
            self.assertEqual((c.resources[3]['skillBan'],c.resources[3]['ban']),(remaining,remaining))
            self.assertEqual(len(c.hands[3]),before+1)
        self.assertTrue(c.skill(3,'pursuit'))

    def test_shadow_skip_from_cross_consumes_both_bans(self):
        g=self.game('shadow','balance','money','pursuit');c=self.table(g,[[7,8],[9,10],[7,7,11],[12,13]])
        g.action(0,'auto',[c.hands[0][0]['id']]);self.assertEqual(c.turn,3)
        c.disable_skill(3)
        before=len(c.hands[3]);g.action(2,'auto',[x['id'] for x in c.hands[2][:2]])
        self.assertEqual((c.resources[3]['skillBan'],c.resources[3]['ban']),(0,0))
        self.assertEqual(len(c.hands[3]),before+1)
        self.assertEqual(c.seat_plays[3]['kind'],'禁手')

    def test_off_turn_urgent_silence_triggers_one_shadow_ban_and_respects_anchor(self):
        g=self.game('shadow','money','anchor','trade');c=self.table(g,[[4],[7],[8],[18,18,9]])
        c.turn=2
        c.resources[1]['money']=3
        for target in (1,2): g.action(3,'urgent',[c.hands[3][0]['id']],effect='silence',target=target)
        self.assertEqual(c.turn,2)
        self.assertEqual((c.resources[1]['skillBan'],c.resources[1]['ban'],c.resources[1]['money']),(3,1,3))
        self.assertEqual((c.resources[2]['skillBan'],c.resources[2]['ban']),(0,0))
        c.turn=1;g.action(1,'pass')
        self.assertEqual((c.resources[1]['skillBan'],c.resources[1]['ban']),(2,0))
        c.turn=1;g.action(1,'play',[c.hands[1][0]['id']])
        self.assertEqual((c.resources[1]['skillBan'],c.resources[1]['ban'],c.resources[1]['money']),(1,0,3))
        self.conservation(g)

    def test_silenced_binding_owner_temporarily_disables_both_views_and_mirroring(self):
        g=self.game('bond','money');c=self.table(g,[[4],[7],[8],[9]])
        c.bonds=[dict(owner=0,seats=[0,1])]
        c.disable_skill(1)
        c.gain(1,1);self.assertEqual(len(c.hands[0]),2)
        self.assertTrue(g.view(1)['conveyor']['boundHands'])
        c.disable_skill(0)
        c.gain(1,1);self.assertEqual(len(c.hands[0]),2)
        self.assertFalse(g.view(1)['conveyor']['boundHands'])

    def test_judgment_marks_stack_and_consume_once_per_judgment(self):
        g=self.game('trade');c=self.table(g,[[18,18,18,8],[7],[8],[9]])
        for effect in ('judge-boost','judge-boost','judge-color'):
            g.action(0,'urgent',[c.hands[0][0]['id']],effect=effect)
        self.assertEqual(c.judge(0,dict(rank=17,suit='J')),(35,None,'红色'))
        self.assertEqual(c.judge(0,dict(rank=16,suit='J')),(25,None,'黑色'))
        self.assertEqual(c.judge(0,dict(rank=8,suit='C')),(8,'S','黑色'))
        self.assertEqual(c.judge(0,dict(rank=8,suit='C')),(8,'C','黑色'))

    def test_delta_and_urgent_judgments_keep_distinct_color_and_suit(self):
        g=self.game('trade')
        c=self.table(g,[[4,9],[7],[8],[11]])
        c.resources[0]['judgeColor']=1
        self.assertEqual(c.judge(0,dict(rank=8,suit='T')),(8,'T','紫色'))
        self.assertEqual(c.judge(0,dict(rank=18,suit='U')),(2,None,None))
        self.assertEqual(c.resources[0]['judgeColor'],1)
        c.offer(0,'deal','献祭',maximum=1)
        c.pile[0]['rank'],c.pile[0]['suit']=17,'J'
        g.action(0,'choice',effect='judge')
        self.assertIn('献祭判定：大王（红色，无花色）。',c.log)
        self.assertEqual(len(c.hands[0]),3)

    def test_redemption_clears_physical_zones_and_counts_unique_mark_types(self):
        g=self.game('redemption','seven','stash','money');c=self.table(g,[[4,5,6],[7,8],[9,10],[11,12]])
        c.resources[1]['marks']=1;c.resources[1]['markCards']=[c.hands[1].pop()]
        c.resources[2]['money']=2;c.resources[3]['money']=3
        c.zones[2]=[c.hands[2].pop()]
        c.free_lead();self.assertEqual(c.pending[0]['kind'],'redemption')
        self.assertEqual(c.pending[0]['maximum'],2)
        self.assertFalse(c.zones[2]);self.assertFalse(c.resources[1]['marks'])
        self.conservation(g)
        g.action(0,'choice',[c.hands[0][0]['id']])
        self.assertEqual(len(c.hands[0]),2);self.conservation(g)

    def test_encourage_accumulates_after_first_gain_and_can_spend_partially(self):
        g=self.game('encourage');c=self.table(g,[[4,5,6],[7],[8],[9]])
        c.enter_turn();c.gain(0,1);self.assertEqual(c.resources[0]['inspire'],0)
        c.gain(0,3);self.assertEqual(c.resources[0]['inspire'],3)
        c.free_lead();self.assertEqual(c.pending[0]['kind'],'inspire')
        g.action(0,'choice',[c.hands[0][0]['id']])
        self.assertEqual(c.resources[0]['inspire'],2)
        c.turn=1;c.enter_turn();c.turn=0;c.resources[0]['turns']+=1;c.enter_turn()
        c.gain(0,1);self.assertEqual(c.resources[0]['inspire'],2)
        self.conservation(g)

    def test_initial_filtering_and_no_infinite_rejection(self):
        g=self.game('clean','gather')
        self.assertTrue(all(c['rank'] not in (4,5,6) for c in g.core.hands[0]))
        self.assertTrue(all(c['rank'] not in (3,15,16,17) for c in g.core.hands[1]))
        c=self.table(g,[[8],[9],[10],[11]])
        c.pile=[dict(id='forbidden',rank=4,suit='S')];c.discard=[]
        self.assertEqual(c.gain(0,2),[])
        self.assertEqual(len(c.discard),1)

    def test_clean_always_keeps_main_without_a_choice(self):
        g = self.game('clean')
        c = self.table(g, [[8], [7], [8], [9]])
        c.pile[0]['rank'] = c.main
        drawn = c.pile[0]['id']
        c.gain(0, 1)
        self.assertIn(drawn, [card['id'] for card in c.hands[0]])
        self.assertFalse(c.pending)
        c.receive(0, [dict(id='received-main', rank=c.main, suit='S')])
        self.assertFalse(c.pending)

    def test_trade_spade_judgment_draws_face_value(self):
        g = self.game('trade')
        c = self.table(g, [[8], [7], [8], [9]])
        c.pile[0]['suit'] = 'S'
        c.offer(0, 'deal', '结束发牌', maximum=1)
        g.action(0, 'choice', effect='judge')
        self.assertEqual(len(c.hands[0]),9) # one original, one normal, seven by judgment
        self.assertFalse(c.pending)
        self.conservation(g)

    def test_rank_mapping_and_no_temporary_maximum(self):
        g=self.game('leap','ascend');c=g.core;c.main=5
        self.assertEqual(c.effective_rank(0,3),25)
        self.assertEqual(c.effective_rank(0,13),15)
        self.assertEqual(c.effective_rank(0,14),5)
        self.assertEqual(c.effective_rank(0,5),5)
        self.assertEqual(c.effective_rank(0,16),17)
        self.assertEqual(c.effective_rank(1,4),25)
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

    def test_free_for_all_waits_for_third_finisher_and_rewards_first_two(self):
        g=self.game();c=self.table(g,[[4],[7],[8],[9]])
        before=len(c.pile)
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertIn(0,g.finished);self.assertEqual(len(c.pile),before)
        self.assertEqual(c.scores,[2,0,0,0])
        c.take(2,c.hands[2][:]);c.finish(2)
        self.assertEqual(g.phase,'play');self.assertEqual(c.scores,[2,0,1,0])
        c.take(1,c.hands[1][:]);c.finish(1)
        self.assertEqual(g.phase,'over');self.assertEqual(g.winner,[0])
        self.assertEqual(c.scores,[2,0,1,0]);self.assertEqual(c.next_main,5)
        self.assertEqual(g.view(0)['remainingHands'][3][0]['rank'],9)

    def test_first_out_option_awards_only_winner_and_preserves_other_hands(self):
        g=self.game('twins','money',first_out=True)
        c=self.table(g,[[4],[6],[7],[8],[9]])
        c.resources[2]['money']=4
        before=[hand[:] for hand in c.hands[1:]]
        g.action(0,'auto',[c.hands[0][0]['id']],actor=0)
        self.assertEqual(g.phase,'over')
        self.assertEqual(g.winner,[0])
        self.assertEqual(c.scores,[2,0,0,0])
        self.assertEqual(c.hands[1:],before)
        self.assertEqual(c.finished,[0,1])
        self.assertEqual(c.pending,[])
        self.assertIsNone(c.priority)
        self.assertTrue(c.round_complete)
        self.assertEqual(c.next_main,3)
        self.conservation(g)

    def test_first_out_option_still_requires_the_third_action(self):
        g=self.game(first_out=True);c=self.table(g,[[4],[7],[8],[9]])
        c.resources[0].update(turns=0,turnStart=0)
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(g.phase,'play')
        self.assertEqual(c.scores,[0,0,0,0])
        self.assertEqual(len(c.hands[0]),1)

    def test_individual_grades_follow_every_finish_order_and_persist(self):
        for order in itertools.permutations(range(4)):
            g=self.game();c=self.table(g,[[7],[8],[9],[10]])
            c.scores=[0,3,6,8];c.initial_scores=c.scores[:]
            expected=c.scores[:]
            expected[order[0]]=min(11,expected[order[0]]+2)
            expected[order[1]]=min(11,expected[order[1]]+1)
            for index,owner in enumerate(order[:3]):
                c.take(owner,c.hands[owner][:]);c.finish(owner)
                self.assertEqual(g.phase,'over' if index==2 else 'play')
            self.assertEqual(c.scores,expected)
            self.assertEqual(g.winner,[order[0]])
            self.assertEqual(c.next_main,expected[order[0]]+3)
            self.assertEqual(g.view(0)['conveyor']['gradeChanges'],[expected[i]-[0,3,6,8][i] for i in range(4)])
            c.take(order[3],c.hands[order[3]][:]);c.finish(order[3])
            self.assertEqual(c.scores,expected)
            following=ConveyorGame('conveyor',g.players,{},previous={'first':order[0],'main':c.next_main,'scores':c.scores})
            self.assertEqual(following.scores,expected)
            self.assertEqual(following.main,expected[order[0]]+3)

    def test_individual_grade_caps_at_ace_and_requires_an_ace_round(self):
        g=self.game();c=self.table(g,[[7],[8],[9],[10]])
        c.scores=[10,11,5,2];c.main=13
        for owner in (0,1,2):c.take(owner,c.hands[owner][:]);c.finish(owner)
        self.assertEqual(c.scores,[11,11,5,2]);self.assertEqual(c.next_main,14)
        self.assertFalse(c.round_complete)
        g=self.game();c=self.table(g,[[7],[8],[9],[10]])
        c.scores=[11,11,5,2];c.main=14
        for owner in (0,2,1):c.take(owner,c.hands[owner][:]);c.finish(owner)
        self.assertTrue(c.round_complete);self.assertEqual(c.next_main,3)
        self.assertEqual(c.scores,[11,11,6,2])

    def test_finished_free_for_all_lead_goes_to_next_seat(self):
        g=self.game();c=self.table(g,[[17],[7,8],[9,10],[11,12]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        for owner in (3,2,1):g.action(owner,'pass')
        self.assertIsNone(c.last);self.assertEqual(c.turn,3)

    def test_twins_share_one_individual_grade_and_one_finish_place(self):
        g=self.game('twins');c=g.core;c.phase='play';c.pending=[]
        for r in c.resources:r.update(turns=2,turnStart=2)
        for owner in (0,1,2):
            actor=next(s for s,o in enumerate(c.owners) if o==owner)
            c.take(actor,c.hands[actor][:]);c.finish(actor)
        self.assertEqual(g.finished,[0,1,2]);self.assertEqual(g.winner,[0])
        self.assertEqual(c.scores,[2,1,0,0]);self.assertEqual(len(c.finished),4)
        self.conservation(g)

    def test_rule_ai_targets_former_opposite_player_as_an_opponent(self):
        g=self.game('pressure');c=self.table(g,[[15,7,8],[6,7,8,9],[10],[6,7,8,9]])
        self.assertEqual(c.bot_action(0)['target'],2)
        g=self.game('balance');c=self.table(g,[[18,7,8,9],[6,7,8,9],[10],[6,7,8,9]])
        self.assertEqual(c.bot_action(0)['target'],2)

    def test_special_chain_keeps_urgent_options_instead_of_auto_skipping(self):
        for skill,hand in [('balance',[18,7,8]),('balance',[(14,'S'),7,8]),('chase_force',[18,7,8])]:
            twins = skill == 'chase_force'
            g=self.game(skill,'gift','anchor','twins' if twins else 'formless')
            hands=[hand,[6,9],[5,5,9],[5,8]]
            if twins: hands.append([8,9])
            c=self.table(g,hands)
            c.turn=3
            g.action(3,'play',[c.hands[3][0]['id']]);g.action(2,'cross',[x['id'] for x in c.hands[2][:2]]);g.action(1,'pass')
            self.assertEqual(c.turn,0);self.assertFalse(c.forced_pass(),skill)
            c.resources[0]['ban']=1;self.assertTrue(c.forced_pass())

    def test_unplayed_stash_blocks_finish_marks_do_not(self):
        g=self.game('stash');c=self.table(g,[[],[7],[8],[9]])
        c.zones[0]=[dict(id='zone',rank=4,suit='S')]
        c.finish(0);self.assertNotIn(0,g.finished)
        c.zones[0]=[];c.resources[0]['money']=8;c.finish(0)
        self.assertIn(0,g.finished)

    def test_urgent_alone_can_finish_and_choice_of_effect(self):
        for effect in ('draw','ban','shield','maximum','rotate'):
            with self.subTest(effect=effect):
                g=self.game();c=self.table(g,[[18],[7,9],[8,10],[11,12]])
                args={'effect':effect}
                if effect in ('draw','ban','maximum'):args['target']=1
                g.action(0,'urgent',[c.hands[0][0]['id']],**args)
                if effect!='rotate':self.assertIn(0,g.finished)
                if effect=='rotate':self.assertEqual(c.destroyed[0]['rank'],18)
                else:self.assertEqual(c.pile[-1]['rank'],18)

    def test_urgent_limit_belongs_to_each_physical_card_and_rotation_destroys_it(self):
        g=self.game();c=self.table(g,[[18,18,8],[9],[10],[11]])
        first,second=[card['id'] for card in c.hands[0][:2]]
        for _ in range(3):
            g.action(0,'urgent',[first],effect='shield')
            card=next(card for card in c.pile if card['id']==first);c.pile.remove(card);c.hands[0].append(card)
        g.action(0,'urgent',[second],effect='ban',target=1)
        self.assertEqual(c.urgent_uses,{first:3,second:1})
        with self.assertRaises(RuleError):g.action(0,'urgent',[first],effect='shield')
        g.action(0,'urgent',[first],effect='rotate')
        self.assertEqual([card['id'] for card in c.destroyed],[first])
        self.assertNotIn(first,[card['id'] for hand in c.hands for card in hand]+[card['id'] for card in c.pile+c.discard])
        self.conservation(g)

    def test_urgent_discard_must_keep_one_and_maximum_cannot_take_last(self):
        g=self.game();c=self.table(g,[[18,7,8],[9],[10],[11]])
        ids=[card['id'] for card in c.hands[0]]
        with self.assertRaises(RuleError):g.action(0,'urgent',ids,effect='discard')
        g.action(0,'urgent',ids[:2],effect='discard')
        self.assertEqual([card['rank'] for card in c.hands[0]],[8])
        g=self.game();c=self.table(g,[[18,7],[9],[10],[11]])
        g.action(0,'urgent',[c.hands[0][0]['id']],effect='maximum',target=1)
        self.assertEqual([card['rank'] for card in c.hands[1]],[9]);self.assertFalse(c.pending)

    def test_formation_adds_one_four_and_ace_before_original_grading(self):
        for rr,expected in [([4,4,14],105),([4,4,4,14],105),([4,4,4,14,14],107)]:
            g=self.game('formation');c=self.table(g,[rr+[9],[7],[8],[10]])
            g.action(0,'auto',[card['id'] for card in c.hands[0][:len(rr)]])
            self.assertEqual(c.last['kind'],'4A4');self.assertEqual(c.last['power'],expected)

    def test_formation_candidates_include_reduced_combos_in_large_hands(self):
        g=self.game('formation');c=self.table(g,[[4,4,14]+[9]*10,[7],[8],[10]])
        ids={card['id'] for card in c.hands[0][:3]}
        self.assertTrue(any(set(move['ids'])==ids and move['power']==105 for move in g.candidates(0)))

    def test_formation_uses_printed_ranks_when_aces_are_declared(self):
        g=self.game('formation');c=self.table(g,[[4,4,(14,'S'),9],[7],[8],[10]])
        cards=c.hands[0][:3]
        g.action(0,'auto',[card['id'] for card in cards],wildcard={cards[2]['id']:4})
        self.assertEqual(c.last['kind'],'4A4');self.assertEqual(c.last['ranks'],[4,4,14])

    def test_4a4_uses_printed_ranks_in_previews_and_actual_play(self):
        for ranks, expected in [([4,4,4,14,14], '4A4'), ([3,3,3,13,13], '三带一对')]:
            with self.subTest(ranks=ranks):
                g=self.game('ascend');c=self.table(g,[ranks+[9],[7],[8],[10]])
                c.main=7
                ids=[card['id'] for card in c.hands[0][:5]]
                self.assertEqual(g.preview_play(0,ids),expected)
                g.action(0,'auto',ids)
                self.assertEqual(c.last['kind'],expected)

    def test_pressure_is_usable_outside_own_turn(self):
        g=self.game('balance','pressure');c=self.table(g,[[7,8],[15,9],[10],[11]])
        before=len(c.hands[2]);g.action(1,'skill',[c.hands[1][0]['id']],target=2)
        self.assertEqual(len(c.hands[2]),before+4);self.assertEqual(c.turn,0)

    def test_pressure_can_interrupt_a_choice_and_refreshes_maximum_choices(self):
        g=self.game('pressure');c=self.table(g,[[15,9],[8],[10],[11]]);c.turn=2
        old=c.hands[1][0]['id'];c.offer(1,'maximum','最大牌',cards=c.hands[1][:],left=1)
        g.action(0,'skill',[c.hands[0][0]['id']],target=1)
        self.assertEqual(c.pending[0]['cards'],c.maximum(1))
        self.assertNotIn(old,[card['id'] for card in c.pending[0]['cards']])
        g.action(1,'choice',[c.pending[0]['cards'][0]['id']]);self.assertFalse(c.pending)

    def test_pressure_cannot_spend_a_card_already_committed_to_duel(self):
        g=self.game('pressure','duel');c=self.table(g,[[15,9],[13,8],[10],[11]])
        card=c.hands[0][0];c.duel=dict(owner=1,choices={0:card});c.offer(2,'duel','死斗')
        with self.assertRaisesRegex(RuleError,'死斗判定'):g.action(0,'skill',[card['id']],target=1)
        self.assertIn(card,c.hands[0]);self.conservation(g)

    def test_numeric_values_and_growth_through_original_main_position(self):
        g=self.game('leap','ascend');c=g.core;c.main=5
        self.assertEqual(c.effective_rank(0,3),25);self.assertEqual(c.effective_rank(1,4),25)
        for rank,value,judgment in [(11,11,11),(12,12,12),(13,13,13),(14,14,14),(15,15,15),(5,16,16),(16,17,20),(17,18,25),(18,0,2)]:
            card=dict(rank=rank,suit='S')
            self.assertEqual(c.card_value(2,card),value)
            self.assertEqual(c.judge(2,card)[0],judgment)
        self.assertEqual(c.judge(0,dict(rank=16,suit='J'),rank_only=True)[0],25)

    def test_judgment_can_raise_a_normal_bomb_but_not_royals(self):
        g=self.game('judgment');c=self.table(g,[[4],[7,7,7,7,9],[8],[10]])
        c.turn=1;g.action(1,'auto',[card['id'] for card in c.hands[1][:4]]);c.turn=0
        c.pile.insert(0,dict(id='judge-bomb',rank=8,suit='S'))
        old_suits=c.last['suits'][:];g.action(0,'skill')
        self.assertEqual(c.last['kind'],'炸弹');self.assertEqual(c.last['ranks'],[8]*4);self.assertEqual(c.last['suits'],old_suits)
        c.last.update(kind='王炸',power=4.5,ranks=[16,17]);self.assertEqual(c.higher_combos(),[])

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

    def test_urgent_rotation_returns_every_played_non_urgent_card(self):
        g=self.game();c=self.table(g,[[18,4],[7],[8,18],[9]])
        returned = [c.pile.pop() for _ in range(5)]
        other_urgent = c.hands[2].pop()
        c.discard.extend(returned + [other_urgent])
        urgent = c.hands[0][0]
        g.action(0,'urgent',[urgent['id']],effect='rotate')
        self.assertCountEqual(c.pile[-5:], returned)
        self.assertEqual(c.discard, [other_urgent])
        self.assertEqual(c.destroyed, [urgent])
        self.conservation(g)

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

    def test_balance_requires_enough_pile_cards_for_a_full_exchange(self):
        g=self.game('balance','equilibrium','anchor','anchor')
        c=self.table(g,[[4,5,6],[7],[8],[9]])
        selected = [card['id'] for card in c.hands[0][:2]]
        pile = c.pile[:]
        before = c.hands[0][:]
        for remaining in (0,1):
            with self.subTest(remaining=remaining):
                c.pile, c.discard = pile[:remaining], pile[remaining:]
                with self.assertRaisesRegex(RuleError,'牌堆不足'):
                    g.action(0,'skill',selected)
                self.assertEqual(c.hands[0],before)
        c.pile, c.discard = pile[:2], pile[2:]
        with self.assertRaisesRegex(RuleError,'平衡之力限制'):
            g.action(0,'skill',selected)
        draw = c.pile[0]
        g.action(0,'skill',selected[:1])
        self.assertIn(draw,c.hands[0])
        self.assertEqual(len(c.hands[0]),3)
        self.conservation(g)

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
        self.assertEqual(len(c.hands[1]),2)

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

    def test_seven_cannot_release_a_seven_card_bomb(self):
        g=self.game('seven');c=self.table(g,[[3,3,4,4,5,5,6,10],[7],[8],[9]])
        g.action(0,'skill',[card['id'] for card in c.hands[0][:7]],effect='store')
        c.turn=0
        with self.assertRaises(RuleError):g.action(0,'skill',effect='release',ranks=[7]*7)
        self.assertEqual(c.resources[0]['marks'],7)

    def test_scavenge_cannot_be_random_first_player(self):
        g=self.game('scavenge');c=g.core;c.first=None;c.pending=[];c.drafted=set(range(4))
        for hand in c.hands: hand[:] = [card for card in hand if not (card['rank']==3 and card['suit']=='S')]
        with patch('engine.random.randrange',return_value=0):c.draft_ready()
        self.assertEqual(c.phase,'play');self.assertNotEqual(c.turn,0)

    def test_scavenge_remains_optional_later_without_end_draw(self):
        g=self.game('balance','scavenge');c=self.table(g,[[4,6],[7,10],[8],[9]])
        card=c.hands[0][0];g.action(0,'auto',[card['id']]);c.turn=1;c.resources[1]['turns']=2
        before=len(c.pile)
        g.action(1,'skill')
        self.assertEqual(c.pending[0]['kind'],'scavenge')
        g.action(1,'choice',[card['id']])
        self.assertEqual(len(c.hands[1]),3)
        self.assertEqual(len(c.pile),before)

    def test_wild_all_aces_cannot_become_urgent(self):
        g=self.game('wild');c=self.table(g,[[(14,'S'),(14,'D'),8],[7],[8],[9]])
        for card in c.hands[0][:2]:
            with self.assertRaises(RuleError):g.action(0,'urgent',[card['id']],wildcard={card['id']:18},effect='shield')

    def test_pursuit_passing_has_no_end_draw(self):
        g=self.game('balance','pursuit');c=self.table(g,[[5,8],[7,10],[8],[9]])
        g.action(0,'auto',[c.hands[0][0]['id']]);c.turn=1
        before=len(c.pile);g.action(1,'pass')
        self.assertEqual(len(c.pile),before)

    def test_blood_draws_from_others_do_not_change_marks(self):
        g=self.game('blood');c=self.table(g,[[4,6],[7],[8],[9]])
        c.resources[0]['blood']=2;g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.resources[0]['blood'],1)
        c.turn=1;c.gain(0,3);self.assertEqual(c.resources[0]['blood'],1)

    def test_blood_balances_hand_without_regular_draw_or_recursive_marks(self):
        g=self.game('blood');c=self.table(g,[[4,6,8,10],[7],[8],[9]]);c.resources[0]['blood']=3
        before=len(c.pile);g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.resources[0]['blood'],2);self.assertEqual(len(c.pile),before)
        self.assertEqual(c.pending[0]['count'],1)
        g.action(0,'choice',[c.hands[0][0]['id']])
        self.assertEqual(len(c.hands[0]),2)
        c.resources[0]['blood']=5;c.end_deal(0,False)
        self.assertEqual(len(c.hands[0]),6);self.assertEqual(c.resources[0]['blood'],6)
        self.assertEqual(len(c.pile),before-4)

    def test_blood_draft_awards_one_mark_per_rejected_card(self):
        g=self.game('blood');c=g.core
        g.action(0,'keep',[x['id'] for x in c.hands[0][:5]])
        self.assertEqual(c.resources[0]['blood'],5)
        self.assertEqual(len(c.hands[0]),5);self.assertFalse(c.pending)
        self.conservation(g)

    def test_blood_shield_skips_draw_but_not_trim(self):
        g=self.game('blood');c=self.table(g,[[4,6,8],[7],[8],[9]]);c.resources[0].update(blood=2,shield=1)
        before=len(c.pile);g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(len(c.pile),before);self.assertEqual(c.pending[0]['count'],1)
        self.assertEqual(c.resources[0]['shield'],1)
        g.action(0,'choice',[c.hands[0][0]['id']])
        self.assertEqual(c.resources[0]['shield'],0)

    def test_blood_early_empty_refills_and_does_not_leak_into_next_action(self):
        g=self.game('blood');c=self.table(g,[[7,9],[7],[8],[10]]);c.resources[0]['turns']=0
        g.action(0,'auto',[c.hands[0][0]['id']]);self.assertEqual(c.pending[0]['count'],1)
        g.action(0,'choice',[card['id'] for card in c.hands[0]])
        self.assertNotIn(0,g.finished);self.assertEqual(len(c.hands[0]),1)
        self.assertNotIn('earlyRefill',c.resources[0])

    def test_second_turn_pending_discard_cannot_finish_before_third_turn(self):
        g=self.game('blood');c=self.table(g,[[7,7,7,8],[9,10],[11,12],[13,14]])
        c.resources[0].update(turns=1,blood=1)
        c.enter_turn()
        g.action(0,'auto',[card['id'] for card in c.hands[0][:3]])
        self.assertEqual(c.resources[0]['turns'],2)
        self.assertEqual(c.pending[0]['kind'],'discard')
        before=len(c.pile)
        g.action(0,'choice',[card['id'] for card in c.hands[0]])
        self.assertNotIn(0,c.finished)
        self.assertEqual(c.scores,[0,0,0,0])
        self.assertEqual(len(c.hands[0]),1)
        self.assertEqual(len(c.pile),before-1)
        c.turn=0;c.start_turn=None;c.last=None;c.priority=None
        c.enter_turn()
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertIn(0,c.finished)
        self.assertEqual(c.scores,[2,0,0,0])

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
        ids=[x['id'] for x in c.hands[0][:3]]
        with self.assertRaises(RuleError):g.action(0,'auto',ids,wildcard={ids[0]:16})
        g.action(0,'auto',ids)
        self.assertEqual(c.last['ranks'],[5,5,5])
        self.assertEqual(c.last['suits'],['D','H','H'])

    def test_undeclared_ace_keeps_its_printed_suit_when_returning(self):
        g=self.game('wild');c=self.table(g,[[(14,'H'),8],[7,9],[8],[9]])
        c.turn=1;g.action(1,'play',[c.hands[1][0]['id']])
        c.turn=0;g.action(0,'hui',[c.hands[0][0]['id']])
        self.assertEqual(c.last['kind'],'回')
        self.assertEqual(c.last['suits'],['H'])

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

    def test_judgment_virtual_success_and_discard(self):
        g=self.game('judgment');c=self.table(g,[[(4,'D')],[7,8],[9],[10]])
        c.turn=1;g.action(1,'play',[c.hands[1][0]['id']]);c.turn=0
        c.pile.insert(0,dict(id='judge',rank=8,suit='S'))
        g.action(0,'skill');self.assertEqual(c.last['ranks'],[8]);self.assertEqual(c.last['suits'],['H'])
        self.assertIn('judge',[card['id'] for card in c.discard])

    def test_trade_card_cost_and_no_ordinary_deal(self):
        g=self.game('trade');c=self.table(g,[[17,4],[7],[8],[9]])
        g.action(0,'skill',[c.hands[0][0]['id']]);self.assertEqual(len(c.hands[0]),6);self.assertEqual(c.turn,0)

    def test_bond_both_directions_no_recursion_and_private_hands(self):
        g=self.game('bond');c=self.table(g,[[4,6],[7,8,9],[10],[11]])
        g.action(0,'skill');self.assertEqual(c.pending[0]['kind'],'bond')
        g.action(0,'choice',target=1)
        g.action(0,'auto',[c.hands[0][0]['id']])
        g.action(0,'choice',value=1)
        self.assertEqual(c.bonds[0]['seats'], [0,1])
        before=len(c.hands[0]);c.gain(1,2);self.assertEqual(len(c.hands[0]),before+2)
        count=len(c.hands[0]);c.take(1,[c.hands[1][0]]);self.assertEqual(c.pending,[]);self.assertEqual(len(c.hands[0]),count)
        self.assertEqual(g.view(0)['conveyor']['boundHands'][0]['name'],c.name(1))
        self.assertEqual(g.view(2)['conveyor']['boundHands'],[])

    def test_bond_draft_requires_target_and_switch_replaces_only_own_link(self):
        g = self.game('bond', 'bond', 'stash', 'balance')
        c = g.core
        g.action(0, 'keep', [card['id'] for card in c.hands[0][:3]])
        self.assertTrue(c.pending[0]['required'])
        with self.assertRaises(RuleError): g.action(0, 'choice')
        g.action(0, 'choice', target=2)
        c.phase = 'play'; c.turn = 0; c.pending = []
        c.bonds.append(dict(owner=1, seats=[1,2]))
        c.zones[2] = [c.hands[2].pop()]
        self.assertEqual(g.view(0)['conveyor']['boundHands'][0]['zone'], c.zones[2])
        self.assertEqual(g.view(3)['conveyor']['boundHands'], [])
        g.action(0, 'skill')
        g.action(0, 'choice', target=3)
        self.assertEqual(c.bonds, [dict(owner=1,seats=[1,2]),dict(owner=0,seats=[0,3])])
        self.conservation(g)

    def test_duel_simultaneous_reveal_and_short_hands_keep_smallest(self):
        g=self.game('duel');c=self.table(g,[[13,4],[5,6],[7,8],[9,10]])
        c.free_lead();g.action(0,'choice',value=True)
        for owner in range(4):g.action(owner,'choice',[c.hands[owner][0]['id']])
        self.assertTrue(any('死斗：' in s for s in c.log))
        while c.pending and c.phase!='over':
            q=c.pending[0];s=q['seat'];g.action(s,'choice',[q['cards'][0]['id']])
        self.assertEqual([[card['rank'] for card in hand] for hand in c.hands],[[4],[6],[8],[10]])
        self.assertEqual(g.finished,[])

    def test_formation_reduced_pattern_and_triple_bomb(self):
        g=self.game('formation');c=self.table(g,[[4,4,14,6],[7],[8],[9]])
        g.action(0,'auto',[x['id'] for x in c.hands[0][:3]])
        self.assertEqual(c.last['kind'],'4A4')
        g=self.game('formation');c=self.table(g,[[5,5,5]+[7]*10,[7],[8],[9]])
        g.action(0,'auto',[x['id'] for x in c.hands[0][:3]]);self.assertEqual(c.last['kind'],'炸弹')

    def test_suitmark_triggers_on_single_suit_normal_play_and_special_reply(self):
        for prior,reply,kind in (([6],[(8,'S')],'play'),([8],[(8,'S'),(8,'S')],'cross')):
            g=self.game('suitmark');c=self.table(g,[reply+[9],prior+[10],[10],[11]])
            c.turn=1
            g.action(1,'play',[c.hands[1][0]['id']])
            g.action(0,'auto',[card['id'] for card in c.hands[0][:len(reply)]])
            self.assertEqual(c.last['special'],kind)
            self.assertEqual(c.resources[1]['suits'],['S'])
            self.assertFalse(c.pending)

    def test_suitmark_joker_without_suit_still_offers_a_mark(self):
        g=self.game('suitmark');c=self.table(g,[[(17,'J'),9],[7,10],[10],[11]])
        c.turn=1;g.action(1,'play',[c.hands[1][0]['id']])
        g.action(0,'auto',[c.hands[0][0]['id']])
        self.assertEqual(c.pending[0]['suits'],list('SHCD'))
        g.action(0,'choice',suit='C')
        self.assertEqual(c.resources[1]['suits'],['C'])

    def test_suitmark_choice_is_from_played_suits_and_resolves_immediately(self):
        g=self.game('suitmark');c=self.table(g,[[(8,'S'),(8,'H'),9],[7,7,10],[10],[11]])
        c.turn=1
        g.action(1,'play',[x['id'] for x in c.hands[1][:2]])
        g.action(0,'play',[x['id'] for x in c.hands[0][:2]])
        self.assertEqual(c.pending[0]['kind'],'suitmark')
        with self.assertRaises(RuleError):g.action(0,'choice',suit='D')
        g.action(0,'choice',suit='H');self.assertEqual(c.resources[1]['suits'],['H'])
        c.offer(0,'suitmark','烙印',target=1,suits=['S','H'])
        before=len(c.hands[1]);g.action(0,'choice',suit='S')
        self.assertEqual(c.resources[1]['suits'],[])
        if c.pending: g.action(1,'choice',[c.pending[0]['cards'][0]['id']])
        self.assertEqual(len(c.hands[1]),before+1)

    def test_binding_partners_are_public_but_their_hands_remain_private(self):
        g=self.game('bond');g.core.bonds=[dict(owner=0,seats=[0,1])]
        for viewer in (None,2):
            view=g.view(viewer)['conveyor']
            self.assertEqual(view['actors'][0]['boundTo'],['玩家1'])
            self.assertEqual(view['actors'][1]['boundTo'],['玩家0'])
            self.assertEqual(view['boundHands'],[])

    def test_bound_hand_matches_the_owners_order_and_effective_ranks(self):
        g=self.game('bond','leap','anchor','money')
        c=self.table(g,[[5,8],[(13,'S'),(7,'H'),(7,'C'),(3,'S')],[9],[10]])
        c.bonds=[dict(owner=0,seats=[0,1])]
        other=g.view(1)['hand']
        self.assertEqual(g.view(0)['conveyor']['boundHands'][0]['cards'],other)
        self.assertEqual([card['rank'] for card in other],[7,7,13,3])
        self.assertEqual([card['effective'] for card in other],[9,9,15,3])

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
        g=self.game();c=self.table(g,[[15,4],[7],[8],[18]])
        g.action(0,'auto',[c.hands[0][0]['id']])
        g.action(3,'urgent',[x['id'] for x in c.hands[3]],effect='shield')
        self.assertEqual(c.turn,2)
        g.action(2,'pass');g.action(1,'pass')
        self.assertEqual(c.turn,0);self.assertIsNone(c.last)
        g.action(0,'auto',[c.hands[0][0]['id']])

    def test_urgent_finish_after_everyone_else_passed_restores_free_lead(self):
        g=self.game();c=self.table(g,[[15,4],[18],[8],[7]])
        g.action(0,'auto',[c.hands[0][0]['id']]);g.action(3,'pass');g.action(2,'pass')
        g.action(1,'urgent',[x['id'] for x in c.hands[1]],effect='shield')
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

    def test_priority_play_consumes_one_shield_turn(self):
        g=self.game('balance','anchor','money','stars');c=self.table(g,[[7,8],[9,10],[7,7,11],[12,13]])
        c.resources[2]['shield']=3
        g.action(0,'play',[c.hands[0][0]['id']])
        g.action(2,'cross',[card['id'] for card in c.hands[2][:2]])
        self.assertEqual(len(c.hands[2]),1)
        self.assertEqual(c.resources[2]['shield'],2)
        self.conservation(g)

    def test_dead_dot_draws_before_automatic_passes_and_then_grants_free_lead(self):
        for rank in (15,3):
            with self.subTest(rank=rank):
                g=self.game('anchor','anchor','anchor','anchor')
                c=self.table(g,[[rank,rank,8],[10,11],[rank,9,10],[11,12]])
                c.interactive=True
                g.action(0,'play',[card['id'] for card in c.hands[0][:2]])
                first_draws=[card['id'] for card in c.pile[:5]]
                before=len(c.log)
                g.action(2,'auto',[c.hands[2][0]['id']])
                self.assertEqual(c.seat_plays[2]['kind'],'死点')
                self.assertEqual([c.hands[s][-1]['id'] for s in (2,3,1,0)],first_draws[:4])
                self.assertEqual(c.log[before+1:],[
                    '玩家2获得1张牌。',
                    '玩家3：不出（自动）。','玩家3获得1张牌。',
                    '玩家1：不出（自动）。','玩家1获得1张牌。',
                    '玩家0：不出（自动）。','玩家0获得1张牌。',
                    '玩家2获得自由牌权。',
                ])
                self.assertEqual(c.turn,2)
                self.assertIsNone(c.priority)
                with self.assertRaises(RuleError): g.action(3,'press',[c.hands[3][0]['id']])
                g.action(2,'play',[c.hands[2][0]['id']])
                self.assertEqual(c.hands[2][-1]['id'],first_draws[4])
                self.conservation(g)

    def test_dead_dot_waits_for_its_draw_choice_before_other_draws(self):
        g=self.game('anchor','extra','extra','anchor')
        c=self.table(g,[[15,15,8],[10,11],[15,9],[11,12]])
        g.action(0,'play',[card['id'] for card in c.hands[0][:2]])
        before=len(c.pile)
        g.action(2,'dot',[c.hands[2][0]['id']])
        self.assertEqual((c.pending[0]['seat'],c.pending[0]['kind']),(2,'deal'))
        self.assertEqual(len(c.pile),before)
        g.action(2,'choice',value=2)
        self.assertEqual((c.pending[0]['seat'],c.pending[0]['kind']),(1,'deal'))
        self.assertEqual(len(c.pile),before-3)
        self.assertNotIn('玩家2获得自由牌权。',c.log)
        g.action(1,'choice',value=1)
        self.assertEqual(len(c.pile),before-5)
        self.assertEqual(c.log[-1],'玩家2获得自由牌权。')
        self.conservation(g)

    def test_next_round_bonus_deals_and_keeps_one_extra_for_first_and_next(self):
        players=[dict(id=i,name=str(i),bot=True,skill=k) for i,k in enumerate(['balance','anchor','leap','stars'])]
        g=ConveyorGame('conveyor',players,{},previous={'first':1,'main':4,'scores':[0,1]})
        self.assertEqual(g.core.deal_counts,[7,8,10,9])
        self.assertEqual(g.core.keep_counts,[7,6,8,6])
        for owner in range(4):
            actor=g.actor(owner)
            g.action(owner,'keep',[card['id'] for card in g.core.hands[actor][:g.core.keep_counts[actor]]])
        self.assertEqual(g.phase,'play')
        self.assertIn('选牌完成。',g.log)

    def test_all_ten_suit_pairs_resolve_and_clear(self):
        for pair in itertools.combinations_with_replacement('SHCD',2):
            with self.subTest(pair=pair):
                g=self.game();c=self.table(g,[[4,5,6,7,8],[9],[10],[11]])
                c.resources[0]['suits']=[pair[0]];c.offer(1,'suitmark','烙印',target=0,suits=[pair[1]])
                g.action(1,'choice',suit=pair[1])
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
        turns=c.resources[2]['turns']
        g.action(2,'auto',[x['id'] for x in c.hands[2] if x['rank']==7])
        self.assertEqual(len(c.hands[3]),before+1)
        self.assertEqual(c.resources[2]['turns'],turns+1)

    def test_priority_cannot_rewind_a_newer_play(self):
        g=self.game('balance','anchor','money','stars')
        c=self.table(g,[[5,8],[5,5,9],[7],[6,10]])
        for player in g.players: player['bot']=False
        c.interactive=True
        g.action(0,'play',[c.hands[0][0]['id']])
        g.action(3,'play',[c.hands[3][0]['id']])
        with self.assertRaises(RuleError):
            g.action(1,'auto',[card['id'] for card in c.hands[1][:2]])
        view=json.loads(json.dumps(g.view(1)))
        self.assertIsNone(view['response'])
        self.assertNotIn('negotiation',view)
        self.assertEqual(view['lastSeat'],3)

    def test_three_group_airplane_hint_with_effective_ranks(self):
        g=self.game('leap','balance','anchor','money')
        c=self.table(g,[[6]*3+[7]*3+[8]*3+[10,11,15,12],[9],[10],[5]*3+[6]*3+[7]*3+[10,11,12,13]])
        c.turn=3;g.action(3,'play',[card['id'] for card in c.hands[3][:-1]])
        for seat in (2,1): g.action(seat,'pass')
        self.assertEqual(c.turn,0)
        move=next(m for m in g.candidates(0) if m['label']=='飞机带单' and m['n']==12)
        g.action(0,'auto',move['ids'])
        self.assertEqual(c.last['value'],10)

    def test_newly_drawn_card_can_dot_on_own_turn_after_priority_window(self):
        g=self.game('balance','anchor','money','stars');c=self.table(g,[[3,3,8],[9],[10],[11]])
        g.action(0,'play',[card['id'] for card in c.hands[0][:2]])
        self.assertFalse(any(move['action']=='dot' for move in g.candidates(1)))
        c.pile[0]['rank']=3
        drawn=c.gain(1,1)[0]
        g.action(3,'pass');g.action(2,'pass')
        self.assertEqual(c.turn,1)
        self.assertIsNone(c.priority)
        self.assertTrue(any(move['action']=='dot' for move in g.candidates(1)))
        g.action(1,'auto',[drawn['id']])
        self.assertEqual(c.last['special'],'dot')
        self.assertEqual(c.turn,1)

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
