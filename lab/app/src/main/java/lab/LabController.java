package lab;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Service 계층 없이 리포지토리를 직접 부른다. DTO도 Mapper도 없다.
 * @ControllerAdvice도 두지 않는다 — 예외는 스프링 기본 처리에 맡긴다.
 *
 * userId는 토큰이 아니라 쿼리 파라미터로 받는다. 인증이 개입할 여지를 없앤다.
 */
@RestController
public class LabController {

    private final LabRepository repo;

    public LabController(LabRepository repo) {
        this.repo = repo;
    }

    /**
     * 오프셋 페이징과 커서 페이징을 같은 경로에서 받는다.
     * cursorId가 오면 커서, 없으면 오프셋. (lab/README.md ⑤ 표 1·2행)
     */
    @GetMapping("/lab/movies")
    public List<Map<String, Object>> movies(
            @RequestParam(required = false) Long cursorId,
            @RequestParam(defaultValue = "10") int limit,
            @RequestParam(defaultValue = "0") int offset) {
        return cursorId != null
                ? repo.moviesByCursor(cursorId, limit)
                : repo.moviesByOffset(limit, offset);
    }

    /**
     * from/to가 오면 기간 조회(복합 인덱스·선택도 실험, lab/README.md ⑤ 표 3행).
     * 없으면 오프셋 조회 — 001-plan.md A-1 ①이 쓰는 형태다.
     * userId도 없으면 전체 목록 기준 오프셋(A-1 ①의 offset=4900000 경우).
     */
    @GetMapping("/lab/ratings")
    public List<Map<String, Object>> ratings(
            @RequestParam(required = false) Long userId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime to,
            @RequestParam(defaultValue = "10") int limit,
            @RequestParam(defaultValue = "0") int offset) {
        if (userId != null && from != null && to != null) {
            return repo.ratingsByUserAndRange(userId, from, to);
        }
        return userId != null
                ? repo.ratingsByUserOffset(userId, limit, offset)
                : repo.ratingsByOffset(limit, offset);
    }

    /** count 집계. (lab/README.md ⑤ 표 4행) */
    @GetMapping("/lab/movies/{id}/stats")
    public Map<String, Object> movieStats(@PathVariable long id) {
        return repo.movieStats(id);
    }
}
