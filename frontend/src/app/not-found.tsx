import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="text-sm font-semibold text-brand-700">404</p>
      <h1 className="text-2xl font-bold text-ink">Page not found</h1>
      <p className="text-ink-muted">The page you are looking for does not exist.</p>
      <Link href="/dashboard" className="mt-2 rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white hover:bg-brand-hover">
        Go to the dashboard
      </Link>
    </main>
  );
}
