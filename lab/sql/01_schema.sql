-- 01_schema.sql
-- 실습용 테이블 4개. overview, movie_vector, keywords, status 등
-- 파이프라인/실험 무관 칼럼은 제외한다. (lab/README.md ① 참고)
--
-- user_rating에는 PK/FK를 걸지 않는다.
-- 500만 건을 넣을 테이블이라 제약이 없어야 대량 INSERT가 빠르다.
-- 인덱스는 04_indexes.sql에서 실험 조건으로 걸었다 뺐다 한다.

CREATE TABLE movies (
    movie_id       bigint PRIMARY KEY,
    title          text NOT NULL,
    original_title text NOT NULL,
    release_date   date,
    runtime        integer,
    director       text,
    vote_count     integer NOT NULL DEFAULT 0,
    poster_path    text
);

CREATE TABLE genres (
    genre_id integer PRIMARY KEY,
    name     text NOT NULL
);

CREATE TABLE movie_genres (
    movie_id bigint  NOT NULL REFERENCES movies(movie_id),
    genre_id integer NOT NULL REFERENCES genres(genre_id),
    PRIMARY KEY (movie_id, genre_id)
);

CREATE TABLE user_rating (
    user_id    bigint NOT NULL,
    movie_id   bigint NOT NULL,
    rating     smallint NOT NULL CHECK (rating BETWEEN 1 AND 10),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
