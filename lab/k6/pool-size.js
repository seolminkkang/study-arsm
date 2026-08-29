// pool-size.js — A-1 ③④ 커넥션 풀 크기를 바꿔가며 포화점 관측
//
// ⚠ 이 파일은 의도적 복잡도다. 단순화하지 마.
//   (CLAUDE.md ponytail 섹션 — lab/k6/ 는 ponytail 끄고 작업한다)
//
//   1. 워밍업 60초는 JVM JIT 때문에 필수다. 초반 수십 초는 인터프리터로 돌아서
//      실제보다 몇 배 느리다. 이 구간을 빼면 모든 측정이 거짓말이 된다.
//
//   2. 도착률(arrival-rate) 기반이다. VU 기반으로 바꾸지 마.
//      VU 기반은 서버가 느려지면 부하도 같이 줄어들어 포화점이 안 보인다.
//
// 이 실험의 핵심은 "산수로 예측하고 실측과 대조하기"다(001-plan.md A-1 ②).
//
//   최대 TPS = 커넥션 풀 크기 / 쿼리 실행 시간(초)
//
// 2026-08-29 리허설 실측: /lab/ratings?offset=4900000 은 유휴 상태 단건 1.16초.
// 산수를 그대로 적용하면 이렇게 된다.
//
//   풀  2  ->  2 / 1.16 =  1.7 TPS
//   풀 10  -> 10 / 1.16 =  8.6 TPS
//   풀 50  -> 50 / 1.16 = 43.1 TPS
//
// 이 값을 노트에 크게 적어두고 실측과 대조한다. 이 계산은 반드시 틀린다.
//
// 얼마나 틀리는지 미리 재봤다 (6건 동시 요청, 풀만 바꿔가며):
//
//   풀  2  ->  8.26초  ->  0.73 TPS   (예측 1.7의 43%)
//   풀 10  -> 10.39초  ->  0.58 TPS   (예측 8.6의 7%)
//   풀 50  -> 10.94초  ->  0.55 TPS   (예측 43.1의 1%)
//
// 풀을 25배 키웠는데 처리량이 늘기는커녕 약간 줄었다.
// DB가 cpus:2 라서 초당 2코어어치가 상한이고, 이 쿼리는 CPU를 태운다.
// 풀을 키우면 동시에 들어간 쿼리들이 같은 2코어를 나눠 쓸 뿐이라
// 처리량은 그대로고 각자가 느려진다.
//
// 이게 책이 말한 "DB CPU가 이미 높으면 풀을 늘리는 게 아니라 줄여야 한다"다.
// 둘 다 "풀을 키우면 빨라진다"고 예측할 가능성이 높은데 정반대가 나온다.
//
// 처리량(TPS)만 보지 말고 p95와 hikaricp_connections_pending을 같이 본다.
// 처리량이 같아도 풀이 클수록 p95가 나빠지는 게 이 실험의 진짜 관측 대상이다.
//
// 실행 — 풀 크기는 스크립트가 아니라 앱 설정이다.
//   lab/app/src/main/resources/application.yml 의
//     spring.datasource.hikari.maximum-pool-size 를 2 / 10 / 50 으로 바꾸고
//   앱을 재시작한 뒤(약 5초) 매번 exp 커밋을 남긴다.
//
//   k6 run -e POOL=2  -e TARGET_HOST=localhost:8080 pool-size.js
//   k6 run -e POOL=10 -e TARGET_HOST=localhost:8080 pool-size.js
//   k6 run -e POOL=50 -e TARGET_HOST=localhost:8080 pool-size.js
//
//   POOL은 결과 태그용일 뿐 서버를 바꾸지 않는다. 실제 풀 크기와 맞춰 적는다.
//   리허설(한 대)은 부하를 낮춘다:  -e PROFILE=rehearsal

import http from 'k6/http';
import { check } from 'k6';

const HOST = __ENV.TARGET_HOST || 'localhost:8080';
const POOL = __ENV.POOL || 'unknown';
const PROFILE = __ENV.PROFILE || 'session';

// README ⑦의 50 → 800 rps는 여기 못 쓴다.
// 실측 지속 가능 처리량이 0.55~0.73 TPS다. 50 rps를 부으면 첫 단계에서
// 즉시 무너져서 "어디서 꺾이는지"가 아니라 "처음부터 안 된다"만 보인다.
//
// 1 rps는 어느 풀이든 소화하고, 2 rps부터 전부 포화된다.
// 그 사이에서 꺾이는 걸 봐야 하므로 이 구간을 천천히 지난다.
//
// 처음에 6ms짜리 가벼운 쿼리로 50~100 rps를 돌려봤는데
// p95 4ms, VU 최대 1개로 아무 일도 안 일어났다(2026-08-29 파일럿).
// 100 rps × 6ms = 동시성 0.6이라 풀 2로도 남아돈다 — 풀이 변수가 안 됐다.
// 풀 크기를 변수로 만들려면 동시성이 풀 크기를 넘어야 하고,
// 그러려면 이 무거운 쿼리를 써야 한다.
const STAGES = PROFILE === 'rehearsal'
  ? [ { target: 1, duration: '60s' },
      { target: 2, duration: '60s' },
      { target: 4, duration: '60s' } ]
  : [ { target: 1, duration: '60s' },
      { target: 2, duration: '60s' },
      { target: 4, duration: '60s' },
      { target: 8, duration: '60s' } ];

const url = `http://${HOST}/lab/ratings?offset=4900000&limit=10`;

export const options = {
  scenarios: {
    // JVM JIT 워밍업. 60초는 그대로 지키되 도착률은 낮춘다.
    // README ⑦의 20 rps로 워밍업하면 풀 2에서는 워밍업 구간부터 포화돼서
    // JIT 워밍업이 아니라 그냥 과부하 측정이 된다.
    // 실측 지속 가능치(0.55~0.73 TPS)와 비슷한 1 rps로 돈다.
    warmup: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 10,
      maxVUs: 200,
      tags: { phase: 'warmup' },
    },
    ramp: {
      executor: 'ramping-arrival-rate',
      startTime: '60s',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      // 서버가 느려질수록 같은 도착률 유지에 더 많은 VU가 필요하다.
      // 모자라면 dropped_iterations가 뜨는데 그건 서버 포화가 아니라 스크립트 문제다.
      maxVUs: 2000,
      stages: STAGES,
      tags: { phase: 'ramp' },
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.01'],
    'dropped_iterations': ['count<100'],
  },
};

export default function () {
  const res = http.get(url, {
    tags: { pool: POOL },
    timeout: '30s',
  });

  check(res, {
    'status 200': (r) => r.status === 200,
  });
}

// Grafana "A-1 한 화면" 을 같이 띄워놓고 본다.
// 하이라이트는 1번(TPS)이 안 오르는데 2번(p95)과 3번(pending)이 치솟는 순간이다.
// 그때 4번(DB CPU)이 200%에 붙어 있으면 "풀을 키워도 소용없는" 이유가 그것이다.
//
// 결과에서 볼 순서 (lab/README.md ⑦)
//   1. dropped_iterations — 0이 아니면 그 실험은 무효
//   2. 목표 rate vs 실제 http_reqs — 안 따라오는 지점이 포화점.
//      이 값을 위 산수(풀/쿼리시간)와 대조한다
//   3. http_req_waiting — duration이 아니라 이것. 순수 서버 처리 시간
//   4. p95 / p99. 평균은 무시
