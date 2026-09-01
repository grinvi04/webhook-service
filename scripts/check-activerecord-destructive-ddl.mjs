#!/usr/bin/env node
/*
 * ActiveRecord 파괴적 DDL 정적 게이트 — Rails db/migrate/*.rb 마이그레이션의 def change/def up 경로에
 *   있는 비가역 데이터-손실 DDL을 배포 전 결정적으로 차단한다. SQL판(check-destructive-ddl.mjs)·
 *   Alembic판(check-alembic-destructive-ddl.mjs)의 .rb 축 형제(같은 정책·같은 승인마커).
 *
 * 운영 장애 클래스: CI는 빈 DB에 마이그레이션을 처음부터 적용하므로 drop_table/remove_column이 있어도
 *   "지울 데이터가 없어" 통과한다(liveness ≠ 데이터 보존). 운영(기존 데이터)에서만 비가역 손실.
 *
 * 스캔 범위 — 순방향 함수 본문만(핵심):
 *   ActiveRecord는 `def down`(역방향=롤백)에 파괴 op를 담는 게 정상이다(up의 add_column을 down의
 *   remove_column으로 되돌림). 파일 전체를 스캔하면 정상 up/down 마이그레이션이 오탐된다. 배포 시
 *   적용되는 것은 `def change`·`def up`이므로 그 경로만 본다(Alembic upgrade()만 스캔과 동형). def down은 비대상.
 *
 * 정책(team-harness): 체크 가능한 규칙은 prose가 아니라 결정적 게이트로. 단, Ruby도 정규언어가 아니므로
 *   **흔한 데이터-손실 형태만** 잡는다(종단 우회는 계층0 코드리뷰 소관 — decisions.md 판정 철학).
 *   - 파괴 판정(수신자 무관 — 별칭·connection. 모두, ActiveRecord DSL은 괄호 생략 가능):
 *       drop_table · drop_join_table · remove_column · remove_columns ·
 *       execute/exec_query/exec_update/exec_delete 내 raw DROP TABLE/DATABASE/SCHEMA·TRUNCATE·DROP COLUMN
 *       (문자열·heredoc 본문 — SQL 라인주석 dash-dash·hash, C-스타일 블록주석 제거 후 검사).
 *   - 비대상(오탐 금지): remove_index/remove_foreign_key(데이터-행 손실 아님 — SQL판 DROP INDEX와 동형).
 *   - forward-only 2단계 배포(db-standards.md §마이그레이션)의 정당한 DROP은 **승인마커**로 통과:
 *       파괴 op와 같은 논리 문장(트레일링) 또는 바로 앞 주석줄의 실제 `#` 주석 `# migration-safety: destructive-ok`.
 *
 * 반증(anti-spoof): `#` 라인주석·`=begin`/`=end` 블록주석·문자열('..','".."')·heredoc 본문 안의 파괴
 *   키워드는 무시하고, 승인마커도 **실제 # 주석 안**일 때만 인정한다(문자열 값 스푸핑 차단). execute의 raw
 *   SQL은 SQL 블록주석·라인주석(--)·SQL 문자열 리터럴을 제거한 뒤 검사한다(블록주석 토큰-분리 우회 차단:
 *   DROP<블록주석>TABLE가 유효 SQL — SQL판 v0.31.0 봉쇄와 동형). heredoc(<<~/<<-/<< + 따옴표) 본문은
 *   strings로 보존해 execute raw SQL 검사에 넣는다(execute(<<~SQL … DROP TABLE … SQL) 관용구 인식).
 *   검증은 통과가 아니라 우회 실패로 확정 — tests/activerecord-destructive-ddl-test.sh의 스푸핑·우회 픽스처.
 *
 * ⚠ 적용 범위 — **ActiveRecord 마이그레이션 .rb 전용**(지문 기반, 경로 무관):
 *   `< ActiveRecord::Migration` **그리고** `def (change|up|down)` 지문을 가진 .rb만 대상. 지문 없는 .rb
 *   (앱 모델·헬퍼)는 비대상.
 *   - 한계(흔한 형태만·계층0 정본): def change/up 밖 헬퍼 함수로 숨긴 파괴 op·동적 SQL 조립·인접 문자열
 *     리터럴 연접(`execute("DROP " "TABLE …")`)·`%w[]`/`%q()` 등 %리터럴 속 DROP·정규식 리터럴 속 키워드·
 *     change_table 블록의 `t.remove`(별칭)·`remove_reference`·무공백 소문자 heredoc(`x<<foo`)은 미검출.
 *   - reversible: `reversible do |dir| dir.up{…}; dir.down{…} end`의 dir.up 파괴는 미검출(FN), dir.down 파괴는
 *     역방향이지만 def change 본문이라 오탐(FP)될 수 있다 — 정당한 dir.down 파괴엔 승인마커를 단다.
 *
 * 단일 출처: docs/db-standards.md · docs/specs/rails-stack-completion.md
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const args = process.argv.slice(2)
if (args.includes('--help') || args.includes('-h')) {
  console.log(`ActiveRecord 파괴적 DDL 게이트 — .rb 마이그레이션 def change/def up의 비가역 데이터-손실 DDL을 배포 전 차단

사용법:
  node scripts/check-activerecord-destructive-ddl.mjs [루트경로 …]

파괴 판정: drop_table · drop_join_table · remove_column(s) (수신자 무관·괄호 생략 가능) · execute 내 raw DROP/TRUNCATE
비대상   : remove_index/remove_foreign_key (데이터-손실 아님) · def down(역방향=롤백)
승인마커 : 파괴 op와 같은 문장(트레일링) 또는 바로 앞 주석줄의 실제 # 주석 \`# migration-safety: destructive-ok\`
스캔대상 : \`< ActiveRecord::Migration\` + \`def (change|up|down)\` 지문을 가진 .rb (경로 무관, 지문 없으면 비대상)

종료 코드:
  0  통과 또는 skip(ActiveRecord 마이그레이션 없음 — 오탐 금지)
  1  FAIL — 승인마커 없는 파괴 DDL 발견
  2  사용법 오류 — 미인식 옵션
`)
  process.exit(0)
}

// 미인식 옵션 → 사용법 오류(SQL·Alembic판 규약과 일치)
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

// ActiveRecord 마이그레이션 지문: `< ActiveRecord::Migration` 상속 + change/up/down 메서드 정의.
//   레거시 Rails 2.x/3.x 클래스-메서드 `def self.up`/`def self.down`도 지문·스코프에서 인식(self. 흡수).
const HAS_AR = /<\s*ActiveRecord::Migration/
const HAS_METHOD = /\bdef\s+(?:self\.)?(?:change|up|down)\b/

const rbFiles = []
for (const root of roots) {
  walk(root, (p, name) => { if (/\.rb$/i.test(name)) rbFiles.push(p) })
}

const migrationFiles = []
const fileText = new Map()
for (const f of rbFiles) {
  let text
  try { text = readFileSync(f, 'utf8') } catch { continue }
  if (HAS_AR.test(text) && HAS_METHOD.test(text)) {
    migrationFiles.push(f)
    fileText.set(f, text)
  }
}

// ── skip: ActiveRecord 마이그레이션 없음 (오탐 금지) ────────
if (migrationFiles.length === 0) {
  console.log('• ActiveRecord 파괴 DDL 게이트: 마이그레이션 .rb 없음 — 통과(skip)')
  console.log('  대상: `< ActiveRecord::Migration` + `def (change|up|down)` 지문을 가진 .rb.')
  process.exit(0)
}

// ── Ruby-인식 토크나이저: 파일 전체를 논리 문장으로 분해 ──────────────────
//   각 문장 → { code, comments, strings }:
//     code     = # 주석·문자열 리터럴·heredoc·=begin 제거본(op 호출 탐지용 — 리터럴 속 키워드 무시).
//     comments = 실제 # 주석 내용만(승인마커 탐지용 — 문자열 값 스푸핑 배제).
//     strings  = 문자열 리터럴 값 + heredoc 본문 배열(execute 문장의 raw DROP 내용 검사용).
//   논리 문장 경계 = 괄호/대괄호/중괄호 depth 0에서의 개행 또는 `;`(다중행 호출은 한 문장, 세미콜론
//     결합 문장은 분리 — 마커 오귀속 차단). heredoc 본문은 문장을 끊지 않는다(호출 인자의 일부).
//   =begin/=end = 줄-앵커 블록주석(첫 컬럼의 =begin … =end). heredoc = <<~/<<-/<< + (따옴표)식별자.

function scanQuoted(src, i, quote) {
  // i는 여는 따옴표 다음. Ruby는 \" 로 문자열이 안 끝난다(백슬래시 이스케이프).
  const n = src.length
  let val = ''
  while (i < n) {
    if (src[i] === '\\') { val += src[i] + (src[i + 1] ?? ''); i += 2; continue }
    if (src[i] === quote) { i++; break }
    val += src[i]; i++
  }
  return { end: i, val }
}

// heredoc 시작 판정: <<~ / <<- (스퀴글/대시 = 명확히 heredoc) · << + 따옴표 · << + 대문자식별자.
//   좌시프트(a << b, x<<2)·append(arr << item, 소문자·공백)는 배제. best-effort(문서화된 계층0).
const HEREDOC_RE = /^<<([~-])?(['"]?)([A-Za-z_]\w*)\2/

function tokenize(src) {
  const stmts = []
  let code = '', comments = '', strings = []
  let depth = 0
  const pendingHeredocs = [] // { term }
  const push = () => {
    if (code.trim() || comments.trim() || strings.length) {
      stmts.push({ code, comments, strings })
    }
    code = ''; comments = ''; strings = []
  }
  // heredoc 본문 소비: i가 개행 다음(줄 시작)일 때 호출. term 줄까지 본문을 strings에 담는다.
  const consumeHeredocs = (src, i, n) => {
    while (pendingHeredocs.length) {
      const h = pendingHeredocs.shift()
      let body = ''
      while (i < n) {
        let ls = i
        while (i < n && src[i] !== '\n') i++
        const line = src.slice(ls, i)
        if (i < n) i++ // 개행 소비
        if (line.trim() === h.term) break
        body += line + '\n'
      }
      strings.push(body)
    }
    return i
  }
  let i = 0
  const n = src.length
  let atLineStart = true // 현재 위치가 물리적 줄의 첫 문자인가(=begin·terminator 판정용)
  while (i < n) {
    const c = src[i]
    // =begin/=end 블록주석(첫 컬럼의 =begin 으로 시작하는 줄 ~ =end 줄) → 통째 폐기.
    //   comments 채널에 넣지 않는다: 승인마커는 실제 `#` 주석만 인정한다(AC-5 — =begin 속 마커 스푸핑 거부).
    if (atLineStart && c === '=' && src.startsWith('=begin', i)) {
      while (i < n) {
        let ls = i
        while (i < n && src[i] !== '\n') i++
        const line = src.slice(ls, i)
        if (i < n) i++
        if (/^=end\b/.test(line)) break
      }
      atLineStart = true
      continue
    }
    // 라인 주석 # … EOL
    if (c === '#') {
      let j = i + 1
      while (j < n && src[j] !== '\n') j++
      comments += src.slice(i + 1, j) + '\n'
      i = j
      atLineStart = false
      continue
    }
    // 문자열 리터럴 '..' / ".." → strings에 값 보존, code엔 공백(토큰 병합 방지)
    if (c === "'" || c === '"') {
      const { end, val } = scanQuoted(src, i + 1, c)
      strings.push(val)
      code += ' '
      i = end
      atLineStart = false
      continue
    }
    // heredoc 시작(<<~SQL 등) → 본문은 다음 줄부터. 지금은 식별자를 등록만 하고 code에서 제외.
    if (c === '<' && src[i + 1] === '<') {
      const m = HEREDOC_RE.exec(src.slice(i, i + 64))
      // 진짜 heredoc만: <<~/<<- (스퀴글·대시) 또는 따옴표 식별자 또는 대문자 식별자.
      //   무공백 소문자 bare `<<val`(append/좌시프트)을 heredoc으로 오판해 뒷줄(drop 포함)을 삼키는 것 방지.
      if (m && (m[1] || m[2] || /^[A-Z]/.test(m[3]))) {
        pendingHeredocs.push({ term: m[3] })
        code += ' '
        i += m[0].length
        atLineStart = false
        continue
      }
      // heredoc 아님 → 좌시프트 등, 그대로 code로(두 문자)
      code += '<<'
      i += 2
      atLineStart = false
      continue
    }
    // 문장 종결: depth 0에서의 개행 또는 세미콜론
    if (c === '\n') {
      if (pendingHeredocs.length) {
        i = consumeHeredocs(src, i + 1, n) // 개행 다음부터 본문 소비
        if (depth === 0) push()
        else code += ' '
        atLineStart = true
        continue
      }
      if (depth === 0) push()
      else code += ' '
      i++
      atLineStart = true
      continue
    }
    if (c === ';' && depth === 0) { push(); i++; atLineStart = false; continue }
    if (c === '(' || c === '[' || c === '{') depth++
    else if (c === ')' || c === ']' || c === '}') { if (depth > 0) depth-- }
    code += c
    if (c !== ' ' && c !== '\t' && c !== '\r') atLineStart = false
    i++
  }
  // 파일 끝에 남은 heredoc 본문
  if (pendingHeredocs.length) consumeHeredocs(src, n, n)
  push()
  return stmts
}

// ── SQL 정규화(execute 내 raw SQL 검사 전) — SQL 주석·문자열 리터럴 제거 ──────────
//   블록주석 토큰-분리(DROP/*x*/TABLE) 우회 차단 + SQL 문자열 값 속 키워드 오탐 방지(SQL·Alembic판 동형).
function normalizeSql(s) {
  let out = ''
  let i = 0
  const n = s.length
  while (i < n) {
    const c = s[i], c2 = s[i + 1]
    if (c === '-' && c2 === '-') { while (i < n && s[i] !== '\n') i++; out += ' '; continue }
    if (c === '#') {
      if (c2 === '{') { // Ruby 인터폴레이션 #{…} — SQL 주석 아님. 균형 중괄호만 중립화(줄 끝까지 삭제 금지 → 뒤 DROP 보존).
        i += 2
        let bd = 1
        while (i < n && bd > 0) { if (s[i] === '{') bd++; else if (s[i] === '}') bd--; i++ }
        out += ' '; continue
      }
      while (i < n && s[i] !== '\n') i++; out += ' '; continue // MySQL '#' 라인주석 토큰-분리 차단
    }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(s[i] === '*' && s[i + 1] === '/')) i++; i = i < n ? i + 2 : n; out += ' '; continue }
    if (c === "'") { i++; while (i < n) { if (s[i] === "'" && s[i + 1] === "'") { i += 2; continue } if (s[i] === "'") { i++; break } i++ } out += ' '; continue }
    out += c; i++
  }
  return out
}

// ── 파괴 판정 규칙 ──────────────────────────────────────────
// 수신자 무관 — 별칭·connection. 모두 매칭. ActiveRecord DSL은 괄호 생략 가능 → `\s*[( ]`(괄호 또는 공백).
const OP_DESTRUCTIVE = [
  { label: 'drop_table', re: /\bdrop_table\s*[( ]/ },
  { label: 'drop_join_table', re: /\bdrop_join_table\s*[( ]/ },
  { label: 'remove_column(s)', re: /\bremove_columns?\s*[( ]/ },
]
// execute + 저수준 raw-SQL 실행 계열(exec_query/update/delete — 같은 데이터-손실 벡터). 수신자 무관.
const EXEC_RE = /\b(?:execute|exec_query|exec_update|exec_delete)\b/
// execute 내 raw SQL 파괴 키워드 — SQL·Alembic판과 동일 세트.
const SQL_DESTRUCTIVE = [
  { label: 'execute: DROP TABLE', re: /\bDROP\s+TABLE\b/i },
  { label: 'execute: DROP DATABASE', re: /\bDROP\s+DATABASE\b/i },
  { label: 'execute: DROP SCHEMA', re: /\bDROP\s+SCHEMA\b/i },
  { label: 'execute: TRUNCATE', re: /\bTRUNCATE\b(?!\s*\()/i }, // TRUNCATE(x,d) 수치함수 제외(오탐), TRUNCATE [TABLE] t는 차단
  { label: 'execute: DROP COLUMN', re: /\bDROP\s+COLUMN\b/i },
]
const MARKER_RE = /migration-safety:\s*destructive-ok/i
const DEF_RE = /^(?:private\s+|protected\s+|public\s+)?def\s+(?:self\.)?(\w+)/
// def change/up 본문 스코프 추적용 — do/블록 키워드 openers, end closers.
const OPENER_LEAD = /^(?:class|module|begin|case|if|unless|while|until|for)\b/
const TRAILING_DO = /\bdo\b(?:\s*\|[^|]*\|)?\s*$/
const IS_END = /^end\b/

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
  let depth = 0            // 블록 중첩(def/class/do/if…end)
  let defName = null       // 현재 직접 속한 def 이름(null=함수 밖)
  let defDepth = -1        // 그 def가 열린 depth
  let leadingMarker = false // 바로 앞 주석줄에 승인마커가 있었나
  for (const stmt of stmts) {
    const codeT = stmt.code.trim()
    // 주석-전용 문장(코드 없음) → 다음 문장용 leadingMarker 갱신
    if (!codeT) {
      if (stmt.comments.trim()) leadingMarker = MARKER_RE.test(stmt.comments)
      continue
    }
    const defM = DEF_RE.exec(codeT)
    if (defM) {
      // def 진입 — 이 문장 자체는 파괴 op 아님. 스코프만 전환.
      defName = defM[1]
      defDepth = depth
      depth += 1
      leadingMarker = false
      continue
    }
    // def change/up 본문 안에서만 판정
    const inScope = defName === 'change' || defName === 'up'
    if (inScope) {
      const label = detect(stmt)
      if (label) {
        const credited = MARKER_RE.test(stmt.comments) || leadingMarker
        if (!credited) {
          const snippet = codeT.replace(/\s+/g, ' ').slice(0, 80)
          failures.push({ file: f, label, snippet })
        }
      }
    }
    // 이 문장의 블록 depth 순변화 반영(openers +1, end -1)
    if (OPENER_LEAD.test(codeT)) depth += 1
    if (TRAILING_DO.test(codeT)) depth += 1
    if (IS_END.test(codeT)) depth -= 1
    if (defName !== null && depth <= defDepth) { defName = null; defDepth = -1 }
    leadingMarker = false
  }
}

if (failures.length > 0) {
  console.error('\n✖ ActiveRecord 파괴적 DDL 게이트 실패 — 승인마커 없는 데이터-손실 DDL(def change/def up):')
  for (const { file, label, snippet } of failures) {
    console.error(`  • ${label}  (${file})`)
    console.error(`      ${snippet}`)
  }
  console.error('\n  파괴 DDL은 CI(빈 DB)는 통과하고 운영(기존 데이터)에서만 비가역 손실을 냅니다.')
  console.error('  해결:')
  console.error('    • 정당한 변경(예: forward-only 2단계 배포의 컬럼 제거)이면 파괴 op와 같은 문장(또는 바로 앞 줄)에')
  console.error('      승인 주석을 답니다:  # migration-safety: destructive-ok')
  console.error('    • 아니면 파괴 DDL을 제거하고 forward-only(새 마이그레이션 추가) 경로로 대체하세요.')
  console.error('  단일 출처: docs/db-standards.md · docs/specs/rails-stack-completion.md\n')
  process.exit(1)
}

console.log(`✓ ActiveRecord 파괴적 DDL 게이트 통과 — 마이그레이션 ${migrationFiles.length}개 · def change/up에 승인 없는 파괴 DDL 없음`)
process.exit(0)
