-- 03_seed_ratings.sql
-- user_rating 약 500만 건 시딩. (lab/README.md ③ 참고)
-- 다시 돌려도 되게 TRUNCATE부터 한다.
--
-- 분포 설계 (사용자 10만 100명):
--   헤비   user_id    1 ~   100 (100명)  각 5,000건 -> 500,000건
--   중간   user_id  101 ~ 10,100 (1만명) 각   300건 -> 3,000,000건
--   라이트 user_id 10,101 ~ 100,100 (9만명) 각 17건 -> 1,530,000건
--   합계 5,030,000건
--
-- 영화 쪽 쏠림: vote_count 상위 200편(popular)에 40%, 나머지 19,501편(longtail)에 60%.
-- popular은 vote_count >= 12,613 (전체 median 157의 80배) — 확실히 구분되는 상위권이다.
--
-- created_at 쏠림: 70%는 최근 90일 이내, 30%는 그 이전 640일(총 2년 범위)에 고르게.
-- updated_at은 created_at + 0~3일(now() 초과 금지) — (user_id, updated_at) 인덱스 실습용으로
-- created_at과 완전히 같지 않게 한다.
--
-- 주의: 헤비 유저는 popular 200편 풀에서 초당 여러 번 독립적으로 뽑으므로
-- 같은 (user_id, movie_id) 조합이 여러 번 나올 수 있다(동일 영화 중복 평점).
-- 유니크 제약을 걸지 않은 이유이기도 하다 — 5,000건은 실제 사용자 행동이 아니라
-- "선택도가 낮은 조건일 때 몇 행이 돌아오는가"를 보기 위한 극단값이다.

\set ON_ERROR_STOP on

TRUNCATE TABLE user_rating;

BEGIN;

CREATE TEMP TABLE popular_movies AS
SELECT movie_id FROM movies ORDER BY vote_count DESC, movie_id LIMIT 200;

CREATE TEMP TABLE longtail_movies AS
SELECT movie_id FROM movies
WHERE movie_id NOT IN (SELECT movie_id FROM popular_movies);

DO $$
DECLARE
    popular_ids  bigint[];
    longtail_ids bigint[];
BEGIN
    SELECT array_agg(movie_id) INTO popular_ids  FROM popular_movies;
    SELECT array_agg(movie_id) INTO longtail_ids FROM longtail_movies;

    INSERT INTO user_rating (user_id, movie_id, rating, created_at, updated_at)
    SELECT
        u.user_id,
        CASE WHEN random() < 0.4
             THEN popular_ids[(1 + floor(random() * array_length(popular_ids, 1)))::int]
             ELSE longtail_ids[(1 + floor(random() * array_length(longtail_ids, 1)))::int]
        END AS movie_id,
        (1 + floor(random() * 10))::smallint AS rating,
        ca.created_at,
        LEAST(ca.created_at + (random() * 3) * interval '1 day', now()) AS updated_at
    FROM (
        SELECT user_id,
               CASE WHEN user_id <= 100 THEN 5000
                    WHEN user_id <= 10100 THEN 300
                    ELSE 17 END AS n
        FROM generate_series(1, 100100) AS user_id
    ) u
    CROSS JOIN LATERAL generate_series(1, u.n) AS s(i)
    CROSS JOIN LATERAL (
        -- s.i를 넣어 진짜 LATERAL(행마다 재평가)로 만든다.
        -- 상관 없는 서브쿼리로 두면 옵티마이저가 한 번만 평가해서
        -- 모든 행의 created_at이 동일해지는 버그가 있었다(재현 확인함).
        SELECT s.i AS _row, CASE WHEN random() < 0.7
                    THEN now() - (random() * interval '90 days')
                    ELSE now() - interval '90 days' - (random() * interval '640 days')
               END AS created_at
    ) ca;
END $$;

COMMIT;

ANALYZE user_rating;
