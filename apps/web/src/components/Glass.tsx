import type { HTMLAttributes, ReactNode } from "react";
export function GlassSurface({
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={"glass " + className} {...props} />;
}
export function GlassPanel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"glass gallery-panel " + className}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function GlassIconBadge({
  children,
  tone = "cool",
}: {
  children: ReactNode;
  tone?: "cool" | "warm" | "violet";
}) {
  return <span className={"icon-glass " + tone}>{children}</span>;
}
