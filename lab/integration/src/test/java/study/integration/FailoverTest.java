package study.integration;

import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.http.HttpStatus;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;
import static org.junit.jupiter.api.Assertions.*;
import java.util.Map;

class FailoverTest {
    @Test void onlyContractConfirmedRejectionAllowsFallback() {
        var builder=RestClient.builder().baseUrl("http://primary");
        var server=MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://primary/provider/grants"))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE).header("X-Lab-Not-Applied","true"));
        server.expect(requestTo("http://points-backup:8083/provider/grants")).andRespond(withSuccess());
        assertEquals("backup",new FailoverController(builder.build()).execute(Map.of("id","test"),"safe").get("provider"));
        server.verify();
    }
    @Test void generic503DoesNotProveNoSideEffect() {
        var builder=RestClient.builder().baseUrl("http://primary");
        var server=MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://primary/provider/grants")).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals("UNKNOWN",new FailoverController(builder.build()).execute(Map.of("id","test"),"safe").get("outcome"));
        server.verify();
    }
    @Test void timeoutDoesNotFallback() {
        var builder=RestClient.builder().baseUrl("http://primary");
        var server=MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://primary/provider/grants")).andRespond(request->{throw new java.net.SocketTimeoutException("late");});
        assertEquals("UNKNOWN",new FailoverController(builder.build()).execute(Map.of("id","test"),"safe").get("outcome"));
        server.verify();
    }
}
