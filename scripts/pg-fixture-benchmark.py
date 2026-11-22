import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'lalalune/thenetwork-1' or not os.environ.get('GITHUB_REF', '').startswith('refs/heads/codex/pg-fixture-benchmark-'):
    raise SystemExit('This experiment runs only in its isolated fork workflow')

fixture = Path('packages/network/test/service-apps.test.ts')
original = fixture.read_text()
replace_call = 'await applySchema(URL_, { reset: true, lockTimeout: "5s" });'
assert original.count(replace_call) == 29
patched = original.replace(replace_call, 'await benchmarkSchemaReset();')
anchor = 'let sql: SQL;'
assert patched.count(anchor) == 1
patched = patched.replace(anchor, '''let sql: SQL;
const benchmarkMode = process.env.PG_FIXTURE_BENCH_MODE;
if (benchmarkMode !== "reset" && benchmarkMode !== "clone") throw new Error("Missing benchmark mode");
const TEMPLATE = `network_service_apps_template_${process.pid}`;
const TEMPLATE_URL = new URL(ADMIN_URL);
TEMPLATE_URL.pathname = `/${TEMPLATE}`;
let templateAdmin: SQL | undefined;
let benchmarkSetupMs = 0;
let benchmarkCleanupMs = 0;
const benchmarkResetMs: number[] = [];

async function benchmarkSchemaReset() {
  const start = performance.now();
  if (benchmarkMode === "clone") {
    if (!templateAdmin) throw new Error("Template is unavailable");
    await sql.close();
    await templateAdmin.unsafe(`drop database if exists ${DB}`);
    await templateAdmin.unsafe(`create database ${DB} template ${TEMPLATE}`);
    sql = new SQL({ url: URL_, max: 2 });
  } else {
    await applySchema(URL_, { reset: true, lockTimeout: "5s" });
  }
  benchmarkResetMs.push(performance.now() - start);
}''')
original_setup = '''    await admin(`drop database if exists ${DB} with (force)`);
    await admin(`create database ${DB}`);
    sql = new SQL({ url: URL_, max: 2 });'''
assert patched.count(original_setup) == 1
patched = patched.replace(original_setup, '''    const start = performance.now();
    if (benchmarkMode === "clone") {
      templateAdmin = new SQL({ url: ADMIN_URL, max: 1 });
      await templateAdmin.unsafe("set lock_timeout = '5s'");
      await templateAdmin.unsafe(`create database ${TEMPLATE}`);
      await applySchema(TEMPLATE_URL.href, { lockTimeout: "5s" });
      await templateAdmin.unsafe(`alter database ${TEMPLATE} allow_connections false`);
    } else {
      await admin(`drop database if exists ${DB} with (force)`);
      await admin(`create database ${DB}`);
    }
    sql = new SQL({ url: URL_, max: 2 });
    benchmarkSetupMs = performance.now() - start;''')
original_cleanup = '''    await sql?.close();
    await admin(`drop database if exists ${DB} with (force)`).catch(() => {});'''
assert patched.count(original_cleanup) == 1
patched = patched.replace(original_cleanup, '''    const start = performance.now();
    await sql?.close();
    if (templateAdmin) {
      try {
        await templateAdmin.unsafe(`drop database if exists ${DB}`);
        await templateAdmin.unsafe(`drop database if exists ${TEMPLATE}`);
      } finally {
        await templateAdmin.close();
      }
    } else {
      await admin(`drop database if exists ${DB} with (force)`).catch(() => {});
    }
    benchmarkCleanupMs = performance.now() - start;
    console.log("PG_RESET_BENCH " + JSON.stringify({ benchmarkMode, benchmarkSetupMs, benchmarkCleanupMs, benchmarkResetMs }));''')

modes = ('reset', 'clone', 'clone', 'reset', 'reset', 'clone')
results = {mode: [] for mode in set(modes)}
try:
    fixture.write_text(patched)
    for mode in modes:
        env = dict(os.environ, PG_FIXTURE_BENCH_MODE=mode, FORCE_COLOR='0', NO_COLOR='1')
        start = time.perf_counter()
        result = subprocess.run(['node', 'node_modules/vitest/vitest.mjs', 'run', '--project', 'integration', str(fixture)], env=env, capture_output=True, text=True)
        wall = time.perf_counter() - start
        output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout + result.stderr)
        records = re.findall(r'PG_RESET_BENCH (\{[^\n]+\})', output)
        if result.returncode or len(records) != 1 or not re.search(r'Tests\s+31 passed', output):
            print(output[-24000:], flush=True)
            raise SystemExit(f'{mode} did not pass all 31 cases or did not record timings')
        record = json.loads(records[0])
        durations = record.pop('benchmarkResetMs')
        if len(durations) != 30:
            raise SystemExit(f'{mode} exercised {len(durations)} refreshes rather than 30')
        sample = dict(wall=wall, setup=record['benchmarkSetupMs'] / 1000, perCase=statistics.median(durations) / 1000, schema=sum(durations) / 1000, cleanup=record['benchmarkCleanupMs'] / 1000)
        results[mode].append(sample)
        print('PG_RESET_SAMPLE ' + json.dumps({'mode': mode, 'cases': 31, 'refreshes': len(durations), **sample}), flush=True)
finally:
    fixture.write_text(original)
for mode in ('reset', 'clone'):
    samples = results[mode]
    print('PG_RESET_SUMMARY ' + json.dumps({'mode': mode, 'trials': len(samples), **{metric: {'p50': statistics.median(x[metric] for x in samples), 'min': min(x[metric] for x in samples), 'max': max(x[metric] for x in samples)} for metric in samples[0]}}), flush=True)
