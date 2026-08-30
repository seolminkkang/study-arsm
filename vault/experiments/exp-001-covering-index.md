---
id: exp-001
aliases: [exp-001]
title: 커버링 인덱스 — 조회 칼럼 하나가 실행계획을 바꾼다
chapter: [3]
status: done
date: 2026-08-30
commit: f9362d9
raw: ["2026-08-30_exp-001_session_results.txt"]
conclusion: 조회 칼럼에 updated_at을 하나 더하자 Index Only Scan이 Bitmap Heap Scan으로 바뀌고 테이블 블록 9,310개를 읽었다
tags: [experiment]
---

## 가설

필요한 칼럼이 전부 인덱스 안에 있으면 테이블을 읽지 않는다.
인덱스에 없는 칼럼을 하나라도 조회하면 테이블을 읽으러 가야 한다.

## 조건
- 앱: 사용 안 함. `psql`에서 `EXPLAIN ANALYZE`만 실행
- DB: PostgreSQL 16, CPU 2 / mem 2g
- 데이터: `user_rating` 5,030,000건. 인기 영화 200편에 평점의 40%가 몰린 분포
- 인덱스: `idx_user_rating__movie_rating (movie_id, rating)`
- 변수: **SELECT 절의 칼럼 목록만 바꾼다.** WHERE 조건은 동일
- 전제: `VACUUM user_rating` 실행 후 측정

`VACUUM`이 왜 전제인가 — 대량 INSERT 직후에는 visibility map(어떤 페이지가
모든 트랜잭션에 보이는지 표시한 지도)이 비어 있다. 이게 비어 있으면
PostgreSQL이 인덱스만 보고 답할 수 있는 상황에서도 테이블을 확인하러 간다.
`ANALYZE`는 통계만 갱신하므로 이걸 대신하지 못한다.

## 예측
> 실행 전에 사람이 직접 쓴다. AI가 채우지 않는다.

| 사람 | 예측 | 근거 |
|---|---|---|
| 설민 | | |
| 팀원 | | |

## 결과
원본: [[2026-08-30_exp-001_session_results]] B-3

```sql
SELECT movie_id, rating            FROM user_rating WHERE movie_id = 60300;
SELECT movie_id, rating, updated_at FROM user_rating WHERE movie_id = 60300;
```

| 조회 칼럼 | 실행계획 | 테이블 접근 | 실행 시간 |
|---|---|---|---|
| `movie_id, rating` | Index Only Scan | `Heap Fetches: 0` | 0.77 ms |
| `movie_id, rating, updated_at` | Bitmap Heap Scan | `Heap Blocks: 9310` | 16.4 ms |

`Heap Fetches: 0`은 테이블(heap)을 한 번도 읽지 않았다는 뜻이다.
`Heap Blocks: 9310`은 테이블 블록 9,310개를 읽었다는 뜻이다.
PostgreSQL의 블록 하나는 8KB이므로 약 73MB를 읽은 셈이다.

**배율은 인용하지 않는다.** 같은 실험에서 08-28에 1,788배, 08-29에 128배,
당일에 21배가 나왔다. 느린 쪽(비커버링)이 OS 페이지 캐시 상태에 따라 요동친다.
안정적인 것은 `Heap Fetches: 0`과 `Heap Blocks: 9310`의 대비다.

## 예측과의 차이
> 이 노트에서 가장 중요한 섹션.
> 무엇을 틀렸고, 왜 틀렸는가.

## 남은 질문
- #question `Heap Blocks: 9310`은 10,339행을 읽으려고 블록 9,310개를 읽었다는 뜻이다.
  블록 하나에 8KB면 수십 행이 들어갈 텐데 왜 행 수와 블록 수가 비슷한가.
  같은 영화의 평점이 테이블에 흩어져 있어서인가
- #question 배율이 21배 ~ 1,788배로 요동친다면, 이 실험에서 "빠르다"고 말할 수 있는
  근거는 무엇인가. 실행계획 종류만인가
- #question `VACUUM` 없이 돌리면 커버링이 안 먹는다는 것은 확인했다.
  운영 중인 DB에서는 autovacuum이 알아서 도는가

## 이번에 물어본 것
- `Heap Fetches`와 `Heap Blocks`는 각각 무엇을 세는 값인가
- `VACUUM`과 `ANALYZE`의 차이

## 관련
- [[커버링 인덱스]]
- [[선택도]]
- [[exp-003]]
