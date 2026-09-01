#!/usr/bin/env node
'use strict'

const { readFileSync } = require('node:fs')
const { execFileSync } = require('node:child_process')

const TYPES = ['feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'chore', 'ci', 'build', 'revert']
const SCOPE_REQUIRED = new Set(['feat', 'fix', 'refactor', 'perf', 'test'])
const REASON_REQUIRED = new Set(['feat', 'fix', 'refactor', 'perf'])
const HEADER_RE = new RegExp(
  `^(${TYPES.join('|')})(?:\\(([a-z0-9][a-z0-9._/-]*)\\))?(!)?: (.+)$`,
)
const BODY_LABEL_RE = /^(이유|영향|검증):\s*(.*)$/
const FOOTER_RE = /^(?:BREAKING CHANGE|[A-Za-z][A-Za-z0-9-]*)(?:: | #)\S/
const MERGE_MESSAGE_RE = /^(?:Merge branch '[^'\n]+'(?: into [A-Za-z0-9._/-]+)?|Merge branch '[^'\n]+' of [^\s\n]+(?: into [A-Za-z0-9._/-]+)?|Merge branches '[^'\n]+'(?:, '[^'\n]+')* and '[^'\n]+'(?: into [A-Za-z0-9._/-]+)?|Merge remote-tracking branch '[^'\n]+'(?: into [A-Za-z0-9._/-]+)?)$/
const GITHUB_MERGE_MESSAGE_RE = /^Merge pull request #[1-9]\d* from [A-Za-z0-9_.-]+\/[A-Za-z0-9._/-]+(?:\n\n[\s\S]+)?$/
const TAG_MERGE_MESSAGE_RE = /^Merge tag '[^'\n]+'(?: into [A-Za-z0-9._/-]+)?(?:\n\n[\s\S]+)?$/
const MERGE_CONFLICT_COMMENTS_RE = /\n\n# Conflicts:\n(?:#[ \t]+[^\n]+(?:\n|$))+$/
const FULL_SHA_PATTERN = '[0-9a-f]{40}(?:[0-9a-f]{24})?'
const FULL_SHA_RE = new RegExp(`^${FULL_SHA_PATTERN}$`)
const RANGE_RE = new RegExp(`^${FULL_SHA_PATTERN}\\.\\.${FULL_SHA_PATTERN}$`)
function isGitGenerated(input) {
  const message = String(input ?? '').replace(/\r\n?/g, '\n').replace(/\n+$/, '')
  const withoutConflictComments = message.replace(MERGE_CONFLICT_COMMENTS_RE, '')
  return MERGE_MESSAGE_RE.test(withoutConflictComments)
    || GITHUB_MERGE_MESSAGE_RE.test(message)
    || TAG_MERGE_MESSAGE_RE.test(message)
}

function validateCommitMessage(input, { allowGitGenerated = false } = {}) {
  const message = String(input ?? '').replace(/\r\n?/g, '\n').replace(/\n+$/, '')
  const errors = []

  if (!message.trim()) return { valid: false, errors: ['커밋 메시지가 비어 있습니다.'] }
  if (isGitGenerated(message)) {
    return allowGitGenerated
      ? { valid: true, errors: [] }
      : { valid: false, errors: ['Git 생성 merge 메시지는 실제 merge provenance가 필요합니다.'] }
  }

  const lines = message.split('\n')
  const header = lines[0]
  const match = HEADER_RE.exec(header)

  if (!match) {
    return {
      valid: false,
      errors: [
        `헤더는 <type>(<scope>): <한국어 요약> 형식이어야 합니다. 허용 type: ${TYPES.join(', ')}`,
      ],
    }
  }

  const [, type, scope, , subject] = match
  if (SCOPE_REQUIRED.has(type) && !scope) {
    errors.push(`${type} 타입은 변경 영역을 나타내는 scope가 필요합니다.`)
  }
  if (!/[가-힣]/u.test(subject)) errors.push('요약에는 한글이 포함되어야 합니다.')
  if ([...subject].length > 50) errors.push('요약은 50자 이하여야 합니다.')
  if (/[.。]$/.test(subject)) errors.push('요약은 마침표로 끝내지 않습니다.')

  if (lines.length > 1 && lines[1] !== '') {
    errors.push('본문은 헤더 다음 빈 줄 뒤에 작성해야 합니다.')
  }

  const content = lines.slice(2).filter((line) => line !== '')
  const labels = []
  let inFooters = false
  for (const line of content) {
    const label = BODY_LABEL_RE.exec(line)
    if (label && !inFooters) {
      if (!label[2].trim()) errors.push(`${label[1]}: 뒤에 내용을 작성해야 합니다.`)
      labels.push(label[1])
      continue
    }
    if (FOOTER_RE.test(line)) {
      inFooters = true
      continue
    }
    errors.push(`본문 항목은 이유:·영향:·검증: 또는 Git footer 형식을 사용해야 합니다: ${line}`)
  }

  const expectedOrder = ['이유', '영향', '검증']
  const uniqueLabels = new Set(labels)
  if (uniqueLabels.size !== labels.length) errors.push('이유:·영향:·검증: 항목은 한 번씩만 작성합니다.')
  const ordered = [...labels].sort((a, b) => expectedOrder.indexOf(a) - expectedOrder.indexOf(b))
  if (labels.some((label, index) => label !== ordered[index])) {
    errors.push('본문 항목 순서는 이유: → 영향: → 검증: 입니다.')
  }
  if (labels.length > 0 && labels[0] !== '이유') errors.push('본문을 작성하면 첫 항목은 이유:여야 합니다.')
  if (REASON_REQUIRED.has(type) && !uniqueLabels.has('이유')) {
    errors.push(`${type} 타입은 빈 줄 뒤에 이유: 항목이 필요합니다.`)
  }

  return { valid: errors.length === 0, errors }
}

function messageFromParsed(parsed) {
  if (typeof parsed?.raw === 'string' && parsed.raw) return parsed.raw
  return [parsed?.header, parsed?.body, parsed?.footer].filter(Boolean).join('\n\n')
}

function commitlintRule(parsed) {
  const result = validateCommitMessage(messageFromParsed(parsed))
  return [result.valid, result.errors.join(' ')]
}

function readCommitMetadata(commit) {
  const git = (format) => execFileSync(
    'git',
    ['show', '-s', `--format=${format}`, commit],
    { encoding: 'utf8' },
  )
  const parents = git('%P').trim().split(/\s+/).filter(Boolean)
  return { message: git('%B'), allowGitGenerated: parents.length >= 2 }
}

function printValidationErrors(result, prefix = '✖ 커밋 메시지 규칙 위반') {
  console.error(prefix)
  for (const error of result.errors) console.error(`  - ${error}`)
}

function main(argv) {
  const rangeIndex = argv.indexOf('--range')
  const commitIndex = argv.indexOf('--commit')
  const fileIndex = argv.indexOf('--file')
  let message
  let allowGitGenerated = argv.includes('--allow-git-generated')

  if (rangeIndex >= 0) {
    const range = argv[rangeIndex + 1]
    if (!RANGE_RE.test(range ?? '')) {
      console.error('--range에는 <40/64자 SHA>..<40/64자 SHA> 형식이 필요합니다.')
      return 2
    }
    let commits
    try {
      commits = execFileSync('git', ['rev-list', '--reverse', range], { encoding: 'utf8' })
        .trim()
        .split(/\s+/)
        .filter(Boolean)
    } catch (error) {
      console.error(`commit range를 읽을 수 없습니다: ${error.message}`)
      return 2
    }
    if (commits.length === 0) {
      console.error('검사할 commit이 없는 range는 허용하지 않습니다.')
      return 1
    }

    let invalid = false
    for (const commit of commits) {
      let metadata
      try {
        metadata = readCommitMetadata(commit)
      } catch (error) {
        console.error(`commit metadata를 읽을 수 없습니다: ${error.message}`)
        return 2
      }
      const result = validateCommitMessage(metadata.message, metadata)
      if (!result.valid) {
        printValidationErrors(result, `✖ ${commit} 커밋 메시지 규칙 위반`)
        invalid = true
      }
    }
    if (invalid) {
      console.error('예: feat(order): 주문 한도 검증 추가\n\n이유: 잘못된 주문의 결제를 방지')
      return 1
    }
    return 0
  } else if (commitIndex >= 0) {
    const commit = argv[commitIndex + 1]
    if (!FULL_SHA_RE.test(commit ?? '')) {
      console.error('--commit에는 40자 또는 64자 전체 commit SHA가 필요합니다.')
      return 2
    }
    try {
      const metadata = readCommitMetadata(commit)
      message = metadata.message
      allowGitGenerated = metadata.allowGitGenerated
    } catch (error) {
      console.error(`commit metadata를 읽을 수 없습니다: ${error.message}`)
      return 2
    }
  } else if (argv.includes('--stdin')) {
    try {
      message = readFileSync(0, 'utf8')
    } catch (error) {
      console.error(`표준 입력을 읽을 수 없습니다: ${error.message}`)
      return 2
    }
  } else {
    const file = fileIndex >= 0 ? argv[fileIndex + 1] : argv[0]
    if (!file) {
      console.error('사용법: node scripts/check-commit-message.cjs --file <파일> | --stdin | --commit <SHA> | --range <SHA>..<SHA>')
      return 2
    }
    try {
      message = readFileSync(file, 'utf8')
    } catch (error) {
      console.error(`커밋 메시지 파일을 읽을 수 없습니다: ${error.message}`)
      return 2
    }
  }

  const result = validateCommitMessage(message, { allowGitGenerated })
  if (result.valid) return 0
  printValidationErrors(result)
  console.error('예: feat(order): 주문 한도 검증 추가\n\n이유: 잘못된 주문의 결제를 방지')
  return 1
}

module.exports = { TYPES, validateCommitMessage, commitlintRule, isGitGenerated }

if (require.main === module) process.exitCode = main(process.argv.slice(2))
