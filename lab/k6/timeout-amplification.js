// timeout-amplification.js — A-1 ⑤ 타임아웃 길이와 재시도 증폭
//
// ⚠ 이 파일은 의도적 복잡도다. 단순화하지 마.
//   (CLAUDE.md ponytail 섹션 — lab/k6/ 는 ponytail 끄고 작업한다)
//
//   1. 워밍업 60초는 JVM JIT 때문에 필수다. 이 구간을 빼면 측정이 거짓말이 된다.
//
//   2. 도착률(arrival-rate) 기반이다. VU 기반으로 바꾸면 이 실험 자체가 성립하지 않는다.
//      이 스크립트가 보여주려는 게 바로 "느려지면 부하가 오히려 늘어난다"인데,
//      VU 기반은 정반대로 느려지면 부하가 줄어든다. 재시도 증폭이 아예 안 보인다.
//
//   3. 아래 재시도 루프도 지우지 마. 이 실험의 주제 그 자체다.
//      책이 2장(커넥션 대기 시간)과 3장(쿼리 타임아웃)에서 두 번 말하는
//      유일한 주제다 — 저자가 제일 강조하고 싶은 것.
//
// 보여줄 것
//   조건 A (connection-timeout 30000): 요청이 30초까지 매달린다.
//     그 사이 사용자는 기다리다 취소하고 다시 누른다. 서버가 붙잡고 있는
//     요청 수가 눈덩이처럼 불어난다.
//   조건 B (connection-timeout 1000): 1초 만에 에러를 받는다.
//     빠르게 실패하니 재시도해도 동시 요청 수가 일정 수준에서 유지된다.
//
// 실행 — 타임아웃은 스크립트가 아니라 앱 설정이다.
//   lab/app/src/main/resources/application.yml 의
//     spring.datasource.hikari.connection-timeout 을 30000 / 1000 으로 바꾸고
//   앱을 재시작한 뒤 매번 exp 커밋을 남긴다.
//
//   k6 run -e COND=A -e TARGET_HOST=localhost:8080 timeout-amplification.js
//   k6 run -e COND=B -e TARGET_HOST=localhost:8080 timeout-amplification.js
//
//   재시도를 끄고 대조군을 보고 싶으면: -e RETRY=off
//   리허설(한 대)은 부하를 낮춘다:      -e PROFILE=rehearsal

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const HOST = __ENV.TARGET_HOST || 'localhost:8080';
const COND = __ENV.COND || 'unknown';
const PROFILE = __ENV.PROFILE || 'session';
const RETRY = (__ENV.RETRY || 'on') !== 'off';

// 사용자가 몇 초 기다리다 포기하고 다시 누르는지.
// 조건 A(서버 타임아웃 30초)에서는 사용자가 서버보다 먼저 포기한다.
// 그 차이가 증폭을 만든다 — 서버는 아직 첫 요청을 붙잡고 있는데
// 같은 사용자가 두 번째, 세 번째 요청을 더 보낸다.
const CLIENT_PATIENCE = __ENV.CLIENT_PATIENCE || '3s';
const MAX_RETRIES = parseInt(__ENV.MAX_RETRIES || '2', 10);

// 이 실험은 포화가 목적이다. 넘지 않으면 대기 자체가 안 생겨서 볼 게 없다.
//
// 지속 가능치는 2026-08-29 실측 기준 약 1.7 TPS다
// (DB가 cpus:2, offset=4900000 이 단건 1.16초 — 자세한 계산은 offset-vs-cursor.js 주석).
// 그 두세 배를 부어서 확실히 포화시킨다.
const STAGES = PROFILE === 'rehearsal'
  ? [ { target: 2, duration: '60s' },
      { target: 5, duration: '60s' } ]
  : [ { target: 2, duration: '60s' },
      { target: 5, duration: '60s' },
      { target: 10, duration: '60s' } ];

const url = `http://${HOST}/lab/ratings?offset=4900000&limit=10`;

// 증폭을 숫자로 잡는다.
// attempts / iterations 가 곧 증폭 배수다. 재시도가 없으면 1.0에 머문다.
const attempts = new Counter('req_attempts');       // 실제로 보낸 요청 수
const givenUp = new Counter('req_given_up');        // 재시도까지 다 실패한 수
const userWait = new Trend('user_total_wait', true); // 사용자가 최종 응답까지 기다린 총 시간

export const options = {
  scenarios: {
    // JVM JIT 워밍업. 이 구간 결과는 버린다.
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
      preAllocatedVUs: 100,
      // 조건 A에서는 요청이 30초씩 매달려서 VU가 급격히 쌓인다.
      // 여기가 모자라면 dropped_iterations가 뜨고, 그러면 증폭을 측정한 게
      // 아니라 k6가 부하를 못 만든 게 된다. 크게 잡는다.
      maxVUs: 3000,
      stages: STAGES,
      tags: { phase: 'ramp' },
    },
  },
  thresholds: {
    // 이 실험은 에러가 나는 게 정상이다(조건 B는 특히).
    // 다른 스크립트와 달리 http_req_failed 임계값을 걸지 않는다.
    'dropped_iterations': ['count<100'],
  },
};

export default function () {
  const started = Date.now();
  let ok = false;

  // 사용자 한 명의 행동을 흉내낸다:
  // 참을성(CLIENT_PATIENCE) 안에 응답이 없으면 취소하고 다시 누른다.
  for (let i = 0; i <= (RETRY ? MAX_RETRIES : 0); i++) {
    attempts.add(1);

    const res = http.get(url, {
      // 클라이언트가 서버보다 먼저 포기하는 상황을 만드는 지점.
      // 조건 A(서버 30초)에서는 여기서 취소되고 재요청이 나간다.
      timeout: CLIENT_PATIENCE,
      tags: { cond: COND, attempt: String(i + 1) },
    });

    if (res.status === 200) {
      ok = true;
      break;
    }
    // 실패했으면 사용자는 곧바로 다시 누른다.
    // 여기에 sleep을 넣지 마 — 사람이 화나서 연타하는 상황이 이 실험의 조건이다.
  }

  if (!ok) {
    givenUp.add(1);
  }
  userWait.add(Date.now() - started);

  check(null, {
    'eventually succeeded': () => ok,
  });
}

// 결과에서 볼 것
//   req_attempts / iterations = 증폭 배수.
//     조건 A에서 이 값이 크게 뜨는 것, 조건 B에서 1에 가깝게 유지되는 것이 핵심.
//   user_total_wait p95 — 사용자가 실제로 기다린 시간.
//     서버가 빨리 실패하는 조건 B가 오히려 이 값이 작다.
//   hikaricp_connections_pending (Grafana 3번 패널)
//     조건 A에서 계속 쌓이고, 조건 B에서 낮게 유지된다.
//
//   그리고 dropped_iterations를 먼저 확인한다. 0이 아니면 전부 무효다.
