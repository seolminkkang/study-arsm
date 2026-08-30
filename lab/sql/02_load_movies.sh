#!/usr/bin/env bash
# 02_load_movies.sh
# 영화 데이터(movies, genres, movie_genres)를 lab-postgres에 적재한다.
#
# 기본 경로 — 원본 Moha 덤프에서 칼럼만 뽑아 적재한다.
#   MOHA_DUMP_DIR="<원본>/exec/sql_dump" ./02_load_movies.sh
#
# 대안 경로 — dump-lite/*.csv 가 있으면 그걸 싣는다.
#   ./02_load_movies.sh
#
# 두 데이터 모두 저장소에 없다. 영화 메타데이터는 TMDB에서 온 것이라
# 약관상 6개월을 넘겨 캐시하거나 데이터셋으로 재배포할 수 없다.
# dump-lite/*.csv 는 각자 만들어 넣는 자리다 — 01_schema.sql의 칼럼 순서에만
# 맞으면 어떤 영화 데이터든 된다. MOHA_DUMP_DIR로 한 번 돌리면 그 CSV가 생긴다.
#
# user_rating은 여기서 다루지 않는다 — 03_seed_ratings.sql이 생성한다.
# movie_id만 존재하면 그 시딩은 어떤 영화 데이터에서도 그대로 작동한다.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LITE_DIR="$HERE/dump-lite"
RAW_DIR="$HERE/dump"
CONTAINER="lab-postgres"
DB_USER="lab"
DB_NAME="${LAB_DB_NAME:-labdb}"   # 검증용으로만 덮어쓴다. 평소엔 labdb

psql_c() { docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" "$@"; }
psql_stdin() { docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" "$@"; }

# ─────────────────────────────────────────────────────────────
# 원본 덤프가 주어졌을 때만: awk로 칼럼을 뽑아 dump/*.tsv 를 만든다
# ─────────────────────────────────────────────────────────────
extract_from_moha_dump() {
  local DUMP_DIR="$1"
  local MOVIES_SRC="$DUMP_DIR/movies/moha_movies_2025-09-27_125634.sql"
  local GENRES_SRC="$DUMP_DIR/movies/moha_genres_2025-09-27_121107.sql"
  local MOVIE_GENRES_SRC="$DUMP_DIR/movies/moha_movie_genres_2025-09-27_121124.sql"

  mkdir -p "$RAW_DIR"

  # movies: movie_id(1) title(3) original_title(4) release_date(7)
  #         runtime(9) director(10) vote_count(11) poster_path(12)
  awk -F'\t' '
    /^COPY movies\.movies/ { flag=1; next }
    flag && /^\\.$/ { flag=0; exit }
    flag { print $1"\t"$3"\t"$4"\t"$7"\t"$9"\t"$10"\t"$11"\t"$12 }
  ' "$MOVIES_SRC" > "$RAW_DIR/movies.tsv"

  # genres: genre_id(1) genre_name(3) -> name
  awk -F'\t' '
    /^COPY movies\.genres/ { flag=1; next }
    flag && /^\\.$/ { flag=0; exit }
    flag { print $1"\t"$3 }
  ' "$GENRES_SRC" > "$RAW_DIR/genres.tsv"

  # movie_genres: movie_id(1) genre_id(2) -> 칼럼 그대로
  #
  # 주의: movie_genres 덤프(121124)가 movies 덤프(125634)보다 4시간 넘게 먼저
  # 떠졌다. 그 사이 파이프라인이 movies 테이블을 정리하면서 원본 71,055개
  # movie_id 후보 중 19,701개만 남았다 — movie_genres의 97,592건(전체의 67%)이
  # 지금 movies.tsv에 없는 movie_id를 참조한다. 두 덤프가 같은 시점의 스냅샷이
  # 아니라서 생기는 불일치이므로, movies.tsv에 실제로 있는 movie_id만 남긴다.
  awk -F'\t' '
    /^COPY movies\.movie_genres/ { flag=1; next }
    flag && /^\\.$/ { flag=0; exit }
    flag { print $1"\t"$2 }
  ' "$MOVIE_GENRES_SRC" > "$RAW_DIR/movie_genres.raw.tsv"

  awk -F'\t' '
    NR==FNR { ids[$1]=1; next }
    ($1 in ids)
  ' "$RAW_DIR/movies.tsv" "$RAW_DIR/movie_genres.raw.tsv" > "$RAW_DIR/movie_genres.tsv"

  echo "movie_genres 원본 $(wc -l < "$RAW_DIR/movie_genres.raw.tsv")건 -> movies에 있는 movie_id만 $(wc -l < "$RAW_DIR/movie_genres.tsv")건"
  echo "추출 행 수:"
  wc -l "$RAW_DIR"/movies.tsv "$RAW_DIR"/genres.tsv "$RAW_DIR"/movie_genres.tsv

  echo "적재: genres  (dump/*.tsv)"
  psql_stdin -c "COPY genres(genre_id, name) FROM STDIN" < "$RAW_DIR/genres.tsv"
  echo "적재: movies  (dump/*.tsv)"
  psql_stdin -c "COPY movies(movie_id, title, original_title, release_date, runtime, director, vote_count, poster_path) FROM STDIN" \
    < "$RAW_DIR/movies.tsv"
  echo "적재: movie_genres  (dump/*.tsv)"
  psql_stdin -c "COPY movie_genres(movie_id, genre_id) FROM STDIN" < "$RAW_DIR/movie_genres.tsv"
}

# 적재된 결과를 저장소에 커밋할 CSV로 다시 쓴다.
# CSV 인용부호 처리를 손으로 하지 않으려고 PostgreSQL의 COPY ... FORMAT csv를 쓴다.
# 제목에 쉼표가 들어간 영화가 실제로 있다(예: "양 한 마리, 양 두 마리").
regenerate_lite_csv() {
  mkdir -p "$LITE_DIR"
  psql_c -c "\copy (SELECT movie_id, title, original_title, release_date, runtime, director, vote_count, poster_path FROM movies ORDER BY movie_id) TO STDOUT WITH (FORMAT csv, HEADER true)" > "$LITE_DIR/movies.csv"
  psql_c -c "\copy (SELECT genre_id, name FROM genres ORDER BY genre_id) TO STDOUT WITH (FORMAT csv, HEADER true)" > "$LITE_DIR/genres.csv"
  psql_c -c "\copy (SELECT movie_id, genre_id FROM movie_genres ORDER BY movie_id, genre_id) TO STDOUT WITH (FORMAT csv, HEADER true)" > "$LITE_DIR/movie_genres.csv"
  echo "dump-lite/*.csv 갱신됨:"
  ls -l "$LITE_DIR"
}

# 대안 경로: 각자 만들어 넣은 dump-lite/*.csv 를 싣는다
# (저장소에 없다. 있으면 쓰고, 없으면 MOHA_DUMP_DIR를 요구한다)
load_from_lite_csv() {
  for f in genres movies movie_genres; do
    [ -f "$LITE_DIR/$f.csv" ] || { echo "없음: $LITE_DIR/$f.csv" >&2; exit 1; }
  done

  # FK 때문에 순서가 정해져 있다: genres -> movies -> movie_genres
  echo "적재: genres  (dump-lite/genres.csv)"
  psql_stdin -c "\copy genres(genre_id, name) FROM STDIN WITH (FORMAT csv, HEADER true)" < "$LITE_DIR/genres.csv"
  echo "적재: movies  (dump-lite/movies.csv)"
  psql_stdin -c "\copy movies(movie_id, title, original_title, release_date, runtime, director, vote_count, poster_path) FROM STDIN WITH (FORMAT csv, HEADER true)" < "$LITE_DIR/movies.csv"
  echo "적재: movie_genres  (dump-lite/movie_genres.csv)"
  psql_stdin -c "\copy movie_genres(movie_id, genre_id) FROM STDIN WITH (FORMAT csv, HEADER true)" < "$LITE_DIR/movie_genres.csv"
}

docker exec "$CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 \
  || { echo "lab-postgres가 안 떠 있다. 'cd lab/docker && docker compose up -d' 먼저." >&2; exit 1; }

if [ -n "${MOHA_DUMP_DIR:-}" ]; then
  echo "== 원본 덤프에서 적재: $MOHA_DUMP_DIR"
  extract_from_moha_dump "$MOHA_DUMP_DIR"
  regenerate_lite_csv
elif [ -f "$LITE_DIR/movies.csv" ]; then
  echo "== dump-lite/*.csv 에서 적재"
  load_from_lite_csv
else
  cat >&2 <<MSG
영화 데이터가 없다. 둘 중 하나를 준비한다.

  1) 원본 Moha 덤프가 있다면
       MOHA_DUMP_DIR="<원본>/exec/sql_dump" ./02_load_movies.sh

  2) 없다면 lab/sql/dump-lite/ 에 CSV 세 개를 직접 넣는다
       movies.csv        movie_id,title,original_title,release_date,runtime,director,vote_count,poster_path
       genres.csv        genre_id,name
       movie_genres.csv  movie_id,genre_id
     헤더 한 줄을 포함한 CSV다. 01_schema.sql의 칼럼 순서에 맞으면
     어떤 영화 데이터든 된다 — user_rating 시딩은 movie_id만 있으면 작동한다.

TMDB 약관 때문에 두 데이터 모두 저장소에 넣지 않는다(README 출처 참고).
MSG
  exit 1
fi

echo "적재 후 건수:"
psql_c -c "
  SELECT 'movies' AS tbl, count(*) FROM movies
  UNION ALL SELECT 'genres', count(*) FROM genres
  UNION ALL SELECT 'movie_genres', count(*) FROM movie_genres;
"
