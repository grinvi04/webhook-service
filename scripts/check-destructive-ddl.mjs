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
 *   - 비대상(오탐 금지): DROP INDEX/VIEW/CONSTRAINT/TRIGGER/SEQUENCE(데이터-행 손실 아님)
 *   - forward-only 2단계 배포(db-standards.md §마이그레이션)의 정당한 DROP COLUMN은 **승인마커**로 통과:
 *       같은 문장에 실제 주석 `-- migration-safety: destructive-ok`.
 *
 * 반증(anti-spoof): 주석(라인 --·MySQL #, 블록)·문자열 리터럴(작은따옴표) 안의 파괴 키워드는 무시하고, 승인마커도
 *   **실제 주석 안**일 때만 인정한다(문자열 값 스푸핑 차단). check-migration-safety.mjs의 따옴표-인식
 *   commentOf() 로직과 동형. 검증은 통과가 아니라 우회 실패로 확정 — tests/destructive-ddl-test.sh의 스푸핑 픽스처.
 *
 * ⚠ 적용 범위 — **마이그레이션 디렉터리 하위 `*.sql` 내용 전용**:
 *   db/migration/(Flyway) · prisma/migrations/ · supabase/migrations/. 파괴성은 파일명 규약 무관이라
 *   Flyway V### 한정이 아니다(check-migration-safety의 out-of-order와 다른 축).
 *   - Alembic: DDL이 `.py`(op.drop_table())라 이 SQL 게이트의 비대상 — 형제 게이트
 *     `check-alembic-destructive-ddl.mjs`가 upgrade() 파괴 op를 본다(destructive-ddl.yml 2번째 스텝).
 *   - 마이그레이션 디렉터리 밖 .sql(seed·스크립트)은 스캔 안 함(오탐 금지).
 *   - 한계(흔한 형태만): Postgres dollar-quoting($$…$$)·동적 SQL 문자열 조립은 미검출 — 계층0 정본.
 *
 * 단일 출처: docs/db-standards.md · docs/specs/secret-runbook-ddl-gate.md
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, basename } from 'node:path'

const args = process.argv.slice(2)
if (args.includes('--help') || args.includes('-h')) {
  console.log(`파괴적 DDL 게이트 — 마이그레이션 SQL의 비가역 데이터-손실 DDL을 배포 전 차단

사용법:
  node scripts/check-destructive-ddl.mjs [루트경로 …]

파괴 판정: DROP TABLE · DROP DATABASE · DROP SCHEMA · TRUNCATE · ALTER…DROP COLUMN
비대상   : DROP INDEX/VIEW/CONSTRAINT/TRIGGER (데이터-손실 아님)
승인마커 : 파괴 문장과 같은 문장의 실제 주석 \`-- migration-safety: destructive-ok\` → 통과
스캔대상 : db/migration/ · prisma/migrations/ · supabase/migrations/ 하위 *.sql
           (Alembic .py는 형제 게이트 check-alembic-destructive-ddl.mjs 소관)

종료 코드:
  0  통과 또는 skip(마이그레이션 SQL 없음 — 오탐 금지)
  1  FAIL — 승인마커 없는 파괴 DDL 발견
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

function walk(dir, onFile, depth = 0) {
  if (depth > 12 || !existsSync(dir)) return
  let entries
  try { entries = readdirSync(dir) } catch { return }
  for (const name of entries) {
    if (IGNORE.has(name)) continue
    const p = join(dir, name)
    let s
    try { s = statSync(p) } catch { continue }
    if (s.isDirectory()) walk(p, onFile, depth + 1)
    else onFile(p, name)
  }
}

const sqlFiles = []
for (const root of roots) {
  walk(root, (p, name) => {
    if (/\.sql$/i.test(name) && MIG_DIR_RE.test(p.replace(/\\/g, '/'))) sqlFiles.push(p)
  })
}

// ── skip: 마이그레이션 SQL 없음 (오탐 금지) ────────────────
if (sqlFiles.length === 0) {
  console.log('• 파괴적 DDL 게이트: 마이그레이션 디렉터리 하위 *.sql 없음 — 통과(skip)')
  console.log('  대상: db/migration/ · prisma/migrations/ · supabase/migrations/ (Alembic .py는 비대상).')
  process.exit(0)
}

// ── 파싱: 문장 단위 분해(따옴표·주석 인식) ──────────────────
// 각 문장 → { code, comments }:
//   code     = 주석·문자열 리터럴을 제거한 텍스트(파괴 키워드 탐지용 — 문자열/주석 속 키워드는 무시).
//   comments = 실제 주석(`--`,`/* */`) 내용만(승인마커 탐지용 — 문자열 값 스푸핑은 여기 안 들어옴).
// 문장 경계 = 문자열·주석 밖의 `;`. 마커는 파괴 키워드와 **같은 문장**의 주석일 때만 크레딧.
function parseStatements(sql) {
  const stmts = []
  let code = '', comments = ''
  const push = () => { if (code.trim() || comments.trim()) stmts.push({ code, comments }); code = ''; comments = '' }
  let i = 0
  const n = sql.length
  while (i < n) {
    const c = sql[i], c2 = sql[i + 1]
    // 라인 주석 -- … EOL
    if (c === '-' && c2 === '-') {
      let j = i + 2
      while (j < n && sql[j] !== '\n') j++
      comments += sql.slice(i + 2, j) + '\n'
      i = j
      continue
    }
    // MySQL '#' 라인 주석 … EOL — 토큰-분리 우회 차단(DROP#x\nTABLE == DROP TABLE, #258).
    //   `--` 와 동형으로 comments 채널에 담아 `# migration-safety` 마커도 MySQL에서 동일하게 인정.
    //   한계(계층0): Postgres '#' 연산자(#>, 비트XOR)를 주석으로 오인해 줄 나머지를 제거할 수 있으나,
    //   제거만 하므로 파괴 키워드를 새로 만들지 못한다(FP로 오차단 불가) — dialect-무관 best-effort.
    if (c === '#') {
      let j = i + 1
      while (j < n && sql[j] !== '\n') j++
      comments += sql.slice(i + 1, j) + '\n'
      i = j
      continue
    }
    // 블록 주석 /* … */
    if (c === '/' && c2 === '*') {
      let j = i + 2
      while (j < n && !(sql[j] === '*' && sql[j + 1] === '/')) j++
      comments += sql.slice(i + 2, j) + '\n'
      code += ' ' // 토큰 병합 방지 — /* */ 는 SQL 토큰 구분자라 DROP/*x*/TABLE == DROP TABLE
      i = j < n ? j + 2 : n
      continue
    }
    // 작은따옴표 문자열 리터럴('' = 이스케이프된 따옴표) → code에서 불투명 처리(키워드 무시)
    if (c === "'") {
      let j = i + 1
      while (j < n) {
        if (sql[j] === "'" && sql[j + 1] === "'") { j += 2; continue }
        if (sql[j] === "'") { j++; break }
        j++
      }
      code += ' ' // 토큰 병합 방지
      i = j
      continue
    }
    // 문장 종결
    if (c === ';') { push(); i++; continue }
    code += c
    i++
  }
  push() // 종결자 없는 마지막 문장
  return stmts
}

// ── 파괴 판정 규칙 ──────────────────────────────────────────
const DESTRUCTIVE = [
  { label: 'DROP TABLE', re: /\bDROP\s+TABLE\b/i },
  { label: 'DROP DATABASE', re: /\bDROP\s+DATABASE\b/i },
  { label: 'DROP SCHEMA', re: /\bDROP\s+SCHEMA\b/i },
  { label: 'TRUNCATE', re: /\bTRUNCATE\b(?!\s*\()/i }, // TRUNCATE(x,d) 수치함수 제외(오탐), TRUNCATE [TABLE] t는 차단(#258)
  { label: 'ALTER…DROP COLUMN', re: /\bDROP\s+COLUMN\b/i },
]
const MARKER_RE = /migration-safety:\s*destructive-ok/i

const failures = []
for (const f of sqlFiles) {
  let text
  try { text = readFileSync(f, 'utf8') } catch { continue }
  for (const stmt of parseStatements(text)) {
    const hit = DESTRUCTIVE.find((d) => d.re.test(stmt.code))
    if (!hit) continue
    if (MARKER_RE.test(stmt.comments)) continue // 승인마커(실제 주석) → 통과
    // 문장 첫 줄(정규화)로 어떤 문장인지 표시
    const snippet = stmt.code.trim().replace(/\s+/g, ' ').slice(0, 80)
    failures.push({ file: f, label: hit.label, snippet })
  }
}

if (failures.length > 0) {
  console.error('\n✖ 파괴적 DDL 게이트 실패 — 승인마커 없는 데이터-손실 DDL:')
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
