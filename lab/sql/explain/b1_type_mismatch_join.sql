-- B-1. 타입이 다른 칼럼 조인 (워밍업용)
-- 출처: vault/sessions/001-plan.md B-1
--
-- 보여줄 것: 인덱스가 있는데도 안 탄다.
-- Moha 원본에는 varchar↔int 조인이 없으므로 실습용 칼럼을 하나 만든다.
--
-- EXPLAIN에서 볼 지점:
--   - 두 번째 쿼리(타입 안 맞는 쪽)에서 Seq Scan이 뜨는가
--   - 각 행마다 타입 변환(::varchar 캐스팅)이 일어나는가
--
-- 정리: 실험 끝나면 lab/sql/99_cleanup.sql로 movie_id_str 칼럼과
-- idx_rating_movie_str 인덱스를 되돌린다.

ALTER TABLE user_rating ADD COLUMN movie_id_str varchar(20);
UPDATE user_rating SET movie_id_str = movie_id::text;
CREATE INDEX idx_rating_movie_str ON user_rating(movie_id_str);
ANALYZE user_rating;

-- 인덱스를 타는 쪽
EXPLAIN ANALYZE
SELECT * FROM user_rating WHERE movie_id_str = '42';

-- 타입이 안 맞는 쪽 (인덱스가 있는데도)
EXPLAIN ANALYZE
SELECT r.* FROM user_rating r JOIN movies m ON r.movie_id_str = m.movie_id::varchar
WHERE m.movie_id = 42;
