// Install only the pinned 1 MB browser engine network; preserve other LFS assets.
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lock = JSON.parse(await readFile(resolve(root, 'analysis-engine-lock.json'), 'utf8'));
const checkout = resolve(root, 'infra/lila-docker/repos/lila');
const target = resolve(checkout, lock.relative_path);
assert.ok(target.startsWith(checkout + sep));
const hash = data => createHash('sha256').update(data).digest('hex');
const existing = await readFile(target).catch(error => {
  if (error.code !== 'ENOENT') throw error;
  return undefined;
});
const valid = existing?.length === lock.bytes && hash(existing) === lock.sha256;
if (!valid || process.argv.includes('--refresh')) {
  assert.ok(!existing || valid || (existing.toString().startsWith('version https://git-lfs.github.com/spec/v1') && existing.includes(lock.sha256)), 'Refusing to replace a modified model');
  const response = await fetch(lock.url, { signal: AbortSignal.timeout(45000) });
  assert.ok(response.ok, `Model HTTP ${response.status}`);
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > lock.bytes) throw new Error('Model exceeds the pinned size');
    chunks.push(chunk);
  }
  const data = Buffer.concat(chunks);
  assert.equal(data.length, lock.bytes);
  assert.equal(hash(data), lock.sha256);
  await mkdir(dirname(target), { recursive: true });
  const temporary = target + '.' + randomUUID() + '.tmp';
  await writeFile(temporary, data, { flag: 'wx' });
  try {
    const current = await readFile(target).catch(error => { if (error.code === 'ENOENT') return undefined; throw error; });
    assert.equal(current && hash(current), existing && hash(existing), 'Model changed during download');
    await rename(temporary, target);
  } finally {
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}
const ready = await readFile(target);
assert.equal(ready.length, lock.bytes);
assert.equal(hash(ready), lock.sha256);
console.log(JSON.stringify({ engine: lock.engine, name: lock.name, bytes: ready.length, sha256: hash(ready), ready: true }));
