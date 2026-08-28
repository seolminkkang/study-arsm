-- 99_cleanup.sql
-- 실험 중 원래 스키마(01_schema.sql)에 없던 칼럼/인덱스를 덧붙인 것들을 되돌린다.
-- lab/README.md "데이터 초기화" 참고. IF EXISTS로 감싸 몇 번을 실행해도 안전하다.

-- B-1. 타입이 다른 칼럼 조인 실습용 (vault/sessions/001-plan.md B-1)
DROP INDEX IF EXISTS idx_rating_movie_str;
ALTER TABLE user_rating DROP COLUMN IF EXISTS movie_id_str;

-- B-4. 컬럼 순서 뒤집은 실습용 인덱스 (vault/sessions/001-plan.md B-4)
DROP INDEX IF EXISTS idx_test_reversed;

-- A-2 ⑦. 통계 미리 집계 실습용 (vault/sessions/001-plan.md A-2)
ALTER TABLE movies DROP COLUMN IF EXISTS rating_count;
ALTER TABLE movies DROP COLUMN IF EXISTS rating_sum;

ANALYZE user_rating;
ANALYZE movies;
