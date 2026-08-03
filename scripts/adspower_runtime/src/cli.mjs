import fs from 'node:fs/promises';
import path from 'node:path';
import { runPublisher } from './publisher.mjs';
import { BitBrowserClient } from './bitbrowser-client.mjs';
import { AdsPowerClient } from './adspower-client.mjs';
import { checkTikTokUploadWindows } from './tiktok-checker.mjs';

const args = parseArgs(process.argv.slice(2));
const configPath = path.resolve(args.config ?? 'bit-video-publisher/config.example.json');
const tasksPath = path.resolve(args.tasks ?? 'bit-video-publisher/tasks.example.json');

try {
  const config = await readJson(configPath);
  if (args['list-windows']) {
    const client = config.adspower ? new AdsPowerClient(config.adspower) : new BitBrowserClient(config.bitbrowser);
    await client.health();
    const windows = await client.listBrowsers({
      groupId: args['group-id'],
      name: args.name,
      remark: args.remark,
      minSeq: args['min-seq'],
      maxSeq: args['max-seq'],
      sort: args.sort
    });
    if (args.out) {
      await fs.writeFile(path.resolve(args.out), `${JSON.stringify(windows, null, 2)}\n`, 'utf8');
    } else {
      console.table(windows);
    }
  } else if (args['check-tiktok-upload']) {
    const report = await checkTikTokUploadWindows({
      config,
      concurrency: args.concurrency,
      minSeq: args['min-seq'],
      maxSeq: args['max-seq'],
      names: args.names
    });
    if (args.out) {
      await fs.writeFile(path.resolve(args.out), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    }
    console.table(report.map((item) => ({
      seq: item.seq,
      name: item.name,
      status: item.status,
      url: item.url,
      reason: item.reason
    })));
    if (report.length === 0) {
      console.error('No matching AdsPower TikTok profiles were found.');
      process.exitCode = 2;
    } else if (report.some((item) => item.status !== 'ready_or_upload_page')) {
      process.exitCode = 2;
    }
  } else {
    const tasks = await readJson(tasksPath);
    if (!Array.isArray(tasks)) throw new Error('Tasks file must be a JSON array');

    const report = await runPublisher({
      config,
      tasks,
      dryRun: Boolean(args['dry-run']),
      taskId: args['task-id'] ?? ''
    });
    if (args.report) {
      await fs.writeFile(path.resolve(args.report), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    }
    const failed = report.filter((item) => !['preview_ready', 'published'].includes(item.status)).length;
    console.log(JSON.stringify({ total: report.length, success: report.length - failed, failed }));
    if (failed > 0) process.exitCode = 2;
  }
} catch (error) {
  console.error(error?.stack ?? error);
  process.exitCode = 1;
}

async function readJson(filePath) {
  const text = await fs.readFile(filePath, 'utf8');
  return JSON.parse(text.replace(/^\uFEFF/, ''));
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}
