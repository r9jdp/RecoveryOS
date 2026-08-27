import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "../..");
const composeFile = path.join(scriptDirectory, "compose.service.yml");
const isWindows = process.platform === "win32";
const command = (name) => (isWindows ? `${name}.exe` : name);
const pnpm = command("pnpm");
const composeProject = `recoveryos-service-e2e-${process.pid}`;
const managed = [];
let cleaning = false;

function log(message) {
  process.stdout.write(`[service-e2e] ${message}\n`);
}

function run(executable, args, options = {}) {
  log(`${path.basename(executable)} ${args.join(" ")}`);
  const result = spawnSync(executable, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    env: options.env ?? process.env,
    stdio: options.capture ? "pipe" : "inherit",
    timeout: options.timeout,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const details = options.capture
      ? `\n${result.stdout ?? ""}\n${result.stderr ?? ""}`
      : "";
    throw new Error(
      `${path.basename(executable)} exited with ${result.status}${details}`,
    );
  }
  return (result.stdout ?? "").trim();
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("could not allocate an isolated TCP port"));
        return;
      }
      server.close(() => resolve(address.port));
    });
  });
}

function start(name, executable, args, env) {
  log(`starting ${name}`);
  const child = spawn(executable, args, {
    cwd: repositoryRoot,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  managed.push({ child, name });
  for (const [stream, output] of [
    [child.stdout, process.stdout],
    [child.stderr, process.stderr],
  ]) {
    let pending = "";
    stream.on("data", (chunk) => {
      pending += chunk.toString();
      const lines = pending.split(/\r?\n/);
      pending = lines.pop() ?? "";
      for (const line of lines) output.write(`[${name}] ${line}\n`);
    });
  }
  child.on("exit", (code, signal) => {
    if (!cleaning && code !== null) {
      process.stderr.write(
        `[service-e2e] ${name} exited early (${code}, ${signal ?? "no signal"})\n`,
      );
    }
  });
  return child;
}

async function awaitHttp(label, url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not attempted";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        log(`${label} ready at ${url}`);
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} did not become ready: ${lastError}`);
}

function stopManagedProcess(child) {
  if (!child.pid || child.exitCode !== null) return;
  if (isWindows) {
    spawnSync("taskkill.exe", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    child.kill("SIGTERM");
  }
}

function composeArgs(...args) {
  return ["compose", "-p", composeProject, "-f", composeFile, ...args];
}

async function cleanup(stackEnv) {
  if (cleaning) return;
  cleaning = true;
  log("stopping isolated service processes");
  for (const entry of [...managed].reverse()) stopManagedProcess(entry.child);
  if (process.env.RECOVERYOS_SERVICE_E2E_KEEP_STACK === "1") {
    log(`keeping Compose project ${composeProject} by request`);
    return;
  }
  log(`removing isolated Compose project ${composeProject} and its volume`);
  spawnSync(
    command("docker"),
    composeArgs("down", "--volumes", "--remove-orphans", "--timeout", "10"),
    { cwd: repositoryRoot, env: stackEnv, stdio: "inherit" },
  );
}

async function main() {
  const scenarioSource = readFileSync(
    path.join(repositoryRoot, "apps/web/e2e/recovery-stack.service.pw.ts"),
    "utf8",
  );
  if (/\b(?:page|context)\.route\s*\(|routeFromHAR\s*\(/.test(scenarioSource)) {
    throw new Error("real-service scenario must not intercept browser network requests");
  }
  const [postgresPort, temporalPort, apiPort, agentPort, webPort] =
    await Promise.all([freePort(), freePort(), freePort(), freePort(), freePort()]);
  const databaseUrl = `postgresql+psycopg://recovery:recovery@127.0.0.1:${postgresPort}/recovery_os`;
  const temporalAddress = `127.0.0.1:${temporalPort}`;
  const apiOrigin = `http://127.0.0.1:${apiPort}`;
  const agentOrigin = `http://127.0.0.1:${agentPort}`;
  const webOrigin = `http://127.0.0.1:${webPort}`;
  const stackEnv = {
    ...process.env,
    RECOVERYOS_SERVICE_POSTGRES_PORT: String(postgresPort),
    RECOVERYOS_SERVICE_TEMPORAL_PORT: String(temporalPort),
  };
  const serviceEnv = {
    ...stackEnv,
    A2A_ENABLED: "false",
    CUSTOMER_AGENT_DATABASE_URL: databaseUrl,
    CUSTOMER_AGENT_ORIGIN: agentOrigin,
    CUSTOMER_AGENT_TASK_STORE: "sql",
    CUSTOMER_AGENT_WEB_ORIGIN: webOrigin,
    DATABASE_URL: databaseUrl,
    NEXT_PUBLIC_API_BASE_URL: apiOrigin,
    NEXT_PUBLIC_RECOVERY_API_URL: apiOrigin,
    PAYMENT_PROVIDER: "mock",
    RAZORPAY_OUTBOX_POLL_SECONDS: "0.1",
    RAZORPAY_WEBHOOK_SECRET: "service-e2e-local-secret",
    RECOVERY_ACTIVITY_MODE: "production",
    RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS: "false",
    RECOVERY_ALLOW_REAL_VOICE_CALLS: "false",
    RECOVERYOS_SERVICE_API_ORIGIN: apiOrigin,
    RECOVERYOS_SERVICE_CUSTOMER_AGENT_ORIGIN: agentOrigin,
    RECOVERYOS_SERVICE_WEB_ORIGIN: webOrigin,
    TEMPORAL_ADDRESS: temporalAddress,
    TEMPORAL_NAMESPACE: "default",
    TEMPORAL_TASK_QUEUE: "recovery-os-service-e2e",
    TEMPORAL_TLS: "false",
    WEB_ORIGIN: webOrigin,
  };

  process.once("SIGINT", () => void cleanup(stackEnv).finally(() => process.exit(130)));
  process.once("SIGTERM", () => void cleanup(stackEnv).finally(() => process.exit(143)));

  try {
    run(command("docker"), composeArgs("up", "-d", "--wait", "--wait-timeout", "150"), {
      env: stackEnv,
      timeout: 180_000,
    });
    run(command("uv"), ["run", "alembic", "-c", "services/api/alembic.ini", "upgrade", "head"], {
      env: serviceEnv,
      timeout: 120_000,
    });
    run(command("uv"), ["run", "python", "-m", "services.api.app.seed", "--reset"], {
      env: serviceEnv,
      timeout: 120_000,
    });

    start(
      "worker",
      command("uv"),
      ["run", "python", "-m", "services.worker.app.main"],
      serviceEnv,
    );
    start(
      "api",
      command("uv"),
      [
        "run",
        "uvicorn",
        "services.api.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(apiPort),
      ],
      serviceEnv,
    );
    start(
      "customer-agent",
      command("uv"),
      [
        "run",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        "services/customer-agent",
        "--host",
        "127.0.0.1",
        "--port",
        String(agentPort),
      ],
      serviceEnv,
    );
    start(
      "web",
      pnpm,
      [
        "--filter",
        "@recovery-os/web",
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        String(webPort),
      ],
      serviceEnv,
    );

    await Promise.all([
      awaitHttp("API", `${apiOrigin}/health/ready`),
      awaitHttp("customer agent", `${agentOrigin}/health/ready`),
      awaitHttp("web", `${webOrigin}/login`),
    ]);
    const prepared = run(
      command("uv"),
      ["run", "python", "scripts/e2e/service_state.py", "start-workflow"],
      { capture: true, env: serviceEnv, timeout: 60_000 },
    );
    log(`workflow prepared: ${prepared}`);
    run(
      pnpm,
      [
        "--filter",
        "@recovery-os/web",
        "exec",
        "playwright",
        "test",
        "--config",
        "e2e/service.playwright.config.ts",
      ],
      { env: serviceEnv, timeout: 180_000 },
    );
    log("real-service Playwright gate passed");
  } finally {
    await cleanup(stackEnv);
  }
}

main().catch((error) => {
  process.stderr.write(
    `[service-e2e] ${error instanceof Error ? error.stack : String(error)}\n`,
  );
  process.exitCode = 1;
});
