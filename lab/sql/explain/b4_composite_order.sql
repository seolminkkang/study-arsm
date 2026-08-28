-- B-4. 단일 vs 복합 인덱스 (컬럼 순서)
-- 출처: vault/sessions/001-plan.md B-4
--
-- 보여줄 것: 같은 두 칼럼이라도 인덱스 순서에 따라 실행계획이 다르다.
--
-- <헤비ID>는 lab/sql/00_find_test_ids.sql로 찾아서 채운다.
-- 값은 vault/sessions/001-plan.md 공통 조건 블록에 기록해둔다.
--
-- EXPLAIN에서 볼 지점:
--   - 세 조건(기준 인덱스 / 인덱스 없음 / 순서 뒤집은 인덱스) 각각의
--     실행 시간(Execution Time)과 스캔 행 수(actual rows)
--
-- 정리: 실험 끝나면 idx_test_reversed는 lab/sql/99_cleanup.sql로 지우고,
-- 원래 (user_id, updated_at DESC) 인덱스는 lab/sql/04_indexes.sql로 복구한다.

-- 기준: (user_id, updated_at DESC) 인덱스 있는 상태
EXPLAIN ANALYZE
SELECT * FROM user_rating
WHERE user_id = <헤비ID> AND updated_at >= '2026-01-01'
ORDER BY updated_at DESC LIMIT 100;

-- 인덱스를 지우고 다시
DROP INDEX idx_user_rating__user_updated;
ANALYZE user_rating;
-- 같은 쿼리 재실행

-- 순서를 뒤집어서
CREATE INDEX idx_test_reversed ON user_rating(updated_at DESC, user_id);
ANALYZE user_rating;
-- 같은 쿼리 재실행
