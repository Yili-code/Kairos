from scripts.audit_competition_discovery import lead_quality


def test_cross_posts_are_review_hints_not_confirmed_opportunities_or_auto_merges():
    rows = [
        {'title':'淡江大學「2026書藝智生—AI生成書法創藝比賽」，歡迎參加', 'url':'https://a.edu.tw/post'},
        {'title':'【校外競賽】2026書藝智生－AI生成書法創藝比賽', 'url':'https://b.edu.tw/post'},
        {'title':'2025書藝智生－AI生成書法創藝比賽', 'url':'https://a.edu.tw/previous'},
    ]
    report = lead_quality(rows)
    assert report['possible_same_event_groups'] == [['https://a.edu.tw/post','https://b.edu.tw/post']]
    assert report['older_year_title_urls'] == ['https://a.edu.tw/previous']
    assert report['all_leads_require_assessment'] is True
    assert len(rows) == 3


def test_equivalent_urls_are_reported_separately_from_different_event_pages():
    report = lead_quality([
        {'title':'Contest A','url':'https://campus.edu.tw/徵件?id=1&lang=tw'},
        {'title':'Contest A copy','url':'https://campus.edu.tw/%E5%BE%B5%E4%BB%B6?lang=tw&id=1'},
        {'title':'Contest B','url':'https://campus.edu.tw/徵件?id=2&lang=tw'},
    ])
    assert len(report['equivalent_url_groups']) == 1
    assert len(report['equivalent_url_groups'][0]) == 2


def test_runtime_separates_parse_failures_dynamic_boards_empty_and_unmatched_results():
    from tests.test_workflow import make_workflow, run_immediate
    class Source:
        last_report = [
            {'status':'parse_error'},
            {'status':'ok','parse_status':'unreadable_or_dynamic'},
            {'status':'ok','parse_status':'no_announcements'},
            {'status':'ok','parse_status':'no_matching_titles'},
            {'status':'ok','parse_status':'filtered_out','from_cache':True},
            {'status':'cooldown'},
        ]
        async def discover(self):
            return [], 1
    workflow,_,telegram,sender = make_workflow()
    workflow.announcement_source = Source()
    result = run_immediate(workflow.discover(()))
    for name in ['parse_failures','unreadable_pages','confirmed_empty_pages','no_match_pages','filtered_pages','cache_hits','deferred_pages']:
        assert result['announcement_'+name] == 1
    assert result['competitions_eligible'] == 0
    assert telegram.cards == [] and sender.sent == []
