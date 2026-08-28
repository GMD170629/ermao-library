import { readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

async function findTests(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const tests = [];

  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      tests.push(...(await findTests(entryPath)));
    } else if (entry.name.endsWith(".test.ts")) {
      tests.push(entryPath);
    }
  }

  return tests;
}

const tests = (await Promise.all([findTests("lib"), findTests("features"), findTests("shared")]))
  .flat()
  .sort();

if (tests.length === 0) {
  console.error("No test files found under lib, features or shared.");
  process.exit(1);
}

const command = process.platform === "win32" ? "tsx.cmd" : "tsx";
const result = spawnSync(command, ["--test", ...tests], {
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
