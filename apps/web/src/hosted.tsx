// Hosted synthetic demo sign-in (Supabase Auth). Active only when the build sets VITE_SUPABASE_URL and
// VITE_SUPABASE_PUBLISHABLE_KEY; otherwise the local developer-token box is shown. The access token is
// sent to the API, which accepts only reviewers listed on the server (CDF_HOSTED_REVIEWERS).
import { useEffect, useState } from "react";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined;
export const hosted = Boolean(url && key);

let client: SupabaseClient | null = null;
function supabase(): SupabaseClient {
  if (!client) client = createClient(url!, key!, { auth: { persistSession: true, autoRefreshToken: true } });
  return client;
}

export function HostedSignIn({ onToken }: { onToken: (token: string) => void }) {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [signedIn, setSignedIn] = useState<string | null>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);

  useEffect(() => {
    const sb = supabase();
    void sb.auth.getSession().then(({ data }) => {
      onToken(data.session?.access_token ?? "");
      setSignedIn(data.session?.user.email ?? null);
    });
    const { data } = sb.auth.onAuthStateChange((_event, session) => {
      onToken(session?.access_token ?? "");
      setSignedIn(session?.user.email ?? null);
    });
    return () => data.subscription.unsubscribe();
  }, [onToken]);

  async function run(action: "in" | "up" | "out") {
    if (action === "up" && password.length < 8) {
      setMessage("كلمة المرور قصيرة: استخدم 8 أحرف على الأقل.");   // keep what was typed
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const sb = supabase();
      if (action === "out") {
        await sb.auth.signOut();
      } else if (action === "in") {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) setMessage(error.message);
      } else {
        const { data, error } = await sb.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) setMessage(error.message);
        else if (!data.session) setMessage("أُرسل رابط تأكيد إلى بريدك؛ أكّد الحساب ثم سجّل الدخول.");
      }
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  if (signedIn)
    return (
      <div className="hosted-signin" aria-label="الجلسة">
        <span>
          مسجّل باسم <bdi>{signedIn}</bdi> · الوصول للمراجعين المدرجين فقط
        </span>
        <button className="button" onClick={() => void run("out")} disabled={busy}>
          تسجيل الخروج
        </button>
      </div>
    );
  return (
    <div className="hosted-signin" aria-label="تسجيل الدخول">
      <label>
        البريد الإلكتروني
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
      </label>
      <label>
        كلمة المرور
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          aria-describedby="password-hint"
        />
        <small id="password-hint">8 أحرف على الأقل لإنشاء حساب</small>
      </label>
      <button className="button dark" onClick={() => void run("in")} disabled={busy || !email || !password}>
        تسجيل الدخول
      </button>
      <button className="button" onClick={() => void run("up")} disabled={busy || !email || !password}>
        إنشاء حساب
      </button>
      {message && <p role="status">{message}</p>}
    </div>
  );
}
