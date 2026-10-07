// commitlint.config.cjs — commitlint CLI 호환 adapter
// Conventional Commits 문법 + team-harness 한국어·가독성 규칙. 단일 출처: docs/code-review.md
// required CI와 commit-msg hook은 scripts/check-commit-message.cjs를 직접 실행한다.
// .cjs 확장자로 module type과 무관하게 CommonJS로 강제 — ESM 컨테이너/리포에서 module.exports 깨짐 방지.
const { existsSync } = require('node:fs')
const { join } = require('node:path')
const validatorPath = existsSync(join(__dirname, 'scripts/check-commit-message.cjs'))
  ? './scripts/check-commit-message.cjs'
  : '../scripts/check-commit-message.cjs'
const {
  commitlintRule,
  isGitGenerated,
  hasConventionalConflictComments,
  TYPES,
} = require(validatorPath)

module.exports = {
  defaultIgnores: false,
  // commitlint CLI는 parent metadata를 읽지 못하므로 Git 생성 메시지를 보조 검사에서 제외한다.
  // provenance는 required CI validator가 별도로 fail-closed 검사한다.
  ignores: [isGitGenerated, hasConventionalConflictComments],
  extends: ['@commitlint/config-conventional'],
  plugins: [{ rules: { 'team-harness-message': commitlintRule } }],
  rules: {
    'type-enum': [2, 'always', TYPES],
    'team-harness-message': [2, 'always'],
    'subject-case': [0],
    'body-max-line-length': [0],
  },
}
