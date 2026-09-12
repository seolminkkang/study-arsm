package study.integration;

import io.micrometer.core.instrument.MeterRegistry;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.core5.util.Timeout;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
@ConditionalOnProperty(name="lab.role", havingValue="review")
class HttpConfiguration {
    @Bean
    PoolingHttpClientConnectionManager pool(MeterRegistry registry,
            @Value("${lab.http-pool}") int size, @Value("${lab.connect-ms}") int connectMs) {
        var pool = PoolingHttpClientConnectionManagerBuilder.create()
            .setMaxConnTotal(size).setMaxConnPerRoute(size)
            .setDefaultConnectionConfig(ConnectionConfig.custom()
                .setConnectTimeout(Timeout.ofMilliseconds(connectMs)).build()).build();
        registry.gauge("lab.http.pool.leased", pool, p -> p.getTotalStats().getLeased());
        registry.gauge("lab.http.pool.available", pool, p -> p.getTotalStats().getAvailable());
        registry.gauge("lab.http.pool.pending", pool, p -> p.getTotalStats().getPending());
        registry.gauge("lab.http.pool.max", pool, p -> p.getTotalStats().getMax());
        return pool;
    }
    @Bean(destroyMethod="close")
    CloseableHttpClient httpClient(PoolingHttpClientConnectionManager pool) {
        // Apache classic client: HTTP/1.1. 숨은 자동 재시도는 꺼서 시도 횟수를 직접 센다.
        return HttpClients.custom().setConnectionManager(pool).disableAutomaticRetries().build();
    }
    @Bean
    RestClient pointsClient(CloseableHttpClient client,
            @Value("${lab.points-url}") String url,
            @Value("${lab.acquire-ms}") int acquireMs, @Value("${lab.read-ms}") int readMs) {
        var factory = new HttpComponentsClientHttpRequestFactory(client);
        factory.setConnectionRequestTimeout(acquireMs);
        factory.setReadTimeout(readMs);
        return RestClient.builder().baseUrl(url).requestFactory(factory).build();
    }
}
