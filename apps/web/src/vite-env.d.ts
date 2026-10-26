/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  /** "CDF" shows the institution's logo and drops the demo labels (set only on the institution's deployment). */
  readonly VITE_SITE_IDENTITY?: string;
}
