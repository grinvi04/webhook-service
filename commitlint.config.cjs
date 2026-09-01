// commitlint.config.cjs — Conventional Commits 강제 (commitlint가 CI에서 검사)
// Conventional Commits 문법 + team-harness 한국어·가독성 규칙. 단일 출처: docs/code-review.md
// new-repo.sh가 repo 루트에 복사하고, ci/commitlint.yml 워크플로가 PR 커밋을 검사한다.
// .cjs 확장자로 module type과 무관하게 CommonJS로 강제 — ESM 컨테이너/리포에서 module.exports 깨짐 방지.
const { existsSync } = require('node:fs')
const { join } = require('node:path')
const validatorPath = existsSync(join(__dirname, 'scripts/check-commit-message.cjs'))
  ? './scripts/check-commit-message.cjs'
  : '../scripts/check-commit-message.cjs'
const { commitlintRule, isGitGenerated, TYPES } = require(validatorPath)

module.exports = {
  defaultIgnores: false,
  ignores: [isGitGenerated],
  extends: ['@commitlint/config-conventional'],
  plugins: [{ rules: { 'team-harness-message': commitlintRule } }],
  rules: {
    'type-enum': [2, 'always', TYPES],
    'team-harness-message': [2, 'always'],
    'subject-case': [0],
    'body-max-line-length': [0],
  },
}
