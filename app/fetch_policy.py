"""Shared origin cooldowns and bounded caches for public contest retrieval."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import re
import time
from urllib.parse import urlsplit
import uuid

from app.public_fetch import PublicPage, fetch_public, retry_after


def key(kind: str, value: str) -> str:
    return kind + '-' + hashlib.sha256(value.encode()).hexdigest()


class MemoryFetchState:
    def __init__(self):
        self.rows = {}

    async def get(self, name):
        return dict(self.rows.get(name, {}))

    async def put(self, name, data):
        self.rows[name] = dict(data)

    async def claim(self, name, owner, now):
        row = self.rows.get(name, {})
        if row.get('retry_at', 0) > now:
            return 'cooldown', row['retry_at']
        if row.get('lease_until', 0) > now and row.get('owner') != owner:
            return 'source_busy', row['lease_until']
        if row.get('pace_until', 0) > now:
            return 'source_paced', row['pace_until']
        self.rows[name] = {**row, 'owner': owner, 'lease_until': now + 120}
        return '', 0

    async def release(self, name, owner, retry_at, pace_until=0):
        row = self.rows.get(name, {})
        if row.get('owner') == owner:
            self.rows[name] = {'lease_until': 0, 'retry_at': max(row.get('retry_at', 0), retry_at), 'pace_until': pace_until}


class FirestoreFetchState:
    def __init__(self, client, collection='kairos_public_fetch'):
        self.client = client
        self.collection = client.collection(collection)

    async def get(self, name):
        snap = await asyncio.to_thread(self.collection.document(name).get, timeout=5, retry=None)
        return snap.to_dict() or {}

    async def put(self, name, data):
        await asyncio.to_thread(self.collection.document(name).set, data, timeout=5, retry=None)

    async def claim(self, name, owner, now):
        from google.cloud import firestore
        ref = self.collection.document(name)
        @firestore.transactional
        def claim(transaction):
            row = ref.get(transaction=transaction).to_dict() or {}
            if row.get('retry_at', 0) > now:
                return 'cooldown', row['retry_at']
            if row.get('lease_until', 0) > now and row.get('owner') != owner:
                return 'source_busy', row['lease_until']
            if row.get('pace_until', 0) > now:
                return 'source_paced', row['pace_until']
            transaction.set(ref, {**row, 'owner': owner, 'lease_until': now + 120})
            return '', 0
        return await asyncio.to_thread(claim, self.client.transaction())

    async def release(self, name, owner, retry_at, pace_until=0):
        from google.cloud import firestore
        ref = self.collection.document(name)
        @firestore.transactional
        def release(transaction):
            row = ref.get(transaction=transaction).to_dict() or {}
            if row.get('owner') == owner:
                transaction.set(ref, {'lease_until': 0, 'retry_at': max(row.get('retry_at', 0), retry_at), 'pace_until': pace_until})
        await asyncio.to_thread(release, self.client.transaction())


class PublicFetcher:
    def __init__(self, state=None, *, clock=time.time, spacing=1.0):
        self.state = state or MemoryFetchState()
        self.clock = clock
        self.spacing = spacing

    async def __call__(self, client, url, allowed):
        if not allowed(url):
            return PublicPage(url, 'unsupported')
        owner, held, last = uuid.uuid4().hex, {}, {}
        cooldown = 0
        try:
            stored = await self.state.get(key('page', url))
            if stored.get('expires_at', 0) > self.clock() and allowed(stored['page']['url']):
                return PublicPage(**{**stored['page'], 'from_cache': True, 'attempts': 0})

            async def guard(target):
                origin = urlsplit(target).netloc.lower()
                name = key('origin', origin)
                if name not in held:
                    status, until = await self.state.claim(name, owner, self.clock())
                    if status == 'source_paced':
                        await asyncio.sleep(max(0, until-self.clock()))
                        status, until = await self.state.claim(name, owner, self.clock())
                    if status:
                        return PublicPage(target, status, retry_at=until)
                    held[name] = origin
                wait = self.spacing - (self.clock() - last.get(origin, 0))
                if wait > 0:
                    await asyncio.sleep(wait)
                last[origin] = self.clock()

            page = await fetch_public(client, url, allowed, before_request=guard)
            if page.status == 'http_429':
                cooldown = retry_after(page.headers.get('retry-after', ''), self.clock())
                page.retry_at = cooldown
            if page.status == 'ok' and len(page.body) <= 500_000:
                control = page.headers.get('cache-control', '').lower()
                if not any(token in control for token in ('no-store', 'no-cache', 'private')):
                    age = re.search(r'(?:^|,)\s*max-age=(\d+)', control)
                    ttl = min(3600, int(age[1])) if age else 3600
                    if ttl:
                        await self.state.put(key('page', url), {'expires_at': self.clock() + ttl, 'page': asdict(page)})
            return page
        except Exception:
            # If shared state cannot be read, do not silently bypass its cooldown.
            return PublicPage(url, 'fetch_state_unavailable')
        finally:
            for name in held:
                try:
                    await asyncio.shield(self.state.release(name, owner, cooldown, self.clock()+self.spacing))
                except Exception:
                    pass  # The short lease expires even if release persistence fails.
