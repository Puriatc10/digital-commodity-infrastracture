import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

async function loadTs(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
    .replace('"openapi-fetch"', JSON.stringify(import.meta.resolve('openapi-fetch')));
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

test('generated client preserves credentials and sends the current CSRF cookie on mutations', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.window = { location: { origin: 'http://localhost:3000' } };
  globalThis.document = { cookie: 'unrelated=value; csrftoken=first-token' };
  const requests = [];
  globalThis.fetch = async (input, init) => {
    requests.push(new Request(input, init));
    return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
  };
  try {
    const { apiClient, bootstrapCsrf } = await loadTs('../src/lib/api/client.ts');
    await bootstrapCsrf();
    await apiClient.POST('/api/auth/demo-switch', { body: { persona: 'buyer' } });
    globalThis.document.cookie = 'csrftoken=rotated-token';
    await apiClient.PATCH('/api/organizations/{id}/', { params: { path: { id: 'example' } }, body: { name: 'Safe' } });
    assert.equal(requests[0].headers.get('X-CSRFToken'), null);
    assert.equal(requests[1].headers.get('X-CSRFToken'), 'first-token');
    assert.equal(requests[2].headers.get('X-CSRFToken'), 'rotated-token');
    assert.deepEqual(JSON.parse(await requests[1].text()), { persona: 'buyer' });
    for (const request of requests) {
      assert.equal(request.credentials, 'include');
      assert.equal(new URL(request.url).origin, 'http://localhost:3000');
    }
  } finally {
    globalThis.fetch = previousFetch;
    delete globalThis.window;
    delete globalThis.document;
  }
});

test('zero/one/multiple organizations reject stale or foreign preference IDs', async () => {
  const { selectOrganization } = await loadTs('../src/lib/organization-preference.ts');
  const own = { organization: { id: 'own' } };
  const second = { organization: { id: 'second' } };
  assert.equal(selectOrganization([], 'foreign'), null);
  assert.equal(selectOrganization([own], 'foreign'), own);
  assert.equal(selectOrganization([own, second], 'foreign'), own);
  assert.equal(selectOrganization([own, second], 'second'), second);
});

test('only the organization ID is persisted and blocked storage is harmless', async () => {
  const { readOrganizationPreference, saveOrganizationPreference } = await loadTs('../src/lib/organization-preference.ts');
  const values = new Map();
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  try {
    saveOrganizationPreference('own');
    assert.deepEqual([...values], [['commodity_platform_pref_org_id', 'own']]);
    assert.equal(readOrganizationPreference(), 'own');
    saveOrganizationPreference(null);
    assert.equal(values.size, 0);
    globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
    assert.equal(readOrganizationPreference(), null);
    assert.doesNotThrow(() => saveOrganizationPreference('own'));
    assert.doesNotThrow(() => saveOrganizationPreference(null));
  } finally { delete globalThis.localStorage; }
});
