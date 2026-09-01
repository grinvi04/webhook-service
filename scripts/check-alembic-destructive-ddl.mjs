#!/usr/bin/env node
/*
 * Alembic 파괴적 DDL 정적 게이트 — Alembic .py 마이그레이션의 upgrade() 경로에 있는 비가역
 *   데이터-손실 DDL을 배포 전 결정적으로 차단한다. SQL판(check-destructive-ddl.mjs)의 .py 축 형제.
 *
 * 운영 장애 클래스: CI는 빈 DB에 마이그레이션을 처음부터 적용하므로 op.drop_table/op.drop_column이
 *   있어도 "지울 데이터가 없어" 통과한다(liveness ≠ 데이터 보존). 운영(기존 데이터)에서만 비가역 손실.
 *   alembic-heads.yml은 다중 head(분기)만 보지 파괴 DDL은 안 본다 → 이 정적 게이트가 그 갭을 메운다.
 *
 * 스캔 범위 — upgrade 계열 함수 본문만(핵심):
 *   정상 autogenerate 마이그레이션은 downgrade()에 파괴 op를 **항상** 담는다(upgrade의 add_column을
 *   downgrade의 drop_column으로 되돌림). 파일 전체를 스캔하면 정상 마이그레이션 거의 100%가 오탐된다.
 *   배포 시 실행되는 것은 upgrade 계열(`upgrade`·multidb `upgrade_engineN`)이므로 그 경로만 본다 —
 *   SQL 게이트가 "앞으로 적용되는 마이그레이션 파일"을 스캔하는 것과 동형. downgrade*·헬퍼는 비대상.
 *
 * 정책(team-harness): 체크 가능한 규칙은 prose가 아니라 결정적 게이트로. 단, Python도 정규언어가 아니므로
 *   **흔한 데이터-손실 형태만** 잡는다(종단 우회는 계층0 코드리뷰 소관 — decisions.md 판정 철학).
 *   - 파괴 판정: drop_table()·drop_column()(수신자 무관 — op.·batch_op.·별칭 모두) ·
 *       execute() 내 raw DROP TABLE/DATABASE/SCHEMA·TRUNCATE·DROP COLUMN(수신자 무관).
 *   - 비대상(오탐 금지): drop_index/drop_constraint(데이터-행 손실 아님) — SQL판 DROP INDEX/CONSTRAINT와 동형.
 *   - forward-only 2단계 배포(db-standards.md §마이그레이션)의 정당한 DROP은 **승인마커**로 통과:
 *       파괴 op와 같은 논리 문장(트레일링) 또는 바로 앞 주석줄의 실제 `#` 주석 `# migration-safety: destructive-ok`.
 *
 * 반증(anti-spoof): 주석(#)·문자열 리터럴('..','".."','''..''',"""..""",r/b/f/u 접두)·docstring 안의 파괴
 *   키워드는 무시하고, 승인마커도 **실제 # 주석 안**일 때만 인정한다(문자열 값 스푸핑 차단). execute의 raw
 *   SQL은 SQL 블록주석·라인주석(--)·SQL 문자열 리터럴을 제거한 뒤 검사한다(블록주석 토큰-분리 우회 차단 — SQL판
 *   v0.31.0 봉쇄와 동형: DROP<블록주석>TABLE가 Postgres에서 유효 SQL; MySQL '#' 라인주석도 동일 차단, #258). 검증은 통과가 아니라 우회 실패로 확정 —
 *   tests/alembic-destructive-ddl-test.sh의 스푸핑·우회 픽스처.
 *
 * ⚠ 적용 범위 — **Alembic 마이그레이션 .py 전용**(지문 기반, 경로 무관):
 *   `from alembic`/`import alembic` + 모듈-레벨 `def upgrade(`/`async def upgrade(` 또는 `revision =` 지문을
 *   가진 .py만 대상(script_location·임포트 스타일 편차 무관, 더 견고). 지문 없는 .py(앱 코드·헬퍼)는 비대상.
 *   - 한계(흔한 형태만·계층0 정본): upgrade 계열이 아닌 헬퍼 함수로 숨긴 파괴 op·동적 SQL 조립·암묵적 문자열
 *     연결(execute("DR" "OP"))·f-string 표현식 내 op 호출(f"{op.drop_table(...)}")은 미검출(난독화=계층0).
 *
 * 단일 출처: docs/db-standards.md · docs/specs/alembic-destructive-ddl.md
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const args = process.argv.slice(2)
if (args.includes('--help') || args.includes('-h')) {
  console.log(`Alembic 파괴적 DDL 게이트 — .py 마이그레이션 upgrade()의 비가역 데이터-손실 DDL을 배포 전 차단

사용법:
  node scripts/check-alembic-destructive-ddl.mjs [루트경로 …]

파괴 판정: drop_table() · drop_column() (수신자 무관: op.·batch_op.·별칭) · execute() 내 raw DROP/TRUNCATE
비대상   : drop_index/drop_constraint (데이터-손실 아님) · downgrade*·비-upgrade 헬퍼 함수(upgrade 계열만 스캔)
승인마커 : 파괴 op와 같은 문장(트레일링) 또는 바로 앞 주석줄의 실제 # 주석 \`# migration-safety: destructive-ok\`
스캔대상 : \`from/import alembic\` + \`def upgrade(\`/\`revision =\` 지문을 가진 .py (경로 무관, 지문 없으면 비대상)

종료 코드:
  0  통과 또는 skip(Alembic 마이그레이션 없음 — 오탐 금지)
  1  FAIL — 승인마커 없는 파괴 DDL 발견
  2  사용법 오류 — 미인식 옵션
`)
  process.exit(0)
}

// 미인식 옵션 → 사용법 오류(SQL판 S2 규약과 일치)
const badFlag = args.find((a) => a.startsWith('-'))
if (badFlag) {
  console.error(`✖ 미인식 옵션: ${badFlag}  (--help 참조)`)
  process.exit(2)
}

const roots = args.length ? args : ['.']

// ── 파일 탐색 ─────────────────────────────────────────────
const IGNORE = new Set(['node_modules', '.git', 'build', 'target', '.gradle', 'dist', '.next', 'out', 'vendor', '.venv'])

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

// Alembic 마이그레이션 지문(임포트 스타일 편차 무관): alembic 임포트 OR revision 식별자 + upgrade 정의.
const HAS_ALEMBIC = /^\s*(?:from\s+alembic\b|import\s+alembic\b)/m
const HAS_REVISION = /^\s*(?:down_)?revision\s*[:=]/m
const HAS_UPGRADE = /^(?:async\s+)?def\s+upgrade\w*\s*\(/m

const pyFiles = []
for (const root of roots) {
  walk(root, (p, name) => { if (/\.py$/i.test(name)) pyFiles.push(p) })
}

const migrationFiles = []
const fileText = new Map()
for (const f of pyFiles) {
  let text
  try { text = readFileSync(f, 'utf8') } catch { continue }
  if (HAS_UPGRADE.test(text) && (HAS_ALEMBIC.test(text) || HAS_REVISION.test(text))) {
    migrationFiles.push(f)
    fileText.set(f, text)
  }
}

// ── skip: Alembic 마이그레이션 없음 (오탐 금지) ────────────
if (migrationFiles.length === 0) {
  console.log('• Alembic 파괴 DDL 게이트: Alembic 마이그레이션 .py 없음 — 통과(skip)')
  console.log('  대상: `from/import alembic` + `def upgrade(`/`revision =` 지문을 가진 .py.')
  process.exit(0)
}

// ── Python-인식 토크나이저: 파일 전체를 논리 문장으로 분해 ──────────────────
//   각 문장 → { code, comments, strings, col0 }:
//     code     = # 주석·문자열 리터럴 제거본(op 호출 탐지용 — 문자열/주석 속 키워드 무시).
//     comments = 실제 # 주석 내용만(승인마커 탐지용 — 문자열 값 스푸핑 배제).
//     strings  = 문자열 리터럴 값 배열(execute 문장의 raw DROP 내용 검사용).
//     col0     = 문장 첫 비공백 문자가 컬럼0인가(모듈-레벨 def/class 스코프 경계 판정용).
//   논리 문장 경계 = 괄호/대괄호/중괄호 depth 0에서의 개행 **또는 `;`**(다중행 op 호출은 한 문장,
//     세미콜론 결합 문장은 분리 — 마커 오귀속 차단). 문자열/주석 인식이라 triple-quote·괄호 안 개행에 안 속는다.
function matchStringStart(src, i) {
  let j = i
  let prefix = ''
  while (j < src.length && /[rRbBuUfF]/.test(src[j]) && prefix.length < 3) { prefix += src[j]; j++ }
  const q3 = src.substr(j, 3)
  if (q3 === "'''" || q3 === '"""') return { quote: q3, start: j }
  const q1 = src[j]
  if (q1 === "'" || q1 === '"') return { quote: q1, start: j }
  return null
}

function scanString(src, i, quote) {
  const n = src.length
  const qlen = quote.length
  let val = ''
  while (i < n) {
    // 백슬래시는 raw 여부와 무관하게 다음 문자의 종결 효력을 없앤다(Python은 raw string도 \" 로 안 끝난다).
    if (src[i] === '\\') { val += src[i] + (src[i + 1] ?? ''); i += 2; continue }
    if (src.startsWith(quote, i)) { i += qlen; break }
    val += src[i]; i++
  }
  return { end: i, val }
}

function tokenize(src) {
  const stmts = []
  let code = '', comments = '', strings = []
  let depth = 0
  let lineCol = 0
  let stmtStartCol = -1
  const push = () => {
    if (code.trim() || comments.trim() || strings.length) {
      stmts.push({ code, comments, strings, col0: stmtStartCol === 0 })
    }
    code = ''; comments = ''; strings = []; stmtStartCol = -1
  }
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    if (stmtStartCol === -1 && c !== ' ' && c !== '\t' && c !== '\r' && c !== '\n') stmtStartCol = lineCol
    // 라인 주석 # … EOL
    if (c === '#') {
      let j = i + 1
      while (j < n && src[j] !== '\n') j++
      comments += src.slice(i + 1, j) + '\n'
      lineCol += j - i
      i = j
      continue
    }
    // 문자열 리터럴(접두사·triple·single 인식) → strings에 값 보존, code엔 공백(토큰 병합 방지)
    const sm = matchStringStart(src, i)
    if (sm) {
      const { end, val } = scanString(src, sm.start + sm.quote.length, sm.quote)
      strings.push(val)
      code += ' '
      const consumed = src.slice(i, end)
      const nl = consumed.lastIndexOf('\n')
      lineCol = nl === -1 ? lineCol + consumed.length : consumed.length - nl - 1
      i = end
      continue
    }
    // 문장 종결: depth 0에서의 개행 또는 세미콜론
    if (c === '\n') {
      if (depth === 0) push()
      else code += ' '
      lineCol = 0
      i++
      continue
    }
    if (c === ';' && depth === 0) { push(); lineCol++; i++; continue }
    if (c === '(' || c === '[' || c === '{') depth++
    else if (c === ')' || c === ']' || c === '}') { if (depth > 0) depth-- }
    code += c
    lineCol++
    i++
  }
  push()
  return stmts
}

// ── SQL 정규화(execute 내 raw SQL 검사 전) — SQL 주석·문자열 리터럴 제거 ──────────
//   블록주석 토큰-분리(DROP/*x*/TABLE) 우회 차단 + SQL 문자열 값 속 키워드 오탐 방지(SQL판과 동형).
function normalizeSql(s) {
  let out = ''
  let i = 0
  const n = s.length
  while (i < n) {
    const c = s[i], c2 = s[i + 1]
    if (c === '-' && c2 === '-') { while (i < n && s[i] !== '\n') i++; out += ' '; continue }
    if (c === '#') { while (i < n && s[i] !== '\n') i++; out += ' '; continue } // MySQL '#' 라인주석 토큰-분리 차단(DROP#x\nTABLE == DROP TABLE, #258). Python/SQL은 인터폴레이션 없어 단순 #→EOL로 충분(AR판 #{} 제외 불필요)
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(s[i] === '*' && s[i + 1] === '/')) i++; i = i < n ? i + 2 : n; out += ' '; continue }
    if (c === "'") { i++; while (i < n) { if (s[i] === "'" && s[i + 1] === "'") { i += 2; continue } if (s[i] === "'") { i++; break } i++ } out += ' '; continue }
    out += c; i++
  }
  return out
}

// ── 파괴 판정 규칙 ──────────────────────────────────────────
// 수신자 무관 — op.·batch_op.(batch_alter_table 컨텍스트)·별칭(o.) 모두 매칭. 문자열은 code에서 제거돼 스푸핑 무해.
const OP_DESTRUCTIVE = [
  { label: 'drop_table', re: /\bdrop_table\s*\(/ },
  { label: 'drop_column', re: /\bdrop_column\s*\(/ },
]
const EXEC_RE = /\bexecute\s*\(/
// execute 내 raw SQL 파괴 키워드 — SQL판(check-destructive-ddl.mjs)과 동일 세트.
const SQL_DESTRUCTIVE = [
  { label: 'execute: DROP TABLE', re: /\bDROP\s+TABLE\b/i },
  { label: 'execute: DROP DATABASE', re: /\bDROP\s+DATABASE\b/i },
  { label: 'execute: DROP SCHEMA', re: /\bDROP\s+SCHEMA\b/i },
  { label: 'execute: TRUNCATE', re: /\bTRUNCATE\b(?!\s*\()/i }, // TRUNCATE(x,d) 수치함수 제외(오탐), TRUNCATE [TABLE] t는 차단(#258)
  { label: 'execute: DROP COLUMN', re: /\bDROP\s+COLUMN\b/i },
]
const MARKER_RE = /migration-safety:\s*destructive-ok/i
const DEF_RE = /^(?:async\s+)?def\s+(\w+)/
const CLASS_RE = /^(?:async\s+)?class\s/

function detect(stmt) {
  const hit = OP_DESTRUCTIVE.find((d) => d.re.test(stmt.code))
  if (hit) return hit.label
  if (EXEC_RE.test(stmt.code)) {
    for (const s of stmt.strings) {
      const norm = normalizeSql(s)
      const sqlHit = SQL_DESTRUCTIVE.find((d) => d.re.test(norm))
      if (sqlHit) return sqlHit.label
    }
  }
  return null
}

const failures = []
for (const f of migrationFiles) {
  const stmts = tokenize(fileText.get(f))
  let inScope = false        // upgrade 계열 함수 본문 안인가
  let leadingMarker = false  // 바로 앞 주석줄에 승인마커가 있었나
  for (const stmt of stmts) {
    const codeT = stmt.code.trim()
    // 모듈-레벨(col0) def/class/기타 문장 → 스코프 전환
    if (stmt.col0 && codeT) {
      const m = DEF_RE.exec(codeT)
      if (m) inScope = /^upgrade/.test(m[1])       // upgrade·upgrade_engineN → 스캔, downgrade*·기타 → 제외
      else if (CLASS_RE.test(codeT)) inScope = false
      else inScope = false                          // 모듈-레벨 import·assignment 등 = 함수 밖
      leadingMarker = false
      continue
    }
    // 주석-전용 문장(코드 없음) → 다음 문장용 leadingMarker 갱신
    if (!codeT) {
      if (stmt.comments.trim()) leadingMarker = MARKER_RE.test(stmt.comments)
      continue
    }
    // 실행 문장 — upgrade 계열 안에서만 판정
    if (inScope) {
      const label = detect(stmt)
      if (label) {
        const credited = MARKER_RE.test(stmt.comments) || leadingMarker
        if (!credited) {
          const snippet = stmt.code.trim().replace(/\s+/g, ' ').slice(0, 80)
          failures.push({ file: f, label, snippet })
        }
      }
    }
    leadingMarker = false
  }
}

if (failures.length > 0) {
  console.error('\n✖ Alembic 파괴적 DDL 게이트 실패 — 승인마커 없는 데이터-손실 DDL(upgrade 계열):')
  for (const { file, label, snippet } of failures) {
    console.error(`  • ${label}  (${file})`)
    console.error(`      ${snippet}`)
  }
  console.error('\n  파괴 DDL은 CI(빈 DB)는 통과하고 운영(기존 데이터)에서만 비가역 손실을 냅니다.')
  console.error('  해결:')
  console.error('    • 정당한 변경(예: forward-only 2단계 배포의 컬럼 제거)이면 파괴 op와 같은 문장(또는 바로 앞 줄)에')
  console.error('      승인 주석을 답니다:  # migration-safety: destructive-ok')
  console.error('    • 아니면 파괴 DDL을 제거하고 forward-only(새 리비전 추가) 경로로 대체하세요.')
  console.error('  단일 출처: docs/db-standards.md · docs/specs/alembic-destructive-ddl.md\n')
  process.exit(1)
}

console.log(`✓ Alembic 파괴적 DDL 게이트 통과 — 마이그레이션 ${migrationFiles.length}개 · upgrade 계열에 승인 없는 파괴 DDL 없음`)
process.exit(0)
