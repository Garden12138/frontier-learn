import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve, extname, relative } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const files = [...new Set(execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean))].filter(name => existsSync(resolve(root, name)));
const errors = [];
let links = 0;
const withoutFences = value => value.replace(/^(```|~~~)[\s\S]*?^\1[^\n]*$/gm, '');
const slug = value => value.toLowerCase().replace(/<[^>]*>/g, '').replace(/[`*_]/g, '').replace(/[^\p{L}\p{N}_\s-]/gu, '').replace(/ /g, '-');
const anchors = name => {
  const seen = new Map();
  return new Set([...withoutFences(readFileSync(name, 'utf8')).matchAll(/^#{1,6}\s+(.+?)\s*#*$/gm)].map(match => {
    const base = slug(match[1]);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return count ? `${base}-${count}` : base;
  }));
};
for (const name of files.filter(name => name.endsWith('.md'))) {
  const body = withoutFences(readFileSync(resolve(root, name), 'utf8'));
  for (const match of body.matchAll(/!?\[[^\]\n]*\]\((<[^>]*>|[^)\n]*)\)/g)) {
    let target = match[1].replace(/^<|>$/g, '').replace(/\s+"[^"]*"$/, '');
    if (/^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
    const [path, anchor] = target.split('#');
    let decoded;
    try { decoded = decodeURIComponent(path.split('?')[0]); } catch { errors.push(`${name}: 无效链接编码`); continue; }
    const destination = decoded ? resolve(dirname(resolve(root, name)), decoded) : resolve(root, name);
    links++;
    if (!existsSync(destination)) errors.push(`${name}: 文件不存在 ${target}`);
    else if (anchor && extname(destination) === '.md' && !anchors(destination).has(decodeURIComponent(anchor))) errors.push(`${name}: 锚点不存在 ${target}`);
  }
}
const secretPatterns = [
  ['私钥', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
  ['GitHub token', /\b(?:gh[pousr]_[A-Za-z0-9]{32,}|github_pat_[A-Za-z0-9_]{50,})\b/],
  ['模型密钥', /\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b/],
  ['AWS key', /\bAKIA[A-Z0-9]{16}\b/],
];
let scanned = 0;
for (const name of files) {
  const buffer = readFileSync(resolve(root, name));
  if (buffer.includes(0)) continue;
  scanned++;
  for (const [index, line] of buffer.toString('utf8').split('\n').entries()) {
    for (const [label, pattern] of secretPatterns) if (pattern.test(line)) errors.push(`${name}:${index + 1}: 疑似${label}，人工复核（不输出匹配内容）`);
  }
}
const fixtureRoot = 'services/api/tests/fixtures/real-notes/';
const provenance = JSON.parse(readFileSync(resolve(root, fixtureRoot, 'provenance.json'), 'utf8'));
for (const [name, expected] of [['self-attention.txt', provenance.blob_sha], ['chapter03_attention.txt', 'c0c95ce8086cf3966ced015631bf0a1102cfa685']]) {
  const content = readFileSync(resolve(root, fixtureRoot, name));
  const actual = createHash('sha1').update(`blob ${content.length}\0`).update(content).digest('hex');
  if (actual !== expected) errors.push(`${fixtureRoot}${name}: 原始 Git blob SHA 已变化`);
}
const ignored = ['.env.trial', '.local/backups/frontier.dump', 'apps/web/dist/index.html', 'apps/extension/.output/chrome-mv3/manifest.json', 'node_modules/', 'services/api/.venv/'];
for (const name of ignored) {
  try { execFileSync('git', ['check-ignore', '-q', name], { cwd: root }); }
  catch { errors.push(`${name}: 应被 Git 忽略`); }
}
const suspicious = files.filter(name => /(?:^|\/)(?:node_modules|__pycache__|\.venv|\.pytest_cache|test-results|playwright-report)(?:\/|$)/.test(name) || /(?:^|\/)\.env(?:\.|$)/.test(name) && !name.endsWith('.example'));
for (const name of suspicious) errors.push(`${relative(root, resolve(root, name))}: 不应纳入版本控制`);
console.log(JSON.stringify({ result: errors.length ? 'FAIL' : 'PASS', files: files.length, markdown_files: files.filter(name => name.endsWith('.md')).length, local_links_checked: links, text_files_scanned: scanned, fixture_blobs: 2, ignore_checks: ignored.length, errors }, null, 2));
process.exitCode = errors.length ? 1 : 0;
