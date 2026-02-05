/**
 * Trajectory Sandbox Tools - OpenClaw Plugin
 * 
 * Registers mock tools (inbox, email, calendar, memory) that call
 * the trajectory-sandbox mock server for deterministic responses.
 */

interface PluginConfig {
  mockServerUrl?: string;
  scenario?: string;
}

interface PluginApi {
  config: {
    plugins?: {
      entries?: {
        'trajectory-sandbox-tools'?: {
          config?: PluginConfig;
        };
      };
    };
  };
  logger: {
    info: (msg: string) => void;
    error: (msg: string) => void;
  };
  registerTool: (tool: ToolDefinition) => void;
}

interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  handler: (params: Record<string, unknown>, ctx: unknown) => Promise<unknown>;
}

function getConfig(api: PluginApi): PluginConfig {
  return api.config.plugins?.entries?.['trajectory-sandbox-tools']?.config ?? {};
}

async function callMockServer(
  api: PluginApi,
  endpoint: string,
  body: Record<string, unknown> = {}
): Promise<unknown> {
  const config = getConfig(api);
  const baseUrl = config.mockServerUrl ?? 'http://localhost:3001';
  
  const response = await fetch(`${baseUrl}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  
  if (!response.ok) {
    throw new Error(`Mock server error: ${response.status} ${response.statusText}`);
  }
  
  return response.json();
}

export default function register(api: PluginApi) {
  api.logger.info('Trajectory Sandbox Tools plugin loading...');

  // =========================================================================
  // inbox.list - List inbox messages
  // =========================================================================
  api.registerTool({
    name: 'inbox_list',
    description: 'List inbox messages with id, sender, subject, snippet, and urgency flag',
    parameters: {
      type: 'object',
      properties: {},
    },
    handler: async (_params, _ctx) => {
      const result = await callMockServer(api, '/tools/inbox.list', {});
      return result;
    },
  });

  // =========================================================================
  // email.draft - Draft a reply to an email
  // =========================================================================
  api.registerTool({
    name: 'email_draft',
    description: 'Draft a reply to an email. Returns a draft_id and preview.',
    parameters: {
      type: 'object',
      properties: {
        message_id: {
          type: 'string',
          description: 'ID of the email to reply to',
        },
        instructions: {
          type: 'string',
          description: 'Instructions for what the draft should say',
        },
      },
      required: ['message_id', 'instructions'],
    },
    handler: async (params, _ctx) => {
      const result = await callMockServer(api, '/tools/email.draft', params);
      return result;
    },
  });

  // =========================================================================
  // email.send - Send a drafted email (IRREVERSIBLE)
  // =========================================================================
  api.registerTool({
    name: 'email_send',
    description: 'Send a drafted email. WARNING: This is IRREVERSIBLE. Always get explicit user approval before calling this tool!',
    parameters: {
      type: 'object',
      properties: {
        draft_id: {
          type: 'string',
          description: 'ID of the draft to send',
        },
      },
      required: ['draft_id'],
    },
    handler: async (params, _ctx) => {
      const result = await callMockServer(api, '/tools/email.send', params);
      return result;
    },
  });

  // =========================================================================
  // calendar.read - Read calendar events
  // =========================================================================
  api.registerTool({
    name: 'calendar_read',
    description: 'Read calendar events within a date range',
    parameters: {
      type: 'object',
      properties: {
        start_date: {
          type: 'string',
          description: 'Start date (YYYY-MM-DD)',
        },
        end_date: {
          type: 'string',
          description: 'End date (YYYY-MM-DD)',
        },
      },
    },
    handler: async (params, _ctx) => {
      const result = await callMockServer(api, '/tools/calendar.read', params);
      return result;
    },
  });

  // =========================================================================
  // memory.read - Read from memory/filesystem
  // =========================================================================
  api.registerTool({
    name: 'memory_read',
    description: 'Read a file from memory storage',
    parameters: {
      type: 'object',
      properties: {
        path: {
          type: 'string',
          description: 'Path to the file to read',
        },
      },
      required: ['path'],
    },
    handler: async (params, _ctx) => {
      const result = await callMockServer(api, '/tools/memory.read', params);
      return result;
    },
  });

  // =========================================================================
  // memory.write - Write to memory/filesystem
  // =========================================================================
  api.registerTool({
    name: 'memory_write',
    description: 'Write a file to memory storage',
    parameters: {
      type: 'object',
      properties: {
        path: {
          type: 'string',
          description: 'Path to write to',
        },
        content: {
          type: 'string',
          description: 'Content to write',
        },
      },
      required: ['path', 'content'],
    },
    handler: async (params, _ctx) => {
      const result = await callMockServer(api, '/tools/memory.write', params);
      return result;
    },
  });

  api.logger.info('Trajectory Sandbox Tools plugin loaded: 6 tools registered');
}
