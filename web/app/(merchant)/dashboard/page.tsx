import Link from "next/link";

const foundations = ["Funnel events", "Agent audit trail", "Provenance labels"];

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-[#17211f] px-6 py-8 text-[#f4f0e7] sm:px-12">
      <nav className="mx-auto flex max-w-6xl items-center justify-between border-b border-[#f4f0e7]/20 pb-5 text-sm font-semibold uppercase tracking-[0.18em]">
        <span>CartPilot / Growth desk</span>
        <Link className="text-[#d8e6bf] underline underline-offset-4" href="/shop">Customer view</Link>
      </nav>
      <section className="mx-auto max-w-6xl py-20">
        <p className="font-mono text-xs uppercase tracking-[0.22em] text-[#e95b2f]">Merchant intelligence</p>
        <h1 className="mt-5 max-w-3xl text-5xl font-black leading-[0.94] tracking-[-0.06em] sm:text-7xl">Growth signals with receipts.</h1>
        <p className="mt-7 max-w-xl text-lg leading-8 text-[#f4f0e7]/70">This dashboard is intentionally waiting on the event and analytics layers. It will never invent a metric to fill space.</p>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {foundations.map((foundation) => (
            <article className="border border-[#f4f0e7]/20 p-6" key={foundation}>
              <p className="font-mono text-xs uppercase tracking-[0.16em] text-[#d8e6bf]">Planned</p>
              <h2 className="mt-8 text-2xl font-bold">{foundation}</h2>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
