import { spawnSync } from 'node:child_process';

const steps = [
  ['pnpm', ['install', '--frozen-lockfile']],
  ['pnpm', ['--filter', '@shuku/web', 'generate:api-v2']],
  ['git', ['diff', '--exit-code', '--', 'apps/web/generated/api-v2.ts']],
  ['pnpm', ['verify:python-backend']],
  ['pnpm', ['typecheck']],
  ['pnpm', ['--filter', '@shuku/web', 'i18n:check']],
  ['pnpm', ['--filter', '@shuku/web', 'test', '--', '--run']],
  ['pnpm', ['build']]
];

if (process.env.VERIFY_WEB_E2E === 'true') {
  steps.push(['pnpm', ['--filter', '@shuku/web', 'test:e2e:release']]);
}

for (const [command, args] of steps) {
  console.log(`\n$ ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, { stdio: 'inherit', shell: false });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

console.log('\nMVP acceptance commands completed.');
