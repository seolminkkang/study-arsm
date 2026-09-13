package study.integration;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class SolutionsTest {
    @Test void breakerBlocksAfterThreeFailuresAndRecoversByOneProbe() throws Exception {
        var breaker=new LabBreaker();
        for(int i=0;i<3;i++) { assertThat(breaker.allow()).isTrue(); breaker.failure(); }
        assertThat(breaker.state()).isEqualTo("OPEN");
        assertThat(breaker.allow()).isFalse();
        Thread.sleep(3050);
        assertThat(breaker.allow()).isTrue();
        assertThat(breaker.state()).isEqualTo("HALF_OPEN");
        assertThat(breaker.allow()).isFalse();
        breaker.success();
        assertThat(breaker.state()).isEqualTo("CLOSED");
    }
}
