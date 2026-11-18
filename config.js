/* =====================================================================
   MYR Invoice — configuration
   Leave supabaseUrl / supabaseAnonKey empty  → LOCAL DEMO MODE
   (data saved in the browser only).
   Fill both                                  → CLOUD MODE (Supabase).
   Only the PUBLIC anon key goes here. NEVER put the service_role key,
   database password or LHDN Client Secret in this file.
   ===================================================================== */
window.MYR_CONFIG = {
  supabaseUrl: 'https://nynghaleoaqilewmhbdi.supabase.co', // Connected MYR Invoices project
  supabaseAnonKey: 'sb_publishable_HlZ8K0vUrlMutN65P2xrig_pOj5XAhk', // Publishable key (safe for browser; NEVER use a secret key)

  // Optional: override the LHDN function URL (default: <supabaseUrl>/functions/v1/lhdn)
  lhdnFunctionUrl: '',

  // Local demo mode only: who can open #/admin (cloud mode uses profiles.is_platform_admin)
  adminEmails: [],

  // Show the "fictional demo company" button (default: true locally, false in cloud)
  allowDemo: false,

  supportEmail: 'support@myrinvoice.com'

  // Optional: override plans/prices
  // plans: [{id:'Starter',price:9,docs:100,users:1,bulk:false,reminders:'Basic',qr:'Limited',reports:'Basic',acct:'No',api:false,approval:false}, ...]
};
