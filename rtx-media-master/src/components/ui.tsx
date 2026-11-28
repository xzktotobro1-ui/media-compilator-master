import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "outline";
  size?: "sm" | "md" | "lg" | "icon";
};

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  const base =
    "inline-flex select-none items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/50 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98]";
  const variants = {
    primary:
      "bg-gradient-to-r from-emerald-500 to-cyan-500 text-zinc-950 shadow-[0_8px_30px_rgba(16,185,129,0.25)] hover:shadow-[0_10px_40px_rgba(6,182,212,0.35)] hover:brightness-110",
    secondary: "bg-white/[0.06] text-zinc-200 hover:bg-white/[0.11] border border-white/[0.08]",
    ghost: "text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.06]",
    danger: "bg-red-500/15 text-red-300 border border-red-500/25 hover:bg-red-500/25",
    outline: "border border-white/[0.12] text-zinc-300 hover:border-emerald-400/40 hover:text-white",
  };
  const sizes = {
    sm: "h-8 px-3 text-xs",
    md: "h-10 px-4 text-sm",
    lg: "h-12 px-6 text-sm",
    icon: "h-9 w-9",
  };
  return <button className={cn(base, variants[variant], sizes[size], className)} {...props} />;
}

export function Card({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-white/[0.08] bg-zinc-900/70 backdrop-blur-md shadow-[0_20px_60px_rgba(0,0,0,0.35)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function Badge({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "emerald" | "cyan" | "amber" | "red" | "violet";
  className?: string;
}) {
  const tones = {
    default: "bg-white/[0.06] text-zinc-300 border-white/[0.08]",
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
    cyan: "bg-cyan-500/10 text-cyan-300 border-cyan-500/25",
    amber: "bg-amber-500/10 text-amber-300 border-amber-500/25",
    red: "bg-red-500/10 text-red-300 border-red-500/25",
    violet: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-xl border border-white/[0.08] bg-zinc-950/60 px-3 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-600 focus:border-emerald-400/40 focus:ring-2 focus:ring-emerald-400/10",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 rounded-xl border border-white/[0.08] bg-zinc-950/60 px-3 text-sm text-zinc-100 outline-none transition-colors focus:border-emerald-400/40",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</span>
      {children}
      {hint && <span className="text-[10px] text-zinc-600">{hint}</span>}
    </label>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5"
      aria-pressed={checked}
    >
      <span
        className={cn(
          "relative h-5 w-9 rounded-full transition-colors",
          checked ? "bg-gradient-to-r from-emerald-500 to-cyan-500" : "bg-white/10",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-[18px]" : "translate-x-0.5",
          )}
        />
      </span>
      {label && <span className="text-sm text-zinc-300">{label}</span>}
    </button>
  );
}

export function SectionTitle({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-zinc-100">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Progress({ value, className }: { value: number; className?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]", className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all duration-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Sparkline({ values, color = "#10b981" }: { values: number[]; color?: string }) {
  if (!values.length) {
    return <div className="flex h-16 items-center justify-center text-[11px] text-zinc-600">нет данных</div>;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);
  const points = values
    .map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${38 - ((v - min) / span) * 32}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-16 w-full overflow-visible">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
