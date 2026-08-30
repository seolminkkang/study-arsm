# backend-study

『주니어 백엔드 개발자가 반드시 알아야 할 실무 지식』(최범균, 한빛미디어) 2인 스터디.
책을 요약하는 스터디가 아니라 **측정해서 확인하는 스터디**입니다.
비전공 개발자 두 명이라 실무에서 겪은 장애가 없습니다. 경험에 기댈 수 없어서
느려지는 상황을 직접 만들어놓고 재는 방식을 택했습니다. 이 책이 산술 모델을
명시적으로 주기 때문에(`풀 크기 / 쿼리 시간 = 최대 TPS`) 경험이 없어도
예측하고 검증할 수 있습니다.

> 문서의 `C:/seolmin/backend-study` 경로는 작성자 기준입니다.
> 각자 clone한 경로로 바꿔 읽으면 됩니다(주로 `vault/sessions/001-cheatsheet.md`).

## 회차 목록

| 회차 | 장 | 주제 | Host | 날짜 | 기록 | 글 |
|---|---|---|---|---|---|---|
| 1 | 2·3장 | 인덱스와 커넥션 풀 | 설민 | 2026-08-30 | [개관](vault/sessions/001-overview.md) · [계획](vault/sessions/001-plan.md) · [실험](vault/experiments/) | |
| 2 | 4·5장 | 외부 연동, 비동기 | 팀원 | | | |

## 1회차에서 나온 것

아래는 회차 전 Host가 혼자 돌린 **리허설 파일럿** 값입니다. 당일 측정치는
`vault/experiments/`에 올라옵니다. 노트북 한 대에서 k6·앱·DB가 CPU를 나눠 쓰므로
절대값이 아니라 조건을 바꿨을 때의 방향만 봅니다.

- **커넥션 풀을 2에서 10으로 5배 늘렸는데 처리량이 늘지 않았다** — 0.73 TPS → 0.58 TPS.
  산술 모델의 예측은 1.7 → 8.6 TPS였다. DB 컨테이너가 `cpus: 2`라 상한을 정한 건
  풀 크기가 아니라 DB CPU였다.
  ([raw](vault/raw/2026-08-29_pilot_k6_load_sizing_rehearsal.txt) 4번)
- **인덱스 하나를 걸었더니 한쪽은 빨라지고 다른 쪽은 느려졌다** — `updated_at` 인덱스를
  걸자 커서 조회는 0.11초 → 0.0057초, 같은 인덱스에서 오프셋 조회는 1.16초 → 8.5초.
  ([raw](vault/raw/2026-08-29_pilot_k6_load_sizing_rehearsal.txt) 3번)
- **조회 칼럼 하나를 더했더니 커버링 인덱스가 깨졌다** — `Index Only Scan`(`Heap Fetches: 0`,
  0.78ms)이 `Bitmap Heap Scan`으로 바뀌면서 테이블 블록 9,315개를 읽으러 갔다(99.8ms).
  ([raw](vault/raw/2026-08-29_pilot_b3_b4_rehearsal.txt) B-3)

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `vault/` | 옵시디언 vault. 주(主)가 되는 기록 |
| `vault/raw/` | 측정 원본(k6 출력, `EXPLAIN` 결과). **수정 금지, 추가만 한다** |
| `vault/experiments/` | 실험 노트 — 가설 → 조건 → 결과 → 해석 |
| `vault/concepts/` | 개념 노트. "아직 모르는 것" 섹션을 비워두지 않는다 |
| `vault/sessions/` | 회차별 개관·계획·커닝페이퍼 |
| `vault/output/` | 공개용 글 |
| `vault/progress.md` | 책 전체 목차와 절별 등급(A/B/C), 넘긴 사유 |
| `lab/` | 실험 환경. `vault/`의 근거다 |
| `lab/app/` | 스프링 앱. 파일 5개, 계층 없음 |
| `lab/sql/` | 스키마, 시딩, 인덱스, 정리 SQL |
| `lab/sql/dump-lite/` | 영화 데이터 CSV를 넣는 자리. gitignore — 저장소에 없다 |
| `lab/k6/` | 부하 스크립트. 도착률 기반 |
| `lab/docker/` | PostgreSQL, Prometheus, Grafana |

## 데이터

**측정 결과는 저장소에 있지만, 데이터는 없습니다.** 이 저장소는 환경을 그대로
복제하는 재현 패키지가 아니라 기록입니다.

| 테이블 | 건수 | 성격 | 저장소 포함 |
|---|---|---|---|
| `movies` / `genres` / `movie_genres` | 19,701 / 19 / 47,104 | TMDB 실제 영화 메타데이터 | ✕ |
| `user_rating` | 5,030,000 | 실험용으로 생성 | ✕ (`03_seed_ratings.sql`이 만든다) |

> **`movies`는 영화 메타데이터면 무엇이든 됩니다.** TMDB일 필요가 없습니다.
> `movie_id`만 존재하면 `user_rating` 시딩과 이후 실험이 그대로 작동합니다.
> 넣는 방법은 [lab/sql/README.md](lab/sql/README.md)에 있습니다.

> **`user_rating`을 균등 분포로 만들면 안 됩니다.**
> 헤비 100명 × 5,000건 / 중간 1만 명 × 300건 / 라이트 9만 명 × 17건,
> 그리고 인기 영화 200편에 전체 평점의 40%가 몰리게 합니다.
> 균등하게 넣으면 누구를 조회하든 건수가 같아져서 **선택도 실험이 성립하지 않습니다.**
> 이 분포가 이 저장소에서 가장 중요한 설계 결정입니다.

## 어디부터 읽나

| 하려는 것 | 읽을 순서 |
|---|---|
| 환경 띄우기 | [SETUP.md](SETUP.md) |
| 방식이 궁금 | [CLAUDE.md](CLAUDE.md) → [vault/index.md](vault/index.md) |
| 1회차에서 뭘 했나 | [001-overview](vault/sessions/001-overview.md) → [001-plan](vault/sessions/001-plan.md) → [experiments/](vault/experiments/) |
| 직접 실행 | [001-cheatsheet](vault/sessions/001-cheatsheet.md) |

## 규칙 4개

- **실측 없이 결론을 쓰지 않는다.** 추측은 `#가설` 태그로 남기고 결론과 구분한다
- **예측은 사람이 쓴다.** 실험 노트의 "예측" 섹션을 AI가 채우지 않는다.
  예측이 틀리는 순간이 학습이 일어나는 유일한 지점이다
- **`vault/raw/`는 수정하지 않는다.** 고치면 그때 실제로 무엇이 측정됐는지
  확인할 방법이 사라진다. 해석이 바뀌면 `experiments/`를 고친다
- **실험이 만든 칼럼·인덱스는 그 실험이 끝나는 즉시 지운다.** 남아 있으면
  다음 실험의 실행계획이 달라져 결과를 신뢰할 수 없다

전체 규칙과 배경은 [CLAUDE.md](CLAUDE.md)에 있습니다.
**Claude Code가 아닌 도구를 쓴다면 CLAUDE.md를 직접 읽혀야 합니다.**
다른 도구는 이 파일을 자동으로 읽지 않습니다.

## 이 방식을 따라해보려면

환경을 복제하는 게 아니라 **방식**을 가져가면 됩니다.

- 책을 정하고, 그 책이 **산술 모델을 주는지** 본다. 주면 경험이 없어도 예측할 수 있다
- 실험 가능한 절만 A(부하 측정) / B(`EXPLAIN` 한 번) / C(읽고 넘김)로 나눈다 —
  [vault/progress.md](vault/progress.md)가 그 예다
- **예측 → 실행 → 차이** 순서를 지킨다. 예측이 틀리는 지점이 배우는 자리다
- **데이터는 각자 준비한다.** 스키마만 있으면 된다 —
  [lab/sql/01_schema.sql](lab/sql/01_schema.sql)

## 출처

- 최범균, 『주니어 백엔드 개발자가 반드시 알아야 할 실무 지식』, 한빛미디어
  (책 내용은 옮기지 않습니다. 실험 설계와 측정 결과만 담습니다)
- 영화 메타데이터 출처: The Movie Database (TMDB) — https://www.themoviedb.org/
  **This product uses the TMDB API but is not endorsed or certified by TMDB.**
  **원본 데이터는 저장소에 포함하지 않습니다** — TMDB 약관상 6개월을 넘긴 캐시와
  데이터셋 재배포가 금지됩니다
- 평점 500만 건은 실험용으로 생성한 데이터이며 실제 사용자 데이터가 아닙니다
