# Competition recovery: three live rounds

Date: 2026-10-24 (Asia/Taipei). Every round changes the implementation, reruns live retrieval and existing-provider analysis, and records ten evidence-backed remaining questions. Local round audits do not send Telegram messages or write Firestore. A final production check is reported separately. Unpublished organizer terms cannot be invented or resolved by contacting organizers without authorization.

## Round 1: retrieve and explain failures

Changes: bounded transient retries, validated HTTPS redirects, declared encodings, 1 MB rule-page bound and per-document status/attempt/byte receipts. Unsafe redirects remain blocked. Tests: 136 passed.

Live result: 31 listing leads, zero local listing errors; TKU returned one document and twelve quoted facts, Post-Meaning four documents and nine quoted facts; FilmFreeway returned HTTP 403. Neither analyzed contest passed all constraints. These local results do not establish cloud-egress success.

Ten remaining questions from the rerun:

1. AI ZONE: FilmFreeway refuses rule-page access (HTTP 403).
2. Post-Meaning: complete attendance obligations lack quoted evidence.
3. Post-Meaning: entrant-controlled public display rights lack quoted evidence.
4. TKU: copyright and licensing terms lack quoted evidence.
5. Post-Meaning: copyright and licensing terms lack quoted evidence.
6. Post-Meaning: public winner recognition lacks quoted evidence.
7. Post-Meaning: full deliverable specifications lack quoted evidence.
8. TKU: estimated AI production share is below 90%; its interpretation needs scrutiny.
9. Post-Meaning: estimated AI production share is below 90%; its interpretation needs scrutiny.
10. AI ZONE: production share cannot be estimated without rules.

Additional findings: estimates treated human review as manual artifact production and claimed a bounded workflow despite unknown finalist obligations. Those are estimator defects, not organizer-confirmed exclusions. A university news article is incomplete evidence of the organizer's full terms.

## Round 2: complete documents and make estimates auditable

Changes: six-document review including FAQ/judging, 3 MB PDF retrieval with the existing twenty-page/text bounds, a verified TKU-related university notice and organizer-PDF link, artifact-component AI-share calculation, explicit human-only work, and semantic guards against equating online entry with no attendance or organizer exhibition with entrant rights. Uncertain estimates remain pending rather than confirmed exclusions; the eligibility thresholds are unchanged. Tests: 141 passed.

Live result: 31 listing leads, zero local listing errors. TKU returned three documents including the 1,200,416-byte organizer PDF and six quoted facts; Post-Meaning returned six documents and eight quoted facts. Both remain pending; AI ZONE remains inaccessible. Fewer accepted facts reflect stricter validation and extraction instability, not necessarily fewer facts published.

Ten remaining questions from the rerun:

1. AI ZONE: its platform still returns HTTP 403.
2. TKU: substantial AI permission was not retained as a grounded fact.
3. TKU: complete attendance obligations remain unconfirmed.
4. Post-Meaning: complete attendance obligations remain unconfirmed.
5. TKU: entrant-controlled public display rights remain unconfirmed.
6. Post-Meaning: entrant-controlled public display rights remain unconfirmed.
7. TKU: copyright and licensing terms remain unconfirmed.
8. Post-Meaning: copyright and licensing terms remain unconfirmed.
9. TKU: registration fees remain unconfirmed.
10. Post-Meaning: complete deliverable specifications remain unconfirmed.

Additional findings: copied PDF quotations can lose provenance through CJK typography/spacing; model output also attributed human-only writing to Post-Meaning without supporting text. Those require validation rather than filling gaps with assumptions.
