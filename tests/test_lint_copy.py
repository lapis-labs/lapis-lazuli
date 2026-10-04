"""Copy detectors of slop_lint, run with the shipped rules on small hand-built extracts and plans.

Every extract here validates against render/extract.schema.yaml and every plan against
plan/schema.yaml; the rules, lists, and thresholds are the shipped ones."""
from __future__ import annotations

import copy
import json
import re
import unicodedata

import jsonschema
import pytest
import yaml

import lapis_design.lint.detectors.copy as copy_detectors
from lapis_design import shared_dir
from lapis_design.lint.cli import problems, run as lint_run
from lapis_design.lint.types import DETECTORS, Context

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text())
BY_ID = {r["id"]: r for r in RULES["rules"]}
EXTRACT = jsonschema.Draft202012Validator(yaml.safe_load((shared_dir() / "render" / "extract.schema.yaml").read_text()))
PLAN = jsonschema.Draft202012Validator(yaml.safe_load((shared_dir() / "plan" / "schema.yaml").read_text()))
SCRIPT = {"en": "latn", "ko": "hang", "ja": "kana", "zh": "hani", "ru": "cyrl"}


def box(n: int) -> str:
    return f"b{n:012x}"


def r(text: str, role: str = "body", **kw) -> dict:
    """A text run spec: type_role, plus box_role, box, parent, parent_role, lang, weight, transform."""
    return {"text": text, "type_role": role, **kw}


def doc(*sections, lang: str = "en", width: int = 1440, derived: bool = True) -> dict:
    """An extract with one viewport. Each section is (archetype, [run specs]); each run gets its own
    box under the section unless its spec names a `box` (and optionally a `parent`)."""
    boxes: dict[str, dict] = {}
    runs, derived_sections = [], []
    counter = iter(range(1, 10_000))

    def add(bid: str, role: str, parent: str | None, y: float) -> None:
        if bid not in boxes:
            boxes[bid] = {"id": bid, "parent": parent, "role": role, "role_confidence": 0.9,
                          "rect": {"x": 0, "y": y, "w": 400, "h": 40}}

    for si, (archetype, specs) in enumerate(sections):
        sid = box(1000 + si)
        boxes[sid] = {"id": sid, "parent": None, "role": "section", "role_confidence": 1,
                      "rect": {"x": 0, "y": si * 1000, "w": width, "h": 1000}}
        derived_sections.append({"box": sid, "archetype": archetype})
        for spec in specs:
            spec = dict(spec)
            y = si * 1000 + 10 + len(runs)
            parent = spec.pop("parent", sid)
            if parent != sid:
                add(parent, spec.pop("parent_role", "other"), sid, y)
            spec.pop("parent_role", None)
            role = spec["type_role"]
            box_role = spec.pop("box_role", {"display": "heading", "heading": "heading", "ui": "button"}.get(role, "text"))
            bid = spec.pop("box", None) or box(next(counter))
            add(bid, box_role, parent, y)
            run_lang = spec.pop("lang", lang)
            text = spec.pop("text")
            runs.append({"id": f"t{len(runs) + 1}", "box": bid, "text": text, "lang": run_lang,
                         "chars": max(1, sum(1 for c in text if not c.isspace())),
                         "script": SCRIPT.get(run_lang.split("-")[0], "latn"),
                         "font": {"requested": "Pretendard", "rendered": "Pretendard"}, "size_px": 16, **spec})
    viewport = {"width": width, "theme": "light", "boxes": list(boxes.values()), "text": runs}
    if derived:
        viewport["derived"] = {"sections": derived_sections}
    out = {"version": 1, "meta": {"extractor": {"name": "render_check", "version": "0.1.0"},
                                  "generated_at": "2026-09-26T10:00:00Z"},
           "source": {"kind": "render", "task": "demo"}, "viewports": [viewport]}
    assert [e.message for e in EXTRACT.iter_errors(out)] == []
    return out


def plan(key_copy=(), *, locales=("en",), register=None, world=None, claims=None,
         subject="Online sales for a small pottery studio") -> dict:
    p = {"version": 0, "mode": "repair", "task": {"id": "demo", "title": "Kiln shop"},
         "brief": {"subject": subject, "one_job": "Reserve a piece", "platform": ["web"], "locales": list(locales),
                   "product_frame": "e-commerce"},
         "defaults": [], "content": {"key_copy": [{"slot": s, "text": t} for s, t in key_copy]}}
    if register:
        p["content"]["voice"] = {"register": register}
    if world:
        p["world_materials"] = list(world)
    if claims:
        p["claims"] = {"known": list(claims)}
    assert [e.message for e in PLAN.iter_errors(p)] == []
    return p


def lint(rule_id: str, layer: str = "render", *, extract=None, plan=None, det=None):
    rule = BY_ID[rule_id]
    det = det or copy.deepcopy(rule["detect"][layer])
    ctx = Context(rules=RULES, extract=extract, plan=plan, extract_path="render.json", plan_path="plan.yaml")
    return DETECTORS[det["detector"]].fn(ctx, det, rule, layer)


def observed(result) -> str:
    return " | ".join(h.observed for h in result.hits)


def filler(n: int) -> str:
    return " ".join(["kiln"] * n)


# ---------------------------------------------------------------- missing input

COPY_RULES = [(rule["id"], layer) for rule in RULES["rules"] for layer, det in (rule.get("detect") or {}).items()
              if det["detector"] in {"copy-family-rate", "rhetorical-shell", "construction-rate", "punctuation-density",
                                     "rhythm-variance", "formatting-residue", "separator-shape",
                                     "register-consistency", "placeholder-genericness", "meta-text",
                                     "name-swap-test", "counterfactual-test"}]


@pytest.mark.parametrize("rule_id,layer", COPY_RULES)
def test_every_copy_rule_skips_without_its_input(rule_id, layer):
    result = lint(rule_id, layer)
    assert result.hits == [] and result.skipped, (rule_id, layer)


@pytest.mark.parametrize("rule_id", ["copy.name-swap", "color.palette-swap-only"])
def test_reviewer_only_copy_decisions_carry_reviewer_cause(rule_id):
    result = lint(rule_id, "review", plan=plan(), extract=doc(("hero", [r("Clay bowls", "display")])))
    assert result.skipped and result.cause == "reviewer"


def test_reference_only_extract_is_skipped_not_passed():
    extract = doc(("hero", [r("Seamless pottery", "display")]))
    for run in extract["viewports"][0]["text"]:
        del run["text"]
    result = lint("copy.buzzwords", extract=extract)
    assert result.hits == [] and "signatures" in result.skipped


# ---------------------------------------------------------------- copy-family-rate

def test_buzzword_in_plan_key_copy_is_located_in_the_plan():
    result = lint("copy.buzzwords", "plan", plan=plan([("headline", "Elevate your pottery workflow"),
                                                        ("subhead", "Bowls from the September firing")]))
    assert [h.location["path"] for h in result.hits] == ["content.key_copy[0].text"]
    assert result.hits[0].evidence == "plan" and "elevate" in result.hits[0].observed


def test_plain_plan_copy_has_no_buzzword():
    result = lint("copy.buzzwords", "plan", plan=plan([("headline", "Bowls from the September firing")]))
    assert result.hits == [] and result.skipped is None


def test_render_buzzwords_are_read_only_in_the_headline_subhead_and_cta_slots():
    extract = doc(("hero", [r("A seamless way to buy bowls", "display"), r("Pick a glaze and a size."),
                            r("Shop now", "ui"), r("Second paragraph is seamless too.")]),
                  ("other", [r("Robust shipping", "heading"), r("Our robust crates travel well.")]))
    result = lint("copy.buzzwords", extract=extract)
    assert [h.location["path"] for h in result.hits] == ["/viewports/0/text/0"]
    assert result.hits[0].location["box"] == extract["viewports"][0]["text"][0]["box"]


def test_korean_buzzword_matches_by_stem():
    extract = doc(("hero", [r("혁신적으로 빚은 사발", "display"), r("이번 가마에서 나온 사발이에요.")]), lang="ko-KR")
    assert "혁신적" in observed(lint("copy.buzzwords", extract=extract))


@pytest.mark.cjk
def test_korean_list_verb_matches_inflected_variants():
    rules = copy.deepcopy(RULES)
    rules["lists"]["significance_markers"]["values"]["ko"].append("판도를 바꾸")
    rule = BY_ID["copy.empty-significance"]
    det = copy.deepcopy(rule["detect"]["render"])
    for text, matched in (("판도를 바꿀 준비를 했어요.", "판도를 바꿀"),
                          ("판도를 바꿔도 좋아요.", "판도를 바꿔"),
                          ("판도를 바꿨다.", "판도를 바꿨")):
        ctx = Context(rules=rules, extract=doc(("other", [r(text)]), lang="ko"))
        result = DETECTORS[det["detector"]].fn(ctx, det, rule, "render")
        assert f'"{matched}"' in observed(result)


@pytest.mark.cjk
def test_korean_list_verb_from_shipped_rules_matches_inflected_copy():
    result = lint("copy.empty-significance", extract=doc(("other", [r("새 역사를 쓸 시간입니다.")]), lang="ko"))
    assert "새 역사를 쓸" in observed(result)

@pytest.mark.cjk
@pytest.mark.parametrize("text", [
    "새 역사를 쓰다",
    "우리는 새 역사를 쓰고 있습니다.",
    "새로운 장을 열었다",
    "새 역사를 쓰다가",
])
def test_korean_significance_phrase_counts_once(text):
    result = lint("copy.empty-significance", extract=doc(("other", [r(text)]), lang="ko"))
    assert len(result.hits) == 1, (text, observed(result))


@pytest.mark.cjk
def test_korean_staging_phrase_does_not_match_other_ending():
    result = lint("copy.staging", extract=doc(("other", [r("자세히 살펴보세요")]), lang="ko"))
    assert result.hits == []


def test_vague_cta_matches_whole_labels_only():
    extract = doc(("hero", [r("Bowls", "display"), r("Submit", "ui"), r("Continue to checkout", "ui"),
                            r("Click here", "ui", box_role="link")]))
    result = lint("copy.vague-cta", extract=extract)
    texts = sorted(h.observed.split('"')[1] for h in result.hits)
    assert texts == ["click here", "submit"]


def test_vague_cta_reports_one_label_on_several_controls():
    extract = doc(("feature-grid", [r("Bowls", "heading"), r("Learn more", "ui", box_role="link"),
                                    r("Cups", "heading"), r("Learn more", "ui", box_role="link")]),
                  ("footer", [r("Contact", "ui", box_role="link"), r("Contact", "ui", box_role="link")]))
    result = lint("copy.vague-cta", extract=extract)
    shared = [h for h in result.hits if "share the label" in h.observed]
    assert len(shared) == 1 and "Learn more" in shared[0].observed and len(shared[0].refs) == 2


def test_distinct_specific_ctas_do_not_hit():
    extract = doc(("hero", [r("Bowls", "display"), r("Reserve this bowl", "ui"), r("See the firing log", "ui")]))
    result = lint("copy.vague-cta", extract=extract)
    assert result.hits == [] and result.skipped is None


def test_vague_cta_on_korean_labels():
    assert lint("copy.vague-cta", "plan", plan=plan([("cta", "예약하기")], locales=("ko-KR",))).hits == []
    assert lint("copy.vague-cta", "plan", plan=plan([("cta", "제출하기")], locales=("ko-KR",))).hits
    assert lint("copy.vague-cta", "plan", plan=plan([("cta", "Continue")])).hits


def test_metaphor_density_and_through_metaphor():
    text = ("Every journey starts with a first kiln. " + filler(30) + " Our roadmap shows each milestone. "
            + filler(30))
    result = lint("copy.generative-metaphor", extract=doc(("other", [r(text)])))
    kinds = observed(result)
    assert "metaphor_families instances" in kinds and "journey family recurs 3 times" in kinds


def test_single_metaphor_is_not_density():
    text = "Every journey starts with a first kiln. " + filler(60)
    result = lint("copy.generative-metaphor", extract=doc(("other", [r(text)])))
    assert result.hits == [] and result.skipped is None


def test_metaphor_from_the_subjects_world_is_literal():
    text = "The blueprint archive holds each blueprint; " + filler(10) + " a blueprint per kiln."
    extract = doc(("other", [r(text)]))
    assert lint("copy.generative-metaphor", extract=extract).hits
    literal = plan(world=["kiln blueprint archive"])
    rule = BY_ID["copy.generative-metaphor"]
    det = rule["detect"]["render"]
    ctx = Context(rules=RULES, extract=extract, plan=literal)
    assert DETECTORS["copy-family-rate"].fn(ctx, det, rule, "render").hits == []


@pytest.mark.parametrize("words,hits", [(2000, 0), (1999, 1)])
def test_density_bound_is_one_per_thousand_words_and_fires_only_above(words, hits):
    text = "incredibly arguably " + filler(words - 2)
    result = lint("copy.intensifier-hedging", extract=doc(("other", [r(text)])))
    assert len(result.hits) == hits


def test_comfort_wording_has_to_recur_on_the_page_to_hit():
    once = doc(("hero", [r("Life happens. Keep what matters.", "display")]))
    assert lint("copy.stock-reassurance", extract=once).hits == []
    twice = doc(("hero", [r("Life happens. Keep what matters.", "display")]),
                ("cta", [r("Make room for peace of mind.", "heading")]))
    result = lint("copy.stock-reassurance", extract=twice)
    assert '"life happens" x1' in observed(result) and '"peace of mind" x1' in observed(result)


def test_comfort_wording_in_plan_key_copy_hits_without_a_count():
    hit = lint("copy.stock-reassurance", "plan", plan=plan([("headline", "A little backup. A lot of peace of mind.")]))
    assert "peace of mind" in observed(hit)
    assert lint("copy.stock-reassurance", "plan", plan=plan([("headline", "Restore any file from the last 30 days")])).hits == []


def test_korean_comfort_wording_counts_with_particles():
    extract = doc(("hero", [r("마음 편히 맡기세요.", "display"), r("백업은 걱정 없이 매일 자동으로 이루어져요.")]), lang="ko")
    assert "reassurance_phrases instances on the page" in observed(lint("copy.stock-reassurance", extract=extract))


def test_offer_terms_hit_when_two_of_them_share_a_section():
    stacked = doc(("hero", [r("Start free", "ui"), r("14-day free trial", "caption"), r("No credit card required", "caption")]))
    assert "2 offer_terms values together" in observed(lint("copy.template-offer-terms", extract=stacked))


def test_one_offer_term_or_terms_in_separate_sections_do_not_hit():
    one = doc(("hero", [r("Start free", "ui"), r("Cancel anytime", "caption")]))
    apart = doc(("hero", [r("Start free", "ui"), r("Cancel anytime", "caption")]),
                ("cta", [r("Start now", "ui"), r("No credit card required", "caption")]))
    assert lint("copy.template-offer-terms", extract=one).hits == []
    assert lint("copy.template-offer-terms", extract=apart).hits == []


# ---------------------------------------------------------------- rhetorical-shell

def test_contrast_frames_hit_by_density():
    body = "It's not a shop. It's a kiln diary. We sell not just bowls, but the firing behind them."
    assert lint("copy.contrast-frame", extract=doc(("other", [r(body)]))).hits
    single = "It's not a shop. It's a kiln diary. " + filler(20)
    result = lint("copy.contrast-frame", extract=doc(("other", [r(single)])))
    assert result.hits == [] and result.skipped is None


def test_korean_contrast_frames():
    body = "단순한 가게가 아니라 가마 일지예요. 사발뿐만 아니라 소성 기록도 보여 드려요."
    assert lint("copy.contrast-frame", extract=doc(("other", [r(body)]), lang="ko")).hits


def test_staging_phrase_hits_once():
    extract = doc(("other", [r("Let's dive in: the September firing.")]))
    assert "let's dive in" in observed(lint("copy.staging", extract=extract))
    plain = lint("copy.staging", extract=doc(("other", [r("The September firing gave 24 bowls.")])))
    assert plain.hits == [] and plain.skipped is None


def test_staging_on_korean_copy():
    assert "알아볼까요" in observed(lint("copy.staging", extract=doc(("other", [r("지금부터 알아볼까요?")]), lang="ko")))
    plain = lint("copy.staging", extract=doc(("other", [r("가마를 열어요.")]), lang="ko"))
    assert plain.hits == [] and plain.skipped is None


def test_staging_on_japanese_copy_is_skipped():
    result = lint("copy.staging", extract=doc(("other", [r("それでは見ていきましょう。")]), lang="ja"))
    assert result.hits == [] and "staging_phrases" in result.skipped and "ja" in result.skipped


def test_forced_triads_hit_by_density():
    extract = doc(("hero", [r("Fast. Simple. Secure.", "display"), r("Plan, fire, and ship every bowl.")]))
    assert "triad shells" in observed(lint("copy.forced-triad", extract=extract))
    four = doc(("hero", [r("Bowls", "display"), r("Plan, glaze, fire, and ship every bowl. " + filler(5))]))
    assert lint("copy.forced-triad", extract=four).hits == []


# ---------------------------------------------------------------- construction-rate

def test_korean_translationese_by_density():
    body = "사발은 장인에 의해 만들어진 것으로 보여집니다. 가마를 통해 구워졌고 유약을 통해 색이 정해집니다."
    result = lint("copy.translationese", extract=doc(("other", [r(body)]), lang="ko"))
    assert "translationese_constructions constructions in ko copy" in observed(result)
    assert 'double-passive "보여집" x1' in observed(result) and '~를 통해 "를 통해" x1' in observed(result)

@pytest.mark.cjk
def test_korean_double_passive_requires_a_passive_stem_before_eo_ji():
    passive = "보여집니다. 되어집니다. 잡혀집니다. 사용되어집니다. 밀려집니다."
    result = lint("copy.translationese", extract=doc(("other", [r(passive)]), lang="ko"))
    assert "double-passive" in observed(result)
    assert observed(result).startswith("5 translationese_constructions constructions")
    active = "사발이 좋아집니다. 물감이 번져집니다."
    assert "double-passive" not in observed(
        lint("copy.translationese", extract=doc(("other", [r(active)]), lang="ko"))
    )


@pytest.mark.cjk
@pytest.mark.parametrize("word", ["그려진", "알려진", "버려진", "남겨진", "맡겨진", "숨겨진", "입혀진", "가려진"])
def test_korean_double_passive_does_not_flag_active_stems(word):
    seg = copy_detectors._Seg(word, "ko", "hang", {"path": "body"}, "render body")
    assert copy_detectors._double_passives(Context(rules=RULES), seg) == []


@pytest.mark.cjk
@pytest.mark.parametrize("word", ["보여지는", "쓰여진", "잊혀진", "닫혀진", "밀려집니다", "개선되어진"])
def test_korean_double_passive_detects_only_listed_passive_stems(word):
    seg = copy_detectors._Seg(word, "ko", "hang", {"path": "body"}, "render body")
    assert len(copy_detectors._double_passives(Context(rules=RULES), seg)) == 1


PASSIVE_NEGATIVES = ["그려진 그림", "알려진 사실", "버려진 상자", "남겨진 메모", "맡겨진 일", "숨겨진 기능",
                     "입혀진 옷", "가려진 부분", "만들어진 제품", "나누어진 영역", "나눠진 영역", "이루어진 계약",
                     "주어진 시간", "보여준 화면", "살려진 문장", "올려진 글", "늘려진 기간", "앉혀진 아이",
                     "익혀진 채소", "옮겨진 짐", "벗겨진 껍질", "밝혀진 사실", "쓰여 있다", "들려준 이야기",
                     "선보여진 신제품", "선보여졌습니다", "내보여진 결과", "부풀려진 숫자", "엇갈려진 의견",
                     "모여든 사람들", "밀려오는 파도", "걸려온 전화", "모여 지낸다"]


@pytest.mark.cjk
@pytest.mark.parametrize(("lemma", "form"), copy_detectors._PASSIVE_PAIRS)
def test_korean_double_passive_covers_every_listed_passive_verb(lemma, form):
    for text in (form + "진 것", form + "졌다", form + "지는 중"):
        seg = copy_detectors._Seg(text, "ko", "hang", {"path": "body"}, "render body")
        assert len(copy_detectors._double_passives(Context(rules=RULES), seg)) == 1, (lemma, text)


@pytest.mark.cjk
@pytest.mark.parametrize("text", ["짓눌려진 마음", "휩쓸려진 마을", "뒤섞여진 색", "파묻혀진 보물", "떠밀려진 배",
                                  "점점 잊혀지는 기억", "잊혀지는 중"])
def test_korean_double_passive_covers_compounds_and_whole_word_readings(text):
    seg = copy_detectors._Seg(text, "ko", "hang", {"path": "body"}, "render body")
    assert len(copy_detectors._double_passives(Context(rules=RULES), seg)) == 1


@pytest.mark.cjk
@pytest.mark.parametrize("text", PASSIVE_NEGATIVES)
def test_korean_double_passive_leaves_causatives_and_plain_forms(text):
    seg = copy_detectors._Seg(text, "ko", "hang", {"path": "body"}, "render body")
    assert copy_detectors._double_passives(Context(rules=RULES), seg) == []


@pytest.mark.parametrize(("lemma", "form"), copy_detectors._PASSIVE_PAIRS)
def test_korean_double_passive_word_pattern_uses_the_same_list(lemma, form):
    pattern = copy_detectors._CONSTRUCTIONS["double-passive"]["ko"]
    assert pattern.search(form + "진 것") and pattern.search(form + "졌다")


@pytest.mark.parametrize("text", PASSIVE_NEGATIVES)
def test_korean_double_passive_word_pattern_leaves_causatives(text):
    assert not copy_detectors._CONSTRUCTIONS["double-passive"]["ko"].search(text)


@pytest.mark.cjk
def test_japanese_density_counts_morphemes_instead_of_half_characters():
    text = "することができる。することができる。器を焼きます。"
    result = lint("copy.translationese", extract=doc(("other", [r(text)]), lang="ja"))
    assert "in 12 words" in observed(result)

@pytest.mark.cjk
def test_chinese_density_counts_segmented_words():
    result = lint("copy.translationese", extract=doc(("other", [r("被邀请、被选中。")]), lang="zh"))
    assert "in 4 words" in observed(result)


@pytest.mark.cjk
def test_lint_report_names_only_analyzers_that_ran(tmp_path):
    ko_path = tmp_path / "ko.json"
    ko_path.write_text(json.dumps(doc(("other", [r("보여집니다. 잡혀집니다.")]), lang="ko")), encoding="utf-8")
    result = lint_run(extract=ko_path, rule_ids=["copy.translationese"])
    assert set(result["analyzers"]) == {"ko"}
    assert re.fullmatch(r"kiwipiepy 0\.24\.\d+", result["analyzers"]["ko"])
    assert problems(result, "report") == []

    en_path = tmp_path / "en.json"
    en_path.write_text(json.dumps(doc(("other", [r("Bowls from the kiln.")]))), encoding="utf-8")
    assert "analyzers" not in lint_run(extract=en_path, rule_ids=["copy.translationese"])



def test_direct_korean_has_no_translationese():
    body = "장인이 빚은 사발이에요. 가마에서 구웠고 유약이 색을 정해요."
    result = lint("copy.translationese", extract=doc(("other", [r(body)]), lang="ko"))
    assert result.hits == [] and result.skipped is None


def test_translationese_on_english_only_render_is_skipped():
    result = lint("copy.translationese", extract=doc(("other", [r("Bowls from the September firing.")])))
    assert result.hits == [] and "ko, ja, zh" in result.skipped


# ---------------------------------------------------------------- punctuation-density

def dash_doc(chars: int) -> dict:
    """Two em dashes in exactly `chars` non-space characters of English copy."""
    head = "a\u2014b c\u2014d "                  # 6 non-space characters
    return doc(("other", [r(head + "x" * (chars - 6))]))


def test_em_dash_ratio_fires_only_above_the_bound():
    base = copy_detectors._GLYPH_BASELINE["em-dash"]["en"]
    bound = BY_ID["copy.dash-cadence"]["detect"]["render"]["threshold"]["ratio_to_baseline_max"]
    at_bound = round(2 / (base * bound) * 1000)          # two dashes exactly at the allowed ratio
    assert lint("copy.dash-cadence", extract=dash_doc(at_bound)).hits == []
    assert len(lint("copy.dash-cadence", extract=dash_doc(at_bound - 1)).hits) == 1


def test_single_em_dash_is_not_density():
    result = lint("copy.dash-cadence", extract=doc(("other", [r("Bowls\u2014fresh")])))
    assert result.hits == [] and result.skipped is None


def test_dash_density_skips_locales_without_a_baseline():
    result = lint("copy.dash-cadence", extract=doc(("other", [r("Бокалы\u2014новые")], ), lang="ru"))
    assert result.hits == [] and "ru" in result.skipped


# ---------------------------------------------------------------- rhythm-variance

def test_uniform_rhythm_with_repeated_openings():
    body = " ".join(f"We fire {w} bowls every week." for w in ("red", "blue", "green", "white", "black", "grey"))
    result = lint("copy.uniform-rhythm", extract=doc(("other", [r(body)])))
    kinds = observed(result)
    assert "barely vary in length" in kinds and 'start with "we"' in kinds


def test_varied_rhythm_does_not_hit():
    body = ("Bowls. The September firing gave us twenty-four pieces, most of them celadon with a pale foot ring. "
            "Some cracked. We kept the ones that rang true when tapped, and we photographed each on the kiln shelf "
            "before it cooled. Prices follow size. Reserve one and we hold it for a week.")
    result = lint("copy.uniform-rhythm", extract=doc(("other", [r(body)])))
    assert result.hits == [] and result.skipped is None


def test_repeated_korean_endings():
    body = ("사발을 제공합니다. 머그잔도 넉넉하게 제공합니다. 접시는 크기별로 골라 담아 제공합니다. "
            "주문 제작도 가능하며 상담을 제공합니다. 배송은 전국 어디든 합니다.")
    assert 'end with "제공합니다"' in observed(lint("copy.uniform-rhythm", extract=doc(("other", [r(body)]), lang="ko")))


def test_rhythm_needs_five_body_sentences():
    result = lint("copy.uniform-rhythm", extract=doc(("other", [r("One. Two words. Three words here.")])))
    assert result.hits == [] and "fewer than 5" in result.skipped


# ---------------------------------------------------------------- paired headings (rhythm-variance)

def paired_page(*headings: str, first: str = "Backups for small studios"):
    sections = [("hero", [r(first, "display")])]
    sections += [("feature-grid", [r(h, "heading")]) for h in headings]
    return doc(*sections)


def test_first_heading_built_as_two_short_sentences_hits():
    result = lint("copy.uniform-rhythm", extract=doc(("hero", [r("Your files. Safe, always.", "display")])))
    assert "the first heading built as two or three short sentences" in observed(result)
    assert '"Your files. Safe, always."' in observed(result)


def test_sentences_joined_by_a_line_break_without_a_space_are_still_two_beats():
    result = lint("copy.uniform-rhythm", extract=doc(("hero", [r("Life happens.Keep what matters.", "display")])))
    assert "Life happens. Keep what matters." in observed(result)


def test_runs_of_one_heading_box_are_one_heading():
    shared = box(7)
    extract = doc(("hero", [r("Your work.", "display", box=shared), r("Safe, always.", "display", box=shared)]))
    assert "Your work. Safe, always." in observed(lint("copy.uniform-rhythm", extract=extract))


def test_one_paired_section_heading_is_not_a_cadence():
    result = lint("copy.uniform-rhythm", extract=paired_page("Set it up. Then get on with it.", "How restores work"))
    assert result.hits == [] and result.skipped is None


def test_three_paired_section_headings_are_a_page_wide_cadence():
    result = lint("copy.uniform-rhythm", extract=paired_page(
        "Set it up. Then get on with it.", "One click. One restore.", "Small price. Big relief.", "How restores work"))
    assert "3 of 5 headings built as two or three short sentences" in observed(result)


def test_quantity_and_negation_pairs_are_named():
    quantity = lint("copy.uniform-rhythm", extract=doc(("hero", [r("A little backup. A lot of calm.", "display")])))
    negation = lint("copy.uniform-rhythm", extract=doc(("hero", [r("Built to be there. Not in the way.", "display")])))
    assert "1 a quantity pair" in observed(quantity)
    assert "1 a negation pair" in observed(negation)


@pytest.mark.parametrize("heading", [
    "Backups for small studios",                                                    # one sentence
    "Every file you save is copied twice to other cities. The second copy lives somewhere far from the first.",  # long sentences
    "A, B. C, D. E, F. G, H.",                                                      # four beats
    "Same words. Same words.",                                                      # one beat said twice
])
def test_headings_that_are_not_short_sentence_pairs_do_not_hit(heading):
    result = lint("copy.uniform-rhythm", extract=doc(("hero", [r(heading, "display")])))
    assert result.hits == [] and result.skipped is None


def test_bilingual_heading_is_a_translation_not_a_pair():
    result = lint("copy.uniform-rhythm", extract=doc(("hero", [r("빛은 사라져도, 감각은 남습니다. Light passes.", "display")]), lang="ko"))
    assert result.hits == [] and result.skipped is None


def test_korean_heading_pair_hits():
    result = lint("copy.uniform-rhythm", extract=doc(("hero", [r("파일은 안전하게. 복구는 빠르게.", "display")]), lang="ko"))
    assert "the first heading built as two or three short sentences" in observed(result)


def test_japanese_heading_pair_is_measured_in_characters():
    pair = lint("copy.uniform-rhythm", extract=doc(("hero", [r("季節を包む。ひとくち。", "display")]), lang="ja"))
    long = lint("copy.uniform-rhythm", extract=doc(("hero", [r("季節の移ろいを一つ一つ丁寧に包みます。毎朝その日の分だけ作ります。", "display")]), lang="ja"))
    assert "the first heading built" in observed(pair)
    assert long.hits == []


# ---------------------------------------------------------------- formatting-residue

def labelled_items(n: int) -> list[dict]:
    specs = []
    for i in range(n):
        item = box(500 + i)
        specs += [r(f"Glaze {i}:", weight=700, box=item, parent=box(499), parent_role="list"),
                  r("celadon from the September firing", weight=400, box=item, parent=box(499), parent_role="list")]
    return specs


def test_bold_label_bullets_need_three_items():
    assert "bold label" in observed(lint("copy.formatting-residue", extract=doc(("other", labelled_items(3)))))
    assert lint("copy.formatting-residue", extract=doc(("other", labelled_items(2)))).hits == []


def test_markdown_markers_left_in_copy():
    result = lint("copy.formatting-residue", extract=doc(("other", [r("**Glaze:** celadon")])))
    assert "markdown emphasis" in observed(result)


def test_emoji_markers_and_title_case_prose():
    extract = doc(("other", [r("🔥 Hot kiln", "heading"), r("✅ Food safe"), r("🚀 Ships fast"),
                             r("Every Bowl Is Thrown By Hand In Our Small Studio")]))
    kinds = observed(lint("copy.formatting-residue", extract=extract))
    assert "emoji marker" in kinds and "capitalizes every word" in kinds


def test_headings_that_restate_the_next_sentence():
    extract = doc(("other", [r("Fast shipping", "heading"), r("Shipping is fast for every order."),
                             r("Careful packing", "heading"), r("Packing is careful for every bowl.")]))
    assert "restate the sentence" in observed(lint("copy.formatting-residue", extract=extract))
    once = doc(("other", [r("Fast shipping", "heading"), r("Shipping is fast for every order."),
                          r("Glazes", "heading"), r("We mix three celadons.")]))
    assert lint("copy.formatting-residue", extract=once).hits == []


def test_flattened_label_value_pairs():
    extract = doc(("other", [r("Size: 12 cm · Glaze: celadon · Firing: September", "caption")]))
    assert "label-value pairs" in observed(lint("copy.formatting-residue", extract=extract))


# ---------------------------------------------------------------- separator-shape

def shaped(n: int, text: str = "{i}: build in minutes") -> dict:
    return doc(("feature-grid", [r(text.format(i=w), "heading") for w in ("Speed", "Scale", "Safety", "Style")[:n]]))


def test_separator_shape_fires_only_above_repeats_max():
    assert len(lint("copy.separator-join", extract=shaped(3)).hits) == 1
    assert lint("copy.separator-join", extract=shaped(2)).hits == []


def test_label_value_fields_are_not_separator_shapes():
    assert lint("copy.separator-join", extract=shaped(4, "{i}: $20 per month")).hits == []


# ---------------------------------------------------------------- register-consistency

MIXED_KO = [r("이번 가마에서 스물네 점이 나왔어요.", "heading"), r("사발은 모두 손으로 빚었어요."),
            r("주문은 이번 주까지 받습니다.")]


def test_register_against_the_plan():
    result = lint("copy.register-mix", extract=doc(("other", MIXED_KO), lang="ko"), plan=plan(register="haeyo"))
    assert len(result.hits) == 1 and "hapnida" in result.hits[0].observed and "plan sets haeyo" in result.hits[0].observed


def test_register_mix_without_a_plan_uses_the_majority():
    result = lint("copy.register-mix", extract=doc(("other", MIXED_KO), lang="ko"))
    assert "most use haeyo" in observed(result)


def test_consistent_register_and_nominal_labels():
    extract = doc(("other", [r("사발은 모두 손으로 빚었어요."), r("예약하기", "ui"), r("주문은 이번 주까지 받아요.")]), lang="ko")
    result = lint("copy.register-mix", extract=extract, plan=plan(register="haeyo"))
    assert result.hits == [] and result.skipped is None


def test_japanese_register_mix():
    extract = doc(("other", [r("器はすべて手作りです。"), r("窯出しは九月だ。")]), lang="ja")
    assert "da-dearu" in observed(lint("copy.register-mix", extract=extract, plan=plan(register="desu-masu")))


# ---------------------------------------------------------------- placeholder-genericness

def test_placeholder_names_in_plan_and_render():
    assert "acme" in observed(lint("copy.placeholder-content", "plan", plan=plan([("headline", "Acme bowls")])))
    extract = doc(("testimonial", [r("“Lovely bowls.”"), r("John Doe, collector", "caption")]))
    assert "john doe" in observed(lint("copy.placeholder-content", extract=extract))
    clean = lint("copy.placeholder-content", extract=doc(("other", [r("Bowls by Mira Seo")])))
    assert clean.hits == [] and clean.skipped is None

@pytest.mark.cjk
def test_korean_placeholder_name_requires_whole_proper_noun_token():
    extract = doc(("other", [r("홍길동전 읽기")]), lang="ko")
    assert lint("copy.placeholder-content", extract=extract).hits == []
    person = doc(("other", [r("홍길동 기자가 왔어요.")]), lang="ko")
    assert "홍길동" in observed(lint("copy.placeholder-content", extract=person))


@pytest.mark.cjk
def test_korean_placeholder_name_after_nfkc_expansion_is_one_proper_noun():
    extract = doc(("other", [r("… 홍길동 님의 후기")]), lang="ko")
    result = lint("copy.placeholder-content", extract=extract)
    assert len(result.hits) == 1
    assert "홍길동" in result.hits[0].observed

@pytest.mark.cjk
def test_korean_placeholder_name_after_nfd_composition_maps_to_original():
    text = "홍길동 님의 후기"
    decomposed = unicodedata.normalize("NFD", text)
    result = lint("copy.placeholder-content", extract=doc(("other", [r(decomposed)]), lang="ko"))
    assert len(result.hits) == 1
    assert "홍길동" in result.hits[0].observed


def test_proof_metrics_need_a_plan_claim():
    extract = doc(("hero", [r("10,000+ collectors", "display"), r("Rated 4.9/5 by buyers")]))
    result = lint("copy.fabricated-proof", extract=extract, plan=plan())
    assert len(result.hits) == 2 and {h.evidence for h in result.hits} == {"not-verified"}
    backed = lint("copy.fabricated-proof", extract=extract, plan=plan(claims=["10,000 collectors bought a bowl", "Rated 4.9 of 5"]))
    assert backed.hits == []


def test_testimonials_logos_and_credits_are_leads():
    extract = doc(("testimonial", [r("“The best bowls I have ever owned.”"), r("— Jane Park, Head of Tea")]),
                  ("other", [r("Photo by Min Lee", "caption")]))
    result = lint("copy.fabricated-proof", extract=extract)
    kinds = sorted(h.observed.split(" in the ")[0].split(' "')[0] for h in result.hits)
    assert kinds == ["customer attribution", "photo credit", "testimonial quotation"]


def dialog_title(role: str, text: str) -> dict:
    """A text run of the given role inside a dialog box."""
    return r(text, role, box=box(700), parent=box(701), parent_role="dialog")


@pytest.mark.parametrize("role,text", [
    ("heading", "‘9월 소성 예약’을 취소할까요?"),
    ("body", "‘9월 소성 예약’을 취소하면 27일 전까지는 되돌릴 수 있어요."),
])
def test_a_dialog_that_quotes_what_it_asks_about_is_not_a_testimonial(role, text):
    extract = doc(("other", [dialog_title(role, text), r("예약 유지", "ui"), r("예약 취소", "ui")]), lang="ko")
    assert lint("copy.fabricated-proof", extract=extract).hits == []


@pytest.mark.parametrize("role", ["heading", "display", "label", "ui"])
def test_a_heading_button_or_label_that_quotes_a_name_is_not_a_testimonial(role):
    extract = doc(("other", [r("“Blue Celadon” is back for September", role), r("Firing closes Sept 20", "caption")]))
    assert lint("copy.fabricated-proof", extract=extract).hits == []


@pytest.mark.parametrize("section", ["other", "testimonial"])
def test_a_quotation_in_body_text_with_an_attribution_line_is_a_lead(section):
    extract = doc((section, [r("“The best bowls I have ever owned.”"), r("— Jane Park, Head of Tea", "caption")]))
    kinds = sorted(h.observed.split(" in the ")[0] for h in lint("copy.fabricated-proof", extract=extract).hits)
    assert kinds == ["customer attribution", "testimonial quotation"]


def test_a_quotation_with_its_attribution_inside_one_run_is_a_lead():
    extract = doc(("other", [r("“The best bowls I have ever owned.” — Jane Park, Head of Tea")]))
    [hit] = lint("copy.fabricated-proof", extract=extract).hits
    assert hit.observed.startswith("testimonial quotation in the body run")


def test_an_unattributed_body_quotation_is_still_a_lead():
    extract = doc(("other", [r("“The best bowls I have ever owned.”")]))
    assert "testimonial quotation" in observed(lint("copy.fabricated-proof", extract=extract))


def test_logo_strip_and_customer_list_are_leads():
    extract = doc(("logo-strip", [r("Trusted by", "label"), r("Kiln Co"), r("Tea House"), r("Clay Lab")]))
    vp = extract["viewports"][0]
    section = vp["derived"]["sections"][0]["box"]
    vp["boxes"] += [{"id": box(900 + i), "parent": section, "role": "media", "role_confidence": 0.9,
                     "rect": {"x": 100 * i, "y": 20, "w": 80, "h": 40}, "media": {"kind": "img", "loaded": True}}
                    for i in range(4)]
    assert [e.message for e in EXTRACT.iter_errors(extract)] == []
    kinds = observed(lint("copy.fabricated-proof", extract=extract))
    assert "strip of 4 logos" in kinds and '3 customer names under "Trusted by"' in kinds


def test_disclosed_sample_data_is_out_of_scope():
    extract = doc(("hero", [r("10,000+ collectors", "display"), r("Sample data for this preview", "caption")]))
    assert lint("copy.fabricated-proof", extract=extract).hits == []


# ---------------------------------------------------------------- meta-text

def test_producer_facing_build_and_demo_text():
    extract = doc(("hero", [r("Your headline goes here", "display"), r("v1.2.3", "caption"), r("DEMO", "label")]))
    kinds = observed(lint("copy.meta-text", extract=extract))
    assert "producer-facing" in kinds and "build or environment label" in kinds and "demo badge" in kinds


def test_chat_leftover_single_words_only_open_a_sentence():
    assert "chat leftover" in observed(lint("copy.meta-text", extract=doc(("other", [r("Certainly! Here are the bowls.")]))))
    plain = lint("copy.meta-text", extract=doc(("other", [r("You will certainly like the celadon.")])))
    assert plain.hits == [] and plain.skipped is None


def test_body_repeating_its_heading():
    extract = doc(("other", [r("Firing log", "label"), r("Firing log", "heading"), r("Temperatures by hour.")]))
    assert "repeats the heading" in observed(lint("copy.meta-text", extract=extract))


def test_meta_text_in_plan_key_copy():
    assert "producer-facing" in observed(lint("copy.meta-text", "plan", plan=plan([("headline", "Insert headline")])))


def test_meta_text_on_korean_copy():
    hit = lint("copy.meta-text", extract=doc(("other", [r("물론입니다! 사발을 빚었어요.")]), lang="ko"))
    assert "물론입니다" in observed(hit)
    plain = lint("copy.meta-text", extract=doc(("other", [r("물론 반품도 돼요.")]), lang="ko"))
    assert plain.hits == [] and plain.skipped is None


NOTICES = {"en": "This page uses fictional example data.",
           "ko": "이 페이지는 가상의 예시 데이터를 사용하는 화면입니다.",
           "ja": "このページは架空の店舗で、仮のサンプルデータを使用しています。"}
TITLES = {"en": "Fire once a month", "ko": "한 달에 한 번 구워요", "ja": "月に一度、焼きます"}
BODIES = {"en": "Wheel-thrown bowls, fired once a month.", "ko": "물레로 빚은 사발을 한 달에 한 번 구워요.",
          "ja": "ろくろで挽いた器を月に一度焼きます。"}


def notice_page(lang, *, hero=(), middle=(), footer=(), heading=None):
    """A hero with the title, a middle section with one line of body copy, and a footer; each argument lists the
    notices that go in that part (strings), and `heading` is a notice set as a heading."""
    return doc(("hero", [r(TITLES[lang], "display"), *[r(t, "caption") for t in hero]]),
               ("feature-grid", [r(BODIES[lang]), *[r(t) for t in middle], *([r(heading, "heading")] if heading else [])]),
               ("footer", [r(t, "caption") for t in footer] or [r("© 2026")]), lang=lang)


def meta(extract, plan=None):
    return lint("copy.meta-text", extract=extract, plan=plan)


@pytest.mark.parametrize("lang", ["en", "ko", "ja"])
def test_the_one_notice_in_the_footer_is_not_meta_text(lang):
    result = meta(notice_page(lang, footer=[NOTICES[lang]]))
    assert result.skipped is None and result.hits == []


@pytest.mark.parametrize("lang", ["en", "ko", "ja"])
def test_a_notice_in_the_hero_is_meta_text_and_the_footer_one_stays(lang):
    hits = meta(notice_page(lang, hero=[NOTICES[lang]], footer=[NOTICES[lang]])).hits
    assert [h.observed for h in hits] == [f'demo notice in the opening: "{NOTICES[lang]}"']


@pytest.mark.parametrize("lang", ["en", "ko", "ja"])
def test_a_notice_set_as_a_heading_is_meta_text(lang):
    hits = meta(notice_page(lang, heading=NOTICES[lang], footer=[NOTICES[lang]])).hits
    assert [h.observed for h in hits] == [f'demo notice in a heading: "{NOTICES[lang]}"']


@pytest.mark.parametrize("lang", ["en", "ko", "ja"])
def test_a_notice_in_the_middle_of_the_page_and_a_second_in_the_footer_are_repeats(lang):
    mid = meta(notice_page(lang, middle=[NOTICES[lang]], footer=[NOTICES[lang]])).hits
    assert [h.observed.split(":")[0] for h in mid] == ["demo notice in the middle of the page (body run)"]
    twice = meta(notice_page(lang, footer=[NOTICES[lang], NOTICES[lang]])).hits
    assert [h.observed.split(":")[0] for h in twice] == ["demo notice repeated"]
    assert twice[0].refs and twice[0].location["path"] != twice[0].refs[0]


def test_a_notice_and_its_translation_side_by_side_count_once():
    page = doc(("hero", [r(TITLES["ko"], "display", lang="ko")]),
               ("footer", [r(NOTICES["ko"], "caption", lang="ko"), r(NOTICES["en"], "caption", lang="en")]))
    result = meta(page)
    assert result.skipped is None and result.hits == []
    spread = doc(("hero", [r(TITLES["ko"], "display", lang="ko")]),
                 ("feature-grid", [r(NOTICES["ko"], lang="ko")]), ("footer", [r(NOTICES["en"], "caption", lang="en")]))
    assert len(meta(spread).hits) == 1                        # the Korean one in the middle; the English footer stays


def test_a_notice_that_is_a_long_paragraph_is_not_a_quiet_line():
    long_note = "This page uses fictional example data. " + "Prices are shown in dollars and include tax. " * 4
    page = doc(("hero", [r(TITLES["en"], "display")]), ("feature-grid", [r(BODIES["en"]), r(long_note)]),
               ("footer", [r(NOTICES["en"], "caption")]))
    assert [h.observed.split(":")[0] for h in meta(page).hits] == ["demo notice in the middle of the page (body run)"]


@pytest.mark.parametrize("text", ["Try the demo", "Book a demo"])
def test_an_action_label_that_says_demo_is_not_a_disclosure(text):
    page = doc(("hero", [r(TITLES["en"], "display"), r(text, "ui")]), ("footer", [r("© 2026", "caption")]))
    assert meta(page).hits == []


def test_a_demo_badge_in_the_hero_is_flagged_but_one_beside_the_logo_is_the_one_notice():
    hero = doc(("hero", [r(TITLES["en"], "display"), r("LIVE DEMO", "label")]), ("footer", [r("© 2026", "caption")]))
    assert [h.observed for h in meta(hero).hits] == ['demo badge in the opening: "LIVE DEMO"']
    header = doc(("other", [r("LIVE DEMO", "label")]), ("hero", [r(TITLES["en"], "display")]),
                 ("footer", [r("© 2026", "caption")]))
    assert meta(header).hits == []


@pytest.mark.parametrize("word", ["Preview", "Sample"])
def test_a_bare_column_label_is_not_a_demo_badge(word):
    assert meta(doc(("hero", [r(TITLES["en"], "display")]), ("footer", [r(word, "caption")]))).hits == []


def asked(plan_, *constraints):
    plan_["brief"]["constraints"] = list(constraints)
    return plan_


def test_without_a_brief_that_asks_for_it_even_the_quiet_notice_is_meta_text():
    page = notice_page("en", footer=[NOTICES["en"]])
    [hit] = meta(page, plan()).hits
    assert hit.observed == f'demo notice in a quiet place, and the brief does not ask for one: "{NOTICES["en"]}"'
    ask = asked(plan(), "State once on the page that it uses fictional example data")
    assert meta(page, ask).hits == []


def test_a_korean_brief_that_asks_for_the_notice_allows_it():
    page = notice_page("ko", footer=[NOTICES["ko"]])
    assert len(meta(page, plan(locales=("ko",))).hits) == 1
    assert meta(page, asked(plan(locales=("ko",)), "가상의 예시 데이터를 쓴다고 한 번만 밝혀 주세요")).hits == []


def test_plan_key_copy_may_hold_one_notice_in_the_other_slot_and_none_in_the_headline():
    ask = asked(plan([("headline", "A demo page with fictional data"), ("other", NOTICES["en"])]),
                "State once on the page that it uses fictional example data")
    hits = lint("copy.meta-text", "plan", plan=ask).hits
    assert [h.observed for h in hits] == ['demo notice in the headline key copy: "A demo page with fictional data"']
    quiet = asked(plan([("headline", "Fire once a month"), ("other", NOTICES["en"])]),
                  "State once on the page that it uses fictional example data")
    assert lint("copy.meta-text", "plan", plan=quiet).hits == []


CHANGE_LOG = [("en", "I fixed the layout and improved the spacing."), ("en", "The footer has been improved."),
              ("en", "We updated the headline copy for clarity."), ("ko", "레이아웃을 개선했어요."),
              ("ko", "히어로 섹션을 수정했습니다."), ("ja", "レイアウトを修正しました。"),
              ("ja", "ヒーローセクションが改善されました。")]


@pytest.mark.parametrize("lang,text", CHANGE_LOG)
def test_change_log_narration_is_meta_text(lang, text):
    [hit] = meta(doc(("feature-grid", [r(text)]), lang=lang)).hits
    assert hit.observed.startswith("change-log narration")


@pytest.mark.parametrize("lang,text", [("en", "Your profile has been updated."),
                                       ("en", "We updated our privacy policy on 3 May."),
                                       ("ko", "프로필이 업데이트되었습니다."), ("ja", "プロフィールを更新しました。")])
def test_a_status_the_product_reports_is_not_change_log_narration(lang, text):
    result = meta(doc(("feature-grid", [r(text)]), lang=lang))
    assert result.skipped is None and result.hits == []


SELF_DESCRIPTION = [("en", "Click the button below to see how the page works."), ("en", "This section explains what the studio does."),
                    ("ko", "아래 버튼을 클릭하면 예약 화면을 확인할 수 있어요."), ("ko", "이 섹션에서는 도자기를 보여줍니다."),
                    ("ja", "下のボタンをクリックすると予約画面をご覧いただけます。"), ("ja", "このセクションでは作品を紹介しています。")]


@pytest.mark.parametrize("lang,text", SELF_DESCRIPTION)
def test_the_page_describing_itself_is_meta_text(lang, text):
    assert len(meta(doc(("feature-grid", [r(text)]), lang=lang)).hits) == 1


@pytest.mark.parametrize("text", ["Click the button to continue.", "Use the filters to narrow the list."])
def test_an_instruction_that_does_not_point_at_the_page_is_not_self_description(text):
    assert meta(doc(("feature-grid", [r(text)]))).hits == []


@pytest.mark.parametrize("lang,text", [("en", "Dev note: wire up the backend later."), ("en", "Replace this with real content."),
                                       ("ko", "개발자 메모: 결제 연동은 추후 구현"), ("ko", "추후 교체 예정입니다."),
                                       ("ja", "開発メモ：決済は後で実装"), ("ja", "後で差し替え予定です。")])
def test_developer_and_test_notes_are_meta_text(lang, text):
    [hit] = meta(doc(("feature-grid", [r(text)]), lang=lang)).hits
    assert hit.observed.startswith("developer or test note")


@pytest.mark.parametrize("lang,text", [("en", "Sorry, this feature is not implemented yet."), ("en", "Unfortunately this part is still being built."),
                                       ("ko", "죄송합니다. 이 기능은 아직 개발 중이에요."),
                                       ("ja", "申し訳ありません。この機能はまだ開発中です。")])
def test_an_apology_for_a_part_nobody_built_is_meta_text(lang, text):
    [hit] = meta(doc(("feature-grid", [r(text)]), lang=lang)).hits
    assert hit.observed.startswith("placeholder apology")


@pytest.mark.parametrize("lang,text", [("en", "Sorry, this size is not available."), ("ko", "죄송합니다. 지원하지 않는 브라우저입니다."),
                                       ("ja", "申し訳ありません。ただいま準備中です。")])
def test_an_apology_for_a_real_state_is_not_a_placeholder_apology(lang, text):
    result = meta(doc(("feature-grid", [r(text)]), lang=lang))
    assert result.skipped is None and result.hits == []


def test_a_build_label_is_a_label_not_a_sentence_and_version_history_is_content():
    assert meta(doc(("feature-grid", [r("Version 3", "caption")]))).hits == []
    long = "All packs need synth version 1.2 or later, installed and licensed on the same machine as your host."
    assert meta(doc(("feature-grid", [r(long)]))).hits == []
    assert "build or environment label" in observed(meta(doc(("feature-grid", [r("v1.2.3", "caption")]))))


def test_decorative_metadata_strip_and_ambient_status():
    extract = doc(("hero", [r("Seoul · Est. 2024 · Open daily", "caption"), r("All systems operational", "label")]))
    kinds = observed(lint("copy.decorative-metadata", extract=extract))
    assert "metadata strip" in kinds and "ambient status" in kinds
    styled = [r(t, "caption", box=box(700), weight=w) for t, w in
              (("Seoul", 500), ("·", 300), ("Est. 2024", 500), ("·", 300), ("Open daily", 500))]
    strips = lint("copy.decorative-metadata", extract=doc(("hero", styled))).hits
    assert len(strips) == 1 and len(strips[0].refs) == 3
    plain = lint("copy.decorative-metadata", extract=doc(("hero", [r("Bowls from the September firing", "display")])))
    assert plain.hits == [] and plain.skipped is None

def test_kiln_shop_firing_log_is_data_not_decorative_metadata():
    example = json.loads((shared_dir() / "render" / "example.extract.json").read_text(encoding="utf-8"))
    result = lint("copy.decorative-metadata", extract=example)
    assert result.hits == []


def test_ambient_weather_line_outside_data_records_remains_a_hit():
    result = lint("copy.decorative-metadata", extract=doc(("hero", [r("20°C", "caption")])))
    assert "ambient status" in observed(result)


def test_three_independent_weather_lines_are_not_data_rows():
    extract = doc(("hero", [r("20°C", "caption"), r("21°C", "caption"), r("22°C", "caption")]))
    assert len(lint("copy.decorative-metadata", extract=extract).hits) == 3


@pytest.mark.parametrize("text", ["20°C", "11:05 UTC", "online"])
@pytest.mark.parametrize("ancestor,role", [(False, "table"), (False, "grid"),
                                           (True, "row"), (True, "cell"), (False, "gridcell")])
def test_ambient_status_with_accessible_data_role_is_not_a_hit(ancestor, role, text):
    extract = doc(("hero", [r(text, "caption", parent=box(700))] if ancestor else [r(text, "caption")]))
    boxes = extract["viewports"][0]["boxes"]
    target = next(b for b in boxes if b["id"] == (box(700) if ancestor else extract["viewports"][0]["text"][0]["box"]))
    target["a11y"] = {"role": role}
    assert list(EXTRACT.iter_errors(extract)) == []
    assert lint("copy.decorative-metadata", extract=extract).hits == []


def test_ambient_status_in_three_uniform_sibling_rows_is_not_a_hit():
    rows = [r(value, "caption", parent=box(700 + i), box=box(800 + i))
            for i, value in enumerate(("20°C", "11:05 UTC", "online"))]
    extract = doc(("hero", rows))
    assert lint("copy.decorative-metadata", extract=extract).hits == []
    # Two rows cannot establish a repeated data record.
    only_two = doc(("hero", rows[:2]))
    assert "ambient status" in observed(lint("copy.decorative-metadata", extract=only_two))


def test_ambient_status_in_rows_with_different_text_run_counts_remains_a_hit():
    rows = [r("20°C", "caption", parent=box(700)), r("21°C", "caption", parent=box(701)),
            r("glaze", "caption", parent=box(701)), r("22°C", "caption", parent=box(702)),
            r("clay", "caption", parent=box(702)), r("glaze", "caption", parent=box(702))]
    assert "20°c" in observed(lint("copy.decorative-metadata", extract=doc(("hero", rows))))


# ---------------------------------------------------------------- name-swap and counterfactual

def test_name_swap_flags_key_copy_with_no_anchor():
    result = lint("copy.name-swap", "plan", plan=plan([("headline", "Build better products faster"),
                                                        ("cta", "Get started")]))
    assert [h.location["path"] for h in result.hits] == ["content.key_copy[0].text"]


@pytest.mark.parametrize("headline", ["Bowls from the September firing", "Twenty-four celadon bowls",
                                      "9월 소성분, 스물네 점이 나왔어요", "Glaze notes from the kiln log"])
def test_name_swap_passes_anchored_key_copy(headline):
    p = plan([("headline", headline)], world=["kiln log", "glaze numbers"])
    assert lint("copy.name-swap", "plan", plan=p).hits == []


def test_name_swap_needs_key_messages():
    result = lint("copy.name-swap", "plan", plan=plan([("cta", "Reserve")]))
    assert result.hits == [] and "headline" in result.skipped


def test_review_layer_tests_are_left_to_the_reviewer():
    extract = doc(("hero", [r("Bowls from the September firing", "display")]))
    swap = lint("copy.name-swap", "review", extract=extract)
    assert swap.hits == [] and "reviewer" in swap.skipped and "September firing" in swap.skipped
    counter = lint("layout.hero-before-priority", "review", plan=plan())
    assert counter.hits == [] and "pottery studio" in counter.skipped
