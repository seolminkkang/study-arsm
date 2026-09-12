package study.integration;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT, properties={
    "lab.role=points","spring.datasource.url=jdbc:h2:mem:points;DB_CLOSE_DELAY=-1",
    "spring.datasource.driver-class-name=org.h2.Driver"})
class PointsTest {
    @LocalServerPort int port;
    @Autowired JdbcTemplate db;
    @Autowired PointsController controller;
    HttpClient client=HttpClient.newHttpClient();
    @BeforeEach void reset() { db.update("DELETE FROM point_grants"); controller.configure(new PointsController.Fault(0,0,false)); }
    HttpResponse<String> post(String path,String body) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+path))
            .header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build(),
            HttpResponse.BodyHandlers.ofString());
    }
    @Test void startingCodeAllowsDuplicateGrants() throws Exception {
        assertThat(post("/grants","{\"reviewId\":\"same\"}").statusCode()).isEqualTo(200);
        post("/grants","{\"reviewId\":\"same\"}");
        assertThat(db.queryForObject("SELECT COUNT(*) FROM point_grants",Integer.class)).isEqualTo(2);
    }
    @Test void failureBeforeWriteDoesNotGrant() throws Exception {
        controller.configure(new PointsController.Fault(0,0,true));
        assertThat(post("/grants","{\"reviewId\":\"fail\"}").statusCode()).isEqualTo(503);
        assertThat(db.queryForObject("SELECT COUNT(*) FROM point_grants",Integer.class)).isZero();
    }
    @Test void delayedResponseDoesNotUndoCommittedGrant() throws Exception {
        controller.configure(new PointsController.Fault(0,1000,false));
        var future=client.sendAsync(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/grants"))
            .header("Content-Type","application/json")
            .POST(HttpRequest.BodyPublishers.ofString("{\"reviewId\":\"late\"}")).build(),HttpResponse.BodyHandlers.ofString());
        long deadline=System.nanoTime()+Duration.ofSeconds(3).toNanos();
        while(db.queryForObject("SELECT COUNT(*) FROM point_grants",Integer.class)==0 && System.nanoTime()<deadline) Thread.sleep(10);
        assertThat(db.queryForObject("SELECT COUNT(*) FROM point_grants",Integer.class)).isEqualTo(1);
        assertThat(future.isDone()).isFalse();
        assertThat(future.get().statusCode()).isEqualTo(200);
    }
    @Test void boundsAndRolesAreEnforced() throws Exception {
        assertThat(post("/control/fault","{\"beforeMs\":-1,\"afterMs\":0,\"fail\":false}").statusCode()).isEqualTo(400);
        assertThat(post("/reviews","{\"id\":\"x\",\"content\":\"x\"}").statusCode()).isEqualTo(404);
    }
}
