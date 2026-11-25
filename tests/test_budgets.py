"""Capacity is reserved durably, spent on start and restored only by elapsed refill."""
from cadence.budgets import Budgets
from cadence.store import Store


def test_durable_balance_and_reservation_across_connections(tmp_path,clock):
    with Store(tmp_path/'state.db',clock) as first, Store(tmp_path/'state.db',clock) as second:
        a,b=Budgets(first),Budgets(second)
        scope=('execution',1,1/3600)
        with first.atomic():
            assert a.reserve('queued',[scope])
            assert a.balance(*scope)==1
        with second.atomic():
            assert not b.reserve('other',[scope])
            assert b.start('queued',[scope])
            assert b.balance(*scope)==0
        clock.advance(1800)
        with first.atomic():
            assert a.balance(*scope)==.5
            assert not a.reserve('next',[scope])
        clock.advance(1800)
        with second.atomic(): assert b.start('next',[scope])


def test_two_bucket_admission_is_atomic_and_a_hold_spends_neither(tmp_path,clock):
    with Store(tmp_path/'state.db',clock) as s:
        b=Budgets(s)
        global_scope=('global',2,1/3600)
        own=('own',1,1/86400)
        with s.atomic():
            assert b.start('first',[global_scope,own])
            assert not b.reserve('pending',[global_scope,own])
            assert b.balance(*global_scope)==1
            assert not s.connection.execute('SELECT 1 FROM reservations').fetchone()


def test_backward_clock_and_capacity_edits_cannot_mint_tokens(tmp_path,clock):
    with Store(tmp_path/'state.db',clock) as s:
        b=Budgets(s)
        with s.atomic():
            assert b.start('first',[('work',2,1/3600)])
            assert b.balance('work',20,20/3600)==1
        clock.wall-=3600
        with s.atomic(): assert b.balance('work',20,20/3600)==1
        clock.wall+=3600
        with s.atomic(): assert b.balance('work',20,20/3600)==1
        clock.advance(3600)
        with s.atomic(): assert b.balance('work',20,20/3600)==20


def test_refill_never_exceeds_capacity_and_reservations_can_be_cancelled(tmp_path,clock):
    with Store(tmp_path/'state.db',clock) as s:
        b=Budgets(s)
        with s.atomic(): assert b.reserve('cancelled',[('work',30,30/86400)])
        clock.advance(100*86400)
        with s.atomic():
            assert b.balance('work',30,30/86400)==30
            b.release('cancelled')
            assert b.available('work',30,30/86400)==30
