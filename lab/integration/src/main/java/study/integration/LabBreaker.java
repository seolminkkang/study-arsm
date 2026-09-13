package study.integration;

/** 교육용: 연속 실패 3회 / 3초 차단 / 시험 요청 1개. 운영용 라이브러리 대체물이 아니다. */
final class LabBreaker {
    private int failures;
    private long openedAt;
    private boolean probe;
    synchronized boolean allow() {
        if (openedAt == 0) return true;
        if (System.nanoTime() - openedAt < 3_000_000_000L || probe) return false;
        probe = true;
        return true;
    }
    synchronized void success() { failures=0; openedAt=0; probe=false; }
    synchronized void failure() {
        if (++failures >= 3 || probe) openedAt=System.nanoTime();
        probe=false;
    }
    synchronized String state() {
        return openedAt==0 ? "CLOSED" : probe ? "HALF_OPEN" : "OPEN";
    }
}
