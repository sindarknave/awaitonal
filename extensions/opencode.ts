/** OpenCode V1 1.18.33. Keep the loader entrypoint's only export callable. */
import type { Plugin } from "@opencode-ai/plugin";
import { createOpenCodeBridge } from "./opencode-core.ts";

const awaitonal: Plugin = async ({ client }) => createOpenCodeBridge({
  getSession: async (id, signal) => {
    const response = await client.session.get({ path: { id }, signal });
    return response.data;
  },
});

export default awaitonal;
