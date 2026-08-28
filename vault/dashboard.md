---
title: dashboard
description: Dataview 대시보드. 실험 현황과 미해결 질문
tags: [dashboard]
---

# 대시보드

> Dataview 플러그인 필요. 커뮤니티 플러그인에서 설치.

## 실험 현황

```dataview
TABLE chapter AS "장", status AS "상태", conclusion AS "결론"
FROM #experiment
SORT date DESC
```

## 미해결 질문

```dataview
LIST
FROM #question
SORT file.mtime DESC
```

## 검증 안 된 가설

```dataview
LIST
FROM #가설
SORT file.mtime DESC
```

## 최근 회차

```dataview
TABLE host AS "Host", chapters AS "장", experiments AS "실험"
FROM #session
SORT date DESC
LIMIT 5
```

## 개념 노트

```dataview
LIST
FROM #concept
SORT file.name ASC
```
