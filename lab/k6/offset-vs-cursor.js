// offset-vs-cursor.js — A-2 ⑥ 오프셋 페이징을 커서 페이징으로 교체
//
// ⚠ 이 파일은 의도적 복잡도다. 단순화하지 마.
//   (CLAUDE.md ponytail 섹션 — lab/k6/ 는 ponytail 끄고 작업한다)
//
//   1. 워밍업 60초는 JVM JIT 때문에 필수다. 초반 수십 초는 인터프리터로 돌아서
//      실제보다 몇 배 느리다. 이 구간을 빼면 모든 측정이 거짓말이 된다.
//      warmup 시나리오에 phase:warmup 태그를 붙여 결과에서 걸러낸다.
//
//   2. 도착률(arrival-rate) 기반이다. VU 기반으로 바꾸지 마.
//      VU 기반은 서버가 느려지면 VU가 응답을 기다리느라 다음 요청을 안 보낸다.
//      즉 부하가 스스로 줄어들어 서버를 보호해버리고, 그러면 포화점이
//      아예 관측되지 않는다. 실제 사용자는 느리다고 요청을 멈추지 않는다.
//
// 실행
//   MODE=offset (기본) 먼저 돌리고, MODE=cursor 를 따로 돌린다.
//   같은 실행에 둘을 넣으면 서로 CPU를 뺏어서 비교가 안 된다.
//
//   k6 run -e MODE=offset  -e TARGET_HOST=localhost:8080 offset-vs-cursor.js
//   k6 run -e MODE=cursor  -e TARGET_HOST=localhost:8080 offset-vs-cursor.js
//
//   리허설(한 대)은 부하를 낮춘다:  -e PROFILE=rehearsal

import http from 'k6/http';
import { check } from 'k6';

const HOST = __ENV.TARGET_HOST || 'localhost:8080';
const MODE = __ENV.MODE || 'offset';
const PROFILE = __ENV.PROFILE || 'session';

// 2026-08-29 리허설 실측 (user_rating 5,030,000건, 유휴 상태 단건)
//   offset=4900000 : 1.16 초
//   cursor(깊음)   : 0.11 초   (updated_at 인덱스 없을 때)
//
// 도착률을 정할 때 쓰는 건 이 단건 값이 아니라 DB CPU 상한이다.
// DB는 cpus:2 라서 CPU를 태우는 쿼리는 초당 2코어어치밖에 못 돈다.
//   offset 쪽 지속 가능 처리량 ≈ 2코어 / 1.16초 ≈ 1.7 TPS
//
// 처음에 워밍업을 3 rps로 잡았다가 워밍업 구간에서 이미 VU가 54개까지
// 쌓이고 30초 타임아웃이 났다(2026-08-29 파일럿). 단건 1.16초를 보고
// "풀 10이면 8 TPS는 되겠지" 라고 계산한 게 틀렸다 —
// 그 산수에는 DB CPU가 빠져 있다. 이게 001-plan.md A-1 ②가 말하는
// "계산은 반드시 틀린다" 의 실제 사례다.
//
// 두 MODE에 같은 프로필을 쓴다. 같은 부하에서 한쪽만 버티는 걸 봐야 한다.
const STAGES = PROFILE === 'rehearsal'
  ? [ { target: 1, duration: '60s' },
      { target: 2, duration: '60s' },
      { target: 4, duration: '60s' } ]
  : [ { target: 1, duration: '60s' },
      { target: 2, duration: '60s' },
      { target: 4, duration: '60s' },
      { target: 8, duration: '60s' } ];

// 오프셋 4,900,000은 DESC 정렬에서 가장 오래된 쪽이다.
// 커서도 같은 깊이를 보게 맞춘다(데이터는 2024-08-28 ~ 2026-08-29).
const DEEP_CURSOR = '2024-10-01T00:00:00Z';

const url = MODE === 'cursor'
  ? `http://${HOST}/lab/ratings?cursorUpdatedAt=${encodeURIComponent(DEEP_CURSOR)}&limit=10`
  : `http://${HOST}/lab/ratings?offset=4900000&limit=10`;

export const options = {
  scenarios: {
    // JVM JIT 워밍업. 60초는 그대로 지키되 도착률은 낮춘다.
    // README ⑦의 20 rps로 워밍업하면 워밍업 구간에서 이미 포화돼서
    // JIT 워밍업이 아니라 그냥 과부하 측정이 된다.
    // 지속 가능치(약 1.7 TPS)보다 낮은 1 rps로 돈다.
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
      // 서버가 느려질수록 같은 도착률을 유지하는 데 더 많은 VU가 필요하다.
      // 여기가 모자라면 dropped_iterations가 뜨는데, 그건 서버 포화가 아니라
      // 스크립트 문제다. 넉넉히 준다.
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
    tags: { mode: MODE },
    // 무거운 쿼리라 기본 타임아웃(60s)보다 짧게 잡아 매달리지 않게 한다.
    timeout: '30s',
  });

  check(res, {
    'status 200': (r) => r.status === 200,
    'rows returned': (r) => {
      try { return JSON.parse(r.body).length > 0; } catch (e) { return false; }
    },
  });
}

// handleSummary는 일부러 두지 않는다.
// 덮어쓰면 k6 기본 요약이 사라지는데, vault/raw/ 에는 그 원본이 그대로
// 들어가야 한다(CLAUDE.md 지식의 세 층). 결과를 볼 순서는 이 파일 맨 아래 참고.
//
// 결과에서 볼 순서 (lab/README.md ⑦)
//   1. dropped_iterations — 0이 아니면 목표 부하를 못 만든 것이고
//      그 실험의 다른 숫자는 전부 무효다. maxVUs 부족(스크립트 문제)인지
//      서버 포화(진짜 결과)인지 k6 쪽 CPU를 보고 구분한다
//   2. 목표 rate vs 실제 http_reqs — 안 따라오기 시작하는 지점이 포화점
//   3. http_req_waiting — http_req_duration이 아니라 이걸 본다.
//      duration은 blocked+connecting+tls+sending+waiting+receiving의 합이고
//      순수 서버 처리 시간은 waiting이다. connecting이 크면 서버가 느린 게
//      아니라 커넥션을 새로 맺는 것이고 처방이 완전히 다르다(4장)
//   4. p95 / p99. 평균은 무시한다 — 일부만 대기하는 걸 평균이 뭉갠다
