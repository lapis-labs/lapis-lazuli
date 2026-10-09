"""Copy detectors: word families, rhetorical shells, constructions, punctuation, rhythm, formatting
residue, separator shapes, register, placeholder and proof content, meta text, the review-layer
name-swap and counterfactual tests, and plan-anchored-text, which keeps form levers tied to the plan's
world materials.

Where copy comes from
  render  the text runs of one viewport of the extract: the one with the most text, ties to the
          widest (copy repeats across viewports). Sections are `derived.sections`, else top-level
          `section` boxes. Runs in `code` (and, for counts, `data`) are not copy.
  plan    the strings at the rule's `path`; when the path ends in a field (`...key_copy[*].text`),
          the owning item gives the slot and locale.

Locale of a piece of copy: Hangul script is ko and kana is ja whatever `lang` says (the script is
measured, `lang` is declared); Han takes a CJK `lang` or zh; anything else takes its `lang`, then the
plan's first non-CJK brief locale, then en. A rule's `locales` keep only matching copy. List values
come from the rules `lists` for that locale plus `all`, plus `latin` for Latin script.

Matching is lexical without the optional cjk extra. When installed, Korean values ending in a
verb or adjective compare lemma sequences, double passives use morpheme order, and placeholder
names require a complete proper noun. Japanese and Chinese density uses analyzed word counts.
Latin terms match whole words with common inflections; Korean lexical terms match from a word
start with particle alternation and `-적인`/`-한` stems; ja/zh lexical terms match substrings.
Values naming a family or construction expand through the lexicons below. Copy whose locale has
no values or patterns is not judged; when nothing hits, the result skips those locales.

Density (`trigger: density`) hits when there are at least two instances and more than one per
`per` unit (default 1,000 words); one instance alone is never density. Without the analyzer,
ja/zh text counts two Han or kana characters as one word. Lexicons, baselines, and bounds below
are v0 seeds to calibrate against the corpora.

Evidence: plan hits are `plan`, render hits `measurement`. Fabricated-proof hits are proof-like
content the plan's claims do not back, so they carry `not-verified`: the detector cannot tell
invented proof from real proof. The review layer of name-swap-test and counterfactual-test is a
reviewer's judgement, so those skip with a reason that says what to judge.

plan-anchored-text compares strings, not copy: the plan strings at `path` against the strings at each
anchor path. Latin-script words of three or more letters match by their first five letters once common
function words are removed; Hangul, kana, and Han text matches by runs of two characters.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import accumulate

from lapis_design.lint import morph
from lapis_design.lint.types import Context, Hit, Result, detector

# ---------------------------------------------------------------- calibration seeds (v0)

_DENSITY_PER_UNIT_MAX = 1.0          # instances per `per` unit allowed before density hits
_DENSITY_MIN_COUNT = 2               # density never hits on a single instance
_CJK_CHARS_PER_WORD = 2              # ja/zh: Han and kana characters counted as one word
_RHYTHM_MIN_SENTENCES = 5            # body sentences a locale needs before rhythm is judged
_RHYTHM_LENGTH_CV_MIN = 0.3          # sentence-length coefficient of variation below this is uniform
_RHYTHM_MIN_REPEATS = 3
_RHYTHM_OPENING_SHARE = 0.4          # one opening on at least this share of sentences (and 3)
_RHYTHM_ENDING_SHARE = 0.5
_BOLD_LABEL_MIN = 3                  # bold-labeled items in one list or section
_EMOJI_MARKER_MIN = 3                # runs that start with an emoji
_RESTATING_HEADINGS_MIN = 2          # headings that restate the sentence after them
_RESTATE_OVERLAP_MIN = 0.6           # share of heading words (or CJK bigrams) found in that sentence

# Glyph names for punctuation-density, and the human rate of each per 1,000 non-space characters
# by locale (`latin` covers Latin-script locales without an entry). Consecutive glyphs count once.
_GLYPHS = {"em-dash": "\u2014\u2015\u2e3a\u2e3b"}
_GLYPH_BASELINE = {"em-dash": {"en": 0.4, "latin": 0.4, "ko": 0.1, "ja": 0.2, "zh": 0.3}}

# Terms that realize each metaphor family (lists.metaphor_families names the families).
_METAPHOR_LEXICON: dict[str, dict[str, list[str]]] = {
    "economic-mass": {"en": ["critical mass", "flywheel", "momentum", "center of gravity", "gravitational pull"],
                      "ko": ["임계질량", "무게중심", "구심력", "관성", "플라이휠"],
                      "ja": ["臨界質量", "重心", "弾み車"], "zh": ["临界质量", "重心", "飞轮效应"]},
    "accounting": {"en": ["ledger", "balance sheet", "bottom line", "pays dividends", "the bill comes due", "price to pay"],
                   "ko": ["청구서", "대차대조표", "장부", "손익계산서", "대가를 치르"],
                   "ja": ["貸借対照表", "帳尻", "ツケ"], "zh": ["账单", "资产负债表", "买单"]},
    "agriculture": {"en": ["plant the seeds", "seeds of", "sow the", "reap", "bear fruit", "fertile ground", "cultivate"],
                    "ko": ["씨앗", "씨를 뿌리", "열매를 맺", "토양", "뿌리내리", "싹을 틔우"],
                    "ja": ["種をまく", "実を結ぶ", "土壌", "根付く"], "zh": ["种子", "播种", "开花结果", "土壤", "扎根"]},
    "architecture": {"en": ["cornerstone", "pillar", "bedrock", "building blocks", "scaffolding", "bridge the gap"],
                     "ko": ["초석", "주춧돌", "기둥", "토대", "디딤돌", "가교"],
                     "ja": ["礎", "土台", "架け橋"], "zh": ["基石", "支柱", "桥梁", "奠基"]},
    "weight": {"en": ["heavy lifting", "weighs on", "burden", "lighten the load", "carry the weight"],
               "ko": ["짓누르", "짓눌", "무게를 덜", "짐을 덜", "어깨를 가볍"],
               "ja": ["重荷", "肩の荷", "のしかかる"], "zh": ["重担", "包袱", "压在"]},
    "signal": {"en": ["cut through the noise", "signal from the noise", "signal-to-noise", "amplify", "resonate"],
               "ko": ["신호탄", "소음을 뚫", "울림", "공명"],
               "ja": ["のろし", "共鳴"], "zh": ["噪音中", "共鸣"]},
    "mirror-shadow": {"en": ["mirror", "in the shadow of", "casts a shadow", "reflection of"],
                      "ko": ["거울", "그림자", "투영"],
                      "ja": ["鏡", "影を落と", "映し出"], "zh": ["镜子", "阴影", "折射出"]},
    "journey": {"en": ["journey", "roadmap", "milestone", "embark", "every step of the way", "path to"],
                "ko": ["여정", "이정표", "로드맵", "첫걸음", "발걸음"],
                "ja": ["旅路", "道のり", "道しるべ", "第一歩"], "zh": ["旅程", "征程", "里程碑", "之旅"]},
    "tapestry": {"en": ["tapestry", "woven", "interwoven", "fabric of", "weave"],
                 "ko": ["태피스트리", "직조", "엮어 내", "씨줄과 날줄"],
                 "ja": ["織りなす", "織り成す", "タペストリー"], "zh": ["交织", "编织", "织就"]},
    "theater": {"en": ["center stage", "take the stage", "set the stage", "spotlight", "behind the scenes", "curtain"],
                "ko": ["무대", "주인공", "스포트라이트", "막이 오르"],
                "ja": ["舞台", "主役", "スポットライト", "幕を開け"], "zh": ["舞台", "主角", "聚光灯", "拉开帷幕"]},
    "compass": {"en": ["compass", "north star", "true north", "guiding star"],
                "ko": ["나침반", "나침판", "북극성"],
                "ja": ["羅針盤", "北極星", "指針"], "zh": ["指南针", "罗盘", "北极星"]},
    "lighthouse": {"en": ["lighthouse", "beacon", "guiding light"], "ko": ["등대", "등불"],
                   "ja": ["灯台", "道標"], "zh": ["灯塔", "明灯"]},
    "key": {"en": ["the key to", "keys to", "master key", "holds the key"], "ko": ["열쇠", "마스터키"],
            "ja": ["鍵を握", "カギを握", "鍵となる"], "zh": ["钥匙", "金钥匙"]},
    "blueprint": {"en": ["blueprint"], "ko": ["청사진", "설계도"], "ja": ["青写真", "設計図"], "zh": ["蓝图"]},
}

# Construction names and patterns (lists.translationese_constructions). Other values match literally,
# with a leading `~` meaning the pattern attaches to the preceding word.
# Passive verbs made with -이-, -히-, -리-, -기- whose common reading is passive, with their -어 forms.
# Adding -어지다 to one of these is a double passive, and so it is for a compound ending in one
# (짓눌리다, 뒤섞이다, 파묻히다). Causatives of the same shape (알리다, 남기다, 맡기다, 숨기다, 입히다,
# 살리다, 옮기다, 벗기다, 물리다 as "hand down") and verbs that only end in that sound (그리다, 버리다,
# 가리다) are left out: their -어지다 forms are ordinary. 불리다, 안기다, 감기다, 씻기다, 읽히다, 묻히다,
# and 들리다 also have causative readings and stay in, a known limit.
_PASSIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("보이다", "보여"), ("놓이다", "놓여"), ("쓰이다", "쓰여"), ("쌓이다", "쌓여"), ("섞이다", "섞여"),
    ("묶이다", "묶여"), ("덮이다", "덮여"), ("꺾이다", "꺾여"), ("모이다", "모여"), ("파이다", "파여"),
    ("깎이다", "깎여"), ("볶이다", "볶여"), ("짜이다", "짜여"), ("꼬이다", "꼬여"), ("바뀌다", "바뀌어"),
    ("나뉘다", "나뉘어"), ("뒤집히다", "뒤집혀"), ("잊히다", "잊혀"), ("닫히다", "닫혀"), ("읽히다", "읽혀"),
    ("잡히다", "잡혀"), ("얽히다", "얽혀"), ("갇히다", "갇혀"), ("박히다", "박혀"), ("찍히다", "찍혀"),
    ("막히다", "막혀"), ("먹히다", "먹혀"), ("뽑히다", "뽑혀"), ("묻히다", "묻혀"), ("밟히다", "밟혀"),
    ("긁히다", "긁혀"), ("꽂히다", "꽂혀"), ("접히다", "접혀"), ("얹히다", "얹혀"), ("걷히다", "걷혀"),
    ("불리다", "불려"), ("열리다", "열려"), ("팔리다", "팔려"), ("밀리다", "밀려"), ("걸리다", "걸려"),
    ("풀리다", "풀려"), ("들리다", "들려"), ("눌리다", "눌려"), ("뚫리다", "뚫려"), ("털리다", "털려"),
    ("갈리다", "갈려"), ("깔리다", "깔려"), ("쓸리다", "쓸려"), ("헐리다", "헐려"), ("찔리다", "찔려"),
    ("잘리다", "잘려"), ("몰리다", "몰려"), ("실리다", "실려"), ("흔들리다", "흔들려"), ("쫓기다", "쫓겨"),
    ("찢기다", "찢겨"), ("끊기다", "끊겨"), ("담기다", "담겨"), ("뜯기다", "뜯겨"), ("빼앗기다", "빼앗겨"),
    ("잠기다", "잠겨"), ("믿기다", "믿겨"), ("안기다", "안겨"), ("감기다", "감겨"), ("씻기다", "씻겨"),
    ("씌다", "씌어"), ("씹히다", "씹혀"), ("업히다", "업혀"), ("치이다", "치여"), ("베이다", "베여"),
)
# Longer verbs that end in a listed one but are not passives of it.
_PASSIVE_EXCLUDED: tuple[tuple[str, str], ...] = (
    ("선보이다", "선보여"), ("내보이다", "내보여"), ("부풀리다", "부풀려"), ("엇갈리다", "엇갈려"),
)


def _passive_form_pattern(form: str) -> str:
    """The -어 form, unless it is the tail of an excluded longer verb (선보여 is not 보여)."""
    heads = [ex[: -len(form)] for _, ex in _PASSIVE_EXCLUDED if ex.endswith(form) and ex != form]
    return "".join(f"(?<!{re.escape(h)})" for h in heads) + re.escape(form)


_CONSTRUCTIONS: dict[str, dict[str, re.Pattern]] = {
    "double-passive": {"ko": re.compile(      # -어지- on a passive stem; 지/져 with any final consonant
        r"되어[\uc9c0-\uc9db\uc838-\uc853]|돼[\uc9c1-\uc9db\uc838-\uc853]"
        r"|(?:" + "|".join(_passive_form_pattern(form) for _, form in _PASSIVE_PAIRS) + r")[\uc9c0-\uc9db\uc838-\uc853]")},
    "~에 있어서": {"ko": re.compile(r"에\s?있어서")},
    "~를 통해": {"ko": re.compile(r"[을를]\s?통(?:해|하여)")},
    "~에 의해": {"ko": re.compile(r"에\s?의(?:해|하여)")},
    "~것이 가능": {"ko": re.compile(r"것이\s?가능")},
    "することができる": {"ja": re.compile(r"(?:する)?ことが(?:でき|出来)")},
    "bei-passive-overuse": {"zh": re.compile(r"被")},
}

# not-x-but-y contrast frames, on case-folded text
_NEG = r"(?:isn't|aren't|wasn't|weren't|doesn't|don't|is not|are not|was not|were not|does not|do not|not)"
_PRON = r"(?:it|this|that|they|we|you|he|she)"
_BE = r"(?:'s|'re|\s+is|\s+are|\s+was|\s+were)"
_CONTRAST = {loc: [re.compile(p) for p in pats] for loc, pats in {
    "en": [r"\bnot\s+(?:just|only|merely|simply)\b[^.!?]{1,80}?\bbut\b",
           rf"\b{_PRON}(?:{_BE})?\s+{_NEG}\b[^.!?;\u2014]{{1,80}}?(?:[.!?;]\s*|\s*[\u2014\u2013]\s*|\s+-\s+){_PRON}{_BE}\b",
           r"\bnot\s+(?!just\b|only\b|merely\b|simply\b)[^.!?;]{1,60}?,\s*but\s",
           r"\bmore than (?:just|merely|simply)\b",
           r"\bless\s+[\w-]+,\s*more\s+[\w-]+"],
    "ko": [r"[이가]\s?아니라", r"뿐(?:만)?\s?아니라", r"[을를]\s?넘어(?:서)?\s", r"에\s?그치지\s?않",
           r"[이가]\s?아닌\s", r"아(?:닙니다|니에요|니다|니죠)[.!]?\s+\S"],
    "ja": [r"だけ(?:で)?なく", r"ではなく", r"にとどまらず", r"というより"],
    "zh": [r"不是[^。！？]{1,30}?而是", r"不(?:仅|只)(?:仅|是)?[^。！？]{1,30}?(?:而且|更|还|也)",
           r"与其说[^。！？]{1,30}?不如说"],
}.items()}

_TRIAD_CONJ = {"en": re.compile(r",?\s+(?:and|or|&)\s+(?=\S)"), "ko": re.compile(r",?\s*(?:그리고|및)\s+")}
_TRIAD_SPLIT = re.compile(r",\s+|[、，]\s*")

# Sentence-final endings by register (ko needs two or more words for the plain -다 ending)
_KO_REGISTERS = (("hapnida", re.compile(r"(?:니다|니까|십시오)$")),
                 ("haeyo", re.compile(r"(?<![필중주수개강소])(?:요|죠)$")),
                 ("haera", re.compile(r"(?<!니)다$")))
_JA_REGISTERS = (("desu-masu", re.compile(r"(?:です|ます|でした|ました|ません|ましょう|でしょう|ください|ませんか)$")),
                 ("da-dearu", re.compile(r"(?:である|であった|であろう|だった|だろう|ではない|じゃない|だ)$")))
_ZH_FORMAL = re.compile(r"您|敬请|予以|烦请")
_ZH_CASUAL = re.compile(r"你|咱们|[吧呢啦呀哦嘛]$")
_REGISTER_LANG = {"haeyo": "ko", "hapnida": "ko", "haera": "ko", "desu-masu": "ja", "da-dearu": "ja",
                  "zh-formal": "zh", "zh-casual": "zh", "en-formal": "en", "en-casual": "en"}

# placeholder-genericness, fabricated-proof
_PROOF_METRICS = [re.compile(p) for p in (
    r"(?<![\w.])\d[\d,.]*\s*(?:k|m|b|만|천|억|万|千|億|亿)?\s*\+(?!\d)",
    r"(?<![\w.])\d[\d.]*\s*[x×](?!\w)",
    r"(?<![\w.])\d[\d.]*\s*%\s*(?:faster|more|less|fewer|higher|lower|uptime|satisfaction|retention|growth|increase"
    r"|reduction|accuracy|of (?:customers|users|teams|companies))",
    r"(?<![\w.])\d[\d,.]*\s*(?:k|m)?\s+(?:happy\s+)?(?:customers|users|teams|companies|businesses|developers|downloads"
    r"|installs|reviews|brands|clients|members|creators|subscribers)\b",
    r"(?<![\w.])\d(?:\.\d)?\s*(?:/\s*5|out of 5)(?!\d)|[★⭐]{3,}",
    r"#\s?1\b|\bno\.\s?1\b|\bnumber one\b|(?:업계|국내|세계)\s*1위|(?:業界|业界|行业)\s*(?:no\.?\s?1|第一|初)",
    r"누적\s*\d|\d[\d,.]*\s*(?:만|천|억)?\s*(?:명|곳|개사|개\s?기업)(?:의|이|가)?\s*(?:고객|사용자|기업|팀|회원)?\S*\s*(?:사용|선택|신뢰|함께|이용)",
    r"\d[\d.]*\s*%\s*(?:향상|증가|감소|절감|만족|성장)|\d[\d.]*\s*배\s*(?:더|빠른|빠르|향상|증가|성장)",
    r"(?:만족도|평점|満足度|满意度)\s*\d",
)]
_SAMPLE_DISCLOSURE = re.compile(
    r"\b(?:sample|example|demo|dummy|fictional|illustrative)\s+(?:data|content|figures|numbers|testimonials?|reviews?|quotes?)\b"
    r"|\bfor illustration\b|예시|샘플|가상의|サンプル|架空|示例|演示数据")
_QUOTE_OPEN = "\"'«„「『"
_TITLE_WORDS = re.compile(r"\b(?:ceo|cto|coo|cmo|founder|co-founder|head of|director|manager|vp|lead)\b"
                          r"|대표|이사|팀장|매니저|창업자|부장|원장")
_TRUSTED_BY = re.compile(r"\b(?:trusted|used|loved|chosen) by\b|고객사|함께하는\s*(?:기업|고객|파트너)|導入企業|合作伙伴")
_PHOTO_CREDIT = re.compile(r"\b(?:photo|image|photograph|illustration)s?\s*(?:by\b|:|©|courtesy of\b)\s*\S"
                           r"|사진\s*(?:제공|출처|:|©)|写真\s*[:：]|撮影\s*[:：]|图片来源|摄影\s*[:：]")

# meta-text patterns by locale (`any` applies to every locale)
_PRODUCER = {loc: [re.compile(p) for p in pats] for loc, pats in {
    "any": [r"\{\{[^}]*\}\}|\$\{[^}]*\}|%s\b",
            r"^(?:undefined|null|nan|\[object object\])$"],
    "en": [r"\b(?:todo|tbd|fixme)\b",
           r"\b(?:your|the)\s+(?:headline|tagline|title|copy|text|description|company name|brand name|logo)\s+(?:goes\s+)?here\b",
           r"\b(?:insert|replace)\s+(?:your\s+|the\s+)?(?:headline|tagline|copy|text|description|image|logo|company|brand|content)\b",
           r"\bthis\s+(?:section|page|card|component|block|hero|banner|module)\s+(?:shows|displays|describes|highlights|presents"
           r"|contains|is where|lets users|will)\b",
           r"\b(?:placeholder|sample text|dummy text)\b",
           r"\[(?:your|company|brand|product|insert)[^\]]*\]",
           r"\bas an ai\b|\blanguage model\b",
           r"\b(?:hero section|above the fold|cta section)\b"],
    "ko": [r"여기에\s*\S*\s*(?:들어갑니다|들어가요|표시됩니다|넣으세요)", r"(?:제목|문구|텍스트|설명)이?\s*들어갑니다",
           r"이\s*(?:섹션|컴포넌트|블록|히어로|모듈)(?:은|는|에서는|에서)", r"(?:더미|샘플)\s*(?:텍스트|문구)"],
    "ja": [r"ここに(?:テキスト|タイトル|見出し|説明)", r"この(?:セクション|コンポーネント|ブロック)(?:では|は)",
           r"(?:ダミー|サンプル)テキスト"],
    "zh": [r"(?:此处|这里)(?:填写|输入|放置)", r"(?:本|此|这个)(?:区块|组件|模块|板块)(?:展示|用于|将)", r"(?:占位|示例)(?:文本|文字)"],
}.items()}
_BUILD_LABELS = {loc: [re.compile(p) for p in pats] for loc, pats in {
    "any": [r"(?<![\w.])v\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?\b", r"\blocalhost\b|\b127\.0\.0\.1\b", r"\bcommit\s+[0-9a-f]{7,40}\b"],
    "en": [r"\bbuild\s*#?\s*\d[\w.]*|\b(?:version|ver\.|release)\s*#?\s*\d+\.\d[\w.]*",
           r"\b(?:dev|staging|preview)\s+(?:build|environment|server|mode)\b",
           r"\bbuilt with\s+(?!(?:care|love|passion|pride|privacy|purpose|intention\w*|attention|heart|you|your|us|our|"
           r"an?|the|no|every|each|craft\w*)\b)\S|\bgenerated (?:by|with)\s+(?!users?\b|you\b|the\b)\S"],
    "ko": [r"버전\s*\d+\.\d|빌드\s*#?\d", r"(?:개발|스테이징)\s*(?:서버|환경|모드|빌드)"],
    "ja": [r"バージョン\s*\d+\.\d|ビルド\s*#?\d"],
    "zh": [r"版本\s*\d+\.\d|构建\s*#?\d"],
}.items()}
_DEMO_BADGES = {loc: [re.compile(p) for p in pats] for loc, pats in {
    "any": [],
    "en": [r"^(?:(?:interactive|live|local|product|offline|design|concept)\s+)?"
           r"(?:demo|beta|alpha|mock|mockup|prototype|placeholder|wip|concept)"
           r"(?:\s+(?:mode|data|version|only|build|preview|site|page))?$",
           r"^(?:interactive|live|local|offline|design|concept|product)\s+(?:preview|sample|example|test)$",
           r"^(?:preview|sample|example|test|draft)\s+(?:mode|data|version|only|build)$"],
    "ko": [r"^(?:데모|베타|목업|시안|체험판|시연)(?:\s*(?:모드|데이터|버전|화면))?$",
           r"^(?:샘플|예시|테스트|미리보기)\s*(?:모드|데이터|버전|화면)$"],
    "ja": [r"^(?:デモ|ベータ|ダミー)(?:版|モード|画面)?$",
           r"^(?:サンプル|テスト|仮|見本)(?:版|モード|画面|データ)$"],
    "zh": [r"^(?:演示|测试|示例|样例|内测)(?:版|模式)?$"],
}.items()}
_AMBIENT = {loc: [re.compile(p) for p in pats] for loc, pats in {
    "any": [r"(?<![\w.])-?\d{1,3}\s*°\s*[cf]?(?!\w)", r"^[●•◉🟢🔴]\s*\S"],
    "en": [r"\ball systems? (?:operational|normal|go)\b", r"\bsystems? (?:operational|online)\b",
           r"^(?:online|offline|live|open now|now open|available|busy|away)$", r"\blocal time\b",
           r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\s*(?:kst|utc|gmt|pst|pdt|est|edt|cet|cest|jst|bst)\b",
           r"\bavailable for (?:work|hire|new projects|freelance|projects)\b"],
    "ko": [r"(?:운영|영업)\s*중", r"정상\s*운영|모든\s*시스템\s*정상", r"^(?:온라인|오프라인|라이브)$", r"현지\s*시각"],
    "ja": [r"営業中|稼働中|現地時間"],
    "zh": [r"营业中|运行正常|系统正常|当地时间"],
}.items()}


def _by_locale(table: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    return {loc: [re.compile(p) for p in pats] for loc, pats in table.items()}


# A notice that the page, its data, or its subject is not real: the one disclosure a brief may ask for.
_NOTICE = _by_locale({
    "any": [],
    "en": [r"\b(?:fictional|fictitious|imaginary|invented|made[- ]up|fake)\b",
           r"\b(?:sample|example|dummy|demo|demonstration|placeholder|test|mock)\s+"
           r"(?:data|content|figures|numbers|names|text|reviews|testimonials)\b",
           r"\b(?:this|the)\s+(?:\w+\s+){0,2}?(?:page|site|website|app|workspace|feature|article|story|screen)\s+"
           r"(?:is|was|uses|contains|runs|simulates|only|does not|doesn't|has no)\b[^.!?]{0,90}"
           r"\b(?:demo|demonstration|prototype|concept|preview|simulat\w+|example|sample|mock\w*|local|offline)\b",
           r"\b(?:this|the)\s+(?:(?:local|interactive|live|product|standalone|offline|design|concept)\s+)*"
           r"(?:demo|demonstration|prototype|simulation|mockup|preview)\b(?!\s+(?:of|for|video|reel))",
           r"\b(?:in|for|on)\s+(?:this|the)\s+(?:local\s+)?(?:demo|demonstration|prototype|preview|concept)\b",
           r"\b(?:local|offline)\s+(?:demo|demonstration|preview|prototype|concept)\b",
           r"\bdemo\s+(?:signup|sign-up|form|reservation|booking|checkout|preview|mode|data|version|site)\b",
           r"\b(?:product|service|offline|illustrative|local)\s+concept\b|\bconcept\s+(?:website|site|page|pricing)\b"
           r"|\ban?\s+(?:(?:product|service|offline|illustrative|local|design|proposed|working)\s+)?concept\b"
           r"(?!\s+(?:car|store|art|design|album|in|of|that|which)\b)",
           r"\bnot (?:a|an) (?:real|actual|genuine)\b|\b(?:isn't|is not|aren't|are not) (?:a |an )?(?:real|actual|genuine)\b"
           r"|\bno real\b",
           r"\b(?:preview|demo|test|sample) only\b",
           r"\bworking title\b"],
    "ko": [r"가상의|가상\s?(?:데이터|도시|병원|의원|인물|매장|서비스|회사|전시|미술관|브랜드)",
           r"허구|실존하지",
           r"실제(?:로)?\s?(?:존재|운영|영업|판매|진료|예약|주문|결제|운행|접수|전시)?[^.。]{0,24}(?:않|아닙|아니|없)",
           r"(?:예시|샘플|시연|테스트|체험|데모)\s?(?:용|데이터|화면|페이지|버전|사이트|문구|목적)",
           r"시뮬레이션\s?(?:입니다|이에요|이며|이고|화면|페이지|용)",
           r"더미|임시\s?데이터"],
    "ja": [r"架空|フィクション",
           r"(?:サンプル|ダミー|テスト|仮)(?:の)?(?:データ|テキスト|情報|店舗|商品|内容)|仮のサンプル",
           r"(?:デモ|体験|サンプル|テスト|見本)(?:用|版|サイト|ページ|画面)",
           r"(?:実在|実際の)[^。]{0,12}(?:ありません|ではありません|しません|行われません|できません|されません)",
           r"モックアップ|シミュレーション(?:です|用|画面)"],
    "zh": [r"虚构|示例数据|演示数据|仅(?:供|用于)演示|并非真实|不是真实|非真实",
           r"(?:本|此)(?:页面|网站|站点)(?:仅|为|是)[^。]{0,16}(?:演示|示例|原型|概念)"],
})
# Narration of what the builder changed.
_PAGE_EN = (r"(?:page|layout|design|section|hero|header|footer|navigation|navbar|button|heading|headline|copy|text|"
            r"wording|styles?|styling|colou?rs?|palette|typography|fonts?|spacing|animations?|responsiveness|mobile|"
            r"accessibility|contrast|code|markup|css|content|ui|interface|site|website|landing page)")
_PAGE_KO = (r"(?:페이지|레이아웃|디자인|섹션|히어로|헤더|푸터|내비게이션|버튼|제목|헤드라인|문구|텍스트|문장|스타일|색상|배색|"
            r"폰트|글꼴|간격|애니메이션|반응형|모바일|접근성|대비|코드|마크업|콘텐츠|화면|ui|인터페이스)")
_PAGE_JA = (r"(?:ページ|レイアウト|デザイン|セクション|ヒーロー|ヘッダー|フッター|ナビゲーション|ボタン|見出し|キャッチコピー|"
            r"文言|テキスト|文章|スタイル|配色|カラー|フォント|余白|アニメーション|レスポンシブ|モバイル|アクセシビリティ|"
            r"コントラスト|コード|マークアップ|コンテンツ|画面|ui|インターフェース)")
_CHANGED_EN = (r"(?:updated|fixed|improved|refactored|redesigned|reworked|rewrote|rewritten|tweaked|adjusted|changed|"
               r"modified|simplified|refined|polished|cleaned up|removed|added|replaced|swapped|reorganized|"
               r"restructured|optimi[sz]ed|revised)")
_CHANGE_LOG = _by_locale({
    "any": [],
    "en": [rf"\b(?:i|we)(?:'ve|\s+have)?\s+(?:just\s+|now\s+|also\s+)?{_CHANGED_EN}\s+"
           rf"(?:the\s+|this\s+|your\s+|our\s+|some\s+|all\s+|its\s+)?(?:\w+\s+){{0,2}}?{_PAGE_EN}\b",
           rf"\b{_PAGE_EN}\s+(?:has|have|was|were)\s+(?:also\s+|now\s+)*(?:been\s+)?{_CHANGED_EN}\b",
           r"\b(?:here(?:'s| is)|below is)\s+the\s+(?:updated|revised|new|improved|fixed)\s+(?:version|page|design|layout|code)\b",
           r"\b(?:i|we)(?:'ve|\s+have)?\s+made\s+(?:the\s+following|these|some|a few)\s+(?:changes|updates|improvements|fixes|adjustments)\b",
           r"\b(?:changes|updates|improvements|fixes)\s+(?:made|applied|included)\s*[:.]"],
    "ko": [rf"{_PAGE_KO}(?:을|를|이|가|은|는|도)?\s*(?:[^\s.!?]{{1,8}}\s+)?"
           r"(?:수정|개선|변경|추가|삭제|제거|교체|정리|보완|리팩터링|업데이트|재구성|재설계|조정|최적화)"
           r"(?:했|하였|해\s?두었|해\s?드렸|되었|됐)",
           r"(?:수정|개선|변경|업데이트|반영)(?:한|된)\s*(?:버전|내용|사항)\s*(?:입니다|이에요|은\s*다음)",
           r"(?:아래|다음)(?:와|과)\s*같이\s*(?:수정|개선|변경)(?:했|하였)"],
    "ja": [rf"{_PAGE_JA}(?:を|が|は|も)?[^。\s]{{0,8}}(?:修正|改善|変更|追加|削除|更新|調整|最適化|見直し|刷新|整理|リファクタリング)"
           r"(?:し(?:ました|た)|いたしました|され(?:ました|た)|済み)",
           r"(?:修正|改善|変更|更新)(?:した|しました)(?:バージョン|内容|点)(?:は|です)",
           r"(?:以下|下記)の(?:ように|とおり|通り)(?:修正|改善|変更)(?:しました|いたしました)"],
    "zh": [r"(?:页面|布局|设计|版块|按钮|标题|文案|样式|配色|字体|间距|动画|代码)(?:已|已经)?(?:被)?(?:修改|优化|改进|调整|更新|修复)(?:了|完成)",
           r"我(?:已|已经|刚)(?:修改|优化|修复|更新)了"],
})
# The page explaining itself instead of its subject.
_SELF_DESCRIPTION = _by_locale({
    "any": [],
    "en": [r"\b(?:this|the)\s+(?:section|page|screen|card|panel|block|hero|banner|module|component|widget|table|chart|form|area)\s+"
           r"(?:explains|demonstrates|gives you|lets you|allows you|lets visitors|allows visitors|is designed to|is meant to|"
           r"will show|helps you)\b",
           r"\b(?:click|tap|press|select|use)\s+(?:on\s+)?(?:the\s+)?(?:\w+\s+){0,2}?"
           r"(?:button|link|icon|tab|card|toggle|form|filters?|controls?|search)\s+(?:below|above)\s+to\b",
           r"\bbelow you(?:'ll| will| can)\s+(?:find|see|read|get)\b|\bhere you(?:'ll| will| can)\s+(?:find|see|read|get)\b",
           r"\bscroll(?: down)? to (?:see|find|read|learn|explore|discover)\b",
           r"\bas (?:shown|seen|described|listed|explained) (?:below|above)\b",
           r"\bthe (?:\w+\s+){0,2}(?:below|above)\s+(?:shows?|lists?|displays?|explains?|describes?)\b",
           r"\b(?:this|the)\s+(?:landing page|webpage|web page|website|site)\s+(?:was|is)\s+(?:designed|built|made|created|written)\s+"
           r"(?:to|for|with|using)\b",
           r"\bwelcome to (?:this|my|our) (?:demo|page|prototype|landing page|site)\b",
           r"\b(?:in|at|on) the next (?:step|screen|page),?\s+(?:you(?:'ll| will| can| may)|we(?:'ll| will))\b",
           r"\b(?:once|after|when) you (?:choose|select|pick|enter|fill)[^.!?]{0,60},?\s+(?:you(?:'ll| will)\s+)?"
           r"(?:move|go|proceed|continue)\s+(?:on\s+)?to the next (?:step|screen|page)\b",
           r"\bthe next step (?:is|will be) to\s+(?:enter|fill|choose|select|confirm|review)\b"],
    "ko": [r"(?:이|본)\s*(?:섹션|페이지|화면|영역|카드|표|차트|폼|패널|블록)(?:은|는|에서는|에서|에는)\s*[^.!?]{0,40}"
           r"(?:보여줍니다|보여드립니다|보여줘요|보여요|확인할\s*수\s*있습니다|확인할\s*수\s*있어요|소개합니다|소개해요|설명합니다|"
           r"설명해요|안내합니다|안내해요|나타냅니다|담고\s*있습니다|담았어요|담았습니다)",
           r"(?:아래|위)(?:의)?\s*(?:버튼|링크|카드|양식|폼|탭)[을를]?\s*(?:클릭|눌러|눌러서|선택)[^.!?]{0,12}"
           r"(?:하면|하여|해서|해\s*주세요|해보세요|하세요)",
           r"스크롤(?:을)?\s*(?:내려|하여|해서)",
           r"이\s*(?:랜딩\s*페이지|웹\s*페이지|웹사이트|사이트)(?:는|은)\s*[^.!?]{0,20}(?:만들었|제작했|제작되었|디자인했|디자인되었)",
           r"다음\s*(?:단계|화면|페이지)(?:에서는|에서|에는)\s*[^.!?]{0,30}?(?:입력|선택|확인|작성)"
           r"(?:합니다|해요|하게\s*됩니다|하게\s*돼요|하시게\s*됩니다|하시면\s*됩니다|하면\s*됩니다|해야\s*합니다|할\s*수\s*있(?:습니다|어요))",
           r"(?:선택|입력|작성)(?:하시면|하면|한\s*뒤|한\s*후)\s*다음(?:\s*(?:단계|화면|페이지))?(?:으로|로)\s*(?:이동|넘어)"],
    "ja": [r"(?:この|本)(?:セクション|ページ|画面|エリア|カード|表|グラフ|フォーム|パネル|ブロック)(?:では|は|には)[^。]{0,40}"
           r"(?:紹介|表示|説明|案内|掲載|ご覧いただけ|確認でき|示)(?:して|し)(?:います|ます|おります|ています)?",
           r"(?:下|上)(?:の|記の)(?:ボタン|リンク|カード|フォーム|タブ)を(?:クリック|押|タップ|選択)(?:して|すると|してください|し)",
           r"スクロール(?:して|すると)(?:ご覧|確認|見)",
           r"このサイトは[^。]{0,20}(?:作成|制作|デザイン)(?:されました|しました|いたしました)",
           r"次の(?:ステップ|画面|ページ)で[^。]{0,30}(?:入力|選択|確認)(?:します|いただきます|していただきます|できます)",
           r"(?:選択|入力)(?:すると|したら)、?次の(?:ステップ|画面|ページ)(?:へ|に)(?:進みます|移動します|進めます)"],
    "zh": [r"(?:本|此)(?:页面|区块|板块)(?:展示|介绍|说明|用于)",
           r"下一步(?:将|会|中)?[^。]{0,16}(?:输入|选择|确认|填写)", r"(?:选择|输入)(?:后|之后)(?:将|会)?(?:进入|跳转到?)下一步"],
})
# Notes between builders and testers.
_DEV_NOTES = _by_locale({
    "any": [],
    "en": [r"\b(?:dev(?:eloper)?|qa|internal)\s+(?:note|notes|only)\b|\bnote to self\b",
           r"\bfor (?:testing|qa|debugging|development)(?: (?:only|purposes))?\b",
           r"\b(?:test|dummy|mock(?:ed)?|stub(?:bed)?|seed) (?:data|account|user|page|mode|build|email|content)\b",
           r"\bdebug(?:ging)?\s+(?:mode|info|panel|output|log)\b",
           r"\bhard-?coded\b",
           r"\b(?:replace|swap)\s+(?:this\s+)?with\s+(?:real|actual|final|production)\b|\bwill be replaced\b"
           r"|\bto be (?:implemented|replaced|added|filled in|wired)\b|\bnot (?:yet )?implemented\b|\bimplement(?:ed)? later\b"],
    "ko": [r"(?:개발자|개발|내부|qa)\s*(?:메모|노트|참고|용도)|테스트(?:용|\s*(?:데이터|계정|페이지|모드|이메일))|디버그|하드코딩"
           r"|목업\s*데이터|임시\s*(?:문구|텍스트|이미지|데이터)|추후\s*(?:교체|구현|추가|수정)|구현\s*예정|나중에\s*(?:교체|구현)"
           r"|구현되지\s*않"],
    "ja": [r"(?:開発|内部|qa)(?:者)?(?:メモ|ノート|用)|テスト(?:用|データ|アカウント|ページ|モード)|デバッグ|ハードコード"
           r"|モックデータ|仮の(?:文言|テキスト|画像|データ)|後で(?:差し替え|実装|追加|修正)|実装予定|未実装|差し替え予定"],
    "zh": [r"开发(?:备注|笔记)|测试(?:用|数据|账号|页面)|调试|硬编码|占位|待实现|稍后替换"],
})
# An apology for a part that was never built.
_APOLOGY = _by_locale({
    "any": [],
    "en": [r"\b(?:sorry|apologi[sz]e|apologies|unfortunately|regret)\b.{0,60}"
           r"\b(?:demo|prototype|not (?:yet )?(?:implemented|built|ready|working|functional)|coming soon|"
           r"under construction|placeholder|still being (?:built|developed|worked on)|work in progress)\b",
           r"\b(?:this|that)\s+(?:feature|section|page|link|button|option)\s+(?:is\s+not|isn't)\s+(?:yet\s+)?"
           r"(?:implemented|built|functional|wired up)\b",
           r"\bnot available in (?:this|the) (?:demo|prototype|preview)\b",
           r"\b(?:is|are) (?:disabled|unavailable) in (?:this|the) (?:demo|prototype|preview)\b"],
    "ko": [r"(?:죄송|양해|불편).{0,40}(?:데모|개발\s*중|구현되지|미구현)",
           r"(?:이\s*)?(?:기능|링크|버튼|페이지)(?:은|는)\s*(?:데모|이\s*화면)에서(?:는)?\s*(?:지원|제공|사용|동작)(?:하지|되지|할\s*수\s*없)"],
    "ja": [r"(?:申し訳|恐れ入り|すみません).{0,30}(?:デモ|開発中|未実装|実装されて)",
           r"この(?:機能|リンク|ボタン|ページ)は(?:デモ|現在)[^。]{0,12}(?:対応していません|利用できません|実装されていません)"],
    "zh": [r"(?:抱歉|对不起).{0,30}(?:演示|暂未实现|尚未实现|开发中|未实现)"],
})
_NOTICE_KINDS = ("demo-badges", "fiction-notice")
_TEXT_KINDS = ("change-log", "developer-notes", "placeholder-apology", "self-description")
_META_KINDS_PLAN = ("producer-facing", "demo-badges", "fiction-notice", "build-labels", "chat-leftovers", *_TEXT_KINDS)
_META_KINDS_RENDER = ("producer-facing", "repeated-heading-body", "demo-badges", "fiction-notice", "build-labels",
                      "chat-leftovers", *_TEXT_KINDS, "decorative-metadata-strip", "ambient-status")
_PLAN_PLACE = {"headline": "hero", "subhead": "hero", "cta": "hero", "nav": "hero",
               "empty-state": "body", "error": "body"}      # the other slots hold a quiet line
_HEADER_BAND = 120                   # px from the top: a short label here is a persistent label, not a notice
_QUIET_FOOT = 0.8                    # share of the page height below which a line is in the foot of the page
_NOTICE_WORDS = 30                   # a quiet notice is a short line: at most this many words,
_NOTICE_CHARS = 120                  # or this many characters in unspaced scripts
_STRIP_SPLIT = re.compile(r"\s+[·•∙|｜/]\s+")
_STRIP_GLYPHS = set("·•∙|｜/ ")

_FORMAT_CHECKS = ("bold-label-bullets", "heading-restates-sentence", "emoji-markers", "decorative-capitalization",
                  "flattened-label-value")
_MD_EMPHASIS = re.compile(r"\*\*[^*\n]{1,60}\*\*|__[^_\n]{1,60}__")
_LABEL_VALUE = re.compile(r"(?:^|[·•|/;,]\s*|\s{2,})([^\W\d_][^:：·•|/;,\n]{0,24}?)\s*[:：]\s*(?!//)([^:：·•|/;,\n]{1,40})")
_SEP_SHAPE = re.compile(r"^(?P<label>[^:：|｜·—–]{1,40}?)\s*(?P<sep>[:：]|[|｜]|\s·\s|\s[—–-]\s|—|–)\s*(?P<tail>\S.*)$")

# name-swap-test: concrete anchors that tie key copy to one subject
_NUMBER_WORDS = re.compile(
    r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand"
    r"|dozen|january|february|march|april|june|july|august|september|october|november|december|monday|tuesday"
    r"|wednesday|thursday|friday|saturday|sunday)\b"
    r"|(?:스물|서른|마흔|쉰|예순|일흔|여든|아흔|열|다섯|여섯|일곱|여덟|아홉|[한두세네])\s?(?:점|개|명|가지|곳|달|해|잔|권|벌|장|시간|주|살|채|그릇)"
    r"|[一二三四五六七八九十百千万两]+\s?(?:个|件|位|名|次|年|月|日|天|种|款|点|枚|杯|人|社|本|つ)")
_STOPWORDS = frozenset(
    "with your from that this have more into what about their there every will make made than them they where when "
    "which while only just also over under most less very much many some such each other ours yours better best "
    "faster simple easy work works".split())

# Families judged on the whole control label: "Continue to checkout" names its outcome, "Continue" does not
_WHOLE_LABEL_FAMILIES = ("vague_cta",)
_CONTROL_ROLES = ("button", "link", "input")
_NOT_COPY = ("code", "data")
_NOT_PROSE = ("ui", "nav", "code", "data")
_CJK_LOCALES = ("ko", "ja", "zh")
_HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9d]")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_UNSPACED = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_TOKEN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|(?<=[。！？])\s*|\n+")
_NAME_VALUE = re.compile(r"[a-z]+(?:-[a-z]+)+")
_PLAN_FIELD = re.compile(r"[a-z_][a-z0-9_]*")
_KO_PARTICLES = {"를": "[을를]", "을": "[을를]", "는": "[은는]", "은": "[은는]", "가": "[이가]", "와": "[와과]", "과": "[와과]"}
_QUOTE_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201b": "'", "\u2032": "'",
                             "\u201c": '"', "\u201d": '"', "\u201e": '"'})


# ---------------------------------------------------------------- copy model

@dataclass
class _Seg:
    """One piece of copy: a render text run or a plan string."""
    text: str
    locale: str | None
    script: str | None
    loc: dict                       # Hit.location
    where: str                      # "heading run", "button label", "headline key copy", ...
    order: int = 0
    role: str | None = None         # text_run.type_role, or the key copy slot
    box: str | None = None
    box_role: str | None = None
    parent: str | None = None
    control: str | None = None      # role of the nearest button, link, or input box
    control_box: str | None = None
    section: int | None = None
    in_nav: bool = False
    list_box: str | None = None
    weight: float | None = None
    transform: str | None = None


@dataclass
class _Page:
    width: int | None
    segs: list[_Seg]
    boxes: dict[str, dict]
    sections: list[str]             # section box ids in order; empty when sections are unknown
    archetypes: list[str | None]    # one per section
    has_roles: bool
    view_height: float = 900.0      # visible height of the capture
    doc_height: float = 0.0         # bottom of the lowest box

    def loc(self, ctx: Context) -> dict:
        out: dict = {"viewport": self.width} if self.width else {}
        if ctx.extract_path:
            out["file"] = ctx.extract_path
        return out

    def archetype(self, section: int | None) -> str | None:
        return self.archetypes[section] if section is not None and section < len(self.archetypes) else None


@dataclass
class _Match:
    seg: _Seg
    label: str                      # the list value: a term, a family, or a construction name
    text: str                       # the matched copy, case-folded


def _straight(text: str) -> str:
    """NFKC with straight quotation marks, keeping the case."""
    return unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLD)


def _fold(text: str) -> str:
    return _straight(text).casefold()


def _clip(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _tokens(text: str) -> int:
    return sum(1 for t in text.split() if any(c.isalnum() for c in t))


def _morph(ctx: Context, text: str, locale: str | None) -> list[morph.Token] | None:
    key = ("copy.morph", locale, text)
    if key not in ctx.cache:
        normalized = unicodedata.normalize("NFC", text) if locale == "ko" else text
        tokens = morph.tokens(normalized, locale)
        if tokens is not None and normalized != text:
            # The analyzer's offsets are in NFC code points; match them to original
            # code-point boundaries by their common canonical decomposition.
            original = [0, *accumulate(len(unicodedata.normalize("NFD", c)) for c in text)]
            analyzed = [0, *accumulate(len(unicodedata.normalize("NFD", c)) for c in normalized)]
            tokens = [(form, lemma, pos, bisect_left(original, analyzed[start]),
                       bisect_left(original, analyzed[end]))
                      for form, lemma, pos, start, end in tokens]
        ctx.cache[key] = tokens
        if tokens is not None:
            analyzers = ctx.cache.setdefault("analyzers", {})
            if locale not in analyzers:
                analyzers[locale] = morph.analyzer_name(locale)
    return ctx.cache[key]


def _words(ctx: Context, text: str, locale: str | None) -> float:
    if locale in ("ja", "zh"):
        tokens = _morph(ctx, text, locale)
        if tokens is not None:
            return sum(1 for surface, _, _, _, _ in tokens if any(c.isalnum() for c in surface))
        return len(_UNSPACED.findall(text)) / _CJK_CHARS_PER_WORD + _tokens(_UNSPACED.sub(" ", text))
    return _tokens(text)


def _chars(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and any(c.isalnum() for c in s)]


def _script(text: str) -> str:
    """The extract's script code for a plan string (render/DERIVED.md, text runs)."""
    hang, kana, han = len(_HANGUL.findall(text)), len(_KANA.findall(text)), len(_HAN.findall(text))
    letters = [c for c in text if c.isalpha()]
    latn = sum(1 for c in letters if c < "\u0250")
    total = len(letters)
    if not total:
        return "other"
    if hang and hang + han >= total / 2:
        return "hang"
    if kana and kana + han >= total / 2:
        return "kana"
    if han >= total / 2:
        return "hani"
    if latn >= 0.8 * total:
        return "latn"
    return "other" if not latn else "mixed"


def _locale(script: str | None, lang: str | None, fallback: str) -> str | None:
    primary = lang.split("-")[0].lower() if lang else None
    if script == "hang":
        return "ko"
    if script == "kana":
        return "ja"
    if script == "hani":
        return primary if primary in _CJK_LOCALES else "zh"
    if primary:
        return primary
    if script in (None, "latn", "mixed", "other"):
        return fallback
    return script


def _fallback_locale(ctx: Context) -> str:
    for loc in ((ctx.plan or {}).get("brief") or {}).get("locales") or []:
        primary = str(loc).split("-")[0].lower()
        if primary not in _CJK_LOCALES:
            return primary
    return "en"


def _in_locales(seg: _Seg, locales: list[str] | None) -> bool:
    if not locales or "all" in locales or seg.locale in locales:
        return True
    return (seg.script == "latn" and "latin" in locales) or seg.script in locales


def _chain(boxes: dict[str, dict], box_id: str | None) -> list[dict]:
    """The box and its ancestors, nearest first."""
    out, seen = [], set()
    while box_id and box_id in boxes and box_id not in seen:
        seen.add(box_id)
        out.append(boxes[box_id])
        box_id = boxes[box_id].get("parent")
    return out


def _section_of(boxes: dict, chain: list[dict], sections: list[str]) -> int | None:
    index = {bid: i for i, bid in enumerate(sections)}
    for b in chain:
        if b.get("id") in index:
            return index[b["id"]]
    rect = chain[0].get("rect") if chain else None
    if rect:
        cx, cy = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
        for i, bid in enumerate(sections):
            r = (boxes.get(bid) or {}).get("rect")
            if r and r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"]:
                return i
    return None


def _render_page(ctx: Context) -> _Page | str:
    if "copy.page" not in ctx.cache:
        ctx.cache["copy.page"] = _build_page(ctx)
    return ctx.cache["copy.page"]


def _build_page(ctx: Context) -> _Page | str:
    ex = ctx.extract
    if not ex:
        return "no render extract given"
    vps = ex.get("viewports") or []
    if not vps:
        return "the render extract has no viewports"
    sizes = [sum(len(t.get("text") or "") for t in vp.get("text") or []) for vp in vps]
    vi = max(range(len(vps)), key=lambda i: (sizes[i], vps[i].get("width") or 0))
    vp = vps[vi]
    width = vp.get("width")
    if not sizes[vi]:
        if any(v.get("text") for v in vps):
            return "the render extract stores no copy: its text runs carry signatures only"
        return _Page(width, [], {}, [], [], False)
    boxes = {b["id"]: b for b in vp.get("boxes") or [] if isinstance(b, dict) and b.get("id")}
    sections = [(s.get("box"), s.get("archetype")) for s in (vp.get("derived") or {}).get("sections") or []]
    if not sections:
        sections = [(b["id"], None) for b in boxes.values() if b.get("role") == "section"
                    and not any(a.get("role") == "section" for a in _chain(boxes, b.get("parent")))]
    section_ids = [bid for bid, _ in sections]
    fallback = _fallback_locale(ctx)
    segs = []
    for j, t in enumerate(vp.get("text") or []):
        text = t.get("text")
        if not text or not text.strip():
            continue
        chain = _chain(boxes, t.get("box"))
        ctl = next((b for b in chain if b.get("role") in _CONTROL_ROLES), None)
        role = t.get("type_role")
        loc: dict = {"viewport": width, "path": f"/viewports/{vi}/text/{j}"}
        if t.get("box"):
            loc["box"] = t["box"]
        if ctx.extract_path:
            loc["file"] = ctx.extract_path
        segs.append(_Seg(
            text=text, locale=_locale(t.get("script"), t.get("lang"), fallback), script=t.get("script"), loc=loc,
            where=f"{ctl['role']} label" if ctl else f"{role} run" if role else "text run",
            order=j, role=role, box=t.get("box"), box_role=chain[0].get("role") if chain else None,
            parent=chain[0].get("parent") if chain else None,
            control=ctl.get("role") if ctl else None, control_box=ctl.get("id") if ctl else None,
            section=_section_of(boxes, chain, section_ids),
            in_nav=role == "nav" or any(b.get("role") == "nav" for b in chain),
            list_box=next((b["id"] for b in chain if b.get("role") == "list"), None),
            weight=t.get("weight"), transform=t.get("transform")))
    view = vp.get("height") or (900 if (width or 0) >= 1024 else 844)
    bottom = max((b["rect"]["y"] + b["rect"]["h"] for b in boxes.values() if b.get("rect")), default=0.0)
    return _Page(width, segs, boxes, section_ids, [a for _, a in sections], any(s.role for s in segs), view, bottom)


def _render_segs(ctx: Context, rule: dict) -> tuple[_Page, list[_Seg]] | Result:
    page = _render_page(ctx)
    if isinstance(page, str):
        return Result(skipped=page)
    if not page.segs:
        return Result(skipped="the render extract has no text runs")
    locales = rule.get("locales")
    segs = [s for s in page.segs if _in_locales(s, locales)]
    if not segs:
        return Result(skipped=f"no rendered copy in the rule's locales ({', '.join(locales)})")
    return page, segs


def _plan_paths(plan: dict) -> dict[int, str]:
    """Index container paths once, keeping the first path to an aliased node."""
    paths: dict[int, str] = {}
    pending = [(plan, "")]
    while pending:
        node, at = pending.pop()
        identity = id(node)
        if identity in paths:
            continue
        paths[identity] = at
        if isinstance(node, dict):
            for key, value in reversed(node.items()):
                if node is plan and isinstance(key, str) and key.startswith("x-"):
                    continue
                if isinstance(value, (dict, list)):
                    pending.append((value, f"{at}.{key}" if at else str(key)))
        else:
            for index in range(len(node) - 1, -1, -1):
                value = node[index]
                if isinstance(value, (dict, list)):
                    pending.append((value, f"{at}[{index}]"))
    return paths


def _plan_segs(ctx: Context, det: dict, rule: dict) -> list[_Seg] | Result:
    if ctx.plan is None:
        return Result(skipped="no plan given")
    path = det.get("path")
    if not path:
        return Result(skipped="the rule sets no plan path")
    from lapis_design.plan_check import resolve   # plan_check imports the lint registry
    parent, _, leaf = path.rpartition(".")
    if parent and _PLAN_FIELD.fullmatch(leaf):
        pairs = [(o.get(leaf), o) for o in resolve(ctx.plan, parent) if isinstance(o, dict)]
    else:
        pairs = [(v, None) for v in resolve(ctx.plan, path)]
    default_lang = (((ctx.plan.get("brief") or {}).get("locales")) or [None])[0]
    fallback = _fallback_locale(ctx)
    segs = []
    for i, (text, owner) in enumerate(pairs):
        if not isinstance(text, str) or not text.strip():
            continue
        owner = owner or {}
        slot = owner.get("slot")
        if owner and "_copy_plan_paths" not in ctx.cache:
            ctx.cache["_copy_plan_paths"] = _plan_paths(ctx.plan)
        where = ctx.cache["_copy_plan_paths"].get(id(owner)) if owner else None
        loc = {"path": f"{where}.{leaf}" if where else path}
        if ctx.plan_path:
            loc["file"] = ctx.plan_path
        script = _script(text)
        segs.append(_Seg(text=text, locale=_locale(script, owner.get("locale") or default_lang, fallback),
                         script=script, loc=loc, where=f"{slot} key copy" if slot else "plan copy", order=i, role=slot))
    if not segs:
        return Result(skipped=f"the plan has no copy at {path}")
    locales = rule.get("locales")
    scoped = [s for s in segs if _in_locales(s, locales)]
    if not scoped:
        return Result(skipped=f"no plan copy in the rule's locales ({', '.join(locales)})")
    return scoped


def _copy(ctx: Context, det: dict, rule: dict, layer: str) -> tuple[_Page | None, list[_Seg]] | Result:
    if layer == "plan":
        segs = _plan_segs(ctx, det, rule)
        return segs if isinstance(segs, Result) else (None, segs)
    return _render_segs(ctx, rule)


# ---------------------------------------------------------------- list terms

def _inflected(word: str) -> str:
    def esc(w: str) -> str:
        return re.escape(w).replace(r"\-", r"[-\s]?")
    if len(word) > 3 and word.endswith("e"):
        return esc(word[:-1]) + "(?:e|es|ed|ing|ement|ements|ely)"
    if len(word) > 3 and word.endswith("y") and word[-2] not in "aeiou":
        return esc(word[:-1]) + "(?:y|ies|ied|ying|ily)"
    return esc(word) + "(?:s|es|ed|ing|ment|ments|ly|ness)?"


@lru_cache(maxsize=4096)
def _term_regex(value: str, whole: bool = False) -> re.Pattern | None:
    v = _fold(value).strip()
    attach = v.startswith("~")
    v = v.lstrip("~").strip()
    if not v:
        return None
    left = right = ""
    if all(c < "\u0250" for c in v):
        words = v.split()
        if len(words) == 1 and not whole:
            core = _inflected(words[0])
        else:
            core = r"\s+".join(re.escape(w).replace(r"\-", r"[-\s]?") for w in words)
        left = r"(?<![\w-])" if v[0].isalnum() and not attach else ""
        right = r"(?![\w-])" if v[-1].isalnum() else ""
    elif _HANGUL.search(v):
        if not attach and " " not in v and len(v) >= 3 and v.endswith("적인"):
            core = re.escape(v[:-1])
        elif not attach and " " not in v and len(v) >= 3 and v.endswith("한"):
            core = re.escape(v[:-1]) + "(?:한|하게|하고|하며|하다|합니다|해요|했|함|성)"
        else:
            parts = v.split()
            head = parts[0]
            head = (_KO_PARTICLES[head[0]] + re.escape(head[1:])) if attach and head[0] in _KO_PARTICLES else re.escape(head)
            core = r"\s?".join([head] + [re.escape(p) for p in parts[1:]])
        left = "" if attach else r"(?<![\uac00-\ud7a3])"
    else:
        core = r"\s*".join(re.escape(p) for p in v.split())
    if whole and " " not in v:      # a one-word label matches only as the whole label
        return re.compile(rf"^[\W_]*{core}[\W_]*$")
    return re.compile(left + core + right)


def _expand(value: str, locale: str | None, whole: bool) -> list[tuple[str, re.Pattern]]:
    if value in _METAPHOR_LEXICON:
        return [(value, rx) for term in _METAPHOR_LEXICON[value].get(locale or "", ()) if (rx := _term_regex(term))]
    if value in _CONSTRUCTIONS:
        rx = _CONSTRUCTIONS[value].get(locale or "")
        return [(value, rx)] if rx else []
    if _NAME_VALUE.fullmatch(value) and locale in _CJK_LOCALES:
        return []                   # a construction or family name without patterns here
    rx = _term_regex(value, whole)
    return [(value, rx)] if rx else []


def _patterns(ctx: Context, key: str, seg: _Seg, whole: bool) -> list[tuple[str, re.Pattern]]:
    ck = ("copy.patterns", key, seg.locale, seg.script == "latn", whole)
    if ck not in ctx.cache:
        values: list[str] = []
        for k in (seg.locale, "all", "latin" if seg.script == "latn" else None):
            if k:
                values += ctx.list_values(key, k)
        ctx.cache[ck] = [p for v in dict.fromkeys(values) for p in _expand(v, seg.locale, whole)]
    return ctx.cache[ck]


def _ko_lemmas(ctx: Context, seg: _Seg, value: str) -> list[tuple[int, int]] | None:
    target = _morph(ctx, value, "ko")
    if not target:
        return None
    if value.endswith("다") and target[-1][0] == "다" and target[-1][2].startswith("E") and len(target) > 1:
        target = target[:-1]  # only dictionary-form -다 can be removed for lemma matching
    if target[-1][2] not in ("VV", "VA"):
        return None
    source = _morph(ctx, seg.text, "ko")
    if source is None:
        return None
    lemmas = tuple(t[1] for t in target)
    n = len(lemmas)
    spans = []
    for i in range(len(source) - n + 1):
        if tuple(t[1] for t in source[i:i + n]) != lemmas:
            continue
        spans.append((source[i][3], source[i + n - 1][4]))
    return spans


_PASSIVE_LEMMAS = tuple(lemma for lemma, _ in _PASSIVE_PAIRS)
# Kiwi sometimes reads a whole -어지다 form as one verb (잊혀지다); that verb is the same double passive.
_PASSIVE_LEXICALIZED = tuple(form + "지다" for _, form in _PASSIVE_PAIRS)
_PASSIVE_EXCLUDED_LEMMAS = frozenset(lemma for lemma, _ in _PASSIVE_EXCLUDED) | frozenset(
    form + "지다" for _, form in _PASSIVE_EXCLUDED)


def _passive_lemma(lemma: str, listed: tuple[str, ...]) -> bool:
    """A listed verb, or a compound ending in one (짓눌리다), but not an excluded longer verb."""
    return lemma not in _PASSIVE_EXCLUDED_LEMMAS and any(lemma.endswith(item) for item in listed)


def _double_passives(ctx: Context, seg: _Seg) -> list[_Match] | None:
    tokens = _morph(ctx, seg.text, "ko")
    if tokens is None:
        return None
    spans = []
    for i, stem in enumerate(tokens):
        if stem[2] == "VV" and _passive_lemma(stem[1], _PASSIVE_LEXICALIZED):
            spans.append((stem[3], stem[4]))
            continue
        if i + 2 >= len(tokens):
            continue
        ending, auxiliary = tokens[i + 1], tokens[i + 2]
        passive = (stem[2] == "XSV" and stem[0] == "되") or (
            stem[2] == "VV" and (stem[1] == "되다" or _passive_lemma(stem[1], _PASSIVE_LEMMAS)))
        if passive and ending[2] == "EC" and ending[0] == "어" and auxiliary[2] == "VX" and auxiliary[1] == "지다":
            spans.append((stem[3], auxiliary[4]))
    return [_Match(seg, "double-passive", seg.text[a:b].casefold()) for a, b in spans]


def _proper_name(ctx: Context, seg: _Seg, value: str, start: int, end: int) -> bool:
    tokens = _morph(ctx, seg.text, "ko")
    return tokens is not None and any(
        pos == "NNP" and surface == value
        and len(_fold(seg.text[:a])) == start and len(_fold(seg.text[:b])) == end
        for surface, _, pos, a, b in tokens)


def _find_terms(ctx: Context, segs: list[_Seg], key: str, *, whole: bool = False
                ) -> tuple[list[_Match], list[_Seg], set[str]]:
    """Every occurrence of the list's terms, the copy that could be judged, and the locales that could not."""
    matches, judged, unjudged = [], [], set()
    for seg in segs:
        pats = _patterns(ctx, key, seg, whole)
        if not pats:
            unjudged.add(seg.locale or "unknown")
            continue
        judged.append(seg)
        folded = _fold(seg.text)
        spans = set() if seg.locale == "ko" else None
        label_spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for label, rx in pats:
            if seg.locale == "ko" and label == "double-passive":
                found = _double_passives(ctx, seg)
                if found is not None:
                    matches.extend(found)
                    continue
            proper_name = False
            if key == "placeholder_entities" and seg.locale == "ko" and label and all(
                    "\uac00" <= char <= "\ud7a3" for char in label):
                target = _morph(ctx, label, "ko")
                proper_name = bool(target and len(target) == 1 and target[0][2] == "NNP"
                                   and target[0][3:5] == (0, len(label)))
            for m in rx.finditer(folded):
                if proper_name and not _proper_name(ctx, seg, label, m.start(), m.end()):
                    continue
                span = m.span()
                if spans is None or (span not in spans and not any(
                        span[0] < b and a < span[1] for a, b in label_spans[label])):
                    if spans is not None:
                        spans.add(span)
                        label_spans[label].append(span)
                    matches.append(_Match(seg, label, m.group(0).strip()))
            if seg.locale == "ko" and not whole and not label.startswith("~") and label not in _CONSTRUCTIONS:
                for start, end in _ko_lemmas(ctx, seg, label) or ():
                    folded_span = (len(_fold(seg.text[:start])), len(_fold(seg.text[:end])))
                    if folded_span not in spans and not any(
                            folded_span[0] < b and a < folded_span[1] for a, b in label_spans[label]):
                        spans.add(folded_span)
                        label_spans[label].append(folded_span)
                        matches.append(_Match(seg, label, seg.text[start:end].casefold()))
    return matches, judged, unjudged


def _named(label: str) -> bool:
    """Whether a list value names a family or construction rather than being the term itself."""
    return label in _METAPHOR_LEXICON or label in _CONSTRUCTIONS


def _labelled(key: str, label: str) -> str:
    return f"{key}: {label}" if _named(label) else key


def _once_hits(matches: list[_Match], what: str, evidence: str) -> list[Hit]:
    hits, seen = [], set()
    for m in matches:
        k = (id(m.seg), m.label, m.text)
        if k in seen:
            continue
        seen.add(k)
        hits.append(Hit(observed=f'"{m.text}" ({_labelled(what, m.label)}) in the {m.seg.where}: "{_clip(m.seg.text)}"',
                        location=dict(m.seg.loc), evidence=evidence))
    return hits


def _density_hit(ctx: Context, matches: list[_Match], judged: list[_Seg], per: str, what: str, loc: dict,
                 evidence: str) -> Hit | None:
    count = len(matches)
    if count < _DENSITY_MIN_COUNT:
        return None
    if per == "page":
        if count <= _DENSITY_PER_UNIT_MAX:
            return None
        amount = f"on the page ({count} per page)"
    else:
        unit = "characters" if per == "1000-chars" else "words"
        total = sum(_chars(s.text) if unit == "characters" else _words(ctx, s.text, s.locale) for s in judged)
        rate = count * 1000 / total if total else 0.0
        if rate <= _DENSITY_PER_UNIT_MAX:
            return None
        amount = f"in {total:.0f} {unit} ({rate:.1f} per 1,000 {unit})"
    tally = Counter(f'{m.label} "{m.text}"' if _named(m.label) else f'"{m.text}"' for m in matches)
    return Hit(observed=f"{count} {what} {amount}: " + ", ".join(f"{t} x{n}" for t, n in tally.most_common(6)),
               location=dict(loc), evidence=evidence, refs=list(dict.fromkeys(m.seg.loc["path"] for m in matches)))


def _unjudged(what: str, locales: set[str]) -> Result:
    return Result(skipped=f"{what} has no values or patterns for {', '.join(sorted(locales))}; that copy was not judged")


def _layer_loc(ctx: Context, page: _Page | None, det: dict) -> dict:
    if page is not None:
        return page.loc(ctx)
    loc = {"path": det.get("path")} if det.get("path") else {}
    if ctx.plan_path:
        loc["file"] = ctx.plan_path
    return loc


def _family_key(ctx: Context, det: dict, default: str | None = None) -> str | Result:
    key = det.get("family") or det.get("list") or default
    if not key:
        return Result(skipped="the rule names no family")
    if key not in (ctx.rules.get("lists") or {}):
        return Result(skipped=f"the rules lists have no {key!r} entry")
    return key


# ---------------------------------------------------------------- copy-family-rate

def _slot_segs(page: _Page, pool: list[_Seg], slots: list[str]) -> list[_Seg]:
    """headline = display or heading runs of the first section, subhead = the first body run after
    it, cta = link and button runs of the first section (detectors.yaml)."""
    segs = page.segs
    if page.sections:
        first = [s for s in segs if s.section == 0]
    else:                           # no sections: the first one runs up to the second heading
        heads = [s for s in segs if s.role in ("display", "heading")]
        end = heads[1].order if len(heads) > 1 else None
        first = [s for s in segs if end is None or s.order < end]
    headline = [s for s in first if s.role in ("display", "heading") and not s.control]
    picked: list[_Seg] = []
    if "headline" in slots:
        picked += headline
    if "subhead" in slots and headline:
        sub = next((s for s in first if s.order > headline[0].order and s.role == "body"), None)
        picked += [sub] if sub else []
    if "cta" in slots:
        picked += [s for s in first if s.control in ("link", "button")]
    in_pool = {s.order for s in pool}
    return sorted({s.order: s for s in picked if s.order in in_pool}.values(), key=lambda s: s.order)


def _label_key(text: str) -> str:
    return " ".join(re.sub(r"^[\W_]+|[\W_]+$", "", _fold(text)).split())


def _duplicate_labels(ctx: Context, page: _Page, segs: list[_Seg], roles: list[str]) -> list[Hit]:
    """One label on several controls outside navigation and the footer."""
    by_control: dict[str, list[_Seg]] = defaultdict(list)
    for s in segs:
        if s.control_box and s.control in roles and not s.in_nav and page.archetype(s.section) != "footer":
            by_control[s.control_box].append(s)
    by_label: dict[str, list[_Seg]] = defaultdict(list)
    for runs in by_control.values():
        label = _label_key(" ".join(r.text for r in runs))
        if label:
            by_label[label].append(runs[0])
    hits = []
    for firsts in by_label.values():
        if len(firsts) >= 2:
            hits.append(Hit(
                observed=f'{len(firsts)} controls share the label "{_clip(firsts[0].text, 40)}"',
                location={**page.loc(ctx), "box": firsts[0].control_box},
                refs=[f.control_box for f in firsts],
                consequence="the label does not say how the outcomes of these controls differ"))
    return hits


@detector("copy-family-rate", layers=("plan", "render"))
def copy_family_rate(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    key = _family_key(ctx, det)
    if isinstance(key, Result):
        return key
    got = _copy(ctx, det, rule, layer)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role != "code"]
    if page is not None:
        roles = params.get("roles")
        if roles:
            segs = [s for s in segs if s.control in roles or s.box_role in roles]
        if params.get("slots"):
            if not page.has_roles:
                return Result(skipped="text runs carry no type_role, so the headline, subhead, and cta slots cannot be found")
            segs = _slot_segs(page, segs, params["slots"])
    evidence = "plan" if page is None else "measurement"
    matches, judged, unjudged = _find_terms(ctx, segs, key, whole=key in _WHOLE_LABEL_FAMILIES)
    if ctx.plan and any(m.label in _METAPHOR_LEXICON for m in matches):
        world = _fold(" ".join([*(ctx.plan.get("world_materials") or []),       # imagery from the subject's
                                str((ctx.plan.get("brief") or {}).get("subject") or "")]))   # own world is literal
        matches = [m for m in matches if m.label not in _METAPHOR_LEXICON or m.text not in world]
    trigger = params.get("trigger", "once")
    hits: list[Hit] = []
    if trigger == "once":
        hits = _once_hits(matches, key, evidence)
    elif trigger == "density":
        hit = _density_hit(ctx, matches, judged, params.get("per", "1000-words"), f"{key} instances",
                           _layer_loc(ctx, page, det), evidence)
        hits = [hit] if hit else []
        repeats = params.get("through_metaphor_min_repeats")
        if repeats:
            for label, n in Counter(m.label for m in matches).items():
                if n >= repeats:
                    terms = list(dict.fromkeys(m.text for m in matches if m.label == label))
                    hits.append(Hit(observed=f"the {label} family recurs {n} times through the copy: " + ", ".join(terms),
                                    location=_layer_loc(ctx, page, det), evidence=evidence,
                                    refs=list(dict.fromkeys(m.seg.loc["path"] for m in matches if m.label == label))))
    elif trigger == "co-occurrence":
        groups: dict = defaultdict(list)
        for m in matches:
            groups[m.seg.section if page is not None else None].append(m)
        for ms in groups.values():
            labels = list(dict.fromkeys(m.label for m in ms))
            if len(labels) >= 2:
                hits.append(Hit(observed=f"{len(labels)} {key} values together: " + ", ".join(labels),
                                location=_layer_loc(ctx, page, det), evidence=evidence,
                                refs=list(dict.fromkeys(m.seg.loc["path"] for m in ms))))
    else:
        return Result(skipped=f"unknown trigger {trigger!r}")
    also = params.get("also") or []
    if page is not None and "duplicate-labels" in ([also] if isinstance(also, str) else also):
        got_all = _render_segs(ctx, rule)
        if not isinstance(got_all, Result):
            hits += _duplicate_labels(ctx, page, got_all[1], params.get("roles") or ["button", "link"])
    if hits:
        return Result(hits=hits)
    return _unjudged(f"list {key}", unjudged) if unjudged else Result()


# ---------------------------------------------------------------- rhetorical-shell

def _triads(seg: _Seg) -> list[str] | None:
    """Padded threes in one piece of copy, or None when its locale has no triad patterns."""
    loc = seg.locale
    if loc not in ("en", "ko", "ja", "zh"):
        return None
    spaced = loc not in ("ja", "zh")

    def short(text: str, n_spaced: int) -> bool:
        return 1 <= _tokens(text) <= n_spaced if spaced else 1 <= _chars(text) <= 8

    sents = _sentences(_fold(seg.text))
    if len(sents) == 3 and all(short(s, 3) for s in sents):
        return [" ".join(sents)]
    out = []
    for s in sents:
        t = _TRIAD_CONJ[loc].sub(", ", s) if loc in _TRIAD_CONJ else s
        parts = [p.strip(" .!?。！？") for p in _TRIAD_SPLIT.split(t)]
        if len(parts) == 3 and all(parts) and short(parts[1], 3):
            out.append(s)
    return out


@detector("rhetorical-shell", layers=("render",))
def rhetorical_shell(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    shell = params.get("shell")
    if shell not in ("not-x-but-y", "staging", "triad"):
        return Result(skipped=f"unknown shell {shell!r}")
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role not in _NOT_PROSE]
    if not segs:
        return Result(skipped="no prose copy (headings, body, captions, labels) in the render")
    if shell == "staging":
        key = _family_key(ctx, det, "staging_phrases")
        if isinstance(key, Result):
            return key
        matches, judged, unjudged = _find_terms(ctx, segs, key)
        what = f"list {key}"
    else:
        matches, judged, unjudged = [], [], set()
        for s in segs:
            if shell == "triad":
                found = _triads(s)
            else:
                pats = _CONTRAST.get(s.locale or "")
                found = [m.group(0) for rx in pats for m in rx.finditer(_fold(s.text))] if pats else None
            if found is None:
                unjudged.add(s.locale or "unknown")
                continue
            judged.append(s)
            matches += [_Match(s, shell, _clip(f, 60)) for f in found]
        what = f"{shell} patterns"
    trigger = params.get("trigger", "once")
    if trigger == "once":
        hits = _once_hits(matches, shell, "measurement")
    else:
        hit = _density_hit(ctx, matches, judged, params.get("per", "1000-words"), f"{shell} shells", page.loc(ctx),
                           "measurement")
        hits = [hit] if hit else []
    if hits:
        return Result(hits=hits)
    return _unjudged(what, unjudged) if unjudged else Result()


# ---------------------------------------------------------------- construction-rate

@detector("construction-rate", layers=("render",))
def construction_rate(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    key = _family_key(ctx, det)
    if isinstance(key, Result):
        return key
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role not in _NOT_PROSE]
    if not segs:
        return Result(skipped="no prose copy (headings, body, captions, labels) in the render")
    matches, judged, unjudged = _find_terms(ctx, segs, key)
    hits = []
    for locale in sorted({s.locale or "" for s in judged}):
        hit = _density_hit(ctx, [m for m in matches if m.seg.locale == locale], [s for s in judged if s.locale == locale],
                           params.get("per", "1000-words"), f"{key} constructions in {locale} copy", page.loc(ctx),
                           "measurement")
        if hit:
            hits.append(hit)
    if hits:
        return Result(hits=hits)
    return _unjudged(f"list {key}", unjudged) if unjudged else Result()


# ---------------------------------------------------------------- punctuation-density

@detector("punctuation-density", layers=("render",))
def punctuation_density(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    glyphs = params.get("glyphs") or []
    known = [g for g in glyphs if g in _GLYPHS]
    if not known:
        return Result(skipped=f"no known glyph among {glyphs}" if glyphs else "the rule names no glyphs")
    bound = float((det.get("threshold") or {}).get("ratio_to_baseline_max", 1.0))
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role not in _NOT_COPY]
    hits, unjudged = [], set()
    for glyph in known:
        base = _GLYPH_BASELINE[glyph]
        rx = re.compile(f"[{re.escape(_GLYPHS[glyph])}]+")
        groups: dict[str, list[_Seg]] = defaultdict(list)
        for s in segs:
            k = s.locale if s.locale in base else "latin" if s.script == "latn" and "latin" in base else None
            if k is None:
                unjudged.add(s.locale or "unknown")
            else:
                groups[k].append(s)
        for k, ss in sorted(groups.items()):
            count = sum(len(rx.findall(s.text)) for s in ss)
            chars = sum(_chars(s.text) for s in ss)
            if count < _DENSITY_MIN_COUNT or not chars:
                continue
            rate = count * 1000 / chars
            ratio = rate / base[k]
            if ratio > bound:
                hits.append(Hit(
                    observed=f"{count} {glyph} glyphs in {chars} characters of {k} copy ({rate:.2f} per 1,000), "
                             f"{ratio:.1f} times the {k} baseline of {base[k]}",
                    location=page.loc(ctx), refs=[s.loc["path"] for s in ss if rx.search(s.text)]))
    if hits:
        return Result(hits=hits)
    return _unjudged("the glyph baseline", unjudged) if unjudged else Result()


# ---------------------------------------------------------------- rhythm-variance

def _length(sentence: str, locale: str | None) -> int:
    return _chars(sentence) if locale in ("ja", "zh") else _tokens(sentence)


def _opening(sentence: str, locale: str | None) -> str | None:
    folded = _fold(sentence)
    if locale in ("ja", "zh"):
        return folded[:2] or None
    words = re.findall(r"[^\W_]+(?:'[^\W_]+)?", folded)
    if not words:
        return None
    return " ".join(words[:2]) if words[0] in ("the", "a", "an") and len(words) > 1 else words[0]


def _ending(sentence: str, locale: str | None) -> str | None:
    s = re.sub(r"[\W_]+$", "", _fold(sentence))
    if locale == "ja":
        return s[-4:] or None
    if locale == "zh":
        return s[-2:] or None
    words = s.split()
    if locale == "ko":
        return words[-1] if words else None
    return " ".join(words[-2:]) if len(words) >= 2 else None


# paired-headings: a heading built as two or three short sentences ("Your files. Safe, always.")
_PAIRED_BEATS = (2, 3)
_PAIRED_BEAT_WORDS = 7               # a beat longer than this is a sentence, not a slogan beat
_PAIRED_BEAT_CHARS = 14              # the same bound for unspaced scripts (ja, zh)
_PAIRED_HEADING_WORDS = 14
_PAIRED_HEADING_CHARS = 28
_PAIRED_HEADINGS_MIN = 3             # paired headings that make a page-wide cadence when the first is plain
_QUANT_OPEN = re.compile(r"^(?:a (?:little|bit|few)|just a (?:little|bit)|less|fewer)\b")
_QUANT_CLOSE = re.compile(r"^(?:a (?:lot|whole lot|world)|lots|plenty|more)\b")
_NEGATED_BEAT = re.compile(r"^(?:not|no|never|without)\b")


def _heading_groups(page: _Page, segs: list[_Seg]) -> list[list[_Seg]]:
    """Heading and display runs grouped by the heading box that holds them, in reading order."""
    groups: dict[str, list[_Seg]] = {}
    for s in segs:
        if s.control or s.in_nav:
            continue
        if not (s.role in ("display", "heading") if page.has_roles else s.box_role == "heading"):
            continue
        owner = next((b["id"] for b in _chain(page.boxes, s.box) if b.get("role") == "heading"), s.box)
        groups.setdefault(owner, []).append(s)
    return sorted(groups.values(), key=lambda g: g[0].order)


_BREAK_JOINED = re.compile(r"([.!?])(?=[A-Z\u00c0-\u00de\uac00-\ud7a3])")


def _paired(group: list[_Seg]) -> tuple[str, str] | None:
    """(heading text, shape) when the heading is two or three short sentences in one script."""
    # a <br> joins sentences without a space ("Life happens.Keep what matters.")
    text = _BREAK_JOINED.sub(r"\1 ", " ".join(s.text.strip() for s in group))
    locale = group[0].locale
    spaced = locale not in ("ja", "zh")
    beats = _sentences(text)
    if len(beats) not in _PAIRED_BEATS or len({_script(b) for b in beats}) != 1:
        return None
    lengths = [_length(b, locale) for b in beats]
    if not all(1 <= n <= (_PAIRED_BEAT_WORDS if spaced else _PAIRED_BEAT_CHARS) for n in lengths):
        return None
    if sum(lengths) > (_PAIRED_HEADING_WORDS if spaced else _PAIRED_HEADING_CHARS):
        return None
    folded = [_fold(b) for b in beats]
    if len(set(folded)) < len(folded):
        return None
    if len(beats) == 2 and _QUANT_OPEN.match(folded[0]) and _QUANT_CLOSE.match(folded[1]):
        shape = "a quantity pair"
    elif locale == "en" and any(_NEGATED_BEAT.match(f) for f in folded):
        shape = "a negation pair"
    else:
        shape = "short beats"
    return " ".join(text.split()), shape


def _paired_heading_hits(ctx: Context, page: _Page, segs: list[_Seg]) -> tuple[list[Hit], int]:
    """Hits for the first heading built as short sentences, or for a page-wide cadence of them, and the
    number of headings that could be judged."""
    groups = _heading_groups(page, segs)
    first = groups[:1]          # the title; the sections the render check derives start with the site header
    found = [(g, p) for g in groups if (p := _paired(g))]
    opens = bool(first) and any(g is first[0] for g, _ in found)
    if not found or not (opens or len(found) >= _PAIRED_HEADINGS_MIN):
        return [], len(groups)
    shapes = Counter(p[1] for _, p in found)
    examples = ", ".join(f'"{_clip(p[0], 48)}"' for _, p in found[:3])
    others = len(found) - opens
    if opens:
        subject = "the first heading" + (f" and {others} of the other {len(groups) - 1} headings" if others else "")
    else:
        subject = f"{len(found)} of {len(groups)} headings"
    return [Hit(observed=f"{subject} built as two or three short sentences "
                         f"({', '.join(f'{n} {s}' for s, n in shapes.most_common())}): {examples}",
                location=page.loc(ctx), refs=[g[0].loc["path"] for g, _ in found])], len(groups)


@detector("rhythm-variance", layers=("render",))
def rhythm_variance(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    checks = (det.get("params") or {}).get("checks") or ["sentence-length-variance", "repeated-openings",
                                                         "repeated-endings"]
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    hits: list[Hit] = []
    headings = 0
    if "paired-headings" in checks:
        hits, headings = _paired_heading_hits(ctx, page, segs)
    body = [s for s in segs if s.role == "body"] if page.has_roles else [s for s in segs if s.box_role == "text"]
    by_locale: dict[str, list[tuple[str, _Seg]]] = defaultdict(list)
    for s in body:
        by_locale[s.locale or "unknown"] += [(sent, s) for sent in _sentences(s.text)]
    judged = {loc: sents for loc, sents in by_locale.items() if len(sents) >= _RHYTHM_MIN_SENTENCES}
    if not judged:
        if headings:
            return Result(hits=hits)
        return Result(skipped=f"fewer than {_RHYTHM_MIN_SENTENCES} body sentences in any locale")
    for locale, sents in sorted(judged.items()):
        n = len(sents)
        refs = list(dict.fromkeys(s.loc["path"] for _, s in sents))
        unit = "characters" if locale in ("ja", "zh") else "words"
        if "sentence-length-variance" in checks:
            lengths = [_length(t, locale) for t, _ in sents]
            mean = statistics.fmean(lengths)
            cv = statistics.pstdev(lengths) / mean if mean else 0.0
            if cv < _RHYTHM_LENGTH_CV_MIN:
                hits.append(Hit(observed=f"{n} {locale} body sentences barely vary in length: coefficient of variation "
                                         f"{cv:.2f}, mean {mean:.1f} {unit}", location=page.loc(ctx), refs=refs))
        for check, fn, share in (("repeated-openings", _opening, _RHYTHM_OPENING_SHARE),
                                 ("repeated-endings", _ending, _RHYTHM_ENDING_SHARE)):
            if check not in checks:
                continue
            tally = Counter(x for x in (fn(t, locale) for t, _ in sents) if x)
            if not tally:
                continue
            top, count = tally.most_common(1)[0]
            if count >= _RHYTHM_MIN_REPEATS and count / n >= share:
                kind = "start" if check == "repeated-openings" else "end"
                hits.append(Hit(observed=f'{count} of {n} {locale} body sentences {kind} with "{top}"',
                                location=page.loc(ctx), refs=refs))
    return Result(hits=hits)


# ---------------------------------------------------------------- formatting-residue

def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF or (0x2600 <= o <= 0x27BF and o not in (0x2605, 0x2606)) or 0x2B05 <= o <= 0x2B55
            or o in (0x231A, 0x231B, 0x3030, 0x303D, 0x3297, 0x3299) or 0x23E9 <= o <= 0x23FA)


def _starts_with_emoji(text: str) -> bool:
    t = text.lstrip()
    return bool(t) and _is_emoji(t[0])


def _title_case(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    long = [w for w in words if len(w) >= 4]
    if len(words) < 6 or len(long) < 4:
        return False
    return sum(1 for w in long if w[0].isupper() and not w.isupper()) / len(long) >= 0.8


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[^\W\d_]+", _fold(text)) if len(w) >= 3 and w not in _STOPWORDS}


def _bigrams(text: str) -> set[str]:
    return {tok[i:i + 2] for tok in _CJK_TOKEN.findall(text) for i in range(len(tok) - 1)}


def _overlap(head: str, other: str, locale: str | None) -> float | None:
    """Share of the heading's words (CJK: bigrams) found in the other text; None when too short."""
    if locale in _CJK_LOCALES:
        h, o = _bigrams(head), _bigrams(other)
    else:
        h, o = _stems(head), _stems(other)
    return len(h & o) / len(h) if len(h) >= 2 else None


def _same_item(a: _Seg, b: _Seg) -> bool:
    return a.box == b.box or (a.parent is not None and a.parent == b.parent) or b.parent == a.box


@detector("formatting-residue", layers=("render",))
def formatting_residue(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    checks = (det.get("params") or {}).get("checks") or list(_FORMAT_CHECKS)
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role not in _NOT_COPY]
    here = page.loc(ctx)
    hits: list[Hit] = []
    if "bold-label-bullets" in checks:
        groups: dict = defaultdict(list)
        for i, s in enumerate(segs):
            label = s.text.strip()
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if ((s.weight or 0) >= 600 and len(label) <= 40 and label.endswith((":", "：")) and nxt is not None
                    and _same_item(s, nxt) and (nxt.weight or 400) < s.weight):
                groups[s.list_box or ("section", s.section)].append(s)
            if _MD_EMPHASIS.search(s.text):
                hits.append(Hit(observed=f'markdown emphasis markers show as text in the {s.where}: "{_clip(s.text)}"',
                                location=dict(s.loc)))
        for ss in groups.values():
            if len(ss) >= _BOLD_LABEL_MIN:
                hits.append(Hit(observed=f"{len(ss)} items open with a bold label and a colon: "
                                         + ", ".join(f'"{_clip(s.text, 30)}"' for s in ss[:5]),
                                location={**here, "box": ss[0].list_box or ss[0].box},
                                refs=[s.loc["path"] for s in ss]))
    if "heading-restates-sentence" in checks:
        found = []
        for i, h in enumerate(segs):
            if h.role not in ("heading", "display"):
                continue
            body = next((b for b in segs[i + 1:i + 4] if b.role == "body" and b.section == h.section), None)
            if body is None:
                continue
            share = _overlap(h.text, (_sentences(body.text) or [body.text])[0], h.locale)
            if share is not None and share >= _RESTATE_OVERLAP_MIN:
                found.append(h)
        if len(found) >= _RESTATING_HEADINGS_MIN:
            hits.append(Hit(observed=f"{len(found)} headings restate the sentence that follows them: "
                                     + ", ".join(f'"{_clip(h.text, 40)}"' for h in found[:5]),
                            location=here, refs=[h.loc["path"] for h in found]))
    if "emoji-markers" in checks:
        marked = [s for s in segs if _starts_with_emoji(s.text)]
        if len(marked) >= _EMOJI_MARKER_MIN:
            hits.append(Hit(observed=f"{len(marked)} runs open with an emoji marker: "
                                     + ", ".join(f'"{_clip(s.text, 30)}"' for s in marked[:5]),
                            location=here, refs=[s.loc["path"] for s in marked]))
    if "decorative-capitalization" in checks:
        for s in segs:
            if s.script != "latn" or s.role not in ("body", "caption"):
                continue
            if (s.transform == "capitalize" and _tokens(s.text) >= 4) or _title_case(s.text):
                hits.append(Hit(observed=f'the {s.where} capitalizes every word of running text: "{_clip(s.text)}"',
                                location=dict(s.loc)))
    if "flattened-label-value" in checks:
        for s in segs:
            pairs = _LABEL_VALUE.findall(s.text)
            if len(pairs) >= 2:
                hits.append(Hit(observed=f"{len(pairs)} label-value pairs run together in one {s.where}: "
                                         f'"{_clip(s.text)}"', location=dict(s.loc)))
    return Result(hits=hits)


# ---------------------------------------------------------------- separator-shape

def _separator_class(sep: str) -> str:
    sep = sep.strip()
    return {":": "colon", "：": "colon", "|": "pipe", "｜": "pipe", "·": "middle-dot"}.get(sep, "dash")


def _shape(seg: _Seg) -> str | None:
    m = _SEP_SHAPE.match(seg.text.strip())
    if not m:
        return None
    label, tail = m["label"].strip(), m["tail"]
    if not any(c.isalpha() for c in label) or label.casefold() in ("http", "https", "mailto", "tel"):
        return None
    if (len(label) > 12) if seg.locale in ("ja", "zh") else not 1 <= len(label.split()) <= 5:
        return None
    letters, digits = sum(c.isalpha() for c in tail), sum(c.isdigit() for c in tail)
    if letters < 2 or letters <= digits or re.match(r"[\d$€£¥₩+-]", tail):
        return None                 # a value field, not a qualifier
    return _separator_class(m["sep"])


@detector("separator-shape", layers=("render",))
def separator_shape(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Shapes only; the engine reports them as leads for semantic review."""
    bound = (det.get("threshold") or {}).get("repeats_max", 1)
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    shapes: dict[tuple[str, str], dict[str, _Seg]] = defaultdict(dict)
    for s in segs:
        if s.role in ("code", "data", "nav") or s.in_nav:
            continue
        sep = _shape(s)
        if sep:
            shapes[(sep, s.role or "text")].setdefault(s.box or s.loc["path"], s)
    hits = []
    for (sep, role), by_box in shapes.items():
        if len(by_box) > bound:
            runs = list(by_box.values())
            hits.append(Hit(observed=f"the label + {sep} + tail shape repeats in {len(runs)} {role} components: "
                                     + "; ".join(f'"{_clip(s.text, 50)}"' for s in runs[:4]),
                            location=page.loc(ctx), refs=[s.loc["path"] for s in runs]))
    return Result(hits=hits)


# ---------------------------------------------------------------- writing roles and register

_COMPACT_ROLES = ("headline", "label", "action")     # no sentence register unless the plan names one for the role
_STATUS_ARIA = ("alert", "status", "log")


def _writing_role(page: _Page, s: _Seg) -> str | None:
    """The writing role of a run: headline, label, action, status, or body. The extract cannot tell a deck,
    help text, or legal text from body copy, so those read as body. None for code and data."""
    if s.role in ("code", "data"):
        return None
    if not page.has_roles:
        return "body"
    if s.role in ("display", "heading"):
        return "headline"
    if s.role == "ui":
        return "action" if s.control == "button" else "label"
    if s.role in ("label", "nav") or s.in_nav:
        return "label"
    if any((b.get("a11y") or {}).get("role") in _STATUS_ARIA for b in _chain(page.boxes, s.box)):
        return "status"
    return "body"


def _voice_entry(ctx: Context, det: dict, locale: str) -> dict:
    """The plan's voice policy for one locale (params.policy is the path to content.voice.locales)."""
    path = (det.get("params") or {}).get("policy")
    if ctx.plan and path:
        from lapis_design.plan_check import resolve
        for value in resolve(ctx.plan, path):
            if isinstance(value, dict) and isinstance(value.get(locale), dict):
                return value[locale]
    return {}


def _register(sentence: str, locale: str | None) -> str | None:
    s = re.sub(r"[\W_]+$", "", unicodedata.normalize("NFKC", sentence))
    if not s or s[0] in _QUOTE_OPEN + "“‘":
        return None                 # quoted speech keeps its own register
    if locale == "ko" and _HANGUL.search(s):
        for name, rx in _KO_REGISTERS:
            if rx.search(s) and (name != "haera" or len(s.split()) >= 2):
                return name
    elif locale == "ja":
        for name, rx in _JA_REGISTERS:
            if rx.search(s):
                return name
    elif locale == "zh":
        if _ZH_FORMAL.search(s):
            return "zh-formal"
        if _ZH_CASUAL.search(s):
            return "zh-casual"
    return None


def _wanted(by_role: dict, prose: str | None, role: str, major: str | None, locale: str) -> tuple[set[str] | None, str]:
    """The registers a sentence of this role may end in, and the basis to quote; None when the role is not judged.
    A role the plan sets to `compact`, and a headline, label, or action it sets nothing for, takes no register.
    Body copy may also end in any register the plan names for the roles the extract reads as body."""
    own = by_role.get(role)
    if own == "compact":
        return None, ""
    if _REGISTER_LANG.get(own) == locale:
        return {own}, f"the plan sets {own} for {role} text"
    if role in _COMPACT_ROLES:
        return None, ""
    if prose:
        want = {prose}
        if role == "body":
            want |= {by_role[r] for r in ("deck", "help", "status", "legal") if _REGISTER_LANG.get(by_role.get(r)) == locale}
        return want, "the plan sets " + "/".join(sorted(want))
    if major:
        return {major}, f"most use {major} (the plan sets no {locale} register)"
    return None, ""


@detector("register-consistency", layers=("render",))
def register_consistency(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    classified: dict[str, list[tuple[str, str, _Seg, str]]] = defaultdict(list)
    unjudged = set()
    for s in segs:
        role = _writing_role(page, s)
        if role is None:
            continue
        if s.locale not in _CJK_LOCALES:
            unjudged.add(s.locale or "unknown")
            continue
        for sent in _sentences(s.text):
            reg = _register(sent, s.locale)
            if reg:
                classified[s.locale].append((reg, sent, s, role))
    if not classified:
        if unjudged:
            return _unjudged("register classification", unjudged)
        return Result(skipped="no ko, ja, or zh sentence ending to classify")
    hits = []
    for locale, rows in sorted(classified.items()):
        entry = _voice_entry(ctx, det, locale)
        by_role = entry.get("by_role") if isinstance(entry.get("by_role"), dict) else {}
        prose = entry.get("prose") if _REGISTER_LANG.get(entry.get("prose")) == locale else None
        tally = Counter(reg for reg, *_ in rows)
        major = tally.most_common(1)[0][0] if len(tally) >= 2 else None
        off: dict[tuple[str, str], list[tuple[str, _Seg]]] = defaultdict(list)
        judged = 0
        for reg, sent, s, role in rows:
            want, basis = _wanted(by_role, prose, role, major, locale)
            if want is None:
                continue
            judged += 1
            if reg not in want:
                off[(reg, basis)].append((sent, s))
        for (reg, basis), these in off.items():
            hits.append(Hit(observed=f"{len(these)} of {judged} {locale} sentences end in the {reg} register "
                                     f'while {basis}: "{_clip(these[0][0], 60)}"',
                            location={**page.loc(ctx), "box": these[0][1].box} if these[0][1].box else page.loc(ctx),
                            refs=list(dict.fromkeys(s.loc["path"] for _, s in these))))
    return Result(hits=hits)


# ---------------------------------------------------------------- role-voice

_VOICE_ROLES = ("headline", "body", "status", "label", "action")


@detector("role-voice", layers=("render",))
def role_voice(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Leads for review: the headlines of a page speak in the same sentence register as its body copy. The
    hit carries the ending counts by role; no count is a score, and a page with few headlines is not judged."""
    th = det.get("threshold") or {}
    headlines_min = th.get("headlines_min", 3)
    share_min = th.get("headline_share_min", 0.5)
    roles_min = th.get("roles_min", 2)
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    if not page.has_roles:
        return Result(skipped="text runs carry no type_role, so headlines cannot be told from body copy")
    runs: dict[str, dict[str, list[tuple[_Seg, str | None]]]] = defaultdict(lambda: defaultdict(list))
    for s in segs:
        role = _writing_role(page, s)
        if role not in _VOICE_ROLES or s.locale not in ("ko", "ja"):
            continue
        if not (_HANGUL.search(s.text) or _KANA.search(s.text)):
            continue
        regs = Counter(r for sent in _sentences(s.text) if (r := _register(sent, s.locale)))
        runs[s.locale][role].append((s, regs.most_common(1)[0][0] if regs else None))
    if not runs:
        return Result(skipped="no ko or ja text runs to read the sentence endings of")
    hits = []
    for locale, by_role in sorted(runs.items()):
        heads = by_role.get("headline", [])
        tally = Counter(reg for _, reg in heads if reg)
        if len(heads) < headlines_min or not tally:
            continue
        reg, count = tally.most_common(1)[0]
        if count / len(heads) < share_min:
            continue
        shared = {role: sum(1 for _, r in by_role.get(role, []) if r == reg) for role in _VOICE_ROLES}
        total = {role: len(by_role.get(role, [])) for role in _VOICE_ROLES}
        others = [role for role in _VOICE_ROLES[1:] if total[role] >= 2 and shared[role] / total[role] >= share_min]
        if 1 + len(others) < roles_min:
            continue
        histogram = ", ".join(f"{role} {shared[role]} of {total[role]}" for role in _VOICE_ROLES if total[role])
        first = next(s for s, r in heads if r == reg)
        hits.append(Hit(observed=f"{locale} headlines and {', '.join(others) or 'no other role'} mostly end in the {reg} "
                                 f"register, the same sentence shape in different jobs (runs ending in {reg}: {histogram}): "
                                 f'"{_clip(first.text, 60)}"',
                        location={**page.loc(ctx), "box": first.box} if first.box else page.loc(ctx),
                        refs=list(dict.fromkeys(s.loc["path"] for s, r in heads if r == reg))))
    return Result(hits=hits)


# ---------------------------------------------------------------- headline-budget

_NARROW_PX = 600                     # captures narrower than this are judged for lines, as compact-navigation does


def _title_groups(vp: dict) -> list[tuple[str, str, list[dict]]]:
    """Heading and display runs of one viewport as logical headings: the runs under one heading box are one title
    (a hero set as word spans), as paired-headings groups them. (key, role, runs)."""
    boxes = {b["id"]: b for b in vp.get("boxes") or [] if isinstance(b, dict) and b.get("id")}
    groups: dict[str, tuple[str, list[dict]]] = {}
    for t in vp.get("text") or []:
        if t.get("type_role") not in ("display", "heading") or not (t.get("text") or "").strip():
            continue
        key = next((b["id"] for b in _chain(boxes, t.get("box")) if b.get("role") == "heading"), t.get("box") or "")
        role, members = groups.setdefault(key, (t["type_role"], []))
        members.append(t)
        groups[key] = ("display" if "display" in (role, t["type_role"]) else role, members)
    return [(key, role, members) for key, (role, members) in groups.items()]


def _rendered_lines(vp: dict, members: list[dict]) -> int:
    """Lines of a logical heading: the rows its boxes occupy, at least the most lines any one run reports."""
    boxes = {b["id"]: b for b in vp.get("boxes") or [] if isinstance(b, dict) and b.get("id")}
    rects = sorted((boxes[t["box"]]["rect"] for t in members if (boxes.get(t.get("box")) or {}).get("rect")),
                   key=lambda q: (q["y"], q["x"]))
    rows, edge = 0, None
    for q in rects:
        if edge is None or q["y"] > edge:
            rows += 1
            edge = q["y"] + q["h"] / 2
        else:
            edge = max(edge, q["y"] + q["h"] / 2)
    return max(rows, *(t.get("lines") or 1 for t in members))


@detector("headline-budget", layers=("render",))
def headline_budget(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Leads for review: a heading longer than its language usually holds, or one that wraps past the lines its role
    keeps at a narrow capture. Lines are read on the logical heading, so a title set as word spans counts once; a
    single display run is left to the oversized-display rule."""
    th = det.get("threshold") or {}
    chars_max = th.get("chars_max") or {}
    words_max = th.get("words_max")
    lines_max = {"display": th.get("display_lines_max"), "heading": th.get("heading_lines_max")}
    ex = ctx.extract
    if not ex:
        return Result(skipped="no render extract given")
    vps = ex.get("viewports") or []
    if not any(t.get("text") for vp in vps for t in vp.get("text") or []):
        return Result(skipped="the render extract stores no copy to measure")
    fallback = _fallback_locale(ctx)
    hits, seen, judged = [], set(), 0
    for vi, vp in enumerate(vps):
        width = vp.get("width")
        for key, role, members in _title_groups(vp):
            text = " ".join(" ".join(t["text"].split()) for t in members)
            script = members[0].get("script")
            locale = _locale(script, members[0].get("lang"), fallback)
            loc = {"viewport": width, "box": key, **({"file": ctx.extract_path} if ctx.extract_path else {})}
            if text not in seen:
                seen.add(text)
                if script in chars_max:
                    judged += 1
                    if len(text) > chars_max[script]:
                        hits.append(Hit(observed=f'{role} heading "{_clip(text, 60)}" is {len(text)} characters, above the '
                                                 f"{chars_max[script]} a {locale} heading holds",
                                        location=loc, refs=[key]))
                elif script == "latn" and words_max:
                    judged += 1
                    if len(text.split()) > words_max:
                        hits.append(Hit(observed=f'{role} heading "{_clip(text, 60)}" is {len(text.split())} words, above the '
                                                 f"{words_max} a heading holds",
                                        location=loc, refs=[key]))
            limit = lines_max.get(role)
            if (width or 9999) <= _NARROW_PX and limit and not (len(members) == 1 and role == "display"):
                lines = _rendered_lines(vp, members)
                if lines > limit:
                    hits.append(Hit(observed=f'{role} heading "{_clip(text, 60)}" wraps to {lines} lines at {width} px, '
                                             f"above the {limit} its role keeps",
                                    location=loc, refs=[key]))
    if not hits and not judged:
        return Result(skipped="the render extract has no heading or display run in a script with a length budget")
    return Result(hits=hits)


# ---------------------------------------------------------------- speaker-anchor

_FIRST_PERSON = {
    "ko": re.compile(r"(?:^|(?<=[\s\"'(]))내\s(?=[\uac00-\ud7a3A-Za-z])"),
    "en": re.compile(r"\bmy\b", re.I),
    "ja": re.compile(r"[私僕俺]の"),
    "zh": re.compile(r"我的"),
}
_KO_PARTICLE_END = re.compile(r"[은는이가을를에도의]$")


def _first_person(text: str, locale: str | None) -> str | None:
    """The first first-person possessive in the text. Korean 내 is a possessive only after a particle or at the
    start: 3일 내 and 기간 내 mean within."""
    rx = _FIRST_PERSON.get(locale or "")
    if not rx:
        return None
    for m in rx.finditer(text):
        if locale == "ko":
            before = text[: m.start()].split()
            if before and not _KO_PARTICLE_END.search(before[-1]):
                continue
        after = text[m.end():].split()[:1]
        return (m.group(0).strip() + (" " if locale in ("ko", "en") else "") + (after[0][:12] if after else "")).strip()
    return None


@detector("speaker-anchor", layers=("render",))
def speaker_anchor(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Leads for review: running copy that says my, with no user voice declared. The speaker is unestablished when
    the possessive sits in a sentence about a product's behavior; whether it belongs to the visitor, the brand, or
    the writer's own session is for the reviewer."""
    got = _render_segs(ctx, rule)
    if isinstance(got, Result):
        return got
    page, segs = got
    hits = []
    for s in segs:
        if s.role in (*_NOT_PROSE, "label") or s.in_nav or _first_person(s.text, s.locale) is None:
            continue
        if (_chars(s.text) < 12) if s.locale in ("ja", "zh") else _tokens(s.text) < 4:
            continue                # a short title such as 내 예약 is the visitor's own area, not a sentence
        if _voice_entry(ctx, det, s.locale or "").get("speaker") == "user":
            continue
        hits.append(Hit(observed=f'{s.where} says "{_first_person(s.text, s.locale)}" and no speaker is set for '
                                 f'{s.locale} copy: "{_clip(s.text, 60)}"',
                        location={**page.loc(ctx), "box": s.box} if s.box else page.loc(ctx), refs=[s.loc["path"]]))
    return Result(hits=hits)


# ---------------------------------------------------------------- placeholder-genericness

def _plan_support(plan: dict | None) -> tuple[str, set[str]]:
    """Folded text and numbers of the claims and sources the plan records."""
    if not plan:
        return "", set()
    claims = plan.get("claims") or {}
    texts = [*(claims.get("known") or []), *(claims.get("declared") or []), str((plan.get("content") or {}).get("source") or "")]
    folded = _fold(" ".join(str(t) for t in texts))
    return folded, {n.replace(",", "") for n in re.findall(r"\d[\d,.]*", folded)}


# A run that opens with a quotation mark reads as a customer quote. Only two kinds of line are not one:
# interface text that quotes a product, a reservation, or a name inside a sentence of its own
# (‘9월 소성 예약’을 취소할까요?), and a button or input. A heading, display run, label, UI line, or dialog
# line that is only a quotation stays a lead, with or without a dash and a name after it, and so does
# every quotation in a testimonial section.
_INTERFACE_TYPE_ROLES = ("display", "heading", "label", "ui")
_INTERFACE_BOX_ROLES = ("heading", "button", "input")
_FIELD_ROLES = ("button", "input")
_QUOTE_CLOSE = {'"': '"', "'": "'", "«": "»", "「": "」", "『": "』"}


def _is_named(text: str) -> bool:
    """A title word (CEO, 대표) or a two-word capitalized name."""
    return bool(_TITLE_WORDS.search(_fold(text)) or re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", text))


def _interface_text(page: _Page | None, s: _Seg) -> bool:
    if s.role in _INTERFACE_TYPE_ROLES or s.box_role in _INTERFACE_BOX_ROLES or s.control:
        return True
    return page is not None and any(b.get("role") == "dialog" for b in _chain(page.boxes, s.box))


def _apostrophe(text: str, i: int) -> bool:
    """A single quote between two Latin letters (I've, Chef's) belongs to the word, not to the quotation."""
    return 0 < i < len(text) - 1 and all(c.isalpha() and ord(c) < 0x250 for c in (text[i - 1], text[i + 1]))


_ATTRIBUTION_VERBS = frozenset(("says", "said", "writes", "wrote"))
_CJK_LETTER = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3\uf900-\ufaff]")
# A Korean particle on its own after a blank ("‘9월 소성 예약’ 을 취소할까요?", "“빠른 배송” 이라는 평가") goes on with the sentence.
_PARTICLE = re.compile(r"(?:을|를|이|가|은|는|의|에|에서|에게|로|으로|와|과|도|만|이라고|라고|이라는|라는|이라며|라며|처럼|보다|부터|까지)(?![가-힣])")
# After a blank (or a blank and an opening bracket) a name is told by its shape: a title word or two capitalized
# words (`_is_named`), two to four Hangul syllables with 님, 고객님, or 씨, or in a bracket a name and a place
# ("(Mina, Seoul)", "(김민아, 서울)").
_NAME_SUFFIX = re.compile(r"[가-힣]{2,4}\s?(?:고객님|님|씨)(?![가-힣])")
_NAME_PLACE = re.compile(r"(?:[A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*)*|[가-힣]{2,4})\s*,\s*[A-Z가-힣]")
_BLANK_GAP = re.compile(r"\s+[(（\[［【]?\s*")
_BRACKET_CLOSE = re.compile(r"[)）\]］】]")


def _name_shaped(name: str, bracketed: bool) -> bool:
    if bracketed:
        name = _BRACKET_CLOSE.split(name, 1)[0]
    return bool(_is_named(name) or _NAME_SUFFIX.match(name) or (bracketed and _NAME_PLACE.match(name)))


def _after_quotation(text: str) -> str:
    """How a line that opens with a quotation mark goes on after the closing mark. `text` keeps its case
    and has straight quotation marks (`_straight`). `ends`: nothing, or only punctuation. `continues`: a
    sentence carries on, which is a Korean, Japanese, or Chinese letter right on the mark or a Korean particle
    after a blank, a lowercase Latin word that is not a speech verb (says, said, writes, wrote), or after a
    blank, or a blank and an opening bracket, anything that is not shaped like a name. `attributed`: a name
    follows, after a dash, a bracket, a middle dot, a bar, a slash, a comma, or a blank, in ten tokens or
    fewer; after a blank it must be name-shaped (`_name_shaped`)."""
    close = _QUOTE_CLOSE[text[0]]
    end = next((i for i in range(1, len(text))
                if text[i] == close and not (close == "'" and _apostrophe(text, i))), None)
    if end is None:
        return "ends"
    rest = text[end + 1:]
    if _CJK_LETTER.match(rest):
        return "continues"
    after = rest.lstrip()
    if after[:1].islower() and ord(after[0]) < 0x250 and re.match(r"[^\W\d_]+", after).group(0) not in _ATTRIBUTION_VERBS:
        return "continues"
    if rest[:1].isspace() and _PARTICLE.match(after):
        return "continues"
    name = next((rest[i:] for i, c in enumerate(rest) if c.isalnum()), "")
    if not name:
        return "ends"
    if not (name[0].isalpha() and _tokens(name) <= 10):
        return "continues"
    gap = _BLANK_GAP.fullmatch(rest[:len(rest) - len(name)])
    spoken = re.match(r"[^\W\d_]+\s+([^\W\d_])", name)         # says Mina, said Mina Kim
    if gap and spoken and name.split()[0] in _ATTRIBUTION_VERBS:
        return "attributed" if spoken[1].isupper() or _CJK_LETTER.match(spoken[1]) else "continues"
    if gap and not _name_shaped(name, bool(gap[0].strip())):
        return "continues"
    return "attributed"


def _reads_as_quote(page: _Page | None, s: _Seg, text: str) -> bool:
    """Whether a run that opens with a quotation mark reads as a customer quote. `text` is the run with
    straight quotation marks and its case."""
    if page is not None and page.archetype(s.section) == "testimonial":
        return True
    after = _after_quotation(text)
    if after == "continues" and _interface_text(page, s):
        return False
    return after == "attributed" or s.control not in _FIELD_ROLES


def _fabricated_proof(ctx: Context, page: _Page | None, segs: list[_Seg], kinds: list[str]) -> list[Hit]:
    support_text, support_numbers = _plan_support(ctx.plan)
    basis = "not traceable to a claim or source in the plan" if ctx.plan else "with no plan claims to trace it to"
    disclosed = {s.section for s in segs if _SAMPLE_DISCLOSURE.search(_fold(s.text))}   # plan copy: section None
    live = [s for s in segs if s.section not in disclosed]
    hits: list[Hit] = []

    def lead(text: str, seg: _Seg, refs: list[str] | None = None) -> None:
        hits.append(Hit(observed=f"{text}, {basis}", location=dict(seg.loc), evidence="not-verified",
                        refs=refs or []))

    quote_at: set[int] = set()          # orders of quotation runs
    for i, s in enumerate(live):
        folded = _fold(s.text).strip()
        if "metrics" in kinds:
            for rx in _PROOF_METRICS:
                for m in rx.finditer(folded):
                    number = re.search(r"\d[\d,.]*", m.group(0))
                    if number and number.group(0).replace(",", "").rstrip(".") in support_numbers:
                        continue
                    lead(f'proof metric "{m.group(0).strip()}" in the {s.where}: "{_clip(s.text)}"', s)
        after_quote = i > 0 and live[i - 1].order in quote_at and live[i - 1].section == s.section
        named = _is_named(s.text)
        dash = re.match(r"^[\u2014\u2013~-]\s*[^\W\d_]", s.text.strip())
        attribution = _tokens(s.text) <= 10 and folded[:1] not in _QUOTE_OPEN and (after_quote or (dash and named))
        if attribution:
            if "customer-names" in kinds and folded not in support_text:
                lead(f'customer attribution in the {s.where}: "{_clip(s.text)}"', s)
        elif len(folded) >= 12 and (
                (folded[0] in _QUOTE_OPEN and _reads_as_quote(page, s, _straight(s.text).strip()))
                or (page is not None and s.role == "body" and page.archetype(s.section) == "testimonial")):
            quote_at.add(s.order)
            if "quotes" in kinds and folded.strip(_QUOTE_OPEN + " ")[:24] not in support_text:
                lead(f'testimonial quotation in the {s.where}: "{_clip(s.text)}"', s)
        if "photo-credits" in kinds and _PHOTO_CREDIT.search(folded):
            lead(f'photo credit in the {s.where}: "{_clip(s.text)}"', s)
    if "customer-names" in kinds and page is not None:
        for i, s in enumerate(live):
            if s.role in ("heading", "display", "label") and _TRUSTED_BY.search(_fold(s.text)):
                names = [n for n in live[i + 1:] if n.section == s.section and _tokens(n.text) <= 3
                         and n.role not in ("heading", "display")]
                if len(names) >= 3:
                    lead(f'{len(names)} customer names under "{_clip(s.text, 40)}"', s,
                         refs=[n.loc["path"] for n in names])
    if "logos" in kinds and page is not None:
        hits += _logo_strips(ctx, page, disclosed, basis)
    return hits


def _logo_strips(ctx: Context, page: _Page, disclosed: set, basis: str) -> list[Hit]:
    media = [b for b in page.boxes.values() if b.get("role") == "media"]
    rows: list[list[dict]] = []
    if page.sections:
        for i, arche in enumerate(page.archetypes):
            if arche == "logo-strip" and i not in disclosed:
                rows.append([b for b in media if _section_of(page.boxes, _chain(page.boxes, b["id"]), page.sections) == i])
    else:
        by_parent: dict = defaultdict(list)
        for b in media:
            by_parent[b.get("parent")].append(b)
        for sib in by_parent.values():
            hs = [b["rect"]["h"] for b in sib if b["rect"]["h"] > 0]
            if len(sib) >= 4 and hs and max(hs) <= 120 and max(hs) <= 1.5 * min(hs):
                rows.append(sib)
    hits = []
    for row in rows:
        if not row:
            continue
        placeholders = sum(1 for b in row if (b.get("media") or {}).get("placeholder"))
        extra = f" ({placeholders} placeholder images)" if placeholders else ""
        hits.append(Hit(observed=f"a strip of {len(row)} logos presented as customers or partners{extra}, {basis}",
                        location={**page.loc(ctx), "box": row[0]["id"]}, evidence="not-verified",
                        refs=[b["id"] for b in row]))
    return hits


@detector("placeholder-genericness", layers=("plan", "render"))
def placeholder_genericness(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    check = params.get("check") or "names-and-companies"
    got = _copy(ctx, det, rule, layer)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role != "code"]
    if check == "fabricated-proof":
        kinds = params.get("kinds") or ["metrics", "customer-names", "quotes", "logos", "photo-credits"]
        return Result(hits=_fabricated_proof(ctx, page, segs, kinds))
    if check != "names-and-companies":
        return Result(skipped=f"unknown check {check!r}")
    key = _family_key(ctx, det, "placeholder_entities")
    if isinstance(key, Result):
        return key
    matches, _, unjudged = _find_terms(ctx, segs, key)
    hits = _once_hits(matches, key, "plan" if page is None else "measurement")
    if hits:
        return Result(hits=hits)
    return _unjudged(f"list {key}", unjudged) if unjudged else Result()


# ---------------------------------------------------------------- meta-text

def _table_matches(segs: list[_Seg], table: dict[str, list[re.Pattern]], unjudged: set[str], *,
                   whole_run: bool = False) -> list[tuple[_Seg, str]]:
    """The copy that the table's patterns for its locale (and `any`) match, with the matched text."""
    found = []
    for s in segs:
        pats = table["any"] + table.get(s.locale or "", [])
        if (s.locale or "") not in table:
            unjudged.add(s.locale or "unknown")
        text = _label_key(s.text) if whole_run else _fold(s.text)
        for rx in pats:
            m = rx.search(text)
            if m:
                found.append((s, m.group(0).strip() or _clip(s.text, 40)))
                break
    return found


def _table_hits(segs: list[_Seg], table: dict[str, list[re.Pattern]], what: str, evidence: str,
                unjudged: set[str], *, whole_run: bool = False) -> list[Hit]:
    return [Hit(observed=f'{what} "{matched}" in the {s.where}: "{_clip(s.text)}"', location=dict(s.loc), evidence=evidence)
            for s, matched in _table_matches(segs, table, unjudged, whole_run=whole_run)]


def _brief_asks_for_notice(plan: dict | None) -> bool | None:
    """Whether the brief says the page uses fictional or sample data; None when there is no plan to ask."""
    if plan is None:
        return None
    brief = plan.get("brief") or {}
    lines = [brief.get("subject"), brief.get("one_job"), brief.get("audience"), *(brief.get("constraints") or ())]
    text = _fold(" ".join(str(line) for line in lines if line))
    return any(rx.search(text) for patterns in _NOTICE.values() for rx in patterns)


def _in_footer(page: _Page, seg: _Seg) -> bool:
    return (page.archetype(seg.section) == "footer"
            or any((b.get("a11y") or {}).get("role") == "contentinfo" for b in _chain(page.boxes, seg.box)))


def _short(text: str) -> bool:
    return _chars(text) <= _NOTICE_CHARS if _UNSPACED.search(text) else _tokens(text) <= _NOTICE_WORDS


def _label_sized(text: str) -> bool:
    return _chars(text) <= 30 if _UNSPACED.search(text) else _tokens(text) <= 8


def _placement(page: _Page | None, seg: _Seg, label: str) -> str:
    """Where a notice sits: in a heading, in the opening, in the middle of the page, or in a quiet place - the
    footer, a short line at the foot of the page, or a short badge in the header band. A plan's key copy sits
    by its slot."""
    if page is None:
        return _PLAN_PLACE.get(seg.role or "other", "quiet")
    if seg.role in ("heading", "display") or seg.box_role == "heading":
        return "heading"
    if _in_footer(page, seg):
        return "quiet"
    archetype = page.archetype(seg.section)
    rect = (page.boxes.get(seg.box or "") or {}).get("rect")
    if rect is None:
        return "hero" if archetype == "hero" else "body"
    middle = rect["y"] + rect["h"] / 2
    if label == "demo badge" and archetype != "hero" and middle < _HEADER_BAND and _tokens(seg.text) <= 3:
        return "quiet"
    if (middle >= _QUIET_FOOT * page.doc_height and _short(seg.text)
            and (seg.section is None or seg.section == len(page.sections) - 1)):
        return "quiet"
    return "hero" if archetype == "hero" or middle < page.view_height else "body"


def _notice_hits(ctx: Context, page: _Page | None, segs: list[_Seg], kinds: list[str], evidence: str,
                 gaps: dict[str, set[str]]) -> tuple[list[Hit], set]:
    """Fictional-data and demo notices, and demo badges: a brief may ask for one, so exactly one is allowed, in a
    quiet place. A notice in a heading, in the opening, or in the middle of the page is meta text, and so is
    every notice after the quiet one. When the plan's brief does not ask for a notice, none is allowed."""
    usable = [s for s in segs if s.control not in ("button", "link")]       # an action label is not a disclosure
    found: list[tuple[_Seg, str, str]] = []
    if "fiction-notice" in kinds:
        found += [(s, "demo notice", m) for s, m in _table_matches(usable, _NOTICE, gaps["fiction-notice"])]
    if "demo-badges" in kinds:
        taken = {id(s) for s, _, _ in found}
        pool = [s for s in usable if id(s) not in taken]
        if page is not None:
            pool = _ambient_outside_records(page, pool)
        found += [(s, "demo badge", m) for s, m in _table_matches(pool, _DEMO_BADGES, gaps["demo-badges"], whole_run=True)]
    found.sort(key=lambda f: f[0].order)
    claimed = {s.loc.get("path") for s, _, _ in found}
    unit: list[int] = []                    # a notice and its translation beside it (same section, other locale) are one
    for i, (s, label, _) in enumerate(found):
        twin = next((j for j in range(i) if found[j][1] == label and found[j][0].locale != s.locale
                     and found[j][0].section == s.section and abs(found[j][0].order - s.order) <= 2), None)
        unit.append(i if twin is None else unit[twin])
    asked = _brief_asks_for_notice(ctx.plan)
    placed = [_placement(page, found[u][0], found[u][1]) for u in unit]
    quiet = sorted({u for u, place in zip(unit, placed) if place == "quiet"})
    allowed = None if asked is False or not quiet else min(quiet, key=lambda u: (
        page is None or not _in_footer(page, found[u][0]), _tokens(found[u][0].text), u))
    hits = []
    for i, ((s, label, _), u, place) in enumerate(zip(found, unit, placed)):
        if u == allowed:
            continue
        if place == "quiet" and asked is not False:
            why = "repeated: the page already has one in a quiet place"
        else:
            why = {"heading": "in a heading", "hero": f"in the {s.where}" if page is None else "in the opening",
                   "body": f"in the middle of the page ({s.where})", "quiet": "in a quiet place"}[place]
            if asked is False:
                why += ", and the brief does not ask for one"
        others = [o.loc["path"] for j, (o, _, _) in enumerate(found) if unit[j] != u][:4]
        hits.append(Hit(observed=f'{label} {why}: "{_clip(s.text)}"', location=dict(s.loc), evidence=evidence, refs=others))
    return hits, claimed


def _chat_leftovers(ctx: Context, segs: list[_Seg], key: str, evidence: str, unjudged: set[str]) -> list[Hit]:
    """List phrases anywhere; single-word values only where they open a sentence ("Certainly! ...")."""
    hits = []
    for s in segs:
        pats = _patterns(ctx, key, s, False)
        if not pats:
            unjudged.add(s.locale or "unknown")
            continue
        for sent in _sentences(_fold(s.text)):
            start = next((i for i, c in enumerate(sent) if c.isalnum()), 0)
            for label, rx in pats:
                m = rx.search(sent)
                if m and (" " in label.strip() or m.start() == start):
                    hits.append(Hit(observed=f'chat leftover "{m.group(0)}" in the {s.where}: "{_clip(s.text)}"',
                                    location=dict(s.loc), evidence=evidence))
                    break
    return hits


def _metadata_strips(segs: list[_Seg]) -> list[tuple[str, list[_Seg]]]:
    def short(t: str) -> bool:
        return _tokens(t) <= 4 if not _UNSPACED.search(t) else _chars(t) <= 12

    out = []
    usable = [s for s in segs if not s.in_nav and s.control != "link" and s.role not in ("code", "display")]
    for s in usable:
        items = [p for p in _STRIP_SPLIT.split(s.text.strip()) if p.strip()]
        if len(items) >= 3 and all(short(p) for p in items) and _tokens(s.text) <= 16:
            out.append((s.text, [s]))
    groups: list[list[_Seg]] = []       # separators styled as their own runs in one box
    for s in usable:
        if groups and s.box == groups[-1][-1].box and s.order == groups[-1][-1].order + 1:
            groups[-1].append(s)
        else:
            groups.append([s])
    for group in groups:
        items = [g for g in group if not set(g.text) <= _STRIP_GLYPHS]
        if len(group) - len(items) >= 2 and len(items) >= 3 and all(short(g.text) for g in items):
            out.append((" ".join(g.text.strip() for g in group), items))
    return out


_TOPIC_ECHO = "metadata items echo the page topic without a decision record"
_RECORD_METADATA = re.compile(
    r"\d|[×=%°]|(?:\b(?:by|source|route|direction|unit|artist|year|material|dimensions?|"
    r"cm|mm|kg|km|minutes?|hours?|seconds?)\b)|"
    r"출처|기자|작가|재료|크기|방향|노선|단위|기간|관람료|명|분|시간|"
    r"出典|作者|素材|寸法|方向|単位|期間|来源|记者|材料|尺寸", re.I)


def _topic_echo(page: _Page, text: str, runs: list[_Seg], headings: list[_Seg]) -> bool:
    """A lexical topic-echo candidate, not a semantic ban on all dot-separated facts."""
    if _RECORD_METADATA.search(text):
        return False
    if any((b.get("role") in ("data", "table", "chart", "media")
            or (b.get("a11y") or {}).get("role") in ("table", "grid", "row", "cell", "gridcell", "figure"))
           for run in runs for b in _chain(page.boxes, run.box)):
        return False
    items = [p.strip() for p in _STRIP_SPLIT.split(text) if p.strip()]
    topic = " ".join(h.text for h in headings)
    stems, bigrams = _stems(topic), _bigrams(topic)
    return any(_stems(item) & stems or _bigrams(item) & bigrams for item in items)

def _ambient_outside_records(page: _Page, segs: list[_Seg]) -> list[_Seg]:
    """A data row is semantic or is one of three same-shaped sibling rows."""
    if not segs:
        return segs
    counts: dict[str, int] = defaultdict(int)
    for seg in page.segs:
        for box in _chain(page.boxes, seg.box):
            counts[box["id"]] += 1
    parents = {box.get("parent") for box in page.boxes.values()}
    siblings: dict[tuple[str, int], list[str]] = defaultdict(list)
    for box in page.boxes.values():
        count = counts[box["id"]]
        if count and box["id"] in parents and box.get("parent") in page.boxes:
            siblings[(box["parent"], count)].append(box["id"])
    rows = {bid for group in siblings.values() if len(group) >= 3 for bid in group}
    data_roles = {"table", "grid", "row", "cell", "gridcell"}
    return [seg for seg in segs if not any(
        (box.get("a11y") or {}).get("role") in data_roles or box["id"] in rows
        for box in _chain(page.boxes, seg.box))]


@detector("meta-text", layers=("plan", "render"))
def meta_text(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    kinds = params.get("kinds") or list(_META_KINDS_PLAN if layer == "plan" else _META_KINDS_RENDER)
    usable = [k for k in kinds if k in (_META_KINDS_PLAN if layer == "plan" else _META_KINDS_RENDER)]
    if not usable:
        return Result(skipped=f"no kind among {kinds} can be judged at the {layer} layer")
    got = _copy(ctx, det, rule, layer)
    if isinstance(got, Result):
        return got
    page, segs = got
    segs = [s for s in segs if s.role != "code"]
    evidence = "plan" if page is None else "measurement"
    hits: list[Hit] = []
    gaps: dict[str, set[str]] = defaultdict(set)     # kind -> locales it could not judge
    taken: set = set()                                # copy that has a hit: one hit per run, by the first kind

    def add(new: list[Hit]) -> None:
        hits.extend(new)
        taken.update(h.location.get("path") for h in new)

    def fresh() -> list[_Seg]:
        return [s for s in segs if s.loc.get("path") not in taken]

    if any(k in usable for k in _NOTICE_KINDS):
        notice_hits, noticed = _notice_hits(ctx, page, segs, usable, evidence, gaps)
        add(notice_hits)
        taken |= noticed
    if "producer-facing" in usable:
        add(_table_hits(fresh(), _PRODUCER, "producer-facing text", evidence, gaps["producer-facing"]))
    if "build-labels" in usable:
        add(_table_hits([s for s in fresh() if _label_sized(s.text)], _BUILD_LABELS, "build or environment label",
                        evidence, gaps["build-labels"]))
    if "chat-leftovers" in usable:
        key = _family_key(ctx, det, "leftover_phrases")
        if isinstance(key, Result):
            return key
        add(_chat_leftovers(ctx, fresh(), key, evidence, gaps[f"chat-leftovers (list {key})"]))
    for kind, table, what in (("change-log", _CHANGE_LOG, "change-log narration"),
                              ("placeholder-apology", _APOLOGY, "placeholder apology"),
                              ("developer-notes", _DEV_NOTES, "developer or test note"),
                              ("self-description", _SELF_DESCRIPTION, "the page describing itself")):
        if kind in usable:
            add(_table_hits(fresh(), table, what, evidence, gaps[kind]))
    if page is not None and "repeated-heading-body" in usable:
        heads = [s for s in segs if s.role in ("heading", "display")]
        for s in segs:
            if s.role in ("heading", "display"):
                continue
            key_s = _label_key(s.text)
            twin = next((h for h in heads if h.section == s.section and _label_key(h.text) == key_s), None)
            if twin and len(key_s) >= 3:
                hits.append(Hit(observed=f'the {s.where} repeats the heading "{_clip(twin.text, 60)}"',
                                location=dict(s.loc), evidence=evidence, refs=[twin.loc["path"]]))
    if page is not None and "decorative-metadata-strip" in usable:
        headings = [s for s in page.segs if s.role in ("heading", "display")]
        for text, runs in _metadata_strips(segs):
            echo = _topic_echo(page, text, runs, headings)
            hits.append(Hit(observed=f'{"topic-echo " if echo else ""}metadata strip in the {runs[0].where}: "{_clip(text)}"',
                            location=dict(runs[0].loc), evidence=evidence, refs=[r.loc["path"] for r in runs],
                            conditions=frozenset({_TOPIC_ECHO}) if echo else frozenset()))
    if page is not None and "ambient-status" in usable:
        ambient = [s for s in segs if s.role not in ("body", "heading", "display") and _tokens(s.text) <= 12]
        ambient = _ambient_outside_records(page, ambient)
        hits += _table_hits(ambient, _AMBIENT, "ambient status", evidence, gaps["ambient-status"])
    if hits:
        return Result(hits=hits)
    gaps = {kind: locs for kind, locs in gaps.items() if locs}
    if gaps:
        return Result(skipped="; ".join(f"{kind} has no values or patterns for {', '.join(sorted(locs))}"
                                        for kind, locs in gaps.items()) + "; that copy was not judged")
    return Result()


# ---------------------------------------------------------------- review-layer tests

def _subject_anchors(plan: dict) -> tuple[set[str], set[str]]:
    source = " ".join([*(str(w) for w in plan.get("world_materials") or []),
                       str((plan.get("brief") or {}).get("subject") or "")])
    return _stems(source), _bigrams(source)


def _anchored(seg: _Seg, stems: set[str], bigrams: set[str], title: set[str]) -> bool:
    folded = _fold(seg.text)
    if _NUMBER_WORDS.search(folded) or _stems(seg.text) & stems or _bigrams(folded) & bigrams:
        return True
    if seg.script == "latn" and not _title_case(seg.text):
        for sent in _sentences(seg.text):
            for word in re.findall(r"[A-Za-z][\w'-]*", sent)[1:]:
                if word[0].isupper() and word != "I" and word.casefold() not in title:
                    return True     # a proper name other than the product's
    return False


@detector("name-swap-test", layers=("plan", "review"))
def name_swap_test(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Plan: key copy with no subject anchor. Review: the judgement itself, left to the reviewer."""
    if layer == "review":
        reason = ("needs a reviewer's judgement: swap the product name in the rendered key copy and check whether "
                  "it stays true for another product")
        page = _render_page(ctx) if ctx.extract else None
        if isinstance(page, _Page):
            head = next((s for s in page.segs if s.role in ("display", "heading")), None)
            if head:
                reason += f' (headline "{_clip(head.text, 60)}")'
        return Result(skipped=reason, cause="reviewer")
    segs = _plan_segs(ctx, det, rule)
    if isinstance(segs, Result):
        return segs
    keyed = [s for s in segs if s.role in (None, "headline", "subhead", "other")]
    if not keyed:
        return Result(skipped=f"the plan has no headline, subhead, or other key copy at {det.get('path')}")
    stems, bigrams = _subject_anchors(ctx.plan)
    title = set(_fold(str((ctx.plan.get("task") or {}).get("title") or "")).split())
    return Result(hits=[
        Hit(observed=f'the {s.where} "{_clip(s.text)}" names no world material, subject term, number, date, or '
                     "proper name, so nothing in it depends on this product",
            location=dict(s.loc), evidence="plan")
        for s in keyed if not _anchored(s, stems, bigrams, title)])


# ---------------------------------------------------------------- plan-anchored-text

# Function words the lever check leaves out, on top of _STOPWORDS: they carry no subject.
_FUNCTION_WORDS = frozenset(
    "the and for nor but yet not are was were been being has had does did can may might must shall should would "
    "could its our out off per via onto upon than then these those whom whose who how why you any all both own "
    "one two".split())
_LETTER_WORD = re.compile(r"[^\W\d_]+")


def _anchor_words(text: str) -> tuple[set[str], set[str]]:
    """The comparable words of a plan string: the first five letters of each word of three or more letters
    outside the function words, and the runs of two characters of Hangul, kana, and Han text."""
    folded = _fold(text)
    stems = {w[:5] for w in _LETTER_WORD.findall(_CJK_TOKEN.sub(" ", folded))
             if len(w) >= 3 and w not in _STOPWORDS and w not in _FUNCTION_WORDS}
    return stems, _bigrams(folded)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [s for item in value for s in _strings(item)] if isinstance(value, list) else []


@detector("plan-anchored-text", layers=("plan",))
def plan_anchored_text(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Strings at the rule's path that share no word with any anchor path (layout.unanchored-lever: a form
    lever that names no world material or signature word). Runs only in the plan modes the rule lists and
    skips the listed style frames. When the path resolves to no string, `empty: hit-unless-operate-only`
    hits unless the surface mode is operate alone: a working surface may go without levers."""
    if ctx.plan is None:
        return Result(skipped="no plan given")
    path = det.get("path")
    if not path:
        return Result(skipped="the rule sets no plan path")
    from lapis_design.plan_check import resolve   # plan_check imports the lint registry
    params = det.get("params") or {}
    plan = ctx.plan
    if params.get("modes") and plan.get("mode") not in params["modes"]:
        return Result()
    skip = params.get("skip_style_frames") or ()
    if any(frame in skip for frame in resolve(plan, "direction.read.style_frame")):
        return Result()
    base = path[:-3] if path.endswith("[*]") and "[" not in path[:-3] else None
    if base is None:
        found = [(path, value) for value in resolve(plan, path)]
    else:
        found = [(f"{base}[{i}]", value) for node in resolve(plan, base) if isinstance(node, list)
                 for i, value in enumerate(node)]
    found = [(at, text) for at, text in found if isinstance(text, str) and text.strip()]
    here = {"file": ctx.plan_path} if ctx.plan_path else {}
    if not found:
        if params.get("empty") != "hit-unless-operate-only":
            return Result()
        modes = {m for value in resolve(plan, "direction.read.surface_mode") if isinstance(value, list)
                 for m in value}
        if modes == {"operate"}:
            return Result()
        return Result(hits=[Hit(observed=f"the plan writes nothing at {base or path}, and its surface is not "
                                         "operate alone", location={**here, "path": base or path},
                                evidence="plan")])
    anchors = params.get("anchors") or ()
    stems: set[str] = set()
    grams: set[str] = set()
    for anchor in anchors:
        for value in resolve(plan, anchor):
            for text in _strings(value):
                s, g = _anchor_words(text)
                stems |= s
                grams |= g
    hits = []
    for at, text in found:
        s, g = _anchor_words(text)
        if not (s & stems or g & grams):
            hits.append(Hit(observed=f'"{_clip(text, 60)}" shares no word with {" or ".join(anchors)}, so it '
                                     "would fit any subject",
                            location={**here, "path": at}, evidence="plan"))
    return Result(hits=hits)


@detector("counterfactual-test", layers=("review",))
def counterfactual_test(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    subject = ((ctx.plan or {}).get("brief") or {}).get("subject")
    target = f'a subject other than "{subject}"' if subject else "a different subject"
    return Result(skipped=f"needs a reviewer's judgement: name which decisions behind {rule.get('id', 'this rule')} "
                          f"would change for {target}", cause="reviewer")
