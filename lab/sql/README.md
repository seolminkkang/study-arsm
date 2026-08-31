# sql

> ⚠ ponytail 끄고 작업할 것 — `03_seed_ratings.sql`은 의도적 복잡도 (`CLAUDE.md` ponytail 섹션 참고)

| 파일 | 역할 |
|---|---|
| `01_schema.sql` | 테이블 4개 생성 (overview, movie_vector 제외) |
| `02_load_movies.sh` | 영화 데이터 로드. `MOHA_DUMP_DIR`가 기본, 없으면 `dump-lite/*.csv` (awk 추출 필요해서 `.sql`이 아니라 `.sh`) |
| `03_seed_ratings.sql` | user_rating 500만 건, 양쪽 치우친 분포 |
| `04_indexes.sql` | 인덱스 생성/삭제 (실험 중 걸었다 뺐다) |
| `00_find_test_ids.sql` | 시딩 후 헤비/라이트 유저, 인기 영화 ID 조회 (B급 쿼리 자리표시자 채우는 용도) |
| `99_cleanup.sql` | 실험용으로 덧붙인 칼럼/인덱스 원복 |
| `explain/` | B급 실험용 쿼리 모음 (`vault/planning/001-plan.md` B-1~B-4) |
| `dump-lite/` | 영화 데이터 CSV 3개. **gitignore.** 각자 만들어 넣는 자리다 |
| `dump/` | 원본 덤프에서 awk로 뽑은 중간 산출물. gitignore |

## 영화 데이터는 저장소에 없다

`dump/`도 `dump-lite/`도 gitignore 대상이다. 영화 메타데이터는 TMDB에서
온 것이라 약관상 6개월을 넘겨 캐시하거나 데이터셋으로 재배포할 수 없다.
저장소 커밋은 영구 보관이므로 이 조항에 걸린다.

**`dump-lite/`는 각자 만들어 넣는 자리다.** 파일이 있으면
`02_load_movies.sh`가 그 경로로 적재한다.

```bash
MOHA_DUMP_DIR="<원본>/exec/sql_dump" ./02_load_movies.sh   # 기본 경로
./02_load_movies.sh                                       # dump-lite/*.csv 가 있을 때
```

`MOHA_DUMP_DIR`를 주면 awk로 칼럼을 뽑아 `dump/*.tsv`를 만들고, 그걸 적재한 뒤
**적재 결과를 다시 `dump-lite/*.csv`로 쓴다.** CSV의 정의가 "DB에 실제로 들어간 것"이
되도록 하기 위해서다. 한 번 돌려두면 다음부터는 CSV 경로로 빠르게 다시 채울 수 있다.

직접 만들 때는 헤더 한 줄을 포함한 CSV로 두고, `01_schema.sql`의 칼럼 순서에 맞춘다.

```
movies.csv        movie_id,title,original_title,release_date,runtime,director,vote_count,poster_path
genres.csv        genre_id,name
movie_genres.csv  movie_id,genre_id
```

**영화 데이터는 아무거나 된다.** TMDB일 필요가 없다. `movie_id`만 존재하면
`03_seed_ratings.sql`의 시딩과 이후 실험이 그대로 작동한다.
실제 제목을 쓰면 디버깅이 쉬울 뿐이다(`title = '스트립퍼 배심원'` vs `'random text 847293'`).

CSV 변환을 awk가 아니라 PostgreSQL의 `COPY ... FORMAT csv`로 하는 이유는
인용부호 처리 때문이다. 제목에 쉼표가 들어간 영화가 실제로 있다
(`양 한 마리, 양 두 마리`). 손으로 TSV를 CSV로 바꾸면 그 행이 깨진다.

user_rating은 CSV로 두지 않는다. `03_seed_ratings.sql`이 매번 같은 분포로
다시 만들어내므로 500만 행을 저장할 이유가 없다.

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
