-- 04_indexes.sql
-- 실험 기준(baseline) 인덱스. B급/A급 실험 중에 이 위에서 걸었다 뺐다 한다.
-- (vault/sessions/001-plan.md B-3, B-4 전제조건)

CREATE INDEX IF NOT EXISTS idx_user_rating__movie_rating
    ON user_rating (movie_id, rating);

CREATE INDEX IF NOT EXISTS idx_user_rating__user_updated
    ON user_rating (user_id, updated_at DESC);

ANALYZE user_rating;
