-- B-3. 커버링 인덱스
-- 출처: vault/sessions/001-plan.md B-3
--
-- 보여줄 것: 필요한 칼럼이 전부 인덱스에 있으면 테이블을 안 읽는다.
-- (movie_id, rating) 인덱스가 이미 있다.
--
-- <인기영화ID>는 lab/sql/00_find_test_ids.sql로 찾아서 채운다.
-- 값은 vault/sessions/001-plan.md 공통 조건 블록에 기록해둔다.
--
-- EXPLAIN에서 볼 지점:
--   - Index Only Scan (첫 쿼리) vs Index Scan (두 번째 쿼리)
--   - Heap Fetches 수치 — 0에 가까울수록 인덱스만으로 끝난 것

-- 인덱스만으로 끝나는 쿼리
EXPLAIN ANALYZE
SELECT movie_id, rating FROM user_rating WHERE movie_id = <인기영화ID>;

-- 테이블을 읽어야 하는 쿼리 (updated_at이 인덱스에 없음)
EXPLAIN ANALYZE
SELECT movie_id, rating, updated_at FROM user_rating WHERE movie_id = <인기영화ID>;
