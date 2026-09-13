package study.integration;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.nio.charset.StandardCharsets;
import jakarta.annotation.PreDestroy;
import jakarta.servlet.http.HttpServletRequest;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

@RestController
@ConditionalOnProperty(name="lab.role", havingValue="points")
class PointsController {
    @org.springframework.beans.factory.annotation.Value("${LAB_PROVIDER:primary}")
    private String provider="primary";
    private String ledger() { return "backup".equals(provider)?"backup_grants":"point_grants"; }
    record Fault(int beforeMs, int afterMs, boolean fail) {}
    record Grant(String reviewId) {}
    private volatile Fault fault = new Fault(0,0,false);
    private final AtomicInteger active=new AtomicInteger();
    private final JdbcTemplate db;
    private final MeterRegistry metrics;
    private final LabQueue queue;
    private volatile boolean consumerPaused=true;
    private final java.util.concurrent.ScheduledExecutorService consumer=Executors.newSingleThreadScheduledExecutor();
    private static final Logger log=LoggerFactory.getLogger(PointsController.class);
    PointsController(JdbcTemplate db, MeterRegistry metrics, LabQueue queue) {
        this.db=db; this.metrics=metrics; this.queue=queue;
        metrics.gauge("lab.points.active",active);
        consumer.scheduleWithFixedDelay(this::consume,1,1,TimeUnit.SECONDS);
    }
    @PostMapping("/control/fault")
    Fault configure(@RequestBody Fault f) {
        if(f.beforeMs()<0 || f.afterMs()<0 || f.beforeMs()>30000 || f.afterMs()>30000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"delay must be 0..30000 ms");
        return fault=f;
    }
    @GetMapping("/control/fault") Fault fault() { return fault; }
    @PostMapping("/grants")
    Map<String,Object> grant(@RequestBody Grant g, HttpServletRequest request) throws InterruptedException {
        if(g.reviewId()==null || !g.reviewId().matches("[A-Za-z0-9_-]{1,100}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"reviewId 확인");
        log.info("received reviewId={} attempt={} remote={}:{}",g.reviewId(),
                request.getHeader("X-Attempt-Id"),request.getRemoteAddr(),request.getRemotePort());
        return apply(g.reviewId(),"true".equals(request.getHeader("X-Idempotent")));
    }
    Map<String,Object> apply(String id, boolean idempotent) throws InterruptedException {
        Fault f=fault;
        active.incrementAndGet();
        metrics.counter("lab.points.received").increment();
        try {
            Thread.sleep(f.beforeMs());
            if(f.fail()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"injected failure");
            // 업무 키의 UNIQUE 제약으로 동시 요청도 원자적으로 중복 방지한다.
            int changed=idempotent
                ? db.update("INSERT INTO "+ledger()+"(review_id,amount,dedupe_key) VALUES (?,100,?) ON CONFLICT (dedupe_key) DO NOTHING",id,id)
                : db.update("INSERT INTO "+ledger()+"(review_id,amount) VALUES (?,100)",id);
            if(changed>0) metrics.counter("lab.points.applied").increment();
            log.info("applied reviewId={} changed={}",id,changed);
            Thread.sleep(f.afterMs()); // DB 커밋 후 응답만 늦춘다.
            return Map.of("reviewId",id,"amount",100,"duplicate",changed==0);
        } finally { active.decrementAndGet(); }
    }
    @GetMapping("/grants")
    List<Map<String,Object>> list() { return db.queryForList("SELECT * FROM "+ledger()+" ORDER BY id"); }
    // 이 교육용 계약만 '미처리 확정'을 알린다. 일반 HTTP 503을 미처리로 가정하면 안 된다.
    @PostMapping("/provider/grants")
    org.springframework.http.ResponseEntity<?> providerGrant(@RequestBody Grant g) throws InterruptedException {
        if(g.reviewId()==null || !g.reviewId().matches("[A-Za-z0-9_-]{1,100}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"reviewId 확인");
        try { return org.springframework.http.ResponseEntity.ok(apply(g.reviewId(),true)); }
        catch(ResponseStatusException e) {
            if(e.getStatusCode().value()!=503) throw e;
            return org.springframework.http.ResponseEntity.status(503)
                .header("X-Lab-Not-Applied","true").body(Map.of("applied",false,"provider",provider));
        }
    }
    @PostMapping("/control/consumer")
    Map<String,Object> consumer(@RequestParam boolean paused) throws Exception {
        consumerPaused=paused; return consumer();
    }
    @GetMapping("/control/consumer")
    Map<String,Object> consumer() throws Exception { return Map.of("paused",consumerPaused,"ready",queue.pending(),"active",active.get()); }
    private void consume() {
        if(consumerPaused) return;
        try {
            var delivery=queue.get();
            if(delivery==null) return;
            long tag=delivery.getEnvelope().getDeliveryTag();
            try {
                apply(new String(delivery.getBody(),StandardCharsets.UTF_8),true);
                queue.ack(tag); // 지급 DB 커밋 뒤 ACK. 사이에 죽으면 재전달되므로 멱등 처리 필요.
            } catch(Exception e) { queue.retry(tag); }
        } catch(Exception e) { log.warn("consumer retry later: {}",e.toString()); }
    }
    @PreDestroy void stop() { consumer.shutdownNow(); }
}
