import pytest
from app.competition_decisions import validate_eligibility
from app.competitions import evaluate
from app.profile import PROFILE
from tests.test_competitions import SOURCES, URL, valid_report

APN = ('Eligibility The Hackathon IS open to individuals who are employed by or authorized to act on behalf of an organization that has registered with the AWS Partner Network (APN).')


@pytest.mark.parametrize('classification', ['eligible', 'ineligible'])
def test_actual_aws_partner_restriction_requires_unknown_affiliation_confirmation(classification):
    raw = valid_report()
    raw['facts']['eligibility'] = {'value': classification, 'quote': APN, 'url': URL}
    result = evaluate(raw, {URL: SOURCES[URL] + ' ' + APN})
    assert result['facts']['eligibility']['value'] == 'unknown'
    assert result['decision'] == 'pending'
    assert result['fact_diagnostics']['eligibility'] == 'affiliation_requires_confirmation'
    assert result['eligibility_requirements'][0]['quote'] == APN
    assert any(q['field'] == 'eligibility' for q in result['verification_questions'])


def test_model_negative_is_not_itself_proof_of_a_profile_conflict():
    result, diagnostic = validate_eligibility({'value': 'ineligible', 'quote': 'Everyone may enter this competition.', 'url': URL}, PROFILE)
    assert result['value'] == 'unknown' and diagnostic == 'ineligibility_not_verified_from_profile'


def test_a_mentioned_university_is_not_necessarily_an_exclusive_institution():
    quote = 'Everyone may enter. National Yang Ming Chiao Tung University students are organizing this competition.'
    result, _ = validate_eligibility({'value': 'eligible', 'quote': quote, 'url': URL}, PROFILE)
    assert result['value'] != 'ineligible'


def test_actual_single_hardware_award_does_not_establish_no_cash_elsewhere():
    quote = 'The winner takes home an Apple Vision Pro!'
    raw = valid_report()
    raw['facts']['prize_kind'] = {'value': 'noncash', 'quote': quote, 'url': URL}
    result = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote})
    assert result['facts']['prize_kind']['value'] == 'unknown'
    assert result['fact_diagnostics']['prize_kind'] == 'noncash_only_not_established'
    assert result['decision'] == 'pending'


def test_explicit_noncash_only_awards_remain_a_hard_rejection():
    quote = 'All prizes are non-cash.'
    raw = valid_report()
    raw['facts']['prize_kind'] = {'value': 'noncash', 'quote': quote, 'url': URL}
    result = evaluate(raw, {URL: SOURCES[URL] + ' ' + quote})
    assert result['decision'] == 'rejected'
