import { useApp, useDataSync, useModelContext, useTheme } from "@nimblebrain/synapse/react";
import {
  AppFrame,
  Badge,
  Button,
  Card,
  Heading,
  SidebarLayout,
  Text,
  tokens,
} from "@nimblebrain/synapse/ui";
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { AppPlan, AppStatus, AvailableApp, GuideState, RecordValue } from "./types";

const groups = [
  { title: "Start", steps: ["welcome"] },
  { title: "Add an app", steps: ["catalog"] },
  { title: "Try a task", steps: ["control", "board"] },
  { title: "Make it yours", steps: ["appearance"] },
  { title: "Connect", steps: ["providers", "agents"] },
  { title: "Build an app", steps: ["build"] },
];
const statuses = { todo: "To do", doing: "Doing", done: "Done" } as const;
const message = (error: unknown) =>
  error instanceof Error ? error.message : "The action could not finish.";
const previewTokens = {
  "--color-background-primary": "Canvas",
  "--color-background-secondary": "color-mix(in srgb, CanvasText 6%, Canvas)",
  "--color-text-primary": "CanvasText",
  "--color-text-secondary": "color-mix(in srgb, CanvasText 65%, Canvas)",
  "--color-text-accent": "CanvasText",
  "--color-text-inverse": "Canvas",
  "--color-border-primary": "color-mix(in srgb, CanvasText 18%, Canvas)",
  "--color-ring-primary": "CanvasText",
} as CSSProperties;

export default function App() {
  const app = useApp();
  const theme = useTheme();
  const [state, setState] = useState<GuideState>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [query, setQuery] = useState("");
  const [idea, setIdea] = useState("");
  const [agent, setAgent] = useState<"claude" | "codex">("claude");
  const [agentSetup, setAgentSetup] = useState<RecordValue>();
  const [plan, setPlan] = useState<AppPlan>();
  const [checks, setChecks] = useState<Record<string, AppStatus>>({});
  const checkAttempts = useRef<Record<string, number>>({});
  const [reducedMotion, setReducedMotion] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const operation = useRef(false);
  const revision = useRef(-1);

  const call = useCallback(
    async <T,>(name: string, args: RecordValue = {}): Promise<T> => {
      const result = await app.callTool<T>(name, args);
      if (result.isError) {
        const parts = result.content ?? [];
        throw new Error(
          parts
            .map((part) =>
              typeof part === "object" && part !== null && "text" in part ? String(part.text) : "",
            )
            .filter(Boolean)
            .join(" ") || "That action did not finish.",
        );
      }
      return result.data;
    },
    [app],
  );
  const accept = useCallback((next: GuideState) => {
    if (!next || !Array.isArray(next.steps) || !Array.isArray(next.cards))
      throw new Error("The guide returned unreadable state. Reconnect and try again.");
    if (next.revision < revision.current) return;
    revision.current = next.revision;
    setState(next);
  }, []);
  const refresh = useCallback(async () => {
    try {
      accept(await call<GuideState>("guide_status"));
      setError("");
    } catch (failure) {
      setError(message(failure));
    }
  }, [accept, call]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useDataSync(() => refresh());
  useEffect(() => {
    if (!state?.appJob || !["queued", "running"].includes(state.appJob.state)) return;
    const timer = setTimeout(() => {
      void refresh();
    }, 2000);
    return () => clearTimeout(timer);
  }, [state, refresh]);
  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReducedMotion(preference.matches);
    preference.addEventListener("change", change);
    return () => preference.removeEventListener("change", change);
  }, []);
  useModelContext(
    () => ({
      state: { step: state?.step, cards: state?.cards, appJob: state?.appJob },
      summary: state
        ? `Showcase: ${state.steps.find((step) => step.id === state.step)?.title}, ${state.cards.length} practice cards`
        : "Showcase is loading",
    }),
    [state],
  );

  const change = async (name: string, args: RecordValue, text = "") => {
    if (operation.current) return false;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      accept(await call<GuideState>(name, args));
      setAnnouncement(text);
      return true;
    } catch (failure) {
      setError(message(failure));
      return false;
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };
  const inspect = async (action: () => Promise<void>) => {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(message(failure));
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };
  const open = (url: string) => {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol))
      throw new Error("This link is not a web address.");
    app.openLink(parsed.href);
  };
  const checkApp = useCallback(
    async (id: AvailableApp["id"]): Promise<AppStatus> => {
      const attempt = (checkAttempts.current[id] ?? 0) + 1;
      checkAttempts.current[id] = attempt;
      setChecks((current) => ({ ...current, [id]: { ready: false, checking: true } }));
      try {
        const status = await call<AppStatus>("app_status", { app: id });
        if (checkAttempts.current[id] !== attempt) return { ready: false };
        setChecks((current) => ({ ...current, [id]: status }));
        return status;
      } catch (failure) {
        const status = { ready: false, error: message(failure) };
        if (checkAttempts.current[id] !== attempt) return { ready: false };
        setChecks((current) => ({ ...current, [id]: status }));
        return status;
      }
    },
    [call],
  );
  const observedJobId = state?.appJob?.id;
  const observedJobState = state?.appJob?.state;
  const observedJobApp = state?.appJob?.app;
  const canCheckApps = state?.capabilities.appStatus;
  useEffect(() => {
    if (observedJobApp && ["queued", "running"].includes(observedJobState ?? "")) {
      checkAttempts.current[observedJobApp] = (checkAttempts.current[observedJobApp] ?? 0) + 1;
      setChecks((current) => {
        const next = { ...current };
        delete next[observedJobApp];
        return next;
      });
      return;
    }
    if (
      observedJobId &&
      observedJobApp &&
      canCheckApps &&
      ["ready", "failed"].includes(observedJobState ?? "")
    )
      void checkApp(observedJobApp);
  }, [observedJobId, observedJobState, observedJobApp, canCheckApps, checkApp]);

  if (!state)
    return (
      <AppFrame>
        <AppFrame.Body>
          <Heading>Showcase</Heading>
          <Text>{error || "Loading your guide…"}</Text>
          <Button onClick={() => void refresh()}>Retry</Button>
        </AppFrame.Body>
      </AppFrame>
    );
  const job = state.appJob;
  const step = state.steps.find((item) => item.id === state.step) ?? state.steps[0];
  const path =
    state.pace === "quick"
      ? state.steps.filter((item) => ["welcome", "catalog", "board", "build"].includes(item.id))
      : state.steps;
  const index = path.findIndex((item) => item.id === step.id);
  const playing = state.view.playing && !reducedMotion;
  const installing = Boolean(job && ["queued", "running"].includes(job.state));
  const navigate = (id: string) => change("guide_step", { step: id });
  const next = async (skip = false) => {
    if (await change("guide_step", { step: step.id, complete: !skip, skip }, "Progress saved.")) {
      const target = path[index + 1];
      if (target) await navigate(target.id);
    }
  };
  const choosePace = async (pace: "quick" | "guided") => {
    if (await change("guide_preferences", { pace })) await navigate("catalog");
  };
  const prompt = `Help me make a small MCP app to ${idea.trim() || "do one useful thing"}. Give it tools, a screen and useful agent instructions. Keep it separate from the runtime, serve it over HTTP, and test the same action through its screen and an agent.`;
  const catalog = state.catalog.filter((item) =>
    `${item.title} ${item.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  const apps = state.apps.filter((item) =>
    `${item.label} ${item.description ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  );

  const board = (
    <div className="practice-board">
      {Object.entries(statuses).map(([status, label]) => (
        <Card key={status} className="board-column">
          <Heading size="sm">{label}</Heading>
          {state.cards
            .filter((card) => card.status === status)
            .map((card) => (
              <Card
                key={card.id}
                className={
                  state.view.focus === "first-card" && card.id === state.cards[0]?.id
                    ? "practice-card focused"
                    : "practice-card"
                }
              >
                <Text>{card.title}</Text>
                <label className="field-label">
                  Move to
                  <select
                    aria-label={`Move ${card.title}`}
                    disabled={busy}
                    value={card.status}
                    onChange={(event) =>
                      void change(
                        "board_move",
                        { id: card.id, status: event.target.value },
                        "Task moved.",
                      )
                    }
                  >
                    {Object.entries(statuses).map(([value, title]) => (
                      <option key={value} value={value}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
              </Card>
            ))}
          {status === "todo" && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void change("board_add", { title: taskTitle }, "Task added.").then((ok) => {
                  if (ok) setTaskTitle("");
                });
              }}
            >
              <label className="field-label">
                New practice task
                <input
                  value={taskTitle}
                  maxLength={120}
                  onChange={(event) => setTaskTitle(event.target.value)}
                />
              </label>
              <Button disabled={busy || !taskTitle.trim()} type="submit">
                Add task
              </Button>
            </form>
          )}
        </Card>
      ))}
    </div>
  );
  let scene: ReactNode;
  switch (step.id) {
    case "welcome":
      scene = (
        <>
          <div className="control-map">
            <Card>
              <Heading size="sm">You</Heading>
              <Text>Use an app’s screen.</Text>
            </Card>
            <span aria-hidden="true">→</span>
            <Card>
              <Heading size="sm">One app</Heading>
              <Text>The same saved work.</Text>
            </Card>
            <span aria-hidden="true">←</span>
            <Card>
              <Heading size="sm">Your agent</Heading>
              <Text>Call the app’s tools.</Text>
            </Card>
          </div>
          <div className="actions">
            <Button disabled={busy} variant="primary" onClick={() => void choosePace("guided")}>
              Start the tour
            </Button>
            <Button disabled={busy} onClick={() => void choosePace("quick")}>
              Explore the apps
            </Button>
          </div>
          <Text tone="muted">You can return to any chapter from the menu.</Text>
        </>
      );
      break;
    case "catalog":
      scene = (
        <>
          {typeof state.installation.appJobError === "string" && (
            <Card className="warning">
              <Heading size="sm">Installation status needs inspection</Heading>
              <Text>{state.installation.appJobError}</Text>
            </Card>
          )}
          <label className="field-label">
            Find an app or guide
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <div className="card-grid">
            {apps.map((item) => (
              <Card key={item.id}>
                <Heading size="sm">{item.label}</Heading>
                <Text>{item.description}</Text>
                <Text tone="muted">
                  {checks[item.id]?.ready
                    ? "Connected"
                    : (item.installBlockedReason ??
                      (item.deployed || item.installed
                        ? "Available · check the current connection"
                        : (item.error ?? "Not added yet")))}
                </Text>
                <div className="actions">
                  <Button
                    disabled={busy || installing || !state.capabilities.appStatus}
                    onClick={() =>
                      void inspect(async () => {
                        const checked = await checkApp(item.id);
                        if (checked.ready && checked.web) open(checked.web);
                      })
                    }
                  >
                    {checks[item.id]?.ready ? "Open app" : "Check and open"}
                  </Button>
                  {state.capabilities.appPlan && (
                    <Button
                      disabled={busy || installing || Boolean(item.installBlockedReason)}
                      onClick={() =>
                        void inspect(async () =>
                          setPlan(await call<AppPlan>("app_plan", { app: item.id })),
                        )
                      }
                    >
                      Review {item.deployed || item.installed ? "connection" : "installation"}
                    </Button>
                  )}
                </div>
                {checks[item.id]?.checking && <Text>Checking…</Text>}
                {checks[item.id]?.error && <Text tone="danger">{checks[item.id].error}</Text>}
              </Card>
            ))}
          </div>
          {!state.apps.length && (
            <Card>
              <Text>
                Your operator can make apps available to this workspace. The practice board works
                here without them.
              </Text>
              <Button disabled={busy} onClick={() => void navigate("board")}>
                Try the practice board
              </Button>
            </Card>
          )}
          {plan && (
            <Card className="install-review">
              <Heading size="sm">
                {plan.mode === "connect" ? "Connect" : "Install"} {plan.app.label}?
              </Heading>
              <Text>
                Your app data stays in <code>{plan.paths.data}</code>.
              </Text>
              <ul>
                {plan.effects.map((effect) => (
                  <li key={effect}>{effect}</li>
                ))}
              </ul>
              <details>
                <summary>Source and reviewed changes</summary>
                <Text>{plan.app.repo}</Text>
                <code>{plan.app.commit}</code>
                <p>
                  Reviewed plan: <code>{plan.planHash}</code>
                </p>
                <p>Full reviewed plan</p>
                <pre>{JSON.stringify(plan, null, 2)}</pre>
              </details>
              {Object.entries(plan.prerequisites)
                .filter(([, ready]) => !ready)
                .map(([name]) => (
                  <Text key={name} tone="danger">
                    Needed first: {name}
                  </Text>
                ))}
              <div className="actions">
                <Button
                  disabled={
                    busy ||
                    installing ||
                    !state.capabilities.appInstall ||
                    Object.values(plan.prerequisites).some((ready) => !ready)
                  }
                  variant="primary"
                  onClick={() =>
                    void inspect(async () => {
                      await call("app_install", {
                        app: plan.app.id,
                        planHash: plan.planHash,
                        confirm: true,
                      });
                      checkAttempts.current[plan.app.id] =
                        (checkAttempts.current[plan.app.id] ?? 0) + 1;
                      setChecks((current) => {
                        const next = { ...current };
                        delete next[plan.app.id];
                        return next;
                      });
                      setPlan(undefined);
                      await refresh();
                    })
                  }
                >
                  {plan.mode === "connect" ? "Connect" : "Install"} {plan.app.label}
                </Button>
                <Button disabled={busy} onClick={() => setPlan(undefined)}>
                  Cancel
                </Button>
              </div>
            </Card>
          )}
          {job && (
            <Card
              className={
                job.state === "failed" && !checks[job.app]?.ready
                  ? "job-status warning"
                  : "job-status"
              }
            >
              <Heading size="sm">
                {checks[job.app]?.ready
                  ? "App connected · current status checked"
                  : checks[job.app]?.checking
                    ? "Checking current app status"
                    : checks[job.app] && !checks[job.app].ready
                      ? "Current app connection not verified"
                      : job.state === "failed"
                        ? "Earlier installation attempt failed"
                        : job.state === "ready"
                          ? "Earlier installation completed"
                          : `Installing · ${job.stage ?? "working"}`}
              </Heading>
              {checks[job.app] ? (
                <details>
                  <summary>Earlier installation result</summary>
                  <Text>{job.message}</Text>
                </details>
              ) : (
                <Text>{job.message}</Text>
              )}
              <Button
                disabled={busy || !state.capabilities.appStatus}
                onClick={() =>
                  void inspect(async () => {
                    await checkApp(job.app);
                  })
                }
              >
                Check current status
              </Button>
            </Card>
          )}
          <Heading size="sm">Already here</Heading>
          <div className="card-grid">
            {catalog.map((item) => (
              <Card key={item.id}>
                <Heading size="sm">{item.title}</Heading>
                <Text>{item.description}</Text>
                <Button
                  disabled={busy}
                  onClick={() => {
                    if (item.action === "open-tasks") {
                      setAnnouncement("Open Tasks from NimbleBrain’s sidebar.");
                      return;
                    }
                    if (item.action === "browse-connectors") {
                      if (item.browseUrl) open(item.browseUrl);
                      else setAnnouncement("Open Settings → Connectors in your workspace.");
                      return;
                    }
                    void navigate(item.action);
                  }}
                >
                  {item.action === "board"
                    ? "Try it"
                    : item.action === "open-tasks"
                      ? "Where to find it"
                      : "Open guide"}
                </Button>
              </Card>
            ))}
          </div>
        </>
      );
      break;
    case "control":
      scene = (
        <>
          <div className={`control-map ${playing ? "playing" : ""}`}>
            {[
              ["manual", "Use the screen"],
              ["shared", "App tools and saved state"],
              ["agent", "Ask your agent"],
            ].map(([id, label], position) => (
              <div key={id} className="control-node">
                <Card className={state.view.focus === id ? "focused" : ""}>
                  <Heading size="sm">{label}</Heading>
                  <Button
                    disabled={busy}
                    onClick={() => void change("guide_view", { focus: id, playing: true })}
                  >
                    Follow this path
                  </Button>
                </Card>
                {position < 2 && (
                  <span className="flow-arrow" aria-hidden="true">
                    →
                  </span>
                )}
              </div>
            ))}
          </div>
          <Text>
            The screen and the agent call the same tools. Move a practice card to see a real shared
            change.
          </Text>
          <Button disabled={busy} variant="primary" onClick={() => void navigate("board")}>
            Open the board
          </Button>
        </>
      );
      break;
    case "board":
      scene = (
        <>
          {board}
          <Text tone="muted">
            Ask your connected agent: “Move my first Showcase practice task to Doing.”
          </Text>
        </>
      );
      break;
    case "appearance":
      scene = (
        <>
          <Card className="appearance-preview">
            <Heading size="sm">A preview inside Showcase</Heading>
            <div className="preview-chart" role="img" aria-label="Sample chart">
              <i style={{ height: "40%" }} />
              <i style={{ height: "75%" }} />
              <i style={{ height: "55%" }} />
              <i style={{ height: "90%" }} />
            </div>
            <Text>
              This guide follows the host’s colors and fonts. Its appearance control changes only
              this app.
            </Text>
          </Card>
          <Text>
            To change NimbleBrain itself, use Profile → General. Workspace branding is an operator
            setting.
          </Text>
        </>
      );
      break;
    case "providers": {
      const providers = Array.isArray(state.installation.providers)
        ? state.installation.providers.map(String)
        : [];
      scene = (
        <>
          <Card>
            <Heading size="sm">Chat needs a model provider</Heading>
            <Text>
              {providers.length
                ? `${providers.join(", ")} is configured. Send a message in NimbleBrain to verify a reply.`
                : "Your operator can configure a provider before you use NimbleBrain’s chat. Keep provider keys out of app tools and messages."}
            </Text>
          </Card>
          <Text>
            The guide and practice board also work with a connected external agent. That connection
            does not verify a model provider.
          </Text>
        </>
      );
      break;
    }
    case "agents":
      scene = (
        <>
          <label className="field-label">
            Your coding agent
            <select
              value={agent}
              onChange={(event) => {
                setAgent(event.target.value as "claude" | "codex");
                setAgentSetup(undefined);
              }}
            >
              <option value="claude">Claude Code</option>
              <option value="codex">Codex</option>
            </select>
          </label>
          <Card>
            <Heading size="sm">Connect the guide’s tools</Heading>
            <Text>
              Your operator provides the connection configuration. Review and approve it in your
              agent before use.
            </Text>
            {state.capabilities.agentSetup ? (
              <Button
                disabled={busy}
                onClick={() =>
                  void inspect(async () =>
                    setAgentSetup(await call<RecordValue>("guide_agent_setup", { agent })),
                  )
                }
              >
                Show my connection configuration
              </Button>
            ) : (
              <Text tone="muted">
                This host has not supplied external-agent setup. Ask your operator for its supported
                MCP connection.
              </Text>
            )}
            {agentSetup && <pre>{JSON.stringify(agentSetup, null, 2)}</pre>}
          </Card>
          <Card>
            <Heading size="sm">Check the connection</Heading>
            <blockquote>
              Read guide_status, then call guide_connection_check. Tell me which step I am on.
            </blockquote>
            {state.agentCheck && (
              <Text>
                Last guide connection check: {new Date(state.agentCheck).toLocaleString()}
              </Text>
            )}
          </Card>
          <Text>
            Setup skills supply instructions. The MCP connection carries tool calls. Other apps have
            their own tools and permissions.
          </Text>
        </>
      );
      break;
    default:
      scene = (
        <>
          <div className="card-grid">
            <Card>
              <Heading size="sm">Tools</Heading>
              <Text>Actions the person and agent can both call.</Text>
            </Card>
            <Card>
              <Heading size="sm">Screen</Heading>
              <Text>A view of the same saved work.</Text>
            </Card>
            <Card>
              <Heading size="sm">Skills</Heading>
              <Text>Instructions that help an agent use the app.</Text>
            </Card>
          </div>
          <label className="field-label">
            What should your app do?
            <input value={idea} maxLength={200} onChange={(event) => setIdea(event.target.value)} />
          </label>
          <blockquote>{prompt}</blockquote>
          <Button
            disabled={busy}
            variant="primary"
            onClick={() => open("https://docs.nimblebrain.ai/apps/overview/")}
          >
            Read the app documentation
          </Button>
        </>
      );
      break;
  }
  const explicitTheme = state.theme !== "host";
  return (
    <AppFrame
      contentWidth="full"
      style={{
        ...(explicitTheme ? previewTokens : {}),
        colorScheme: explicitTheme ? state.theme : theme.mode,
        color: tokens.fg,
        background: tokens.bg,
      }}
      className={reducedMotion ? "reduced-motion" : ""}
    >
      <AppFrame.Header>
        <Heading size="sm">Showcase</Heading>
        <label className="compact-field">
          Appearance
          <select
            aria-label="Showcase appearance"
            value={state.theme}
            disabled={busy}
            onChange={(event) => void change("guide_preferences", { theme: event.target.value })}
          >
            <option value="host">Follow NimbleBrain</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
      </AppFrame.Header>
      <AppFrame.Body bleed>
        <SidebarLayout width={210} collapseMode="drawer">
          <SidebarLayout.Sidebar>
            <nav aria-label="Guide chapters" className="chapters">
              {groups.map((group, position) => (
                <Button
                  key={group.title}
                  variant={group.steps.includes(step.id) ? "secondary" : "ghost"}
                  aria-current={group.steps.includes(step.id) ? "step" : undefined}
                  disabled={busy}
                  onClick={() => void navigate(group.steps[0])}
                >
                  <span className="chapter-position" aria-hidden="true">
                    {state.completed.includes(group.steps[group.steps.length - 1])
                      ? "✓"
                      : position + 1}
                  </span>
                  {group.title}
                </Button>
              ))}
            </nav>
          </SidebarLayout.Sidebar>
          <SidebarLayout.Main>
            <main className="guide-main" aria-busy={busy}>
              <div className="guide-toolbar">
                <SidebarLayout.Trigger aria-label="Open guide chapters" />
                <Badge>
                  {
                    groups.filter((group) =>
                      state.completed.includes(group.steps[group.steps.length - 1]),
                    ).length
                  }{" "}
                  of {groups.length} completed
                </Badge>
                <label className="compact-field">
                  Path
                  <select
                    aria-label="Guide pace"
                    value={state.pace}
                    disabled={busy}
                    onChange={(event) =>
                      void change("guide_preferences", { pace: event.target.value })
                    }
                  >
                    <option value="guided">Guided</option>
                    <option value="quick">Quick</option>
                  </select>
                </label>
              </div>
              <Heading>{step.title}</Heading>
              <Text>{step.body}</Text>
              {error && (
                <div className="error-message" role="alert">
                  <Text tone="danger">{error}</Text>
                  <Button onClick={() => void refresh()}>Retry</Button>
                </div>
              )}
              {typeof state.installation.hostError === "string" && (
                <Card className="warning">
                  <Text>{state.installation.hostError}</Text>
                </Card>
              )}
              <section className="guide-scene" aria-label={step.title}>
                <div className="scene-toolbar">
                  {["board", "control"].includes(step.id) && (
                    <Button
                      disabled={busy || reducedMotion}
                      onClick={() => void change("guide_view", { playing: !state.view.playing })}
                    >
                      {playing ? "Pause" : "Play"}
                    </Button>
                  )}
                  <Button
                    aria-label="Zoom out"
                    disabled={busy || state.view.zoom <= 0.75}
                    onClick={() =>
                      void change("guide_view", {
                        zoom: Math.max(0.75, Math.round((state.view.zoom - 0.1) * 100) / 100),
                      })
                    }
                  >
                    −
                  </Button>
                  <span role="status" className="zoom-value" aria-label="Current zoom">
                    {Math.round(state.view.zoom * 100)}%
                  </span>
                  <Button
                    aria-label="Zoom in"
                    disabled={busy || state.view.zoom >= 1.6}
                    onClick={() =>
                      void change("guide_view", {
                        zoom: Math.min(1.6, Math.round((state.view.zoom + 0.1) * 100) / 100),
                      })
                    }
                  >
                    +
                  </Button>
                  <Button disabled={busy} onClick={() => void change("guide_view", { zoom: 1 })}>
                    Reset zoom
                  </Button>
                </div>
                <div className="scene-window">
                  <div className="scene-content" style={{ zoom: state.view.zoom } as CSSProperties}>
                    {scene}
                  </div>
                </div>
              </section>
              <footer className="chapter-footer">
                <Button
                  disabled={busy || index <= 0}
                  onClick={() => void navigate(path[index - 1].id)}
                >
                  Back
                </Button>
                <Button variant="ghost" disabled={busy} onClick={() => void next(true)}>
                  Skip for now
                </Button>
                <Button variant="primary" disabled={busy} onClick={() => void next()}>
                  {path[index + 1] ? "Done, continue" : "Finish the guide"}
                </Button>
              </footer>
              <label className="motion-preference">
                <input
                  type="checkbox"
                  checked={reducedMotion}
                  onChange={(event) => setReducedMotion(event.target.checked)}
                />
                Reduce motion
              </label>
            </main>
          </SidebarLayout.Main>
        </SidebarLayout>
      </AppFrame.Body>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
    </AppFrame>
  );
}
