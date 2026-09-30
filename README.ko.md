# LapisLazuli

AI 코딩 에이전트를 위한 디자인 스킬과, 그 스킬이 기대는 명령줄 도구 두 개예요.

LapisLazuli는 에이전트가 코드를 쓰기 전에 인터페이스를 계획하고, 만든 결과를 실제 브라우저에서 확인하고, 폰트·색·레퍼런스에 대해 정직하게 말하도록 도와요. 한 원천에서 빌드한 플러그인 세 개와, 스킬·훅·MCP 서버가 부르는 CLI 두 개(`lapis-design`, `lazuli`)로 이루어져 있어요.

[English README](README.md)

## 작동 방식

1. **계획.** `lapis`가 요청을 계획 파일 `.lapis/plans/<task>.yaml`로 바꿔요. 브리프, 세계 재료, 글꼴·색 역할, 레이아웃, 핵심 문구, 이름 붙은 기본값마다 유지·거절 판단이 들어가요. `lapis-design plan check`가 코드를 쓰기 전에 계획을 검사해요.
2. **구현.** 에이전트가 계획대로 구현해요. `lps-ux`, `lps-copy`, `lps-system`이 흐름, 문구, 디자인 시스템을 맡아요.
3. **검사.** `ultramarine`이 우리 렌더에 `lapis-design`을 돌려요. 아홉 가지 조건(너비 320~1440px, 라이트·다크, 모션 줄이기, 모바일 브라우저 UI)으로 캡처하고, 스텁 백엔드에서 작업 흐름을 끝까지 돌려 보고, 뻔해 보이거나 기만적인 패턴과 빠진 권리 기록을 린트하고, 측정으로 판단할 수 없는 것은 별도의 평가자에게 넘겨요. 마지막 관문은 `ulm-release`예요.
4. **조회.** `lazuli`가 요청할 때 사실을 가져다줘요. 이 컴퓨터의 폰트, 카탈로그의 분류와 라이선스, 색 체계 코드, 페이지 하나, 레퍼런스 프로필이에요.

## 플러그인과 스킬

| 플러그인 | 스킬 | 하는 일 |
|---|---|---|
| `lapis` | `lapis` | 새 인터페이스, 리디자인, 시각 방향을 코드 전에 계획하고, CLI가 검사하는 계획 파일로 남겨요. |
| | `lps-ux` | 흐름, 상태, 내비게이션이 동작하고 복구되도록 설계하고, 그것을 검사할 스텁을 써요. |
| | `lps-copy` | 대상 언어로, 화면마다 하나의 어조로, 대상의 사실에 바탕해 인터페이스 문구를 써요. |
| | `lps-system` | 계획의 결정을 디자인 시스템으로 바꿔요. OKLCH 색 단계, 글자 크기 체계, 간격, 모션, 테마, `DESIGN.md`예요. |
| `ultramarine` | `ultramarine` | 이미 있는 인터페이스를 검사해요. 렌더 캡처, 동작 탐침, 슬롭 린트, 별도의 평가자예요. |
| | `ulm-maintain` | 기존 프런트엔드를 유지보수해요. 리팩터링, 업그레이드, 성능, 디자인 부채를 캡처한 기준선에서 작은 단계로 검사하며 처리해요. |
| | `ulm-release` | 릴리스 관문을 돌리고, 결과물을 내보내도 되는지 알려 주는 보고서를 써요. |
| `lazuli` | `lazuli` | `lazuli` CLI를 실행하고 계획 필드를 조회 명령에 이어 줘요. |
| | `lzl-fonts` | 폰트 사실을 근거와 함께 알려 줘요. 인벤토리, 카탈로그 분류, 순위 후보, 라이선스, 문자 체계 커버리지를 다루고 폰트 잠금을 써요. |
| | `lzl-color` | 색 체계 코드를 확인하고 사용자가 밝힌 값을 기록해 둬요. |
| | `lzl-research` | 어디를 볼지 찾고, 요청한 것만 읽어요. 출처 등록부, 페이지 하나, 레퍼런스 프로필, 노트예요. |

모든 스킬은 훅·에이전트·MCP 없이도 동작해요. 그런 것이 도움이 될 자리에서는 스킬이 직접 돌릴 명령을 알려 줘요.

## 명령줄 도구

- `lapis-design`: `plan check`, `rights check`, `render check`, `behavior check`, `stub serve`, `slop lint`, `release check`, 그리고 하네스가 부르는 `hook`·`mcp` 진입점이에요.
- `lazuli`: `local fonts`, `catalog`, `search`, `lock`, `class`, `sources`, `color`, `read`, `ref`, `doctor`, `setup`이에요. 상태는 사용자 캐시에 두고, `lazuli doctor`가 설치를 점검해요.

명령과 옵션은 `--help`로 볼 수 있어요.

## 지원하는 하네스

| 하네스 | 상태 | 비고 |
|---|---|---|
| [Claude Code](INSTALLATION.md#claude-code) | 확인함 (2.1.274, 2026-09-27) | 플러그인, 세션 시작 훅, 계획 모드 훅, MCP 서버, 평가자 서브에이전트예요. |
| [OpenAI Codex CLI](INSTALLATION.md#openai-codex-cli) | 확인함 (0.157.x, 2026-09-27) | 플러그인, 세션 시작 훅(`/hooks`에서 직접 신뢰해야 해요), MCP 서버, 설치 스크립트가 복사하는 에이전트 파일로 된 평가자예요. |
| [Oh-My-Pi](INSTALLATION.md#oh-my-pi) | 확인함 (18.3.1, 2026-09-27) | 마켓플레이스로 설치하는 플러그인, 세션 시작 확장, MCP 서버, 작업 에이전트로 불러오는 평가자예요. |
| [그 밖의 Agent Skills 하네스](INSTALLATION.md#other-agent-skills-harnesses) (Cursor, Gemini CLI, GitHub Copilot, opencode, Windsurf, Kiro CLI) | `skills` CLI로 확인함 (1.7.0, 2026-09-27) | 스킬만 들어가고, 세션 요약과 MCP 설정은 `AGENTS.md` 조각으로 안내해요. 에이전트마다 따로 시험하지는 않았어요. |
| [pi](INSTALLATION.md#pi-experimental) | 실험적 | 스킬과 세션 시작 확장이에요. 실제 설치에서는 아직 확인하지 않았어요. |
| [Hermes Agent](INSTALLATION.md#hermes-agent-experimental) | 실험적 | 스킬, Hermes 플러그인, MCP예요. 실제 설치에서는 아직 확인하지 않았어요. |

상태는 `install/harnesses.yaml`에서 가져왔고, 하네스별 정확한 명령은 [INSTALLATION.md](INSTALLATION.md)에 있어요.

## 빠른 시작

1. [INSTALLATION.md](INSTALLATION.md)를 따라 해요. 설치 스크립트는 `--dry-run`을 받아서 실행할 명령을 모두 보여 주고 아무것도 바꾸지 않으니, 먼저 미리 보세요. 스크립트는 `uv`나 `pipx`로 CLI를 설치하고, 찾은 하네스마다 플러그인을 등록해요.
2. CLI를 확인해요: `lapis-design --version`, `lazuli doctor`.
3. 선택 사항, 렌더·동작 검사용: INSTALLATION.md의 안내대로 Chromium을 설치해요.
4. 하네스에서 `lapis` 스킬로 디자인 작업을 시작해요(Claude Code는 `/lapis:lapis`, Codex는 `$lapis:lapis`, Oh-My-Pi는 `/skill:lapis`). 계획을 쓰고, 계획을 바꿀 질문만 물어봐요.

## 요구 사항

- Python 3.12 이상.
- CLI를 설치할 `uv` 또는 `pipx`.
- `render check`, `behavior check`, `lazuli read --render`, `lazuli ref capture`에는 Playwright의 `chromium-headless-shell`로 설치하는 Chromium이 필요해요. 나머지는 없어도 동작해요.
- `lazuli` 데이터베이스용 SQLite 3.34 이상(FTS5 trigram 지원).
- 선택 사항: `cjk` 추가 패키지(한국어·일본어·중국어 형태소 분석기, 약 340 MB). 체크아웃에서 `uv sync --extra cjk`로 설치해요.

## 하지 않는 일

- **살아 있는 사이트 긁어 가기.** `lazuli read`는 요청한 페이지 하나만 출처 등록부 정책과 사이트의 `robots.txt` 안에서 읽어요. 카탈로그 조회는 사람 수준 속도와 명시된 크롤 지연을 지키고, 요청 헤더에 lazuli를 밝히고, 차단이나 로그인을 우회하지 않아요. 약관이 자동 수집을 금지하는 곳(Adobe Fonts, 눈누)에는 아무 요청도 보내지 않고 링크만 줘요.
- **Adobe Fonts 파일 열기.** Adobe Fonts 구독이 켜 둔 폰트는 macOS에서 운영체제 폰트 API(Core Text)로 목록을 읽고, 시스템이 그린 글리프로 재서 파생 수치만 남겨요. 파일은 열지 않아요. Windows에는 그런 목록이 없어서 Adobe Fonts가 인벤토리에 없어요.
- **남의 페이지 구동하기.** 렌더·동작 검사는 우리 페이지만 캡처해요. `localhost`, 루프백·사설 주소, 사설 주소로만 풀리는 `.test` 이름이에요. 공개 주소는 `--public`이 있어야 하고, 출처 등록부의 호스트나 계획이 레퍼런스로 적은 호스트는 절대 안 돼요. 나머지 호스트는 모두 막아요.
- **실제 계정 건드리기.** 동작 검사는 스텁이나 격리된 로컬 백엔드와 합성 데이터만 쓰고, 실제 계정·자격 증명·결제 수단은 쓰지 않아요. 입력값, 질의 문자열, 헤더, 요청 본문도 저장하지 않아요.
- **레퍼런스를 권리 이상으로 보관하기.** 레퍼런스 캡처는 사용자가 준 URL만 열고, 로그인하거나 양식을 제출하지 않고, 출처의 권리가 허락하는 것만 남겨요. 레퍼런스 전용 캡처는 문구, 대체 텍스트, 접근 이름, 스크린숏 없이 키 서명과 지각 해시만 남겨요.
- **폰트를 가져가거나 폰트 사이트에서 대신 행동하기.** 폰트 파일은 읽기만 하고 프로젝트로 복사하거나 변환하지 않아요. 배포용으로 사용자가 직접 준 파일만 들어가요. lazuli는 사용자를 대신해 로그인, 내려받기, 활성화, 구매, 약관 동의를 하지 않아요. 폰트 데이터베이스는 사용자 캐시에만 있어요.
- **법률 자문.** 권리 검사는 사용자가 적어 둔 기록을 서로 대조할 뿐, 법적 결론을 말하지 않아요. 원장과 잠금에는 자격 증명, 라이선스 키, 결제 정보, 개인 영수증이 들어가지 않아요.
- **대신 승인하기.** 계획 모드 훅은 막아야 하는 판정이 있는 계획을 거부할 뿐이고, 승인은 사용자에게 남아 있어요.

## 상태

버전 0.1.0, 초기 단계예요. 계약은 `version: 0` 초안이라 릴리스 사이에 바뀔 수 있어요. `lazuli setup`은 선택 사항인 폰트 스타일 임베딩 모델을 설치하는 명령인데 공개된 모델이 아직 없어서 지금은 종료 코드 1로 끝나요. CI는 Linux에서 계약 테스트, Chromium 테스트, 선택 사항인 CJK 테스트를 돌려요.

## 저장소에서 작업하기

`src/`를 고치세요. `plugins/`, `dist/`, 카탈로그, 설치 스크립트는 `uv run python tools/build/build.py`가 만들고, 어긋나면 CI가 실패해요. 저장소 규칙과 명령은 [AGENTS.md](AGENTS.md)에 있어요. 계약과 도구 참고 자료는 아래에 한국어로 있어요.

`src/skills/`와 `src/shared/`의 지식은 대부분 작성자의 이전 저장소인 `design-and-frontend`에서 옮겨 온 것이고, 그 저장소는 이 저장소에 들어 있지 않아요. `src/shared/slop/rules.yaml`에서 `memo:`로 시작하는 출처는 공개하지 않은 작성자의 메모예요. 이 저장소가 남겨 둔 제3자 자료는 [NOTICE](NOTICE)에 있어요.

## 라이선스

Markdown 파일은 CC BY 4.0, 그 밖의 모든 파일은 MIT 라이선스예요. 단 NOTICE에 적은 제3자 자료는 예외예요.

SPDX 표현은 `MIT AND CC-BY-4.0`이에요. [LICENSE](LICENSE)에는 MIT 전문이, [LICENSE-docs](LICENSE-docs)에는 CC BY 4.0 법률 문서(legal code)가 들어 있어요. 플러그인 폴더, 스킬 폴더, Hermes 플러그인 폴더에 두 파일이 모두 들어 있어서 폴더 하나만 설치해도 함께 가요. 제3자 자료 중 어느 것이 소유자의 조건을 따르는지는 [NOTICE](NOTICE)에 있어요.

Markdown 파일을 다시 쓸 때는 출처를 밝히고, 라이선스 링크를 달고, 고쳤다면 고쳤다고 적어 주세요. 예를 들면 이래요.

> `<file>` from LapisLazuli by lapis-labs, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/),
> https://github.com/lapis-labs/lapis-lazuli

---

## 유지보수 자료

아래는 저장소를 고치는 사람을 위한 자료예요.

스킬은 열한 개예요: `lapis`, `lps-copy`, `lps-ux`, `lps-system`, `ultramarine`, `ulm-maintain`, `ulm-release`, `lazuli`, `lzl-fonts`, `lzl-color`, `lzl-research`(`src/skills/<이름>/SKILL.md`). 평가자는 `src/agents/critic.md`이고, 빌드가 두 에이전트 파일(`plugins/ultramarine/agents/critic.md`, `dist/codex/agents/ulm-critic.toml`)로 만들어요.

### 계약 (`src/shared/`)

| 파일 | 내용 |
| --- | --- |
| `plan/schema.yaml`, `plan/example.plan.yaml` | 계획 파일 스키마와 예시 (`.lapis/plans/<task-id>.yaml`). `flows`로 동작 층이 끝까지 돌려 볼 작업 흐름을 적고, 나가는 흐름은 `pair`로 들어오는 흐름과 짝지어요 |
| `plan/HARNESS-PLAN-MODES.md` | 하네스 계획 모드와의 관계 지침 (영어, `lapis` 참조용) |
| `behavior/session.schema.yaml`, `behavior/DERIVED.md`, `behavior/example.session.json` | 동작 세션 기록 형식 v0, 관찰·파생 값 정의, 예시 세션. 루프백·사설 주소의 우리 렌더만 구동하고(다른 호스트 요청은 차단, 스텁 백엔드 또는 격리된 로컬 백엔드, 합성 데이터), 입력값·질의 문자열·요청 본문은 남기지 않아요. 경로의 ID 같은 조각은 `:id`로 바꿔요. 예시에는 탐지기가 잡을 문제 두 가지(타이머 팝업의 거절 링크, 거절 뒤 재등장)를 일부러 넣었어요 |
| `behavior/stub.schema.yaml`, `behavior/example.stub.yaml` | 스텁 백엔드 픽스처 형식 v0(2026-09-26 추가). 경로, 상태 있는 컬렉션과 효과 수, 상태 탐침용 변형(`empty`·`partial`), 합성 입력값, 합성 계정, 긴급성 근거(마감·재고·수요·활동), 외부 서비스 대체 응답을 적어요. 예시는 도자기 공방 계획에 맞췄어요 |
| `render/extract.schema.yaml`, `render/DERIVED.md`, `render/example.extract.json` | 렌더 추출·레퍼런스 프로필 공통 형식 v1, 측정·파생 값 정의, 예시 추출. 레퍼런스 전용 캡처는 문구·대체 텍스트·접근 이름·스크린숏 없이 키 서명만 저장 |
| `slop/rules.yaml` | 규칙 184개, 묶음 6개, 목록 16개. 원본 체크리스트 73개와 anti-slop 카탈로그 107행 이관분 125개에 동작 층 규칙 44개(기만·강요 패턴 12, 동작 접근성 17, 상태·복구·마찰 12, 동작 묶음 3), 렌더 층 대상 크기 규칙 1개, 권리 규칙 14개(`rights.*`: 출처 기록, 라이선스 범위·만료, 크레딧·고지, 예약 글꼴 이름, 타사 표장, 생성 매체, 초상·재산 동의)를 더했어요. 경계값과 목록 값은 v0 씨앗 |
| `slop/rules.schema.yaml`, `slop/rules.example.yaml` | 규칙 파일 스키마(출처 종류에 `regulation` 추가), 그리고 `plan_check` 단위 테스트용 부분집합 7개 |
| `slop/detectors.yaml` | 탐지기 89개 등록부(모두 구현, 코드와 등록부가 어긋나면 테스트가 실패해요), 규칙이 쓰는 모든 `params`·`threshold` 키 선언, 렌더 탐지기가 읽는 추출 필드(`reads`), 동작 탐지기가 읽는 세션 필드(`reads_session`), 자산 원장·폰트 잠금 필드(`reads_ledger`, `reads_lock`), 계획 경로식 문법 |
| `slop/finding.schema.yaml` | 판정 보고 형식 (behavior_check·rights_check, 세션·원장 경로, 문맥·흐름·단계·자산 위치 포함) |
| `fonts/lock.schema.yaml`, `fonts/example.fonts.lock.json` | 폰트 잠금 파일 (프로젝트 단위, 폰트마다 사용 작업 목록, 용도별 허가(`uses`), 배포 파일·변형·예약 이름·고지) |
| `assets/ledger.schema.yaml`, `assets/CHECKS.md`, `assets/example.assets.ledger.json` | 자산 원장 v0 (`.lapis/assets.ledger.json`, 폰트 밖 매체의 출처·라이선스·용도·크레딧·고지·표장·생성 기록), 권리 검사 정의, 예시 원장. 법적 판단이 아니라 기록 대조만 해요 |
| `fonts/system-fonts.yaml` | 시스템 폰트 표 (검증 여부 표기) |
| `sources/registry.yaml`, `sources/registry.schema.yaml` | 출처 등록부 v0: 폰트·색·자산·검색 출처 80곳과 접근 정책(`adapter` 카탈로그 어댑터, `read` 요청한 페이지만 읽기, `browser-link` 사용자용 링크만, `refused` 약관이 도구를 금지해 요청하지 않음, 조항 인용). 카탈로그 어댑터의 정책과 어긋나면 테스트가 실패해요 |
| `vocab/type.yaml` | PANOSE 라틴 10자리, 한중일 측정·분류와 측정 정의(`measure.py`와 대조), 문자 체계 포함 기준, 라틴 장르와 라이선스 ID(`catalog/labels.py`가 읽어요), 폰트 특징 영역 5개(탐지기가 읽어요), 탈네모틀 `square_spread` 0.1(보정 전 씨앗), 이름 규칙. 기호 폰트는 모든 문자 체계를 통틀어 글자가 20개 미만인 폰트이고(`letter_count`), 윤곽이 픽셀 계단뿐인 폰트는 `pixel_outline`으로 표시해 획 모양을 재지 않아요. 고정폭은 장르가 아니라 serif·sans 형태 옆에 붙는 폭 속성이에요. 원본 출처는 `provenance` 키에 두고 빌드가 지워요 |
| `vocab/color.yaml` | 결정 6축, 역할 7종, 관계 6종, 데이터 척도, 값 출처 분류, 색 체계 |
| `vocab/glossary.yaml` | 원본 용어집 178개 + 새 용어 6개, 영어 정의와 한국어 병기 |
| `index.yaml` | 공유 항목 목록과 소비 스킬별 보기 |

### 코드와 도구

| 파일 | 내용 |
| --- | --- |
| `cli/lapis_design/text_sig.py` | 키를 쓰는 MinHash 문구 서명의 기준 구현 (render_check와 lazuli ref가 같은 값을 내야 함) |
| `cli/lapis_design/behavior.py` | 동작 세션 파생 값의 기준 구현 (결과 분류, 초점 가시성, 탭 순서 역행, 재요청 횟수, 선택지 두드러짐 비와 거절 노력, 긴급성 재설정, 가격 뒤늦은 공개, 끼워 넣기, 숨은 약관, 나가기 노력) |
| `cli/lapis_design/plan_check.py` | plan_check v0: 스키마, 기본값(계획 층 탐지기 6종과 기본값 묶음), 계약, 폰트(배포 경로, 배포할 수 없는 취득 경로, 용도별 허가), 레퍼런스, 흐름 짝 검사. 판정 보고 형식으로 출력. 하네스 계획 속 블록 검사(`--from-markdown`)와 요약(`--summary`) |
| `cli/lapis_design/rights_check.py` | 권리 검사 기준 구현: 배포 파일·원격 호스트·아이콘 라이브러리의 원장 대조, 라이선스·용도·만료·크레딧·고지·예약 이름·표장·생성 매체·동의 검사. 원천 호스트가 우리 것인 렌더에서는 같은 출처·루프백·사설 주소의 매체를 소스 규칙에 맡기고, 이미지 최적화 경로(`/_next/image?url=...`)가 나르는 다른 호스트의 이미지는 원격으로 대조해요 |
| `cli/lapis_design/lint/` | `lapis-design slop lint`: 규칙마다 계획·소스·렌더·동작·리뷰 층의 탐지기를 부르고, 심각도·예외(`keep`)·차단 여부는 엔진만 정해요. 탐지기는 관찰(`Hit`)을 돌려주거나 판단할 수 없으면 이유와 함께 건너뛰어서, 입력이 없는 것이 통과로 읽히지 않아요. 탐지기는 `detectors/`의 여섯 모듈(source, render_type, render_layout, render_visual, copy, behavior)에 있어요 |
| `install/harnesses.schema.yaml`, `install/harnesses.yaml` | 하네스 정의 단일 원천 v0: 빌드 산출물 15종, 하네스 6종(Claude Code, Codex, Oh-My-Pi, pi, Hermes, 그 밖)의 감지·설치·갱신·제거·확인 명령(argv 배열), 세션 시작·평가자·MCP 방식, 신뢰 단계, 충돌, 미확인 사항(`unverified`), 로컬에서 확인한 사실(`verified`, 날짜·버전과 함께) |
| `tools/build/installers.py`, `install/install.sh`, `install/install.ps1`, `INSTALLATION.md` | 설치 도구. `install/harnesses.yaml`에서 설치 스크립트(macOS·Linux용 sh, Windows용 PowerShell)와 설치 안내서를 생성해요. 감지된 하네스마다 CLI 설치와 플러그인 등록을 하고, `--dry-run`, `--harness`, `--plugin`, `--update`, `--uninstall`, `--yes`를 받아요. 설치 방법은 [INSTALLATION.md](INSTALLATION.md)에 있어요 |
| `install/OUTPUTS.md`, `tools/build/build.py`, `tools/build/manifests.py` | 빌드 산출물 명세와 빌드. `build.py`가 `src/`와 `install/harnesses.yaml`에서 스킬·공유 보기·매니페스트·카탈로그·훅·MCP·에이전트·확장·Hermes 플러그인·패키지를 만들고, `--check`로 커밋된 산출물과 비교해요. 매니페스트·카탈로그·훅·MCP·패키지 형태는 `manifests.py`가 정해요 |
| `pyproject.toml`, `uv.lock`, `.python-version` | CLI 배포 패키지 `lapis-design`(PyPI의 `lapis-lazuli`는 다른 프로젝트가 써요). 진입점 `lapis-design`·`lazuli`, `src/shared` 전체를 `lapis_design/shared` 패키지 데이터로 넣어요 |
| `cli/lapis_design/cli.py`, `cli/lapis_design/hooks.py`, `cli/lapis_design/mcp_server.py`, `cli/lazuli/cli.py` | `lapis-design --version`, `plan check`·`rights check`(위 두 검사의 명령), `hook exit-plan`(Claude Code 계획 모드 종료 시 lapis-plan 블록 검사, 막을 때만 거부하고 대신 승인하지 않음), `hook session-start`(폰트 인벤토리 요약을 맥락으로 출력, 스캔은 하지 않음), `mcp`(공식 MCP Python SDK, `slop_lint` 도구). `lazuli --version` |
| `cli/lapis_design/render/`, `cli/lapis_design/sig_key.py` | `lapis-design render check URL [--task ID] [--plan PATH] [--public]`: `render/DERIVED.md`대로 우리 렌더를 9개 조건(320·390·768·1440, 라이트·다크, 모션 줄이기, 모바일 브라우저 UI)으로 캡처해 `render/extract.schema.yaml`에 맞는 추출물을 `.lapis/renders/<task>.json`에 써요. 우리 것인 호스트만 기본으로 캡처해요: `localhost`, 루프백·사설 주소, 그리고 시작할 때 사설 주소로만 풀리는 `.test` 이름(그 주소에 고정하고 `source.addresses`에 기록해요). 판단은 `ours.py` 하나가 렌더·동작 검사 모두에 맡아요. 공개 주소는 `--public`일 때만 캡처하고, 그때도 출처 등록부의 호스트와 계획 `references`의 호스트는 리디렉션까지 막아요(`hosts.py`). 캡처한 페이지가 연 새 창도 같은 규칙으로 막고 바로 닫아요. 남의 페이지는 `lazuli ref capture`로 캡처해요. 상자·텍스트 기본값은 `capture.py`, 측정 필드는 `fields/`(text·visual·interaction), 파생 값은 `derived.py`가 맡아요. 문구 서명 키는 사용자 캐시에만 둬요 |
| `cli/lapis_design/behavior_check/`, `cli/lapis_design/stub/` | `lapis-design behavior check URL --task ID --plan PLAN --stub FIXTURE [--timezone ZONE]`: `behavior/DERIVED.md`대로 루프백·사설 주소의 우리 렌더를 구동해 `behavior/session.schema.yaml`에 맞는 세션을 `.lapis/behavior/<task>.json`에 써요. 시간대는 기본 UTC예요. 드라이버 코어와 탐침(`probes/`)으로 나뉘고, 파생 값은 `behavior.py`가 채워요. `data-lapis-*` 힌트는 요소를 찾고 묶는 데만 쓰고, 힌트와 판단이 다르면 `hint_mismatch`로 적어 탐지기가 차단하지 않고 미확인으로 보고해요. 스텁은 엔진 하나를 브라우저 요청 가로채기(기본)나 `lapis-design stub serve`(서버 렌더링 앱용 HTTP)로 연결해요. `--backend local-dev`에서는 `--values`의 합성 값만 쓰고 실패 주입과 파괴적 탐침은 하지 않아요 |
| `cli/lazuli/db/migrations/` | lazuli DB 마이그레이션 (SQLite 3.34 이상, FTS5 trigram). `0002_color.sql`은 사용자가 기록한 색 체계 값(`color_record`, 화면 샘플은 항상 탐지 전용), `0003_user_label.sql`은 사용자가 알려 준 폰트 분류(`user_label`, 카탈로그 분류보다 우선)예요. 둘 다 다시 만들 수 없는 사용자 데이터예요. `0004_adobe_core_text.sql`은 Adobe 폴더의 파일을 열어 모았던 행을 지우고, 다음 스캔에서 Core Text로 다시 모으게 해요 |
| `cli/lazuli/catalog/` | `lazuli catalog sync\|lookup\|status`: 카탈로그에서 사람이 붙인 분류·라이선스를 사람 수준 속도로 받아 사용자 캐시에만 두고, 설치된 폰트와 PostScript 이름·패밀리 이름(한국어 이름 포함)·느슨한 이름으로 매칭해요. Google Fonts·Fontsource·Fontshare·안심글꼴은 스냅숏, 시스템 폰트 표는 번들, 산돌은 요청 시 조회(10초 간격)예요. Adobe Fonts와 눈누는 약관이 자동 수집을 금지해서 요청 없이 브라우저 링크만 줘요 |
| `cli/lazuli/` | `lazuli local fonts [--summary] [--family NAME] [--json]`: OS·사용자 폴더의 폰트를 읽기 전용으로 스캔하고(바뀐 파일만 다시 읽음), macOS에서는 Adobe Fonts가 켜 둔 폰트를 운영체제 폰트 API(Core Text)로 나열해 이름과 커버리지를 읽고 시스템이 그린 글리프로 재요(Adobe 폴더의 파일은 열지 않아요. Windows에는 Adobe 폰트가 없어요). PANOSE 라틴(굵기·비례·대비·x높이, 세리프 여부)과 한중일 확장(부리 비, 획 대비, 네모틀 편차, 라틴 대비 굵기)을 재서 사용자 캐시의 lazuli DB에 둬요. `lazuli doctor`는 SQLite·캐시·인벤토리·폰트 폴더·Adobe 폰트 수(macOS)·브라우저를 점검해요. 테스트는 코드로 만든 작은 합성 폰트를 써서 저장소에 폰트 파일이 없어요 |
| `cli/lazuli/lock.py`, `search.py` | `lazuli lock`: 고른 폰트의 출처·라이선스·배포 경로를 그 시점에 `.lapis/fonts.lock.json`에 고정해요. 카탈로그·파일 메타데이터의 라이선스는 힌트로만 적고, 용도별 허가는 사용자가 밝힌 것만 적어요. `lazuli search`: 문자 체계·역할·분류·라이선스·배포 경로·비슷한 폰트(측정 거리)로 후보와 근거를 순위대로 돌려줘요. `--type color`·`--type source`는 아래 모듈로 넘겨요 |
| `cli/lazuli/color.py`, `sources.py` | `lazuli color lookup\|record`: 색 체계 코드를 정규화하고 공식 링크를 줘요. HLC·RAL DESIGN SYSTEM plus는 좌표라 OKLCH 근삿값을 계산하고, Pantone·RAL CLASSIC·NCS·Munsell·Freetone은 코드와 링크만 저장소에 두고 값은 사용자 기록에서만 가져와요(접미사 없는 Pantone 번호는 불완전한 사양으로 알려요). `lazuli sources`는 출처 등록부를 보여 줘요 |
| `cli/lazuli/read.py`, `cli/lazuli/ref/` | `lazuli read URL`: 사용자가 요청한 페이지 하나를 등록부 정책과 robots.txt 안에서 Markdown으로 읽어요(`--render`는 스크립트로 그리는 페이지용). `lazuli ref capture\|profile\|system`: 레퍼런스 프로필을 렌더 추출 형식으로 `.lapis/refs/<slug>.json`에 써요. `reference-only` 캡처는 문구·대체 텍스트·이름·스크린숏 없이 키 서명과 지각 해시만 남겨요 |
| `cli/lazuli/setup.py` | `lazuli setup`: 공개된 임베딩 모델과 배포 목록 형식이 아직 없어서, 그렇다고 알리고 종료 코드 1로 끝나요 |
| `cli/lazuli/user_class.py` | `lazuli class set FAMILY --genre ID [--subclass ID] [--url URL]`, `lazuli class list [FAMILY]`, `lazuli class remove FAMILY`: 패밀리마다 사용자가 정한 분류를 기록해요. 장르, 선택적인 세부 분류, 그리고 lazuli가 열지 않는 선택적인 링크예요. 분류에서만 카탈로그보다 우선하고, 라이선스와 문자 체계는 계속 카탈로그에서 가져와요. 사용자 캐시 DB에만 둬요. `local fonts`·`search`·`lock`은 출처를 `user`로 보여 주고, `lock`은 힌트로만 다뤄요 |
| `tests/` | 계약 테스트, plan_check 테스트, 문구 서명 테스트, 동작 파생 값 테스트, 권리 검사 테스트, 하네스 정의 테스트, 렌더 추출 테스트(루프백 fixture와 Chromium), 슬롭 탐지기·엔진 테스트, lazuli 명령 테스트 |
| `.github/workflows/contracts.yml` | CI에서 테스트 실행 |
| `tools/migration-map.yaml` | 원본 222개 파일의 행선지와 진행 상태 (2026-09-25에 core 문서 4개 추가, 슬롭·동작·권리 원천 부분 완료 표시) |
| `tools/slop-id-trace.yaml` | 원본 체크리스트 ID 73개와 anti-slop 카탈로그 107행 → 새 규칙 ID 추적표 |
| `tools/calibration/calibrate.py` | lazuli DB의 측정값을 카탈로그 분류와 대조한 보정 보고서(혼동 행렬, 클래스별 정밀도·재현율, 틀린 패밀리, 경계값 훑기)를 Markdown으로 써요. DB를 읽기 전용으로 열고 요청을 보내지 않아요. 보고서에는 패밀리 이름과 수치만 들어가요 |

```bash
uv sync
uv run playwright install chromium-headless-shell
uv run pytest -q -m "not browser"   # 계약·검사·파생 값 (몇 초)
uv run pytest -q -m browser -n auto  # Chromium 테스트 병렬 실행 (몇 분)
uv run lapis-design --version
uv run lapis-design plan check src/shared/plan/example.plan.yaml \
  --rules src/shared/slop/rules.yaml --lock src/shared/fonts/example.fonts.lock.json
uv run lapis-design plan check src/shared/plan/example.plan.yaml --summary
uv run lapis-design plan check --from-markdown harness-plan.md
# 예시 원장의 파일·고지 경로가 이 저장소에 없어서 rights.notice-missing이 나오는 게 정상이에요
uv run lapis-design rights check --ledger src/shared/assets/example.assets.ledger.json \
  --lock src/shared/fonts/example.fonts.lock.json --extract src/shared/render/example.extract.json
uv run lapis-design render check http://127.0.0.1:8000/ --task demo
uv run lapis-design behavior check http://127.0.0.1:8000/ --task demo --plan .lapis/plans/demo.yaml --stub .lapis/stub.yaml
uv run lapis-design stub serve src/shared/behavior/example.stub.yaml --port 8787
uv run lapis-design slop lint --plan .lapis/plans/demo.yaml --extract .lapis/renders/demo.json --session .lapis/behavior/demo.json
uv run lazuli local fonts --summary
uv run lazuli doctor
uv run lazuli catalog sync
uv run lazuli catalog status
uv run lazuli search --script hang --role body --license open
uv run lazuli lock "Family" --role body --task demo --dry-run
uv run lazuli sources --type color
uv run lazuli color lookup pantone "186 C"
uv run lazuli read https://example.com/page
uv run lazuli ref capture https://example.com/ --rights reference-only
uv run lazuli setup
uv run python tools/build/build.py
uv run python tools/build/build.py --check
```

### 주석 언어

YAML과 코드의 주석·설명은 영어예요. 이관 지도만 한국어이고, 예시 계획·세션의 실제 UI 문구, 어휘 파일의 한국어 이름 필드(`ko`), 목록의 한국어 씨앗 값은 데이터라 그대로 둬요. 한국 법령 조항을 가리키는 출처 메모에는 영어 설명 뒤에 법령 용어를 괄호로 붙였어요.

### 규제 출처

`provenance`의 `regulation` 항목은 규칙이 어느 법령과 맞닿는지 유지보수용으로 기록할 뿐, 법 준수 여부를 판정하지 않아요. 2026-09-25 기준으로 확인한 상태예요: 한국 전자상거래법 다크패턴 조항(2025-02-14 시행), EU DSA 제25조, EU 소비자권리지침·불공정거래지침, 미국 ROSCA(FTC 부정적 옵션 규칙은 2025년 7월 항소법원에서 무효, 2026년 3월 사전 공고 단계), EU 디지털 공정성법은 2026년 4분기 제안 예정.

### 버전 규칙

렌더 추출은 `version: 1`(2026-09-25. v0로 만든 추출물이 아직 없어서 변환기는 두지 않았어요), 동작 세션·자산 원장·하네스 정의를 포함한 나머지 파일은 `version: 0`이에요. 폰트 잠금의 `license.web_embedding`은 `license.uses.web`으로 바뀌었어요(v0 초안 안의 변경이라 버전은 그대로). 필드를 바꾸면 버전을 올리고, `plan_check`가 옛 버전을 읽을 때 변환하거나 안내해요.
