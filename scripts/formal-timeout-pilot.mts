import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout } from "node:timers/promises";
import { performance } from "node:perf_hooks";
import { gunzipSync } from "node:zlib";
import { formalFiles, prepareProject } from "./vibestack.ts";
import { act } from "../tools/vibestack/vibestack/action.ts";
import { withFormalCache } from "../tools/vibestack/vibestack/cache.ts";
import { modules, readSpecs } from "../tools/vibestack/vibestack/parse.ts";

const [mode, expected] = process.argv.slice(2);
const project = join(process.env.RUNNER_TEMP!, "formal-timeout-project");
const actionDir = join(project, "gen", "typecheck");
const live = join(process.cwd(), ".spec-cache", "formal");
const archive = join(process.cwd(), ".cache", "formal-timeout-pilot");
const entryPattern = /^action-[a-f0-9]{24}\.json\.gz$/;
const digest = (bytes: Uint8Array | string) => createHash("sha256").update(bytes).digest("hex");
function verify(dir: string) {
  const entries = readdirSync(dir).filter(name => entryPattern.test(name) && lstatSync(join(dir, name)).isFile());
  assert.equal(entries.length, 1);
  const [name] = entries;
  const bytes = readFileSync(join(dir, name));
  const ran = JSON.parse(gunzipSync(bytes).toString("utf8"));
  assert.equal(ran.ok, true);
  assert.equal(ran.status, 0);
  assert.equal(ran.stopped, undefined);
  const ir = ran.files["ir.json"];
  assert.ok(JSON.parse(ir).modules.some(({ name }) => name === "brandIdentity"));
  return { name, bytes, ir };
}

if (mode === "export") {
  assert.ok(existsSync(join(project, ".spec-cache", "unfinished-projection.json")));
  assert.ok(readdirSync(live).some(name => name.endsWith(".tmp")));
  const { name, bytes, ir } = verify(live);
  mkdirSync(archive, { recursive: true });
  writeFileSync(join(archive, name), bytes);
  writeFileSync(process.env.GITHUB_OUTPUT!, `digest=${digest(ir)}\n`, { flag: "a" });
  console.log(`Exported one completed raw action (${bytes.length} bytes); ignored projection and incomplete atomic-write sentinel`);
} else {
  const producing = mode === "produce";
  assert.ok(producing || mode === "consume");
  prepareProject(project, formalFiles());
  const specs = readSpecs(project);
  const spec = specs.find(spec => spec.name === "brandIdentity");
  assert.ok(spec);
  if (producing) assert.equal(existsSync(live), false);
  else {
    const { ir } = verify(archive);
    assert.equal(readdirSync(archive).length, 1);
    assert.equal(digest(ir), expected);
  }
  const start = performance.now();
  const result = await withFormalCache(producing ? live : archive, () => act(
    { root: project, fresh: false, used: new Set() },
    "quint", ["typecheck", "--out", "ir.json", "brandIdentity.qnt"], actionDir, modules(spec, specs),
  ));
  const ms = Math.round(performance.now() - start);
  assert.equal(result.ok, true);
  assert.equal(existsSync(actionDir), producing);
  if (producing) {
    const { name, ir } = verify(live);
    assert.equal(result.files["ir.json"], ir);
    mkdirSync(join(project, ".spec-cache"), { recursive: true });
    writeFileSync(join(project, ".spec-cache", "unfinished-projection.json"), "{}");
    writeFileSync(join(live, `${name}.123.unfinished.tmp`), "simulated interrupted write");
    console.log(`Cold raw action ran in ${ms} ms; ${digest(ir)}. Waiting for the timeout after the completed action.`);
    await setTimeout(120_000);
    throw new Error("GNU timeout did not stop the probe");
  }
  assert.equal(digest(result.files["ir.json"]), expected);
  assert.equal(existsSync(join(project, ".spec-cache")), false);
  console.log(`Restored raw action reused in ${ms} ms with no Quint work directory; ${expected}`);
}
