# k6

도착률(arrival rate) 기반으로 짠다. 이유는 `lab/README.md` ⑦ 참고.

| 파일 | 실험 |
|---|---|
| `offset-vs-cursor.js` | 오프셋 페이징 vs 커서 페이징 |
| `pool-size.js` | 커넥션 풀 크기 (2 / 10 / 50) |
| `timeout-amplification.js` | 타임아웃 길이와 재시도 증폭 |

공통 규칙
- 워밍업 60초는 타협하지 않는다 (JVM JIT). 이 구간 결과는 버린다
- `dropped_iterations`를 제일 먼저 확인한다. 0이 아니면 그 실험은 무효
- 평균이 아니라 p95를 본다

출력은 `vault/raw/`에 원본 그대로 저장한다.

## 결과 저장 방법

측정하고 결과를 안 남기는 실수가 제일 흔하다. **실행 전에 파일명을 먼저
정하고 시작한다.** (파일명 규칙은 `vault/raw/README.md` 참고)

```bash
# 방법 1: k6 자체 요약 export
k6 run --summary-export=vault/raw/2026-09-06_exp-001_session_k6.json script.js

# 방법 2: 콘솔 출력 전체를 그대로 저장 (요약 지표 외에 로그도 남기고 싶을 때)
k6 run script.js | tee vault/raw/2026-09-06_exp-001_session_k6.txt
```

파일명 규칙:
```
YYYY-MM-DD_exp-NNN_rehearsal_k6.txt   -- 리허설
YYYY-MM-DD_exp-NNN_session_k6.txt     -- 당일
```

리허설과 당일은 조건(한 대 vs 두 대, 부하 크기)이 다르므로 파일명으로
반드시 구분한다. 자세한 이유는 `vault/raw/README.md` 참고.
