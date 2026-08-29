package lab;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * JPA가 아니라 JdbcTemplate으로 raw SQL을 직접 쓴다.
 *
 * 엔티티를 만들면 파일이 늘고, 무엇보다 Hibernate가 실제로 날리는 SQL이
 * 여기 적힌 것과 달라질 수 있다. 그러면 psql에서 EXPLAIN한 쿼리와
 * 앱이 실행한 쿼리가 다른 것이 되어 실험이 성립하지 않는다.
 * 여기 있는 문자열이 곧 DB가 받는 문자열이어야 한다.
 *
 * 반환 타입도 DTO 없이 Map 그대로 둔다.
 */
@Repository
public class LabRepository {

    private final JdbcTemplate jdbc;

    public LabRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** 오프셋 페이징. offset이 커질수록 앞의 행을 세면서 버리는 비용이 늘어난다. */
    public List<Map<String, Object>> moviesByOffset(int limit, int offset) {
        return jdbc.queryForList("""
                SELECT movie_id, title, release_date, vote_count
                FROM movies
                ORDER BY movie_id
                LIMIT ? OFFSET ?
                """, limit, offset);
    }

    /** 커서 페이징. 앞을 세지 않고 인덱스에서 바로 시작 위치를 찾는다. */
    public List<Map<String, Object>> moviesByCursor(long cursorId, int limit) {
        return jdbc.queryForList("""
                SELECT movie_id, title, release_date, vote_count
                FROM movies
                WHERE movie_id > ?
                ORDER BY movie_id
                LIMIT ?
                """, cursorId, limit);
    }

    /**
     * 복합 인덱스 (user_id, updated_at DESC) 와 선택도 실험용.
     * LIMIT을 걸지 않는다 — 헤비 유저와 라이트 유저의 반환 행 수 차이가
     * 이 실험의 관측 대상이라 LIMIT으로 덮으면 안 된다.
     */
    public List<Map<String, Object>> ratingsByUserAndRange(
            long userId, OffsetDateTime from, OffsetDateTime to) {
        return jdbc.queryForList("""
                SELECT user_id, movie_id, rating, updated_at
                FROM user_rating
                WHERE user_id = ? AND updated_at >= ? AND updated_at < ?
                ORDER BY updated_at DESC
                """, userId, from, to);
    }

    /** A-1 ①: 특정 유저 안에서 오프셋을 키운다. */
    public List<Map<String, Object>> ratingsByUserOffset(long userId, int limit, int offset) {
        return jdbc.queryForList("""
                SELECT user_id, movie_id, rating, updated_at
                FROM user_rating
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """, userId, limit, offset);
    }

    /** A-1 ①: userId 없이 전체 목록 기준으로 오프셋을 크게 잡는 경우. */
    public List<Map<String, Object>> ratingsByOffset(int limit, int offset) {
        return jdbc.queryForList("""
                SELECT user_id, movie_id, rating, updated_at
                FROM user_rating
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """, limit, offset);
    }

    /** A-2 ⑦ before: 조회 시점에 센다. 데이터가 많아질수록 느려진다. */
    public Map<String, Object> movieStats(long movieId) {
        return jdbc.queryForMap("""
                SELECT count(*) AS rating_count, avg(rating) AS rating_avg
                FROM user_rating
                WHERE movie_id = ?
                """, movieId);
    }
}
