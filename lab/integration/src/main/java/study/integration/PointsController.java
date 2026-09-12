package study.integration;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
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
    record Fault(int beforeMs, int afterMs, boolean fail) {}
    record Grant(String reviewId) {}
    private volatile Fault fault = new Fault(0,0,false);
    private final AtomicInteger active=new AtomicInteger();
    private final JdbcTemplate db;
    private final MeterRegistry metrics;
    private static final Logger log=LoggerFactory.getLogger(PointsController.class);
    PointsController(JdbcTemplate db, MeterRegistry metrics) {
        this.db=db; this.metrics=metrics;
        metrics.gauge("lab.points.active",active);
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
        Fault f=fault;
        active.incrementAndGet();
        metrics.counter("lab.points.received").increment();
        try {
            log.info("received reviewId={} attempt={} remote={}:{}",g.reviewId(),
                request.getHeader("X-Attempt-Id"),request.getRemoteAddr(),request.getRemotePort());
            Thread.sleep(f.beforeMs());
            if(f.fail()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"injected failure");
            // TODO 실습 2: 동일 reviewId의 중복 지급을 막는 기준과 원자적 처리를 직접 구현.
            db.update("INSERT INTO point_grants(review_id,amount) VALUES (?,100)",g.reviewId());
            metrics.counter("lab.points.applied").increment();
            log.info("applied reviewId={}",g.reviewId());
            Thread.sleep(f.afterMs()); // DB 커밋 후 응답만 늦춘다.
            return Map.of("reviewId",g.reviewId(),"amount",100);
        } finally { active.decrementAndGet(); }
    }
    @GetMapping("/grants")
    List<Map<String,Object>> list() { return db.queryForList("SELECT * FROM point_grants ORDER BY id"); }
}
