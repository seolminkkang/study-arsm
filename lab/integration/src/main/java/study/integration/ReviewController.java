package study.integration;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import jakarta.annotation.PreDestroy;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

@RestController
@ConditionalOnProperty(name="lab.role", havingValue="review")
class ReviewController {
    record Review(String id, String content) {}
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final RestClient points;
    private final MeterRegistry metrics;
    private final AtomicBoolean paused = new AtomicBoolean(false);
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(
        1, 1, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<>(20));
    private static final Logger log = LoggerFactory.getLogger(ReviewController.class);

    ReviewController(JdbcTemplate db, PlatformTransactionManager tm, RestClient points, MeterRegistry metrics) {
        this.db=db; this.tx=new TransactionTemplate(tm); this.points=points; this.metrics=metrics;
        metrics.gauge("lab.async.queued", worker, w -> w.getQueue().size());
        metrics.gauge("lab.async.active", worker, ThreadPoolExecutor::getActiveCount);
    }
    @PostMapping("/reviews")
    Map<String,Object> create(@RequestBody Review review,
            @RequestParam(defaultValue="sync") String mode,
            @RequestHeader(value="X-Attempt-Id", defaultValue="manual") String attempt) {
        if(review.id()==null || !review.id().matches("[A-Za-z0-9_-]{1,100}") ||
           review.content()==null || review.content().length()>1000 ||
           !(mode.equals("sync") || mode.equals("async")))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "id/content/mode 확인");
        if(mode.equals("sync")) {
            // 실습 1: 외부 호출 동안 DB 연결을 점유하는 시작 코드. 정답 구현이 아니다.
            tx.executeWithoutResult(s -> { insert(review); grant(review.id(), attempt); });
        } else {
            // 비교용 출발점: 커밋 이후 메모리에만 작업을 맡긴다. 내구성은 없다.
            tx.executeWithoutResult(s -> insert(review));
            try {
                worker.execute(() -> {
                    try {
                        while(paused.get()) Thread.sleep(25);
                        grant(review.id(), attempt);
                    } catch (Exception e) {
                        metrics.counter("lab.async.failed").increment();
                        log.warn("async_failed reviewId={} attempt={} type={}", review.id(), attempt, e.getClass().getSimpleName());
                    }
                });
            } catch(java.util.concurrent.RejectedExecutionException e) {
                // 리뷰는 이미 커밋되었다. 이 틈도 후속 실습의 대상이다.
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "worker full; review already saved");
            }
        }
        return Map.of("reviewId",review.id(),"mode",mode,"pointsCompleted",mode.equals("sync"));
    }
    private void insert(Review r) {
        db.update("INSERT INTO reviews(id,content) VALUES (?,?)", r.id(), r.content());
    }
    private void grant(String id, String attempt) {
        metrics.counter("lab.points.attempts").increment();
        log.info("points_start reviewId={} attempt={}",id,attempt);
        points.post().uri("/grants").header("X-Attempt-Id",attempt)
            .body(Map.of("reviewId",id)).retrieve().toBodilessEntity();
        log.info("points_response reviewId={} attempt={}",id,attempt);
    }
    @GetMapping("/reviews")
    List<Map<String,Object>> list() { return db.queryForList("SELECT * FROM reviews ORDER BY id"); }
    @PostMapping("/control/worker")
    Map<String,Object> pause(@RequestParam boolean paused) {
        this.paused.set(paused); return worker();
    }
    @GetMapping("/control/worker")
    Map<String,Object> worker() {
        return Map.of("paused",paused.get(),"active",worker.getActiveCount(),"queued",worker.getQueue().size());
    }
    @PreDestroy void stop() { worker.shutdownNow(); }
}
