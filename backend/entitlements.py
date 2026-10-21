"""Transactional card redemption and retryable, absolute 3x-ui entitlements.

No browser data is trusted for quota, duration, identity, or panel credentials.
Panel writes cannot participate in a SQLite transaction: an outbox records the
absolute desired state, so a retry never grants another copy of an entitlement.
"""

import hashlib
import secrets
import sqlite3
import time
import threading
from contextlib import contextmanager
from errors import DomainError
from panel import PartialSync

GIB = 1024**3


class Ledger:
    def __init__(self, path):
        self.path = path
        self.billing_lock = threading.RLock()
        # Explicit rollout gate: never migrate balances merely by deploying code.
        self.package_billing = False
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS members (
                    id TEXT PRIMARY KEY,
                    panel_email TEXT NOT NULL UNIQUE,
                    panel_auth TEXT NOT NULL,
                    sub_id TEXT NOT NULL UNIQUE,
                    quota INTEGER NOT NULL DEFAULT 0 CHECK(quota>=0),
                    expires INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0,
                    synced_revision INTEGER NOT NULL DEFAULT 0,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    sync_error TEXT,
                    created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL UNIQUE,
                    suffix TEXT NOT NULL,
                    label TEXT NOT NULL,
                    quota INTEGER NOT NULL CHECK(quota>0),
                    days INTEGER NOT NULL CHECK(days>0),
                    redeem_before INTEGER NOT NULL,
                    created INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    redeemed_by TEXT REFERENCES members(id),
                    redeemed_at INTEGER,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    created INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cards_redeemed_by ON cards(redeemed_by);
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created);
                CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit(actor);
                CREATE INDEX IF NOT EXISTS idx_audit_target ON audit(target);
                PRAGMA optimize;
            """)
            card_columns = {r['name'] for r in db.execute('PRAGMA table_info(cards)')}
            if 'note' not in card_columns:
                # Admin-only recipient memo; never shown to customers.
                db.execute("ALTER TABLE cards ADD COLUMN note TEXT NOT NULL DEFAULT ''")
            if 'granted' not in card_columns:
                # Internal one-time cards created by an administrator grant.
                db.execute('ALTER TABLE cards ADD COLUMN granted INTEGER NOT NULL DEFAULT 0')
            if 'deleting' not in {r['name'] for r in db.execute('PRAGMA table_info(members)')}:
                db.execute('ALTER TABLE members ADD COLUMN deleting INTEGER NOT NULL DEFAULT 0')
            if 'previous_sub_id' not in {
                r['name'] for r in db.execute('PRAGMA table_info(members)')
            }:
                db.execute('ALTER TABLE members ADD COLUMN previous_sub_id TEXT')
            if 'previous_panel_auth' not in {
                r['name'] for r in db.execute('PRAGMA table_info(members)')
            }:
                db.execute('ALTER TABLE members ADD COLUMN previous_panel_auth TEXT')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(members)')}
            for column in ('last_sync_attempt', 'last_synced_at', 'ready_revision'):
                if column not in columns:
                    db.execute(
                        'ALTER TABLE members ADD COLUMN ' + column + ' INTEGER NOT NULL DEFAULT 0'
                    )
            if 'kind' not in {r['name'] for r in db.execute('PRAGMA table_info(cards)')}:
                db.execute("ALTER TABLE cards ADD COLUMN kind TEXT NOT NULL DEFAULT 'base'")
            from cycles import install_rules

            install_rules(db, 'cards')
            if 'billing_blocked' not in columns:
                db.execute(
                    'ALTER TABLE members ADD COLUMN billing_blocked INTEGER NOT NULL DEFAULT 0'
                )
            db.execute("""CREATE INDEX IF NOT EXISTS idx_cards_owner_redeemed
                ON cards(redeemed_by,redeemed_at DESC,id DESC)""")
        from package_ledger import install

        with self.connect() as db:
            install(db)
            self.package_billing = bool(
                db.execute('SELECT 1 FROM billing_rollout WHERE id=1').fetchone()
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    @staticmethod
    def digest(code):
        normalized = code.strip().upper().replace('-', '').replace(' ', '')
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def audit(db, actor, action, target):
        db.execute(
            'INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)',
            (actor, action, target, int(time.time())),
        )

    def create_member(self, member_id):
        with self.transaction() as db:
            self.insert_member(db, member_id)

    @staticmethod
    def insert_member(db, member_id, *, quota=0, expires=0, revision=0, now=None):
        """Use the caller's transaction so account/card/session creation stays atomic."""
        db.execute(
            'INSERT INTO members(id,panel_email,panel_auth,sub_id,quota,expires,revision,created) VALUES(?,?,?,?,?,?,?,?)',
            (
                member_id,
                'jn_' + secrets.token_hex(12),
                secrets.token_hex(24),
                secrets.token_hex(24),
                quota,
                expires,
                revision,
                int(time.time()) if now is None else now,
            ),
        )

    @staticmethod
    def card_note(note):
        if note is None:
            return ''
        if not isinstance(note, str) or len(note.strip()) > 100:
            raise DomainError('卡密备注最多 100 字')
        return note.strip()

    def set_card_note(self, actor, card_id, note):
        note = self.card_note(note)
        with self.transaction() as db:
            if not db.execute('UPDATE cards SET note=? WHERE id=?', (note, card_id)).rowcount:
                raise DomainError('卡密不存在')
            self.audit(db, actor, 'card.note', card_id)

    def card_spec(self, label, quota_gib, days, count, valid_days, kind='base', **options):
        """Validate one issuing request; shared by card batches and direct grants.

        Mirrors the panel's flexibility: fractional GiB, and 0 days means no expiry.
        """
        from cycles import rules, MAX_GIB

        if kind not in ('base', 'addon') or (kind == 'addon' and not self.package_billing):
            raise DomainError('流量包计费尚未启用')
        if kind == 'addon':
            # An add-on always follows its parent package's expiry and cycle.
            options = {**options, 'permanent': False, 'reset_period': 'never'}
            days = 1  # Historical SQL CHECK(days>0); addon duration is never used.
        elif days == 0:
            options = {**options, 'permanent': True}
        rule = rules(options)
        if (rule['permanent'] or rule['reset_period'] != 'never') and not self.package_billing:
            raise DomainError('请先启用套餐计费')
        if rule['permanent']:
            days = 1  # Preserve the historical SQL CHECK; permanent is explicit.
        if type(quota_gib) not in (int, float) or not all(
            type(v) is int for v in (days, count, valid_days)
        ):
            raise DomainError('请输入数字')
        quota = round(quota_gib * GIB)
        if not isinstance(label, str) or not (
            2**20 <= quota <= MAX_GIB * GIB
            and 1 <= days <= 365000
            and 1 <= count <= 1000
            and 0 <= valid_days <= 365000
            and 1 <= len(label.strip()) <= 60
        ):
            raise DomainError('卡密参数超出范围')
        return {
            'label': label.strip(),
            'quota': quota,
            'days': days,
            'valid_days': valid_days,
            'kind': kind,
            'rule': rule,
            'note': self.card_note(options.get('note')),
        }

    def insert_card(self, db, actor, spec, now, granted=False):
        from cycles import FOREVER

        raw = secrets.token_hex(16).upper()
        code = '-'.join(raw[i : i + 8] for i in range(0, len(raw), 8))
        card_id = secrets.token_hex(12)
        db.execute(
            """INSERT INTO cards
            (id,digest,suffix,label,quota,days,redeem_before,created,created_by,kind)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                card_id,
                self.digest(code),
                raw[-8:],
                spec['label'],
                spec['quota'],
                spec['days'],
                now + spec['valid_days'] * 86400 if spec['valid_days'] else FOREVER,
                now,
                actor,
                spec['kind'],
            ),
        )
        db.execute(
            'UPDATE cards SET permanent=?,reset_period=?,reset_interval=?,note=?,granted=? WHERE id=?',
            (*spec['rule'].values(), spec.get('note', ''), int(granted), card_id),
        )
        self.audit(db, actor, 'card.issue', card_id)
        return card_id, code

    def issue(self, actor, label, quota_gib, days, count, valid_days, kind='base', **options):
        spec = self.card_spec(label, quota_gib, days, count, valid_days, kind, **options)
        now = int(time.time())
        result = []
        with self.transaction() as db:
            for _ in range(count):
                card_id, code = self.insert_card(db, actor, spec, now)
                result.append({'id': card_id, 'code': code, 'suffix': code.replace('-', '')[-8:]})
        # Plaintext codes are returned once, never stored or logged.
        return result

    def apply_card(self, db, member, card, now, target=None):
        """Grant one unredeemed card inside the caller's transaction."""
        member_id = member['id']
        if self.package_billing:
            from package_ledger import grant

            self.ensure_billing(db, member, now)
            grant(db, member_id, card, now, target)
            self.refresh_desired(db, member_id, now, force=True)
        else:
            if card['kind'] != 'base':
                raise DomainError('流量包计费尚未启用')
            expires = max(now, member['expires']) + card['days'] * 86400
            db.execute(
                """UPDATE members SET quota=quota+?,expires=?,revision=revision+1,
                       sync_error=NULL WHERE id=?""",
                (card['quota'], expires, member_id),
            )
        db.execute(
            'UPDATE cards SET redeemed_by=?,redeemed_at=? WHERE id=?',
            (member_id, now, card['id']),
        )

    def redeem(self, member_id, code, now=None, target=None):
        now = int(time.time()) if now is None else now
        with self.transaction() as db:
            member = db.execute('SELECT * FROM members WHERE id=?', (member_id,)).fetchone()
            if not member or member['disabled']:
                raise DomainError('账号不可用')
            card = db.execute('SELECT * FROM cards WHERE digest=?', (self.digest(code),)).fetchone()
            if not card or card['revoked_at']:
                raise DomainError('卡密无效或已过期')
            if card['redeemed_by']:
                if card['redeemed_by'] == member_id:
                    return {'already_redeemed': True, 'card_id': card['id']}
                raise DomainError('卡密已使用')
            if card['redeem_before'] <= now:
                raise DomainError('卡密无效或已过期')
            self.apply_card(db, member, card, now, target)
            self.audit(db, member_id, 'card.redeem', card['id'])
        return {'already_redeemed': False, 'card_id': card['id']}

    def grant(self, actor, member_id, spec, target=None, now=None):
        """Administrator grant: an internal one-time card issued and redeemed atomically.

        The card row keeps grants visible in card, batch and redemption history and
        reuses the same billing path as a customer redemption.
        """
        now = int(time.time()) if now is None else now
        with self.transaction() as db:
            member = db.execute('SELECT * FROM members WHERE id=?', (member_id,)).fetchone()
            if not member:
                raise DomainError('用户不存在')
            if member['deleting']:
                raise DomainError('账号删除处理中，不能调整权益')
            if member['disabled']:
                raise DomainError('账号已停用，请先恢复账号再赠送')
            card_id, _ = self.insert_card(db, actor, spec, now, granted=True)
            card = db.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone()
            self.apply_card(db, member, card, now, target)
            self.audit(db, actor, 'account.grant', member_id)
        return {'card_id': card_id}

    def ensure_billing(self, db, member, now):
        from package_ledger import initialize

        state = db.execute(
            'SELECT * FROM billing_accounts WHERE member_id=?', (member['id'],)
        ).fetchone()
        if not state and not member['quota']:
            initialize(db, member, 0, now)
            return
        if not state or state['fault'] or now - state['sampled'] > 60:
            raise DomainError('流量数据待核对，请稍后重试；卡密未消耗')

    def refresh_desired(self, db, uid, now, force=False):
        from package_ledger import desired

        d = desired(db, uid, now)
        row = db.execute('SELECT * FROM members WHERE id=?', (uid,)).fetchone()
        if force or any(row[k] != d[k] for k in d):
            db.execute(
                """UPDATE members SET quota=?,expires=?,billing_blocked=?,
                revision=revision+1,sync_error=NULL WHERE id=?""",
                (d['quota'], d['expires'], int(d['billing_blocked']), uid),
            )

    def sample_billing(self, values, now=None):
        if not self.package_billing:
            return
        from package_ledger import initialize, sample

        now = int(time.time()) if now is None else now
        with self.billing_lock, self.transaction() as db:
            for member in db.execute('SELECT * FROM members WHERE revision>0').fetchall():
                raw = values.get(member['panel_email'])
                if type(raw) is int and raw >= 0:
                    initialize(db, member, raw, now)
                    sample(db, member['id'], raw, now)
                if db.execute(
                    'SELECT 1 FROM billing_accounts WHERE member_id=?', (member['id'],)
                ).fetchone():
                    self.refresh_desired(db, member['id'], now)

    def billing_snapshot(self, uid, now=None):
        if not self.package_billing:
            return None
        from package_ledger import snapshot

        with self.connect() as db:
            return snapshot(db, uid, int(time.time()) if now is None else now)

    def revoke(self, actor, card_id):
        with self.transaction() as db:
            n = db.execute(
                """UPDATE cards SET revoked_at=? WHERE id=?
                AND redeemed_by IS NULL AND revoked_at IS NULL""",
                (int(time.time()), card_id),
            ).rowcount
            if not n:
                raise DomainError('只能作废尚未使用的卡密')
            self.audit(db, actor, 'card.revoke', card_id)

    def revoke_batch(self, actor, label, created, now=None):
        """Revoke every unused, unexpired card from one issuing batch."""
        if not isinstance(label, str) or type(created) is not int:
            raise DomainError('批次参数不正确')
        now = int(time.time()) if now is None else now
        with self.transaction() as db:
            ids = [
                r[0]
                for r in db.execute(
                    """SELECT id FROM cards WHERE label=? AND created=? AND redeemed_by IS NULL
                    AND revoked_at IS NULL AND redeem_before>?""",
                    (label, created, now),
                )
            ]
            for card_id in ids:
                db.execute('UPDATE cards SET revoked_at=? WHERE id=?', (now, card_id))
                self.audit(db, actor, 'card.revoke', card_id)
        return len(ids)

    def sync_member(self, member_id, panel):
        """Caller serializes sync jobs; never hold a DB transaction across HTTP.

        Concurrent redemption is safe: after sending revision N, mark exactly N
        synced. A newer revision remains pending. Never reset traffic counters.
        """
        with self.connect() as db:
            member = db.execute('SELECT * FROM members WHERE id=?', (member_id,)).fetchone()
        if not member or member['deleting'] or member['revision'] == member['synced_revision']:
            return False
        desired = dict(member)
        with self.connect() as db:
            db.execute(
                'UPDATE members SET last_sync_attempt=? WHERE id=?', (int(time.time()), member_id)
            )
        try:
            panel.apply(desired)
        except Exception as exc:
            with self.connect() as db:
                db.execute(
                    'UPDATE members SET sync_error=? WHERE id=?',
                    ('节点同步暂未完成，系统会自动重试', member_id),
                )
                if isinstance(exc, PartialSync) and exc.usable and not member['previous_sub_id']:
                    db.execute(
                        'UPDATE members SET ready_revision=?,sync_error=? WHERE id=? AND revision=?',
                        (
                            member['revision'],
                            '部分节点暂不可用，其余节点可正常使用',
                            member_id,
                            member['revision'],
                        ),
                    )
            return False
        with self.connect() as db:
            db.execute(
                'UPDATE members SET synced_revision=?,sync_error=NULL,last_synced_at=? WHERE id=?',
                (member['revision'], int(time.time()), member_id),
            )
            db.execute(
                'UPDATE members SET previous_sub_id=NULL,previous_panel_auth=NULL WHERE id=? AND revision=?',
                (member_id, member['revision']),
            )
        return True

    def pending(self):
        with self.connect() as db:
            return [
                r['id']
                for r in db.execute(
                    """SELECT id FROM members WHERE revision>synced_revision
                   ORDER BY last_sync_attempt,id LIMIT 100"""
                )
            ]
