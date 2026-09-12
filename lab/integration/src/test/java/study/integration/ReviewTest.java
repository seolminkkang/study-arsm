package study.integration;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.Set;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(properties={"lab.role=review","spring.datasource.url=jdbc:h2:mem:review;DB_CLOSE_DELAY=-1",
    "spring.datasource.driver-class-name=org.h2.Driver","lab.read-ms=100","lab.acquire-ms=100"})
class ReviewTest {
    static HttpServer server;
    static ExecutorService executor=Executors.newCachedThreadPool();
    static AtomicInteger applied=new AtomicInteger();
    static Set<Integer> ports=ConcurrentHashMap.newKeySet();
    static volatile int delay=0;
    static {
        try {
            server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
            server.setExecutor(executor);
            server.createContext("/grants", exchange -> {
                exchange.getRequestBody().readAllBytes();
                ports.add(exchange.getRemoteAddress().getPort());
                applied.incrementAndGet();
                try {
                    Thread.sleep(delay);
                    byte[] body="{}".getBytes(StandardCharsets.UTF_8);
                    exchange.sendResponseHeaders(200,body.length);
                    exchange.getResponseBody().write(body);
                } catch(InterruptedException e) { Thread.currentThread().interrupt(); }
                finally { exchange.close(); }
            });
            server.start();
        } catch(Exception e) { throw new RuntimeException(e); }
    }
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("lab.points-url",()->"http://127.0.0.1:"+server.getAddress().getPort());
    }
    @Autowired ReviewController review;
    @Autowired JdbcTemplate db;
    @BeforeEach void reset() { db.update("DELETE FROM reviews"); delay=0; applied.set(0); ports.clear(); }
    @AfterAll static void stopServer() { server.stop(0); executor.shutdownNow(); }
    @Test void sequentialRequestsReuseHttpConnection() {
        review.create(new ReviewController.Review("one","a"),"sync","1");
        review.create(new ReviewController.Review("two","b"),"sync","2");
        assertThat(applied.get()).isEqualTo(2);
        assertThat(ports).hasSize(1);
        assertThat(review.list()).hasSize(2);
    }
    @Test void timeoutRollsBackReviewButNotRemoteGrantAndRetryDuplicates() {
        delay=400;
        assertThatThrownBy(()->review.create(new ReviewController.Review("retry","a"),"sync","1"))
            .isInstanceOf(org.springframework.web.client.ResourceAccessException.class);
        assertThat(review.list()).isEmpty();
        assertThat(applied.get()).isEqualTo(1);
        delay=0;
        review.create(new ReviewController.Review("retry","a"),"sync","2");
        assertThat(applied.get()).isEqualTo(2);
        assertThat(review.list()).hasSize(1);
    }
    @Test void pausedAsyncWorkReturnsBeforeGrant() throws Exception {
        review.pause(true);
        try {
            var result=review.create(new ReviewController.Review("async","a"),"async","1");
            assertThat(result.get("pointsCompleted")).isEqualTo(false);
            assertThat(review.list()).hasSize(1);
            assertThat(applied.get()).isZero();
        } finally { review.pause(false); }
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while((applied.get()==0 || (int)review.worker().get("active")>0) && System.nanoTime()<deadline) Thread.sleep(10);
        assertThat(applied.get()).isEqualTo(1);
    }
}
