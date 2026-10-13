"""Supporting evidence in approval questions: a link the draft record declares as evidence (a specimen, a reference
capture, a ?query variant of a shown page) is recorded with its file's hash and claim and shown to the critic, and never
becomes a page under review; a page, an undeclared link, or an alternate presented for approval still does."""
from __future__ import annotations

import json
import os

import pytest
from PIL import Image

from lapis_design import critic_packet, draft, next_step, preview
from procedure_support import TASK, ask, save
from test_draft_review import EXTRACT, LINT, URL, critic, reviewed
from test_draft_review import project  # noqa: F401  (a project that asked about URL)

SPECIMEN = "specimens/ko-type.html"
VARIANT_LINK = "http://127.0.0.1:4173/system.html?footer=fluid"
CLAIM = "Korean display faces at both widths, for question 3"
REPORT = ".lapis/critic/shown-page.json"


def evidence_file(root, name=SPECIMEN, body="<p>가나다</p>"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if name.endswith(".png"):
        Image.new("RGB", (4, 4), "white").save(path)
    else:
        path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def record(project):
    """The draft record of a passing review of the page the questions link."""
    return reviewed(project)


def declare(root, record, *entries):
    """`record` with `entries` declared as supporting evidence: the critic report is made again on the packet that now lists
    them, and the record is written last, as the maker does after the files it names."""
    record["supporting"] = list(entries)
    save(root, f"drafts/{TASK}.yaml", record)
    critic(root)
    save(root, f"drafts/{TASK}.yaml", record)


def specimen(**more):
    return {"kind": "specimen", "link": SPECIMEN, "path": SPECIMEN, "claim": CLAIM, **more}


def variant(**more):
    return {"kind": "query-variant", "link": VARIANT_LINK, "path": "variant-390.png", "page": URL,
            "claim": "The same build with the fluid footer, at 390", **more}


def asked_with(root, *links):
    ask(root, "Approve this draft? " + URL + "\n" + "\n".join(f"Evidence: {link}" for link in links), 200)


def state(root):
    return next_step.evaluate(root, TASK)


def test_a_declared_specimen_link_is_evidence_and_does_not_make_a_page_to_review(project, record):
    evidence_file(project)
    declare(project, record, specimen())
    asked_with(project, SPECIMEN)
    assert draft.links(project, TASK) == [URL, SPECIMEN]                      # the questions still link both
    assert draft.shown(project, TASK) == [URL]                                # only one of them is a page
    assert state(project)["state"] == "waiting-for-user"
    assert draft.check(project, TASK, asked=draft.shown(project, TASK))[0] == []


def test_an_undeclared_local_link_still_counts_as_a_shown_page_needing_review(project, record):
    evidence_file(project)
    asked_with(project, SPECIMEN)
    assert draft.shown(project, TASK) == [URL, SPECIMEN]
    result = state(project)
    assert result["step"]["id"] == "draft-review" and f"shown page has no review record: {SPECIMEN}" in result["reason"]


def test_a_link_declared_with_another_address_does_not_cover_the_undeclared_one(project, record):
    evidence_file(project)
    evidence_file(project, "specimens/other.html")
    declare(project, record, specimen(link="specimens/other.html", path="specimens/other.html"))
    asked_with(project, SPECIMEN)
    assert state(project)["step"]["id"] == "draft-review"


def test_a_page_of_the_record_cannot_be_declared_as_evidence_to_skip_its_review(project, record):
    evidence_file(project)
    declare(project, record, specimen(link=URL))
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and "is a page of this record" in errors[0] and SPECIMEN in errors[0]


def test_a_source_of_a_shown_page_is_no_evidence_file(project, record):
    declare(project, record, specimen(path=".lapis/specimens/system.html"))
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and "is a source of a shown page" in errors[0]


def test_an_evidence_file_that_is_not_there_is_a_problem_and_the_link_stays_declared(project, record):
    declare(project, record, specimen())
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and errors[0].startswith(f"supporting evidence {SPECIMEN}: review input is not a file")


def test_a_query_variant_of_the_shown_page_is_evidence_only_when_declared_with_its_page(project, record):
    evidence_file(project, "variant-390.png")
    asked_with(project, VARIANT_LINK)
    assert state(project)["step"]["id"] == "draft-review"                     # undeclared: a page with no review record
    declare(project, record, variant())
    assert draft.shown(project, TASK) == [URL] and draft.check(project, TASK)[0] == []
    declare(project, record, {k: v for k, v in variant().items() if k != "page"})
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and "names `page`" in errors[0]


def test_a_query_variant_of_another_address_or_a_stale_capture_is_no_evidence(project, record):
    evidence_file(project, "variant-390.png")
    declare(project, record, variant(link="http://127.0.0.1:4173/pricing.html?footer=fluid"))
    assert "is not a ?query variant of" in draft.check(project, TASK)[0][0]
    declare(project, record, variant(link=URL.split("?")[0]))                  # no query: that is the page itself
    assert "is not a ?query variant of" in draft.check(project, TASK)[0][0]
    declare(project, record, specimen(link=VARIANT_LINK, path="variant-390.png"))   # a variant declared as a specimen
    assert "is a page of this record" in draft.check(project, TASK)[0][0]
    declare(project, record, variant())
    os.utime(project / "variant-390.png", (1, 1))                              # a variant older than the source it varies
    assert "is older than the shown source it is a variant of" in draft.check(project, TASK)[0][0]


def test_a_supporting_link_must_still_be_alive_when_the_questions_show_it(project, record, monkeypatch):
    evidence_file(project, "variant-390.png")
    declare(project, record, variant())
    asked_with(project, VARIANT_LINK)
    monkeypatch.setattr(preview, "answers", lambda url, timeout=preview.TIMEOUT_S: url == URL)
    result = state(project)
    assert result["step"]["id"] == "draft-review" and VARIANT_LINK in result["reason"]


def test_evidence_is_recorded_with_path_hash_and_claim_and_listed_to_the_critic(project, record):
    path = evidence_file(project)
    declare(project, record, specimen())
    [entry] = draft.supporting(project, TASK)
    assert entry == {"kind": "specimen", "link": SPECIMEN, "path": SPECIMEN, "claim": CLAIM,
                     "sha256": critic_packet.digest(path.read_bytes())}
    doc = json.loads(critic_packet.build(project, TASK, {"extracts": [EXTRACT], "lint": LINT, "session": None}))
    assert doc["supporting"] == [entry]
    assert {i["path"]: i["kind"] for i in doc["inputs"]}[SPECIMEN] == "supporting-evidence"
    assert [i["sha256"] for i in doc["inputs"] if i["path"] == SPECIMEN] == [entry["sha256"]]


def test_a_changed_evidence_file_makes_the_critic_report_and_the_review_stale(project, record):
    path = evidence_file(project)
    declare(project, record, specimen())
    assert critic_packet.verify(project, project / REPORT, allow_delta=True) == []
    path.write_text("<p>다른 시편</p>", encoding="utf-8")
    assert any("changed since" in p for p in critic_packet.verify(project, project / REPORT))
    path.touch()
    assert any("review record is older than its supporting evidence" in e for e in draft.check(project, TASK)[0])


def test_a_packet_for_a_page_carries_only_the_evidence_of_that_page_or_of_none(project, record):
    evidence_file(project)
    evidence_file(project, "variant-390.png")
    declare(project, record, specimen(), variant())
    kinds = lambda extract, lint: [e["kind"] for e in json.loads(critic_packet.build(
        project, TASK, {"extracts": [extract], "lint": lint, "session": None}))["supporting"]]
    assert kinds(EXTRACT, LINT) == ["specimen", "query-variant"]
    assert kinds(f".lapis/renders/{TASK}.json", f".lapis/lint/{TASK}.json") == ["specimen"]


def test_supporting_evidence_added_after_a_full_review_is_a_delta_not_a_new_page_or_a_full_review(project, record):
    evidence_file(project)
    critic(project)                                                            # the full review of the shown build
    delta = critic_packet.delta(project, TASK, REPORT)
    assert delta.document is None and "nothing changed" in delta.reasons[0]
    record["supporting"] = [specimen()]
    save(project, f"drafts/{TASK}.yaml", record)
    delta = critic_packet.delta(project, TASK, REPORT)
    assert delta.document["supporting"]["changed"] == draft.supporting(project, TASK)
    assert delta.document["requirements"]["changed"] == []


@pytest.mark.parametrize("entry", [{"kind": "page", "link": SPECIMEN, "path": SPECIMEN, "claim": CLAIM},
                                   {"kind": "specimen", "link": SPECIMEN, "path": SPECIMEN, "claim": "short"}])
def test_an_entry_without_a_known_kind_or_a_claim_declares_nothing(project, record, entry):
    evidence_file(project)
    declare(project, record, entry)
    asked_with(project, SPECIMEN)
    assert draft.declared(project, TASK) == [] and draft.shown(project, TASK) == [URL, SPECIMEN]
    assert draft.check(project, TASK)[0]
