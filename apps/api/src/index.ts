export interface Env {}

const corsHeaders = {
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Origin": "*"
};

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json; charset=utf-8");

  for (const [key, value] of Object.entries(corsHeaders)) {
    headers.set(key, value);
  }

  return new Response(JSON.stringify(body, null, 2), {
    ...init,
    headers
  });
}

export default {
  async fetch(request: Request, _env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders
      });
    }

    if (request.method !== "GET") {
      return jsonResponse(
        {
          ok: false,
          error: "Method not allowed"
        },
        {
          status: 405,
          headers: {
            Allow: "GET, OPTIONS"
          }
        }
      );
    }

    if (url.pathname === "/") {
      return jsonResponse({
        ok: true,
        message: "Hello from api.typesafe.pro",
        service: "typesafe-pro-api"
      });
    }

    if (url.pathname === "/health") {
      return jsonResponse({
        ok: true,
        status: "healthy"
      });
    }

    return jsonResponse(
      {
        ok: false,
        error: "Not found"
      },
      {
        status: 404
      }
    );
  }
};
