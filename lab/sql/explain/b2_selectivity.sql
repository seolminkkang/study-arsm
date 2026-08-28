-- B-2. 선택도
-- 출처: vault/sessions/001-plan.md B-2
--
-- 보여줄 것: 같은 쿼리인데 조회 대상(헤비 유저 vs 라이트 유저)에 따라
-- 실행계획이 달라진다.
--
-- <헤비ID>, <라이트ID>는 lab/sql/00_find_test_ids.sql로 찾아서 채운다.
-- 값은 vault/sessions/001-plan.md 공통 조건 블록에 기록해둔다.
--
-- EXPLAIN에서 볼 지점:
--   - rows 추정치와 실제값(actual rows)의 차이
--   - 인덱스 스캔 vs 시퀀셜 스캔으로 전환되는 지점
--
-- 시딩을 균등 분포로 하면 이 실험이 통째로 죽는다.
-- 누구를 조회하든 건수가 같아지기 때문이다 (lab/README.md ③ 참고).

-- 헤비 유저 (5,000건)
EXPLAIN ANALYZE
SELECT movie_id, rating FROM user_rating WHERE user_id = <헤비ID>;

-- 라이트 유저 (17건)
EXPLAIN ANALYZE
SELECT movie_id, rating FROM user_rating WHERE user_id = <라이트ID>;
