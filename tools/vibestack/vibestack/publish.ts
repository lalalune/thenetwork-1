import { constants, copyFileSync, linkSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync } from "node:fs";
import { dirname, join, relative } from "node:path";

const stat = (file: string) => lstatSync(file, { throwIfNoEntry: false });

function entries(directory: string) {
  return new Map(readdirSync(directory, { recursive: true, withFileTypes: true }).map(entry => [relative(directory, join(entry.parentPath, entry.name)), entry]));
}

function sameFile(source: string, target: string): boolean {
  const sourceInfo = lstatSync(source);
  const targetInfo = stat(target);
  return targetInfo?.isFile() === true && sourceInfo.size === targetInfo.size && sourceInfo.mode === targetInfo.mode
    && readFileSync(source).equals(readFileSync(target));
}

function linkMatchingFile(target: string, staged: string): boolean {
  try {
    linkSync(target, staged);
  } catch (error) {
    if (error instanceof Error && "code" in error && ["EACCES", "EMLINK", "ENOSYS", "ENOTSUP", "EPERM", "EXDEV"].includes(String(error.code))) return false;
    throw error;
  }
  if (!lstatSync(staged).isFile()) throw new Error(`Generated output changed during publication: ${target}`);
  return true;
}

export function publishGeneratedTree(source: string, target: string): void {
  if (!stat(source)?.isDirectory()) throw new Error(`Expected a generated directory: ${source}`);
  const incoming = entries(source);
  const current = stat(target);
  const previous = current?.isDirectory() ? entries(target) : undefined;
  const matching = new Set<string>();
  for (const [file, entry] of incoming) {
    const old = previous?.get(file);
    if (entry.isDirectory()) {
      if (old?.isDirectory()) matching.add(file);
    } else if (entry.isFile()) {
      if (old?.isFile() && sameFile(join(source, file), join(target, file))) matching.add(file);
    } else throw new Error(`Expected a regular generated file or directory: ${join(source, file)}`);
  }
  if (matching.size === incoming.size && previous?.size === incoming.size) return;

  const publication = mkdtempSync(join(dirname(target), ".gen-publication-"));
  const ready = join(publication, "ready");
  const backup = join(publication, "previous");
  let preserveBackup = false;
  try {
    mkdirSync(ready);
    for (const [file, entry] of incoming) {
      if (entry.isDirectory()) mkdirSync(join(ready, file), { recursive: true });
    }
    for (const [file, entry] of incoming) {
      if (entry.isDirectory()) continue;
      const destination = join(ready, file);
      if (!matching.has(file) || !linkMatchingFile(join(target, file), destination)) {
        copyFileSync(join(source, file), destination, constants.COPYFILE_EXCL);
      }
    }
    if (current) renameSync(target, backup);
    try {
      renameSync(ready, target);
    } catch (error) {
      if (current) {
        preserveBackup = true;
        try {
          renameSync(backup, target);
          preserveBackup = false;
        } catch (restoreError) {
          throw new AggregateError([error, restoreError], `Could not restore generated output. The previous tree is at ${backup}.`);
        }
      }
      throw error;
    }
  } finally {
    if (!preserveBackup) rmSync(publication, { recursive: true, force: true });
  }
}
