#!/usr/bin/env node
/*
 * 파괴적 DDL 정적 게이트 — 마이그레이션 SQL에 섞인 비가역 데이터-손실 DDL을 배포 전 결정적으로 차단한다.
 *
 * 운영 장애 클래스: CI는 빈 DB에 마이그레이션을 처음부터 적용하므로 DROP TABLE·TRUNCATE·DROP COLUMN이
 *   있어도 "지울 데이터가 없어" 통과한다(liveness ≠ 데이터 보존). 운영(기존 데이터)에서만 비가역 손실이 난다.
 *   이 정적 게이트가 그 함정을 CI에서 잡는다.
 *
 * 정책(team-harness): 체크 가능한 규칙은 prose가 아니라 결정적 게이트로. 단, SQL도 정규언어가 아니므로
 *   **흔한 데이터-손실 형태만** 잡는다(종단 우회는 계층0 코드리뷰 소관 — decisions.md 가드/게이트 판정 철학).
 *   - 파괴 판정: DROP TABLE · DROP DATABASE · DROP SCHEMA · TRUNCATE · ALTER…DROP COLUMN
 *   - 비대상(오탐 금지): DROP INDEX/VIEW/CONSTRAINT/TRIGGER/SEQUENCE(데이터-행 손실 아님),
 *     GRANT/REVOKE privilege 목록의 TRUNCATE 권한
 *   - forward-only 2단계 배포(db-standards.md §마이그레이션)의 정당한 DROP COLUMN은 **승인마커**로 통과:
 *       같은 문장에 실제 주석 `-- migration-safety: destructive-ok`.
 *
 * 반증(anti-spoof): 비실행 주석·문자열 리터럴 안의 파괴 키워드는 무시하고, MySQL 실행형 주석(`/*!`로 시작)
 *   본문은 실제 코드로 검사한다. `--`·`#`·backslash quote·문장 경계의 방언 차이는 PostgreSQL·PostgreSQL
 *   escape·MySQL·T-SQL lexer를 모두 적용해 어느 해석에서든 파괴문이면 차단한다. 승인마커도
 *   **실제 주석 시작**에 있을 때만 인정한다(문자열·중첩 주석 스푸핑 차단). check-migration-safety.mjs의 따옴표-인식
 *   commentOf() 로직과 동형. 검증은 통과가 아니라 우회 실패로 확정 — tests/destructive-ddl-test.sh의 스푸핑 픽스처.
 *
 * ⚠ 적용 범위 — **마이그레이션 디렉터리 하위 `*.sql` 내용 전용**:
 *   db/migration/(Flyway) · prisma/migrations/ · supabase/migrations/. 파괴성은 파일명 규약 무관이라
 *   Flyway V### 한정이 아니다(check-migration-safety의 out-of-order와 다른 축).
 *   - Alembic: DDL이 `.py`(op.drop_table())라 이 SQL 게이트의 비대상 — 형제 게이트
 *     `check-alembic-destructive-ddl.mjs`가 upgrade() 파괴 op를 본다(destructive-ddl.yml 2번째 스텝).
 *   - 마이그레이션 디렉터리 밖 .sql(seed·스크립트)은 스캔 안 함(오탐 금지).
 *   - 한계(흔한 형태만): 동적 SQL 문자열 조립은 미검출 — 계층0 정본.
 *
 * 단일 출처: docs/db-standards.md · docs/specs/secret-runbook-ddl-gate.md
 */
import { readFileSync, readdirSync, statSync, lstatSync, existsSync, realpathSync } from 'node:fs'
import { join, basename, relative, isAbsolute, sep } from 'node:path'

const args = process.argv.slice(2)
if (args.includes('--help') || args.includes('-h')) {
  console.log(`파괴적 DDL 게이트 — 마이그레이션 SQL의 비가역 데이터-손실 DDL을 배포 전 차단

사용법:
  node scripts/check-destructive-ddl.mjs [루트경로 …]

파괴 판정: DROP TABLE · DROP DATABASE · DROP SCHEMA · TRUNCATE · ALTER…DROP COLUMN
비대상   : DROP INDEX/VIEW/CONSTRAINT/TRIGGER, GRANT/REVOKE의 TRUNCATE 권한 (데이터-손실 아님)
실행 주석: MySQL 실행형 주석(/*! [버전] SQL */)의 실행 가능 본문도 실제 코드로 검사
승인마커 : 파괴 문장과 같은 문장의 실제 주석 시작에 \`migration-safety: destructive-ok\` → 통과
스캔대상 : db/migration/ · prisma/migrations/ · supabase/migrations/ 하위 *.sql
           (Alembic .py는 형제 게이트 check-alembic-destructive-ddl.mjs 소관)

종료 코드:
  0  통과 또는 skip(마이그레이션 SQL 없음 — 오탐 금지)
  1  FAIL — 승인마커 없는 파괴 DDL 또는 모든 지원 lexer에서 경계 오류 발견
  2  사용법 오류 — 미인식 옵션
`)
  process.exit(0)
}

// 미인식 옵션 → 사용법 오류(S2 규약과 일치)
const badFlag = args.find((a) => a.startsWith('-'))
if (badFlag) {
  console.error(`✖ 미인식 옵션: ${badFlag}  (--help 참조)`)
  process.exit(2)
}

const roots = args.length ? args : ['.']

// ── 파일 탐색 ─────────────────────────────────────────────
const IGNORE = new Set(['node_modules', '.git', 'build', 'target', '.gradle', 'dist', '.next', 'out', 'vendor', '.venv'])
// 마이그레이션 디렉터리 경로 세그먼트(파일명 규약 무관 — 내용이 문제). 경로 구분자는 정규화해 비교.
const MIG_DIR_RE = /(^|\/)(db\/migration|prisma\/migrations|supabase\/migrations)(\/|$)/i

function isWithinRoot(rootIdentity, targetIdentity) {
  const rel = relative(rootIdentity, targetIdentity)
  return rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel)
}

function failSymlink(p, reason) {
  console.error(`✖ symlink 탐색 경계 위반: ${p} — ${reason}`)
  process.exit(1)
}

function walk(root, onFile, isRelevant) {
  if (!existsSync(root)) return
  let rootIdentity
  try { rootIdentity = realpathSync(root) } catch { return }

  function visit(dir) {
    let entries
    try { entries = readdirSync(dir) } catch { return }
    for (const name of entries) {
      if (IGNORE.has(name)) continue
      const p = join(dir, name)
      let s
      try { s = lstatSync(p) } catch { continue }
      if (s.isSymbolicLink()) {
        let target
        try { target = statSync(p) } catch {
          if (isRelevant(p, name)) failSymlink(p, 'dangling target')
          continue
        }
        // Directory link는 exact root·cycle·fan-out 경계를 모호하게 하므로 순회하지 않고 차단한다.
        if (target.isDirectory()) failSymlink(p, 'directory symlink unsupported')
        if (!isRelevant(p, name)) continue
        if (!target.isFile()) failSymlink(p, 'target is not a regular file')
        let targetIdentity
        try { targetIdentity = realpathSync(p) } catch { failSymlink(p, 'target resolution failed') }
        if (!isWithinRoot(rootIdentity, targetIdentity)) failSymlink(p, 'target escapes scan root')
        onFile(p, name)
      } else if (s.isDirectory()) visit(p)
      else if (s.isFile() && isRelevant(p, name)) onFile(p, name)
    }
  }

  visit(root)
}

const sqlFiles = []
for (const root of roots) {
  const isMigrationSql = (p, name) => /\.sql$/i.test(name) && MIG_DIR_RE.test(p.replace(/\\/g, '/'))
  walk(root, (p) => { sqlFiles.push(p) }, isMigrationSql)
}

// ── skip: 마이그레이션 SQL 없음 (오탐 금지) ────────────────
if (sqlFiles.length === 0) {
  console.log('• 파괴적 DDL 게이트: 마이그레이션 디렉터리 하위 *.sql 없음 — 통과(skip)')
  console.log('  대상: db/migration/ · prisma/migrations/ · supabase/migrations/ (Alembic .py는 비대상).')
  process.exit(0)
}

// ── 파싱: 문장 단위 분해(따옴표·주석 인식) ──────────────────
// 각 문장 → { code, approved, valid }:
//   code     = 주석·문자열 리터럴을 제거한 텍스트(파괴 키워드 탐지용 — 문자열/주석 속 키워드는 무시).
//   approved = 실제 주석 시작 직후의 정식 승인마커만 true(문자열·중첩 comment text 스푸핑 제외).
//   valid    = 해당 문장의 quote/comment 경계가 이 lexer 해석에서 닫혔는지.
// 문장 경계 = 문자열·주석 밖의 `;`. 마커는 파괴 키워드와 **같은 문장**의 주석일 때만 크레딧.
const LEXER_MODES = [
  {
    dashCommentRequiresSpace: false, hashComment: false, backslashEscapes: false,
    doubleQuoteBackslashEscapes: false, nestedBlockComments: true,
    mysqlExecutableComments: false, newlineStatements: false, postgresDollarQuotes: true,
  }, // PostgreSQL
  {
    dashCommentRequiresSpace: false, hashComment: false, backslashEscapes: true,
    doubleQuoteBackslashEscapes: false, nestedBlockComments: true,
    mysqlExecutableComments: false, newlineStatements: false, postgresDollarQuotes: true,
  }, // PostgreSQL E-string
  {
    dashCommentRequiresSpace: true, hashComment: true, backslashEscapes: true,
    doubleQuoteBackslashEscapes: true, nestedBlockComments: false,
    mysqlExecutableComments: true, newlineStatements: false, postgresDollarQuotes: false,
  }, // MySQL
  {
    dashCommentRequiresSpace: false, hashComment: false, backslashEscapes: false,
    doubleQuoteBackslashEscapes: false, nestedBlockComments: false,
    mysqlExecutableComments: false, newlineStatements: true, postgresDollarQuotes: false,
  }, // T-SQL
]
const LINE_MARKER_RE = /^\s*migration-safety:\s*destructive-ok\b/i
const TSQL_LINE_START_RE = /^\s*(?:(?:IF|ELSE|BEGIN|END|WHILE|TRUNCATE|GRANT|REVOKE|DROP|ALTER|CREATE|DELETE|UPDATE|INSERT|EXEC(?:UTE)?|MERGE|SELECT|WITH|DECLARE|SET|PRINT|GOTO|RETURN|THROW|RAISERROR|USE|WAITFOR|COMMIT|ROLLBACK|SAVE|GO)\b|[A-Za-z_][A-Za-z0-9_]*\s*:)/i
const PRIVILEGE_CONTINUATION_RE = /^\s*(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|REFERENCES|TRIGGER|EXECUTE|USAGE|CREATE|CONNECT|TEMPORARY)\b/i

function isPrivilegeListContinuation(code, nextLine) {
  return /^\s*(?:GRANT|REVOKE)\b/i.test(code) &&
    !/\b(?:TO|FROM)\b/i.test(code) && PRIVILEGE_CONTINUATION_RE.test(nextLine)
}

function parseStatements(sql, mode) {
  const stmts = []
  let code = '', approved = false, statementValid = true, hadLexicalError = false
  const push = () => {
    if (code.trim() || approved) stmts.push({ code, approved, valid: statementValid })
    code = ''
    approved = false
    statementValid = true
  }
  let i = 0
  let n = sql.length
  while (i < n) {
    const c = sql[i], c2 = sql[i + 1]
    // PostgreSQL dollar-quoted string. MySQL은 `$`를 unquoted identifier에 허용하므로 PostgreSQL mode에서만
    // 불투명 문자열로 본다. 다른 mode는 `$tag$` 사이의 파괴문을 코드로 유지해 방언 중의성을 fail-closed한다.
    if (mode.postgresDollarQuotes && c === '$' && (i === 0 || !/[A-Za-z0-9_$]/.test(sql[i - 1]))) {
      const delimiter = sql.slice(i).match(/^\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$/)?.[0]
      if (delimiter) {
        const end = sql.indexOf(delimiter, i + delimiter.length)
        if (end < 0) {
          statementValid = false
          hadLexicalError = true
          code += ' '
          i = n
          continue
        }
        code += ' '
        i = end + delimiter.length
        continue
      }
    }
    // ANSI/PostgreSQL은 `--`를 항상 주석으로, MySQL은 뒤가 공백/control일 때만 주석으로 본다.
    if (c === '-' && c2 === '-') {
      let j = i + 2
      while (j < n && sql[j] !== '\n') j++
      const body = sql.slice(i + 2, j)
      const dashComment = LINE_MARKER_RE.test(body) || !mode.dashCommentRequiresSpace ||
        i + 2 >= n || /[\s\x00-\x1f\x7f]/.test(sql[i + 2])
      if (dashComment) {
        if (LINE_MARKER_RE.test(body)) approved = true
        i = j
        continue
      }
    }
    // MySQL은 `#`부터 EOL까지 주석, PostgreSQL은 XOR 연산자다. 두 해석은 LEXER_MODES에서 병렬 검증한다.
    if (c === '#') {
      let j = i + 1
      while (j < n && sql[j] !== '\n') j++
      const body = sql.slice(i + 1, j)
      if (mode.hashComment || LINE_MARKER_RE.test(body)) {
        if (LINE_MARKER_RE.test(body)) approved = true
        i = j
        continue
      }
    }
    // MySQL 실행형 주석 /*! [버전] SQL */ — top-level에서만 실행 가능 본문을 실제 코드로 펼친다.
    // 문자열·라인주석·일반 블록주석은 각 분기에서 끝까지 소비하므로 그 안의 `/*!`는 여기에 도달하지 않는다.
    if (c === '/' && c2 === '*' && sql[i + 2] === '!' && mode.mysqlExecutableComments) {
      let j = i + 3
      while (j < n && !(sql[j] === '*' && sql[j + 1] === '/')) j++
      if (j >= n) { // 닫히지 않은 실행형 주석은 실행 불가능한 일반 주석처럼 처리
        statementValid = false
        hadLexicalError = true
        code += ' '
        i = n
        continue
      }
      const rawBody = sql.slice(i + 3, j)
      const digits = rawBody.match(/^\d+/)?.[0] ?? ''
      if (digits && digits.length < 5) { // MySQL은 1~4자리 버전형을 실행하지 않는다.
        if (LINE_MARKER_RE.test(rawBody)) approved = true
        code += ' '
        i = j + 2
        continue
      }
      // 6자리 뒤 공백/end이면 6자리 버전, 그 외 5자리 이상은 앞 5자리만 버전이고 나머지는 본문이다.
      const versionLength = digits.length === 0
        ? 0
        : digits.length === 6 && (rawBody.length === 6 || /\s/.test(rawBody[6])) ? 6 : 5
      const body = rawBody.slice(versionLength)
      sql = sql.slice(0, i) + ' ' + body + ' ' + sql.slice(j + 2)
      n = sql.length
      continue
    }
    // 일반 블록 주석 /* … */
    if (c === '/' && c2 === '*') {
      let j = i + 2, depth = 1
      while (j < n && depth > 0) {
        if (mode.nestedBlockComments && sql[j] === '/' && sql[j + 1] === '*') {
          depth++
          j += 2
          continue
        }
        if (sql[j] === '*' && sql[j + 1] === '/') {
          depth--
          j += 2
          continue
        }
        j++
      }
      const closed = depth === 0
      const bodyEnd = closed ? j - 2 : n
      const body = sql.slice(i + 2, bodyEnd)
      if (LINE_MARKER_RE.test(body)) approved = true
      if (!closed) {
        statementValid = false
        hadLexicalError = true
      }
      code += ' ' // 토큰 병합 방지 — /* */ 는 SQL 토큰 구분자라 DROP/*x*/TABLE == DROP TABLE
      i = closed ? j : n
      continue
    }
    // 주석 시작 없이 나타난 닫힘은 이 lexer 해석에서 문법 오류다.
    if (c === '*' && c2 === '/') {
      statementValid = false
      hadLexicalError = true
      code += ' '
      i += 2
      continue
    }
    // 작은따옴표 문자열 리터럴('' = 이스케이프된 따옴표) → code에서 불투명 처리(키워드 무시)
    if (c === "'") {
      let j = i + 1
      let closed = false
      while (j < n) {
        if (mode.backslashEscapes && sql[j] === '\\' && j + 1 < n) { j += 2; continue }
        if (sql[j] === "'" && sql[j + 1] === "'") { j += 2; continue }
        if (sql[j] === "'") { j++; closed = true; break }
        j++
      }
      if (!closed) {
        statementValid = false
        hadLexicalError = true
      }
      code += ' ' // 토큰 병합 방지
      i = j
      continue
    }
    // 따옴표 식별자/문자열(PostgreSQL·ANSI "", MySQL ``, T-SQL [])는 실행 키워드가 아니다.
    if (c === '"' || c === '`') {
      const quote = c
      let j = i + 1
      let closed = false
      while (j < n) {
        if (quote === '"' && mode.doubleQuoteBackslashEscapes && sql[j] === '\\' && j + 1 < n) { j += 2; continue }
        if (sql[j] === quote && sql[j + 1] === quote) { j += 2; continue }
        if (sql[j] === quote) { j++; closed = true; break }
        j++
      }
      if (!closed) {
        statementValid = false
        hadLexicalError = true
      }
      code += ' '
      i = j
      continue
    }
    if (c === '[') {
      let j = i + 1
      let closed = false
      while (j < n) {
        if (sql[j] === ']' && sql[j + 1] === ']') { j += 2; continue }
        if (sql[j] === ']') { j++; closed = true; break }
        j++
      }
      if (!closed) {
        statementValid = false
        hadLexicalError = true
      }
      code += ' '
      i = j
      continue
    }
    // T-SQL은 세미콜론이 없어도 다음 command keyword로 새 문장을 시작할 수 있다.
    if (c === '\n' && mode.newlineStatements && code.trim()) {
      const nextLine = sql.slice(i + 1)
      if (TSQL_LINE_START_RE.test(nextLine) && !isPrivilegeListContinuation(code, nextLine)) {
        push()
        i++
        continue
      }
    }
    // 문장 종결
    if (c === ';') { push(); i++; continue }
    code += c
    i++
  }
  push() // 종결자 없는 마지막 문장
  return { stmts, hadLexicalError }
}

// ── 파괴 판정 규칙 ──────────────────────────────────────────
const DESTRUCTIVE = [
  { label: 'DROP TABLE', re: /\bDROP\s+TABLE\b/i },
  { label: 'DROP DATABASE', re: /\bDROP\s+DATABASE\b/i },
  { label: 'DROP SCHEMA', re: /\bDROP\s+SCHEMA\b/i },
  { label: 'TRUNCATE', re: /\bTRUNCATE\b(?!\s*\()/i }, // 제어문·label 뒤 TRUNCATE도 차단. 수치함수는 제외.
  { label: 'ALTER…DROP COLUMN', re: /\bDROP\s+COLUMN\b/i },
]

function isTruncatePrivilegeStatement(code) {
  if (!/^\s*(?:GRANT|REVOKE)\b/i.test(code)) return false
  const truncateAt = code.search(/\bTRUNCATE\b(?!\s*\()/i)
  if (truncateAt < 0) return false
  // 앞선 TO/FROM은 이미 첫 privilege 문장이 끝났음을 뜻한다(세미콜론 없는 T-SQL batch 포함).
  if (/\b(?:TO|FROM)\b/i.test(code.slice(0, truncateAt))) return false
  const suffix = code.slice(truncateAt)
  const onAt = suffix.search(/\bON\b/i)
  const recipientAt = suffix.search(/\b(?:TO|FROM)\b/i)
  return onAt >= 0 && recipientAt > onAt
}

const failures = []
const failureKeys = new Set()
for (const f of sqlFiles) {
  let text
  try { text = readFileSync(f, 'utf8') } catch { continue }
  const parsedModes = LEXER_MODES.map((mode) => parseStatements(text, mode))
  for (const parsed of parsedModes) {
    for (const stmt of parsed.stmts) {
      if (!stmt.valid) continue
      const hit = DESTRUCTIVE.find((d) => {
        if (!d.re.test(stmt.code)) return false
        return d.label !== 'TRUNCATE' || !isTruncatePrivilegeStatement(stmt.code)
      })
      if (!hit) continue
      if (stmt.approved) continue // 승인마커(실제 주석 시작) → 통과
      // 문장 첫 줄(정규화)로 어떤 문장인지 표시. 방언별 중복 판정은 한 건으로 합친다.
      const snippet = stmt.code.trim().replace(/\s+/g, ' ').slice(0, 80)
      const key = `${f}\0${hit.label}\0${snippet}`
      if (failureKeys.has(key)) continue
      failureKeys.add(key)
      failures.push({ file: f, label: hit.label, snippet })
    }
  }
  if (parsedModes.every((parsed) => parsed.hadLexicalError)) {
    const key = `${f}\0UNPARSEABLE SQL`
    if (!failureKeys.has(key)) {
      failureKeys.add(key)
      failures.push({ file: f, label: 'UNPARSEABLE SQL', snippet: '모든 지원 lexer 해석에서 quote/comment 경계 오류' })
    }
  }
}

if (failures.length > 0) {
  console.error('\n✖ 파괴적 DDL 게이트 실패 — 승인마커 없는 데이터-손실 DDL 또는 해석 불가 SQL:')
  for (const { file, label, snippet } of failures) {
    console.error(`  • ${label}  (${file})`)
    console.error(`      ${snippet}`)
  }
  console.error('\n  파괴 DDL은 CI(빈 DB)는 통과하고 운영(기존 데이터)에서만 비가역 손실을 냅니다.')
  console.error('  해결:')
  console.error('    • 정당한 변경(예: forward-only 2단계 배포의 컬럼 제거)이면 파괴 문장과 같은 문장에')
  console.error('      승인 주석을 답니다:  -- migration-safety: destructive-ok')
  console.error('    • 아니면 파괴 DDL을 제거하고 forward-only(새 버전 추가) 경로로 대체하세요.')
  console.error('  단일 출처: docs/db-standards.md · docs/specs/secret-runbook-ddl-gate.md\n')
  process.exit(1)
}

console.log(`✓ 파괴적 DDL 게이트 통과 — 마이그레이션 SQL ${sqlFiles.length}개 · 승인 없는 파괴 DDL 없음`)
process.exit(0)
