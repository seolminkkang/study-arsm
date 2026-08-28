-- 00_find_test_ids.sql
-- B급 EXPLAIN 쿼리(explain/b2, b3, b4)와 A-1 실험에 쓰이는
-- <헤비ID>, <라이트ID>, <인기영화ID> 자리표시자의 실제 값을 찾는다.
--
-- 03_seed_ratings.sql로 시딩한 뒤 한 번 실행하고,
-- 찾은 값은 vault/sessions/001-plan.md의 "공통 조건" 블록에 적어둔다.
-- (매 회차 시딩 결과가 조금씩 달라질 수 있으므로 노트에 고정값으로 박아둔다)

-- 헤비 유저 상위 5명 (<헤비ID> 후보)
SELECT user_id, count(*) AS rating_count
FROM user_rating
GROUP BY user_id
ORDER BY rating_count DESC
LIMIT 5;

-- 라이트 유저 5명 (<라이트ID> 후보)
SELECT user_id, count(*) AS rating_count
FROM user_rating
GROUP BY user_id
ORDER BY rating_count ASC
LIMIT 5;

-- 평점이 많이 달린 영화 상위 5개 (<인기영화ID> 후보)
SELECT movie_id, count(*) AS rating_count
FROM user_rating
GROUP BY movie_id
ORDER BY rating_count DESC
LIMIT 5;

-- 평점이 적게 달린 영화 5개 (선택도 비교용 참고값)
SELECT movie_id, count(*) AS rating_count
FROM user_rating
GROUP BY movie_id
ORDER BY rating_count ASC
LIMIT 5;
