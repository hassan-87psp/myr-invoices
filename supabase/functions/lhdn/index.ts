// Retired legacy proxy. Central intermediary connector is the only supported route.
// Deliberately has no imports, credentials, external calls, database writes or feature flag.
Deno.serve((_req: Request) => new Response(JSON.stringify({
  error:{message:"Legacy LHDN integration retired. Use MYR Invoice Integrations."},
  code:"legacy_endpoint_retired",
  submission_enabled:false
}), {status:410,headers:{"Content-Type":"application/json","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}}));
