#!/usr/bin/env bash
# 02_load_movies.sh
# 원본 Moha 덤프(exec/sql_dump/movies/*)에서 실습에 필요한 칼럼만
# awk로 뽑아 lab-postgres 컨테이너에 COPY로 적재한다.
#
# 원본 덤프는 COPY ... FROM stdin 형식이고 스키마가 다르다(칼럼이 더 많다).
# 그대로 로드할 수 없으므로 칼럼 인덱스만 골라 탭 구분 파일로 만든 뒤 싣는다.
#
# 사용법:
#   MOHA_DUMP_DIR="C:/seolmin/portfolio/moha_cinema/moha_cinema-app/moha_project/exec/sql_dump" \
#     ./02_load_movies.sh

set -euo pipefail

DUMP_DIR="${MOHA_DUMP_DIR:?MOHA_DUMP_DIR (원본 exec/sql_dump 경로)를 지정하세요}"
OUT_DIR="$(dirname "$0")/dump"
CONTAINER="lab-postgres"
DB_USER="lab"
DB_NAME="labdb"

MOVIES_SRC="$DUMP_DIR/movies/moha_movies_2025-09-27_125634.sql"
GENRES_SRC="$DUMP_DIR/movies/moha_genres_2025-09-27_121107.sql"
MOVIE_GENRES_SRC="$DUMP_DIR/movies/moha_movie_genres_2025-09-27_121124.sql"

mkdir -p "$OUT_DIR"

# movies: movie_id(1) title(3) original_title(4) release_date(7)
#         runtime(9) director(10) vote_count(11) poster_path(12)
awk -F'\t' '
  /^COPY movies\.movies/ { flag=1; next }
  flag && /^\\\.$/ { flag=0; exit }
  flag { print $1"\t"$3"\t"$4"\t"$7"\t"$9"\t"$10"\t"$11"\t"$12 }
' "$MOVIES_SRC" > "$OUT_DIR/movies.tsv"

# genres: genre_id(1) genre_name(3) -> name
awk -F'\t' '
  /^COPY movies\.genres/ { flag=1; next }
  flag && /^\\\.$/ { flag=0; exit }
  flag { print $1"\t"$3 }
' "$GENRES_SRC" > "$OUT_DIR/genres.tsv"

# movie_genres: movie_id(1) genre_id(2) -> 칼럼 그대로
#
# 주의: movie_genres 덤프(121124)가 movies 덤프(125634)보다 4시간 넘게 먼저
# 떠졌다. 그 사이 파이프라인이 movies 테이블을 정리하면서 원본 71,055개
# movie_id 후보 중 19,701개만 남았다 — movie_genres의 97,592건(전체의 67%)이
# 지금 movies.tsv에 없는 movie_id를 참조한다. 두 덤프가 같은 시점의 스냅샷이
# 아니라서 생기는 불일치이므로, movies.tsv에 실제로 있는 movie_id만 남긴다.
awk -F'\t' '
  /^COPY movies\.movie_genres/ { flag=1; next }
  flag && /^\\\.$/ { flag=0; exit }
  flag { print $1"\t"$2 }
' "$MOVIE_GENRES_SRC" > "$OUT_DIR/movie_genres.raw.tsv"

awk -F'\t' '
  NR==FNR { ids[$1]=1; next }
  ($1 in ids)
' "$OUT_DIR/movies.tsv" "$OUT_DIR/movie_genres.raw.tsv" > "$OUT_DIR/movie_genres.tsv"

echo "movie_genres 원본 $(wc -l < "$OUT_DIR/movie_genres.raw.tsv")건 -> movies에 있는 movie_id만 $(wc -l < "$OUT_DIR/movie_genres.tsv")건"

echo "추출 행 수:"
wc -l "$OUT_DIR"/movies.tsv "$OUT_DIR"/genres.tsv "$OUT_DIR"/movie_genres.tsv

echo "적재: genres"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -c "COPY genres(genre_id, name) FROM STDIN" < "$OUT_DIR/genres.tsv"

echo "적재: movies"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -c "COPY movies(movie_id, title, original_title, release_date, runtime, director, vote_count, poster_path) FROM STDIN" \
  < "$OUT_DIR/movies.tsv"

echo "적재: movie_genres"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -c "COPY movie_genres(movie_id, genre_id) FROM STDIN" < "$OUT_DIR/movie_genres.tsv"

echo "적재 후 건수:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT 'movies' AS tbl, count(*) FROM movies
  UNION ALL SELECT 'genres', count(*) FROM genres
  UNION ALL SELECT 'movie_genres', count(*) FROM movie_genres;
"
