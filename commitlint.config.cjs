// commitlint.config.cjs — Conventional Commits 강제 (commitlint가 CI에서 검사)
// 타입은 영어, 제목·본문은 한국어 허용. 단일 출처: team-harness code-review.md
// new-repo.sh가 repo 루트에 복사하고, ci/commitlint.yml 워크플로가 PR 커밋을 검사한다.
// .cjs 확장자로 module type과 무관하게 CommonJS로 강제 — ESM 컨테이너/리포에서 module.exports 깨짐 방지.
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // 허용 타입(영어): feat/fix/docs/style/refactor/test/chore/ci
    'type-enum': [2, 'always', ['feat', 'fix', 'docs', 'style', 'refactor', 'test', 'chore', 'ci']],
    // 한국어 제목·본문 허용 — case·줄길이 제한 해제
    'subject-case': [0],
    'body-max-line-length': [0],
  },
}
