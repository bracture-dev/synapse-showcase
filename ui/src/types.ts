export type RecordValue = Record<string, unknown>;
export interface Step {
  id: string;
  title: string;
  body: string;
  target: string;
}
export interface Card {
  id: string;
  title: string;
  status: "todo" | "doing" | "done";
}
export interface AvailableApp {
  id: "todo-board" | "crm";
  label: string;
  description?: string;
  installed?: boolean;
  deployed?: boolean;
  // Why the host will not plan this app's next step. Any other error can be retried.
  installBlockedReason?: string;
  error?: string;
}
export interface AppJob {
  id: string;
  app: "todo-board" | "crm";
  state: "queued" | "running" | "ready" | "failed";
  stage?: string;
  message: string;
  web?: string;
}
export interface GuideState {
  revision: number;
  step: string;
  completed: string[];
  skipped: string[];
  pace: "guided" | "quick";
  theme: "host" | "light" | "dark";
  agentCheck?: string;
  steps: Step[];
  cards: Card[];
  view: { zoom: number; playing: boolean; focus: string | null };
  installation: RecordValue;
  apps: AvailableApp[];
  appJob: AppJob | null;
  capabilities: {
    appPlan: boolean;
    appInstall: boolean;
    appStatus: boolean;
    appLifecycle: boolean;
    agentSetup: boolean;
  };
  catalog: { id: string; title: string; description: string; action: string; browseUrl?: string }[];
}
export interface AppPlan {
  mode?: string;
  app: {
    id: AvailableApp["id"];
    label: string;
    repo: string;
    commit: string;
  };
  paths: { data: string };
  prerequisites: Record<string, boolean>;
  effects: string[];
  planHash: string;
}
export interface AppStatus {
  ready: boolean;
  checking?: boolean;
  error?: string;
  web?: string;
}
