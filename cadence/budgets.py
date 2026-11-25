"""Durable continuous token buckets and unspent admission reservations.

All callers compose these operations under Store.atomic(). A reservation holds
capacity for a queued turn; only start() debits it. Wall time is persisted across
restarts; a backward clock never produces refill or moves the refill anchor back.
"""
import math


class Budgets:
    def __init__(self, store):
        self.store = store
        with store.atomic():
            store.connection.execute('CREATE TABLE IF NOT EXISTS buckets '
                '(name TEXT PRIMARY KEY, tokens REAL NOT NULL, updated REAL NOT NULL, '
                'capacity REAL NOT NULL, rate REAL NOT NULL)')
            store.connection.execute('CREATE TABLE IF NOT EXISTS reservations '
                '(ticket TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(ticket,name))')

    def balance(self, name, capacity, rate, *, initial=None):
        if not all(math.isfinite(x) and x >= 0 for x in (capacity, rate)):
            raise ValueError('invalid bucket configuration')
        now = self.store.clock.now()
        db = self.store.connection
        row = db.execute('SELECT * FROM buckets WHERE name=?', (name,)).fetchone()
        if row is None:
            tokens, anchor = min(capacity, capacity if initial is None else initial), now
        else:
            anchor = max(now, row['updated'])
            tokens = min(row['capacity'], row['tokens'] + max(0, now-row['updated'])*row['rate'])
            tokens = min(tokens, capacity)
        db.execute('INSERT INTO buckets VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET '
            'tokens=excluded.tokens,updated=excluded.updated,capacity=excluded.capacity,rate=excluded.rate',
            (name, tokens, anchor, capacity, rate))
        return tokens

    def available(self, name, capacity, rate, *, initial=None, ticket=None):
        tokens = self.balance(name, capacity, rate, initial=initial)
        held = self.store.connection.execute('SELECT COUNT(*) FROM reservations WHERE name=? AND ticket!=?',
                                             (name, ticket or '')).fetchone()[0]
        return max(0, tokens-held)

    def reserve(self, ticket, scopes):
        if any(self.available(*scope, ticket=ticket) < 1-1e-9 for scope in scopes):
            return False
        for name, _, _ in scopes:
            self.store.connection.execute('INSERT OR IGNORE INTO reservations VALUES (?,?)', (ticket, name))
        return True

    def start(self, ticket, scopes):
        if not self.reserve(ticket, scopes):
            return False
        for name, capacity, rate in scopes:
            balance = self.balance(name, capacity, rate)
            self.store.connection.execute('UPDATE buckets SET tokens=? WHERE name=?', (max(0, balance-1), name))
        self.release(ticket)
        return True

    def release(self, ticket):
        self.store.connection.execute('DELETE FROM reservations WHERE ticket=?', (ticket,))

    def reset(self, name):
        self.store.connection.execute('DELETE FROM buckets WHERE name=?', (name,))
