# sql

> ⚠ ponytail 끄고 작업할 것 — `03_seed_ratings.sql`은 의도적 복잡도 (`CLAUDE.md` ponytail 섹션 참고)

| 파일 | 역할 |
|---|---|
| `01_schema.sql` | 테이블 4개 생성 (overview, movie_vector 제외) |
| `02_load_movies.sh` | 원본 덤프에서 칼럼만 뽑아 영화 데이터 로드 (awk 추출 필요해서 `.sql`이 아니라 `.sh`) |
| `03_seed_ratings.sql` | user_rating 500만 건, 양쪽 치우친 분포 |
| `04_indexes.sql` | 인덱스 생성/삭제 (실험 중 걸었다 뺐다) |
| `00_find_test_ids.sql` | 시딩 후 헤비/라이트 유저, 인기 영화 ID 조회 (B급 쿼리 자리표시자 채우는 용도) |
| `99_cleanup.sql` | 실험용으로 덧붙인 칼럼/인덱스 원복 |
| `explain/` | B급 실험용 쿼리 모음 (`vault/sessions/001-plan.md` B-1~B-4) |

원본 덤프(`dump/`)는 gitignore. 스크립트만 커밋한다.

`03` 실행 후 반드시 `ANALYZE user_rating;`

## `02_load_movies.sh` 실측 건수

`lab/README.md`에 적힌 건수(19,731 / 49 / 144,741)는 원본 덤프와 다르다.
실제로 적재되는 건 다음과 같다.

| 테이블 | lab/README.md 기재값 | 실측 |
|---|---|---|
| movies | 19,731 | 19,701 |
| genres | 49 | 19 |
| movie_genres | 144,741 | 47,104 (원본 144,696건 중) |

genres가 49 → 19인 건 단순 오기로 보인다 (TMDB 표준 장르 수와 일치).

movie_genres가 크게 줄어든 건 오기가 아니다. 원본 덤프 세 개의 export
시각이 다르다 — `movie_genres`(12:11)가 `movies`(12:56)보다 45분 먼저
떠졌다. 그 사이 movies 정리 파이프라인이 71,055개 movie_id 후보 중
19,701개만 남기고 정리했고, movie_genres는 정리 전 스냅샷이라 그중
97,592건(전체의 67%)이 지금 movies에 없는 movie_id를 참조한다.
두 파일이 같은 시점의 스냅샷이 아니라서 생기는 불일치다.

`02_load_movies.sh`는 movie_genres를 movies.tsv에 실제로 있는
movie_id로 필터링해서 적재한다. 필터링 후에도 19,701개 영화 전부가
장르를 최소 1개는 갖고 있다(확인 완료).
