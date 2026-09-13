package study.integration;

import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** 두 실제 HTTP 프로세스, 별도 장부. 호스트/DB 장애 격리까지 구현한 것은 아니다. */
@RestController
@ConditionalOnProperty(name="lab.role", havingValue="review")
class FailoverController {
    private final RestClient client;
    FailoverController(RestClient client) { this.client=client; }
    @PostMapping("/extension/failover")
    Map<String,Object> execute(@RequestBody Map<String,String> body,
                              @RequestParam(defaultValue="safe") String mode) {
        String id=body.get("id");
        if(id==null || !id.matches("[A-Za-z0-9_-]{1,100}") ||
           !java.util.Set.of("single","safe","unsafe").contains(mode))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"id/mode 확인");
        try {
            client.post().uri("/provider/grants").body(Map.of("reviewId",id)).retrieve().toBodilessEntity();
            return Map.of("outcome","CONFIRMED","provider","primary");
        } catch(RestClientException e) {
            boolean known=e instanceof RestClientResponseException r && r.getStatusCode().value()==503 &&
                r.getResponseHeaders()!=null && "true".equals(r.getResponseHeaders().getFirst("X-Lab-Not-Applied"));
            if(mode.equals("single")) return Map.of("outcome",known?"REJECTED":"UNKNOWN","provider","primary");
            if(!known && !mode.equals("unsafe"))
                return Map.of("outcome","UNKNOWN","provider","primary","next","주 서비스 결과 조회; 대체 지급 금지");
            client.post().uri("http://points-backup:8083/provider/grants")
                .body(Map.of("reviewId",id)).retrieve().toBodilessEntity();
            return Map.of("outcome","CONFIRMED","provider","backup","primaryKnownNotApplied",known);
        }
    }
}
