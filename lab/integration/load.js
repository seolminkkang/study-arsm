import http from 'k6/http';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';
const attempts = new Counter('review_attempts');
const success = new Counter('review_success');
const host=__ENV.TARGET || 'http://localhost:8081';
const run=__ENV.RUN_ID;
if (!run) throw new Error('RUN_ID is required: use a new ID for each experiment');
export const options = {
  scenarios: {
    warmup: {executor:'constant-arrival-rate',rate:1,timeUnit:'1s',duration:'60s',preAllocatedVUs:4,maxVUs:20,tags:{phase:'warmup'}},
    measure: {executor:'constant-arrival-rate',startTime:'65s',rate:Number(__ENV.RATE || 5),timeUnit:'1s',duration:'60s',preAllocatedVUs:20,maxVUs:100,tags:{phase:'measure'}},
    independent_reads: {exec:'readReviews',executor:'constant-arrival-rate',startTime:'65s',rate:2,timeUnit:'1s',duration:'60s',preAllocatedVUs:10,maxVUs:30,tags:{phase:'measure',operation:'list'}}
  },
  thresholds: {
    'dropped_iterations':['count==0'],
    'http_req_duration{phase:measure,operation:create}':[],
    'http_req_duration{phase:measure,operation:list}':[],
    'http_req_failed{phase:measure}':[],
    'review_success{phase:measure}':[]
  }
};
export default function () {
  const id=run+'-'+exec.scenario.name+'-'+__VU+'-'+__ITER;
  attempts.add(1);
  const r=http.post(host+'/reviews?mode='+(__ENV.MODE || 'sync'),JSON.stringify({id,content:'lab'}),
    {headers:{'Content-Type':'application/json','X-Attempt-Id':id},timeout:'5s',tags:{operation:'create'}});
  if(r.status===200) success.add(1);
}
export function readReviews() {
  http.get(host+'/reviews',{timeout:'5s',tags:{operation:'list'}});
}
// warmup과 measure를 구분한다. 이 스크립트는 사용자 재시도를 넣지 않은 기준선이다.
// 실패율과 실제 성공 건수를 같이 읽는다. dropped_iterations 발생 시 목표 부하 미달을 기록한다.
