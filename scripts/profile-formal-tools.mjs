import childProcess from "node:child_process";
import { appendFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { basename } from "node:path";

const file = process.env.VIBESTACK_TOOL_TIMINGS;
const profiler = Symbol.for("vibestack.profile-formal-tools");

if (file && !childProcess[profiler]) {
  const original = childProcess.spawn;
  const known = new Set(["quint", "quint_evaluator", "lemmascript", "lsc", "dafny", "z3", "vibelang", "vitest", "bombadil"]);
  const modes = new Set(["run", "compile", "typecheck", "gen", "gen-check", "verify", "audit", "simulate-from-stdin", "test-from-stdin"]);
  let nextId = 0;
  const publicName = (value) => typeof value === "string" && /^[-.\w]+$/.test(value) ? value : undefined;
  const opt = (args, flag) => {
    const at = args.indexOf(flag);
    return at === -1 ? undefined : publicName(args[at + 1]);
  };
  const describe = (exe, args, options) => {
    const executable = basename(exe).replace(/\.(?:exe|cmd)$/i, "");
    const entrypoint = args[0] && basename(args[0]);
    const tool = executable === "node" && entrypoint === "simulator.ts" ? "simulator" :
      executable === "node" && entrypoint === "dafny-emit.js" ? "lsc" : executable;
    if (!known.has(tool) && tool !== "simulator") return undefined;
    const command = args[tool === "simulator" || executable === "node" ? 1 : 0];
    const dir = typeof options?.cwd === "string" ? options.cwd.match(/(?:^|\/)gen\/(?:traces|proof)\/([a-zA-Z_][\w-]*)(?:[./]|$)/)?.[1] : undefined;
    const main = opt(args, "--main");
    const unit = publicName(args.find(arg => typeof arg === "string" && /^[-.\w]+\.(?:dfy(?:\.gen)?|qnt|ts)$/.test(arg)));
    return {
      tool, mode: modes.has(command) ? command : undefined,
      model: main?.replace(/_run$/, "") ?? dir,
      unit,
      invariant: opt(args, "--invariant"), step: opt(args, "--step"),
      samples: opt(args, "--max-samples"), depth: opt(args, "--max-steps"),
    };
  };
  const emit = (row) => {
    try { appendFileSync(file, JSON.stringify(row) + "\n"); } catch { /* Timing must not interrupt a check. */ }
  };
  childProcess.spawn = function (...values) {
    const [exe, args, options] = values;
    const record = typeof exe === "string" && Array.isArray(args) ? describe(exe, args, options) : undefined;
    if (!record) return original.apply(this, values);

    const start = process.hrtime.bigint();
    const child = original.apply(this, values);
    const id = ++nextId;
    const identity = { pid: process.pid, child: child.pid, id, ...record };
    emit({ ...identity, phase: "start", time_ms: Date.now() });
    child.once("close", (status, signal) => {
      emit({ ...identity, phase: "end", time_ms: Date.now(), elapsed_ms: Number(process.hrtime.bigint() - start) / 1e6, status, signal });
    });
    return child;
  };
  Object.defineProperty(childProcess, profiler, { value: true });
  syncBuiltinESMExports();
}
