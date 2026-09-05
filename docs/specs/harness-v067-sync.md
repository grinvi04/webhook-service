# Team Harness v0.67.0 안전 검사 정본 동기화

## 승인 범위

- 추적: [Team Harness #442](https://github.com/grinvi04/team-harness/issues/442).
- 제품 판단: 연결. 이미 배포된 정책 검사기를 반영하며 새 기능·별도 서비스는 추가하지 않는다.
- 정본 revision: `8c405c2a36782b95d619ca6efb89ed20e8e8c3c1`.
- 변경: commitlint workflow·config·validator와 SQL·Alembic·ActiveRecord 검사기, 총 6파일.
- 그대로 유지: 기존 앱 코드·테스트·migration·DB·배포 설정·브랜치 보호, commit-msg hook과 destructive-DDL workflow.

## 수용 기준

1. commitlint workflow와 config는 정본 `templates/` 파일, 4개 검사기는 정본 `scripts/` 파일과 동일하다.
2. 기존 deep migration 탐색 누락과 merge provenance·릴리즈/backmerge 범위 반례가 변경 전 실패하고 변경 후 통과한다.
3. 정본의 commit-message, destructive-ddl, alembic-destructive-ddl, activerecord-destructive-ddl 회귀 테스트를 해당 소비 검사기 대상으로 통과한다.
4. repo-sync MISSING 0과 DDL 3파일 정본 digest 일치를 별도로 확인한다. repo-sync의 존재 검사만으로 최신 DDL 반영을 주장하지 않는다.
5. 기존 앱 품질·required CI·PR 리뷰를 통과하고, 병합 후 최신 develop SHA와 브랜치 보호 보존을 확인한다.

## 검증 방법

정본 테스트·fixture는 격리 검사 디렉터리에 그대로 두고, 테스트 대상 workflow·config·검사기 경로만 이 저장소 파일에 연결한다.
동일 테스트를 변경 전후에 실행하며 기존 앱 테스트는 수정하지 않는다. 생성 fixture에서만 위험 구문을 검사하며 실제 DB에는 실행하지 않는다.

## 비목표

Team Harness #432의 PR 외부 신뢰 경계 문제는 이번 동기화로 해결되지 않는다. main 릴리즈나 보호 설정 변경도 포함하지 않는다.
