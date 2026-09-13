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
    private final LabQueue queue;
    private final java.util.concurrent.Semaphore slots=new java.util.concurrent.Semaphore(2);
    private final LabBreaker breaker=new LabBreaker();
    private volatile boolean relayPaused=true;
    private volatile String relayScope="";
    private final java.util.concurrent.ScheduledExecutorService relay=java.util.concurrent.Executors.newSingleThreadScheduledExecutor();
    private final AtomicBoolean paused = new AtomicBoolean(false);
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(
        1, 1, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<>(20));
    private static final Logger log = LoggerFactory.getLogger(ReviewController.class);

    ReviewController(JdbcTemplate db, PlatformTransactionManager tm, RestClient points, MeterRegistry metrics, LabQueue queue) {
        this.db=db; this.tx=new TransactionTemplate(tm); this.points=points; this.metrics=metrics; this.queue=queue;
        metrics.gauge("lab.async.queued", worker, w -> w.getQueue().size());
        metrics.gauge("lab.async.active", worker, ThreadPoolExecutor::getActiveCount);
        relay.scheduleWithFixedDelay(this::deliver,1,1,TimeUnit.SECONDS);
    }
    @PostMapping("/reviews")
    Map<String,Object> create(@RequestBody Review review,
            @RequestParam(defaultValue="sync") String mode,
            @RequestHeader(value="X-Attempt-Id", defaultValue="manual") String attempt) {
        if(review.id()==null || !review.id().matches("[A-Za-z0-9_-]{1,100}") ||
           review.content()==null || review.content().length()>1000 ||
           !java.util.Set.of("sync","fresh","async","outside","guarded","circuit","idempotent","outbox","broker").contains(mode))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "id/content/mode 확인");
        if(mode.equals("outside") || mode.equals("guarded") || mode.equals("circuit")) {
            boolean limited=!mode.equals("outside");
            if(limited && !slots.tryAcquire()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"bulkhead full");
            boolean admitted=false;
            try {
                if(mode.equals("circuit") && !breaker.allow())
                    throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"circuit open");
                admitted=true;
                // HTTP 대기를 DB 트랜잭션 밖으로 이동. 원격 지급 후 로컬 실패 위험은 여전히 남는다.
                grant(review.id(),attempt,true);
                if(mode.equals("circuit")) breaker.success();
                tx.executeWithoutResult(s -> insert(review));
            } catch(org.springframework.web.client.RestClientException e) {
                if(mode.equals("circuit") && admitted) breaker.failure();
                throw e;
            } finally { if(limited) slots.release(); }
        } else if(mode.equals("outbox") || mode.equals("broker")) {
            tx.executeWithoutResult(s -> {
                insert(review);
                db.update("INSERT INTO outbox(review_id,channel) VALUES (?,?)",review.id(),mode.equals("broker")?"BROKER":"HTTP");
            });
        } else if(mode.equals("sync") || mode.equals("fresh") || mode.equals("idempotent")) {
            // 실습 1: 외부 호출 동안 DB 연결을 점유하는 시작 코드. 정답 구현이 아니다.
            tx.executeWithoutResult(s -> { insert(review); grant(review.id(), attempt,mode.equals("idempotent"),mode.equals("fresh")); });
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
        return Map.of("reviewId",review.id(),"mode",mode,"pointsCompleted",java.util.Set.of("sync","fresh","idempotent","outside","guarded","circuit").contains(mode));
    }
    private void insert(Review r) {
        db.update("INSERT INTO reviews(id,content) VALUES (?,?)", r.id(), r.content());
    }
    private void grant(String id, String attempt) {
        grant(id,attempt,false);
    }
    private void grant(String id, String attempt, boolean idempotent) {
        grant(id,attempt,idempotent,false);
    }
    private void grant(String id, String attempt, boolean idempotent, boolean close) {
        metrics.counter("lab.points.attempts").increment();
        log.info("points_start reviewId={} attempt={}",id,attempt);
        var request=points.post().uri("/grants").header("X-Attempt-Id",attempt).header("X-Idempotent",String.valueOf(idempotent));
        if(close) request.header("Connection","close"); // HTTP/1.1 비교 실험에서만 재사용을 끈다.
        request.body(Map.of("reviewId",id)).retrieve().toBodilessEntity();
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
    @GetMapping("/control/solutions")
    Map<String,Object> solutions() {
        return Map.of("breaker",breaker.state(),"availableSlots",slots.availablePermits(),"relayPaused",relayPaused,
            "outbox",db.queryForList("SELECT * FROM outbox ORDER BY review_id"));
    }
    @PostMapping("/control/relay")
    Map<String,Object> relay(@RequestParam boolean paused, @RequestParam(defaultValue="") String scope) {
        if(!scope.isEmpty()) {
            if(!scope.matches("[A-Za-z0-9-]{1,80}")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"scope 확인");
            relayScope=scope;
        }
        if(!paused && relayScope.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"실습 세션 scope 필요");
        relayPaused=paused; return solutions();
    }
    @PostMapping("/control/breaker-reset")
    Map<String,Object> resetBreaker() { breaker.success(); return solutions(); }
    private void deliver() {
        if(relayPaused) return;
        try { deliverPending(); } catch(Exception e) { log.warn("relay retry later: {}",e.toString()); }
    }
    private void deliverPending() {
        // 단일 A / 단일 전달자 실습. 다중 인스턴스에는 행 선점·리스·순서 설계가 추가로 필요하다.
        for(var row:db.queryForList("SELECT * FROM outbox WHERE status='WAITING' AND review_id LIKE ? ORDER BY review_id LIMIT 20",relayScope+"-%")) {
            if(relayPaused) break;
            String id=(String)row.get("review_id");
            try {
                db.update("UPDATE outbox SET attempts=attempts+1 WHERE review_id=?",id);
                if("BROKER".equals(row.get("channel"))) queue.publish(id);
                else grant(id,"outbox",true);
                db.update("UPDATE outbox SET status='DONE' WHERE review_id=?",id);
            } catch(Exception e) {
                log.warn("outbox_pending reviewId={} error={}",id,e.toString());
                break; // 1초 뒤 재시도. 실패 원인별 분류·상한·DLQ는 운영 시 추가 필요.
            }
        }
    }
    @PreDestroy void stop() { worker.shutdownNow(); relay.shutdownNow(); }
}
