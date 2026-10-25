from copy import deepcopy
import html
import re

import pytest

from app.models import Candidate
from app.telegram import TelegramClient
from tests.test_workflow import run_immediate


@pytest.mark.parametrize('edit', [False, True])
def test_screenshot_regression_is_compact_for_new_cards_and_updates(edit):
    url = 'https://example.test/rules'
    report = {
        'decision': 'pending', 'sources': [url],
        'facts': {
            'prize': {'value': '$20,000 in prizes', 'quote': '$20,000 in prizes', 'url': url},
            'deadline': {'value': '2026-12-16T00:00:00+08:00', 'date': '2026-12-15',
                         'defaults': '台灣時間、24:00', 'quote': 'December 15, 2026', 'url': url},
            'registration_fee': {'value': 'unknown'},
            'deliverables': {'value': '2–20 minute film with official watermark created in Showrunner Studio'},
            'submission': {'value': 'online'},
            'ai_policy': {'value': 'broad_allowed', 'quote': 'RULES OF ENTRY 01 — Films must be created in Showrunner Studio 02 — Runtime: 2 to 20 minutes', 'url': url},
        },
        'estimate': {'total_hours': 12, 'extra_tools_twd': 0, 'ai_share': .82, 'plan': 'validated plan',
                     'planning': 3, 'generation_wait': 6, 'review': 2, 'submission': 1, 'finals': 0},
        'blockers': ['入圍、答辯與頒獎出席要求待確認', '台灣個人／學生參賽資格待確認',
                     '成果公開展示權限待確認', '報名費待確認，未假設免費', '其他限制'],
    }
    original = deepcopy(report)

    class Capture(TelegramClient):
        async def call(self, method, payload):
            self.method, self.payload = method, payload
            return {'message_id': 99}

    row = Candidate('card-format', 'organizer', 'Gossip Goblin x Showrunner Competition', url, '', 'test',
                    category='ai_competition', competition=report, telegram_message_id=99)
    client = Capture('not-a-token', 42)
    run_immediate(client.send_competition(row, edit=edit))
    text = client.payload['text']
    assert client.method == ('editMessageText' if edit else 'sendMessage')
    for forbidden in ('預設台灣時間', '當日結束', '（實際費用未確認）', '目標：', '耗時含等待',
                      '工具優先使用', '報名費另計', '估算不代表得獎機率', 'AI 規則摘錄', 'RULES OF ENTRY',
                      '待補：', '決策前先確認', '另有 ', '是否值得投入'):
        assert forbidden not in text
    assert '2026/12/15 24:00' in text and '報名費：未確認' in text
    assert '流程估算：製作 9h · 檢查／交件 3h' in text
    assert '後續0h' not in text and '生成等待6h' not in text
    assert text.count('<b>待確認</b>') == 1
    assert report['blockers'][0] in text and report['blockers'][1] in text
    assert report['blockers'][2] not in text
    assert '規則來源 1' in text and 'AI 製作 82%' in text
    visible = html.unescape(re.sub(r'<[^>]+>', '', text))
    assert len(visible) < 1000
    assert len(visible.splitlines()) <= 25
    assert row.competition == original
